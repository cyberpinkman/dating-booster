from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
import io
import re
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from dating_boost.harness.base import (
    SubprocessRunner,
    WindowInfo,
    parse_window_info as _parse_window_info,
    short as _short,
    window_from_payload as _window_from_payload,
)
from dating_boost.harness.input_backends import (
    click_iphone_mirroring_view_menu_item as _click_iphone_mirroring_view_menu_item_backend,
    core_graphics_click as _core_graphics_click_backend,
    core_graphics_command_v as _core_graphics_command_v_backend,
    core_graphics_drag as _core_graphics_drag_backend,
    core_graphics_wheel as _core_graphics_wheel_backend,
)
from dating_boost.harness.screen_state import (
    BUMBLE_FOREGROUND_STATES,
    TINDER_FOREGROUND_STATES,
    WECHAT_FOREGROUND_STATES,
    bumble_layout_hints as _bumble_layout_hints,
    bumble_top_level_bottom_nav_present as _bumble_top_level_bottom_nav_present,
    classify_bumble_screen_text,
    classify_bumble_screen_image,
    classify_screen_image,
    classify_screen_text,
    classify_wechat_screen_text,
    combine_bumble_screen_states as _combine_bumble_screen_states,
    combine_screen_states as _combine_screen_states,
    _read_png_pixels as _read_png_pixels_for_send_button,
    _region_stats as _region_stats_for_send_button,
    redacted_screen as _redacted_screen,
    tinder_layout_hints as _tinder_layout_hints,
    tinder_profile_danger_action_visible as _tinder_profile_danger_action_visible,
    tinder_profile_expand_control_visible as _tinder_profile_expand_control_visible,
    tinder_profile_field_coverage as _tinder_profile_field_coverage,
    wechat_layout_hints as _wechat_layout_hints,
)
from dating_boost.core.live_send_contract import (
    bumble_target_binding_specific_marker_present,
    target_binding_structural_evidence_present,
)
from dating_boost.core.send_verification import (
    expected_text_observation_stats as _expected_text_observation_stats,
    hash_text as _hash_text,
    message_text_comparable as _message_text_comparable,
    message_text_matches as _message_text_matches,
    normalize_text as _normalize_text,
    outbound_text_ocr_evidence as _outbound_text_ocr_evidence,
    staged_text_ocr_evidence as _staged_text_ocr_evidence,
    staged_text_visual_verification_request as _staged_text_visual_verification_request,
    text_fingerprint_fields as _text_fingerprint_fields,
)
from dating_boost.core.harness_steps import harness_step_validation_reason as _harness_step_validation_reason

GUI_HARNESS_SCHEMA_VERSION = 2
IPHONE_MIRRORING_HARNESS_BACKEND = "iphone_mirroring_macos"
MAC_IOS_APP_HARNESS_BACKEND = "mac_ios_app"
WECHAT_HARNESS_BACKEND = "macos_wechat_desktop"
HARNESS_BACKEND = IPHONE_MIRRORING_HARNESS_BACKEND


def _contains_cjk_text(text: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        or "\U00020000" <= char <= "\U0002ebef"
        for char in text
    )


def direct_text_entry_block_reason(text: str) -> str | None:
    """Return why AppleScript direct keystroke is unsafe for payload text."""
    if text == "":
        return "empty_direct_text_entry"
    if "\n" in text or "\r" in text:
        return "multiline_direct_text_entry_not_supported"
    if _contains_cjk_text(text):
        return "cjk_direct_type_not_supported"
    if any(ord(char) < 32 or ord(char) > 126 for char in text):
        return "non_ascii_direct_type_not_supported"
    return None


class NativeGuiHarness:
    def __init__(
        self,
        *,
        app_id: str = "tinder",
        platform: str | None = None,
        runner: Any | None = None,
        window_title: str = "iPhone Mirroring",
        runtime: str | None = None,
    ):
        self.app_id = app_id
        self.platform = platform or sys.platform
        self.runner = runner or SubprocessRunner()
        self.window_title = window_title
        self.harness_backend = runtime or IPHONE_MIRRORING_HARNESS_BACKEND
        self.runtime_config: dict[str, Any] = {}

    def doctor(self, *, capture: bool = True, output: Path | None = None, ocr: bool = True) -> dict[str, Any]:
        payload = self._base_payload("ok")
        payload["checks"] = self._command_checks()
        if not self.platform.startswith("darwin"):
            payload.update({"status": "blocked", "reason": "unsupported_platform"})
            return payload
        missing_required = [
            name
            for name in ("osascript", "screencapture")
            if not payload["checks"].get(name, {}).get("available")
        ]
        if missing_required:
            payload.update({"status": "blocked", "reason": "missing_required_macos_tools"})
            return payload

        activate = self._activate_window()
        payload["activation"] = activate
        if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND and activate.get("status") == "blocked":
            reason = str(activate.get("reason") or "mac_ios_app_activation_failed")
            if reason in {"mac_ios_app_gui_session_not_interactive", "mac_ios_app_not_active"}:
                payload.update({"status": "blocked", "reason": reason})
                return payload
        window = self._window_info()
        if window is None:
            reason = (
                "mac_ios_app_window_not_found"
                if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND
                else "iphone_mirroring_window_not_found"
            )
            if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND:
                failure = mac_ios_window_failure_payload(self, activation=activate, default=reason)
                payload.update(failure)
                reason = str(failure.get("reason") or reason)
            payload.update({"status": "blocked", "reason": reason})
            return payload
        payload["window"] = window.to_dict()
        if not window.frontmost:
            if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND:
                frontmost_retry = self._activate_window()
                payload["frontmost_retry_activation"] = frontmost_retry
                retry_window = self._window_info()
                if retry_window is not None:
                    payload["frontmost_retry_window"] = retry_window.to_dict()
                    if retry_window.frontmost:
                        window = retry_window
                        payload["window"] = window.to_dict()
                    else:
                        payload.update({"status": "blocked", "reason": "mac_ios_app_not_frontmost"})
                        return payload
                else:
                    payload.update({"status": "blocked", "reason": "mac_ios_app_window_not_found_after_frontmost_retry"})
                    return payload
            else:
                payload.update({"status": "blocked", "reason": "iphone_mirroring_not_frontmost"})
                return payload
        if not window.frontmost:
            reason = (
                "mac_ios_app_not_frontmost"
                if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND
                else "iphone_mirroring_not_frontmost"
            )
            payload.update({"status": "blocked", "reason": reason})
            return payload

        if capture:
            screen = self.capture_window(output=output, window=window, ocr=ocr)
            payload["screen"] = _redacted_screen(screen)
            if screen["state"] in {"iphone_mirroring_locked", "screen_permission_prompt"}:
                payload.update({"status": "blocked", "reason": screen["state"]})
            elif screen["ocr_status"] == "unavailable":
                payload.update({"status": "degraded", "reason": "ocr_unavailable"})
        return payload

    def capture_window(
        self,
        *,
        output: Path | None = None,
        window: WindowInfo | None = None,
        ocr: bool = True,
    ) -> dict[str, Any]:
        if window is None:
            window = self._window_info()
        if window is None:
            return {
                "status": "blocked",
                "reason": "window_not_found",
                "state": "unknown",
                "ocr_status": "not_run",
            }
        output = (output or _default_screenshot_path()).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        window_id = getattr(window, "window_id", None)
        if window_id is not None:
            command = ["screencapture", "-x", "-l", str(window_id), str(output)]
        else:
            command = [
                "screencapture",
                "-x",
                "-R",
                f"{window.x},{window.y},{window.width},{window.height}",
                str(output),
            ]
        result = self.runner.run(command)
        if result.returncode != 0:
            return {
                "status": "blocked",
                "reason": "screenshot_failed",
                "stderr": _short(result.stderr),
                "state": "unknown",
                "ocr_status": "not_run",
            }
        ocr_payload = self._ocr(output) if ocr else {"status": "skipped", "text": "", "error": None}
        return {
            "schema_version": GUI_HARNESS_SCHEMA_VERSION,
            "status": "ok",
            "path": str(output),
            "state": "unknown",
            "text_state": "unknown",
            "visual_state": "unknown",
            "visual_status": "not_applicable",
            "visual_active_tab": "unknown",
            "visual_bottom_nav_present": False,
            "ocr_status": ocr_payload["status"],
            "ocr_error": ocr_payload.get("error"),
            "text": ocr_payload.get("text", ""),
        }

    def _activate_window(self) -> dict[str, Any]:
        if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND:
            attempts: list[dict[str, Any]] = []
            bundle_id = str(self.runtime_config.get("bundle_id") or "").strip()
            if bundle_id:
                app_result = self.runner.run(["open", "-b", bundle_id])
                attempts.append({
                    "method": "open_bundle_id",
                    "bundle_id": bundle_id,
                    "status": "ok" if app_result.returncode == 0 else "blocked",
                    "stderr": _short(app_result.stderr),
                })
                active_probe = self._mac_ios_active_application_probe()
                attempts.append({"method": "verify_active_application", "result": active_probe})
                if active_probe.get("status") == "ok":
                    return {"status": "ok", "attempts": attempts}
                if active_probe.get("status") == "blocked":
                    reason = str(active_probe.get("reason") or "mac_ios_app_not_active")
                    if reason == "mac_ios_app_gui_session_not_interactive":
                        return {
                            "status": "blocked",
                            "reason": reason,
                            "attempts": attempts,
                        }
                    attempts.append({
                        "method": "defer_blocked_active_probe_to_frontmost_retry",
                        "reason": reason,
                    })
            for attempt_index in range(6):
                if attempt_index:
                    time.sleep(0.35)
                for process_name in self._mac_ios_process_names():
                    frontmost_result = self.runner.run(
                        [
                            "osascript",
                            "-e",
                            f'tell application "System Events" to set frontmost of process {_applescript_string_literal(process_name)} to true',
                        ]
                    )
                    attempts.append({
                        "method": "set_process_frontmost",
                        "process_name": process_name,
                        "attempt": attempt_index + 1,
                        "status": "ok" if frontmost_result.returncode == 0 else "blocked",
                        "stderr": _short(frontmost_result.stderr),
                    })
                    if frontmost_result.returncode == 0:
                        active_probe = self._mac_ios_active_application_probe()
                        attempts.append({"method": "verify_active_application", "result": active_probe})
                        if active_probe.get("status") == "blocked":
                            reason = str(active_probe.get("reason") or "mac_ios_app_not_active")
                            if reason == "mac_ios_app_gui_session_not_interactive":
                                return {
                                    "status": "blocked",
                                    "reason": reason,
                                    "attempts": attempts,
                                }
                            attempts.append({
                                "method": "retry_after_frontmost_active_probe_blocked",
                                "reason": reason,
                            })
                            continue
                        return {
                            "status": "ok",
                            "attempts": attempts,
                        }
            return {
                "status": "blocked",
                "reason": "mac_ios_app_process_not_frontmost",
                "attempts": attempts,
            }
        result = self.runner.run(["osascript", "-e", f'tell application "{self.window_title}" to activate'])
        frontmost_result = self.runner.run(
            [
                "osascript",
                "-e",
                f'tell application "System Events" to set frontmost of process "{self.window_title}" to true',
            ]
        )
        return {
            "status": "ok" if result.returncode == 0 and frontmost_result.returncode == 0 else "blocked",
            "stderr": _short(result.stderr or frontmost_result.stderr),
        }

    def _window_info(self) -> WindowInfo | None:
        process_names = self._mac_ios_process_names() if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND else [self.window_title]
        for process_name in process_names:
            for index in range(1, 5):
                script = (
                    f'tell application "System Events" to tell process {_applescript_string_literal(process_name)} '
                    f"to get {{frontmost, position of window {index}, size of window {index}, name of window {index}}}"
                )
                result = self.runner.run(["osascript", "-e", script])
                if result.returncode != 0:
                    continue
                window = _parse_window_info(result.stdout)
                if window is not None and self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND:
                    if _looks_like_mac_ios_app_window(window):
                        return window
                elif window is not None and _looks_like_iphone_mirroring_window(window):
                    return window
        if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND:
            return self._mac_ios_core_graphics_window_info(process_names)
        return None

    def _mac_ios_process_names(self) -> list[str]:
        names = [
            self.window_title,
            str(self.runtime_config.get("process_name") or ""),
            str(self.runtime_config.get("display_name") or ""),
            str(self.runtime_config.get("application_name") or ""),
        ]
        unique: list[str] = []
        for name in names:
            cleaned = name.strip()
            if cleaned and cleaned not in unique:
                unique.append(cleaned)
        return unique or [self.window_title]

    def _mac_ios_process_pids(self, process_names: list[str]) -> list[int]:
        bundle_id = str(self.runtime_config.get("bundle_id") or "").strip()
        script = _mac_ios_running_application_lookup_script(bundle_id=bundle_id, candidates=process_names)
        result = self.runner.run(["xcrun", "swift", "-e", script])
        if result.returncode != 0:
            return []
        pids: list[int] = []
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 4 or parts[0] != "target":
                continue
            try:
                pid = int(parts[3])
            except ValueError:
                continue
            if pid not in pids:
                pids.append(pid)
        return pids

    def _mac_ios_core_graphics_window_info(self, process_names: list[str]) -> WindowInfo | None:
        pids = self._mac_ios_process_pids(process_names)
        script = _mac_ios_core_graphics_window_lookup_script(pids=pids, candidates=process_names)
        result = self.runner.run(["xcrun", "swift", "-e", script])
        if result.returncode != 0:
            return None
        return _parse_core_graphics_window_info(result.stdout)

    def _mac_ios_active_application_probe(self) -> dict[str, Any]:
        process_names = self._mac_ios_process_names()
        bundle_id = str(self.runtime_config.get("bundle_id") or "").strip()
        script = _mac_ios_running_application_lookup_script(bundle_id=bundle_id, candidates=process_names)
        result = self.runner.run(["xcrun", "swift", "-e", script])
        if result.returncode != 0:
            return {
                "status": "unknown",
                "reason": "mac_ios_active_application_probe_failed",
                "stderr": _short(result.stderr),
            }
        return _parse_mac_ios_active_application_probe(result.stdout, bundle_id=bundle_id, candidates=process_names)

    def _mac_ios_window_probe(self) -> dict[str, Any]:
        probes: list[dict[str, Any]] = []
        for process_name in self._mac_ios_process_names():
            script = (
                'tell application "System Events"\n'
                f"if exists process {_applescript_string_literal(process_name)} then\n"
                f"tell process {_applescript_string_literal(process_name)} to get "
                "{frontmost, visible, count of windows}\n"
                "else\n"
                'return "missing"\n'
                "end if\n"
                "end tell"
            )
            result = self.runner.run(["osascript", "-e", script])
            probe = {
                "process_name": process_name,
                "status": "ok" if result.returncode == 0 else "blocked",
                "stdout": _short(result.stdout),
                "stderr": _short(result.stderr),
            }
            parsed = _parse_mac_ios_process_probe(result.stdout)
            if parsed:
                probe.update(parsed)
            probes.append(probe)
        frontmost = self.runner.run(
            ["osascript", "-e", 'tell application "System Events" to get name of first process whose frontmost is true']
        )
        return {
            "status": "ok",
            "processes": probes,
            "frontmost_process": frontmost.stdout.strip() if frontmost.returncode == 0 else None,
            "frontmost_probe_status": "ok" if frontmost.returncode == 0 else "blocked",
            "frontmost_probe_stderr": _short(frontmost.stderr),
        }

    def _click_ratio(self, window: WindowInfo, ratio: dict[str, float]) -> dict[str, Any]:
        x = round(window.x + window.width * float(ratio["x"]))
        y = round(window.y + window.height * float(ratio["y"]))
        if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND:
            readiness = self._mac_ios_active_application_probe()
            if readiness.get("status") == "blocked":
                activation_retry = self._activate_window()
                retry_readiness = self._mac_ios_active_application_probe()
                if retry_readiness.get("status") == "blocked":
                    return {
                        "status": "blocked",
                        "reason": retry_readiness.get("reason") or readiness.get("reason") or "mac_ios_app_not_active",
                        "point": {"x": x, "y": y},
                        "input_backend": "blocked_core_graphics",
                        "input_readiness": retry_readiness,
                        "initial_input_readiness": readiness,
                        "activation_retry": activation_retry,
                    }
        if self._command_available("xcrun"):
            result = self._core_graphics_click(x, y)
            if result["status"] == "ok":
                return result
        result = self.runner.run(
            [
                "osascript",
                "-e",
                f'tell application "System Events" to click at {{{x}, {y}}}',
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "accessibility_click_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "point": {"x": x, "y": y}, "input_backend": "applescript_accessibility"}

    def _core_graphics_click(self, x: int, y: int) -> dict[str, Any]:
        return _core_graphics_click_backend(self.runner, x, y)

    def _swipe_ratio(self, window: WindowInfo, swipe: dict[str, Any]) -> dict[str, Any]:
        if not self._command_available("xcrun"):
            return {"status": "blocked", "reason": "missing_core_graphics_swipe_backend"}
        start = swipe["from"]
        end = swipe["to"]
        start_x = round(window.x + window.width * float(start["x"]))
        start_y = round(window.y + window.height * float(start["y"]))
        end_x = round(window.x + window.width * float(end["x"]))
        end_y = round(window.y + window.height * float(end["y"]))
        return _core_graphics_drag_backend(
            self.runner,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
            duration_seconds=float(swipe.get("duration_ms", 350)) / 1000.0,
        )

    def _wheel_ratio(self, window: WindowInfo, wheel: dict[str, Any]) -> dict[str, Any]:
        if not self._command_available("xcrun"):
            return {"status": "blocked", "reason": "missing_core_graphics_wheel_backend"}
        x = round(window.x + window.width * float(wheel.get("x", 0.5)))
        y = round(window.y + window.height * float(wheel.get("y", 0.5)))
        delta_y = int(wheel.get("delta_y", 0))
        delta_x = int(wheel.get("delta_x", 0))
        repeats = max(1, int(wheel.get("repeats", 1)))
        interval_us = max(1000, int(wheel.get("interval_us", 18000)))
        return _core_graphics_wheel_backend(
            self.runner,
            x=x,
            y=y,
            delta_y=delta_y,
            delta_x=delta_x,
            repeats=repeats,
            interval_us=interval_us,
        )

    def _click_iphone_mirroring_view_menu_item(self, item_name: str) -> dict[str, Any]:
        return _click_iphone_mirroring_view_menu_item_backend(
            self.runner,
            window_title=self.window_title,
            item_name=item_name,
        )

    def _execute_step(self, window: WindowInfo, step: dict[str, Any]) -> dict[str, Any]:
        validation_reason = _harness_step_validation_reason(step)
        if validation_reason is not None:
            return {"status": "blocked", "reason": validation_reason}
        if "tap_ratio" in step:
            return self._click_ratio(window, step["tap_ratio"])
        if "swipe" in step:
            return self._swipe_ratio(window, step["swipe"])
        if "wheel" in step:
            return self._wheel_ratio(window, step["wheel"])
        if step["intent"] == "open_iphone_home_screen":
            return self._click_iphone_mirroring_view_menu_item("Home Screen")
        if step["intent"] == "open_ios_spotlight":
            result = self._click_iphone_mirroring_view_menu_item("Spotlight")
            if result["status"] == "ok":
                return result
            fallback = self._click_ratio(window, {"x": 0.5, "y": 0.84})
            return {**fallback, "fallback_from": "spotlight_menu"}
        if step["intent"] == "type_app_name_verified":
            app_name = str(step.get("text") or "Tinder")
            expected_labels = step.get("expected_app_labels")
            labels = [str(item) for item in expected_labels] if isinstance(expected_labels, list) else None
            return self._type_app_name_with_search_verification(window, app_name, expected_app_labels=labels)
        if step["intent"] == "type_app_name":
            app_name = str(step.get("text") or "Tinder")
            return self._type_text_with_ime_commit(app_name, failure_reason="text_entry_failed")
        if step["intent"] == "press_return":
            result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
            if result.returncode != 0:
                return {"status": "blocked", "reason": "return_key_failed", "stderr": _short(result.stderr)}
            return {"status": "ok"}
        return {"status": "blocked", "reason": "unknown_gui_step"}

    def _type_app_name_with_search_verification(
        self,
        window: WindowInfo,
        app_name: str,
        *,
        expected_app_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        first_type = self._type_text_without_ime_commit(app_name, failure_reason="text_entry_failed")
        if first_type["status"] != "ok":
            return first_type
        time.sleep(0.2)
        first_screen = self.capture_window(window=window)
        first_verified = _app_search_result_visible(first_screen, app_name, expected_app_labels=expected_app_labels)
        if first_verified:
            return {
                "status": "ok",
                "search_result_verified": True,
                "retried_after_input_source_switch": False,
                "ime_commit_after_typing": False,
                "expected_app_labels": list(expected_app_labels or [app_name]),
                "text_entry": first_type,
                "verification": _redacted_screen(first_screen),
            }

        switch = _switch_ascii_input_source(self.runner)
        if switch["status"] != "ok":
            return {
                **switch,
                "first_verification": _redacted_screen(first_screen),
                "text_entry": first_type,
                "search_result_verified": False,
            }
        home = self._click_iphone_mirroring_view_menu_item("Home Screen")
        if home["status"] != "ok":
            return {**home, "first_verification": _redacted_screen(first_screen), "input_source_switch": switch}
        time.sleep(0.3)
        spotlight = self._click_iphone_mirroring_view_menu_item("Spotlight")
        if spotlight["status"] != "ok":
            fallback = self._click_ratio(window, {"x": 0.5, "y": 0.84})
            if fallback["status"] != "ok":
                return {
                    **fallback,
                    "fallback_from": "spotlight_menu_after_input_source_switch",
                    "first_verification": _redacted_screen(first_screen),
                    "text_entry": first_type,
                    "input_source_switch": switch,
                }
        time.sleep(0.3)
        second_type_payload = self._type_text_without_ime_commit(app_name, failure_reason="text_entry_retry_failed")
        if second_type_payload["status"] != "ok":
            return {
                **second_type_payload,
                "first_verification": _redacted_screen(first_screen),
                "first_text_entry": first_type,
                "input_source_switch": switch,
            }
        time.sleep(0.2)
        second_screen = self.capture_window(window=window)
        if not _app_search_result_visible(second_screen, app_name, expected_app_labels=expected_app_labels):
            return {
                "status": "blocked",
                "reason": "app_search_result_not_verified",
                "first_verification": _redacted_screen(first_screen),
                "retry_verification": _redacted_screen(second_screen),
                "first_text_entry": first_type,
                "retry_text_entry": second_type_payload,
                "input_source_switch": switch,
            }
        return {
            "status": "ok",
            "search_result_verified": True,
            "retried_after_input_source_switch": True,
            "ime_commit_after_typing": False,
            "expected_app_labels": list(expected_app_labels or [app_name]),
            "first_verification": _redacted_screen(first_screen),
            "retry_verification": _redacted_screen(second_screen),
            "first_text_entry": first_type,
            "retry_text_entry": second_type_payload,
            "input_source_switch": switch,
        }

    def _type_text_without_ime_commit(self, text: str, *, failure_reason: str) -> dict[str, Any]:
        block_reason = direct_text_entry_block_reason(text)
        if block_reason is not None:
            return {"status": "blocked", "reason": block_reason, "input_backend": "blocked_direct_keystroke"}
        type_result = self.runner.run(
            ["osascript", "-e", f'tell application "System Events" to keystroke {_applescript_string_literal(text)}']
        )
        if type_result.returncode != 0:
            return {"status": "blocked", "reason": failure_reason, "stderr": _short(type_result.stderr)}
        return {"status": "ok", "input_backend": "applescript_direct_keystroke", "ime_commit_key": None}

    def _type_text_with_ime_commit(self, text: str, *, failure_reason: str) -> dict[str, Any]:
        block_reason = direct_text_entry_block_reason(text)
        if block_reason is not None:
            return {"status": "blocked", "reason": block_reason, "input_backend": "blocked_direct_keystroke"}
        type_result = self.runner.run(
            ["osascript", "-e", f'tell application "System Events" to keystroke {_applescript_string_literal(text)}']
        )
        if type_result.returncode != 0:
            return {"status": "blocked", "reason": failure_reason, "stderr": _short(type_result.stderr)}
        commit_result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 49'])
        if commit_result.returncode != 0:
            return {
                "status": "blocked",
                "reason": "ime_commit_space_failed",
                "stderr": _short(commit_result.stderr),
            }
        return {
            "status": "ok",
            "input_backend": "applescript_accessibility",
            "ime_commit_key": "space",
        }

    def _copy_to_clipboard(self, text: str) -> dict[str, Any]:
        if not self._command_available("pbcopy"):
            return {"status": "blocked", "reason": "missing_pbcopy"}
        result = self.runner.run(["pbcopy"], input=text)
        if result.returncode != 0:
            return {"status": "blocked", "reason": "clipboard_copy_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "pbcopy"}

    def _read_clipboard(self) -> dict[str, Any]:
        if not self._command_available("pbpaste"):
            return {"status": "blocked", "reason": "missing_pbpaste"}
        result = self.runner.run(["pbpaste"])
        if result.returncode != 0:
            return {"status": "blocked", "reason": "clipboard_read_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "text": result.stdout}

    def _paste_clipboard_into_frontmost_app(self, *, prefer_core_graphics_keyboard: bool = False) -> dict[str, Any]:
        core_graphics_result: dict[str, Any] | None = None
        if prefer_core_graphics_keyboard:
            core_graphics_result = _core_graphics_command_v_backend(self.runner)
            if core_graphics_result["status"] == "ok":
                return core_graphics_result
        result = self.runner.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using {command down}',
            ]
        )
        if result.returncode != 0:
            return {
                "status": "blocked",
                "reason": "clipboard_paste_failed",
                "stderr": _short(result.stderr),
                "primary_attempt": core_graphics_result,
            }
        return {
            "status": "ok",
            "input_backend": "applescript_accessibility",
            "fallback_from": core_graphics_result.get("reason") if core_graphics_result else None,
        }

    def _type_text_into_frontmost_app(self, text: str) -> dict[str, Any]:
        block_reason = direct_text_entry_block_reason(text)
        if block_reason is not None:
            return {"status": "blocked", "reason": block_reason, "input_backend": "blocked_direct_keystroke"}
        result = self.runner.run(
            [
                "osascript",
                "-e",
                f'tell application "System Events" to keystroke {_applescript_string_literal(text)}',
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "direct_text_entry_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_direct_keystroke"}

    def _press_return_key(self) -> dict[str, Any]:
        result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
        if result.returncode != 0:
            return {"status": "blocked", "reason": "return_key_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_accessibility"}

    def _press_space_key(self) -> dict[str, Any]:
        result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 49'])
        if result.returncode != 0:
            return {"status": "blocked", "reason": "ime_commit_space_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_accessibility", "ime_commit_key": "space"}

    def _press_escape_key(self) -> dict[str, Any]:
        result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 53'])
        if result.returncode != 0:
            return {"status": "blocked", "reason": "escape_key_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_accessibility", "key": "escape"}

    def _press_backspace_key(self) -> dict[str, Any]:
        result = self.runner.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke (ASCII character 8)']
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "backspace_key_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_accessibility", "key": "backspace"}

    def _ocr(self, image_path: Path) -> dict[str, str]:
        if not self._command_available("tesseract"):
            return {"status": "unavailable", "text": ""}
        result = self.runner.run(
            [
                "tesseract",
                str(image_path),
                "stdout",
                "-l",
                "eng+chi_sim",
                "--psm",
                "6",
            ]
        )
        if result.returncode != 0:
            fallback = self.runner.run(["tesseract", str(image_path), "stdout", "--psm", "6"])
            if fallback.returncode != 0:
                return {"status": "failed", "text": "", "error": _short(fallback.stderr or result.stderr)}
            return {"status": "ok", "text": fallback.stdout}
        return {"status": "ok", "text": result.stdout}

    def _command_checks(self) -> dict[str, dict[str, Any]]:
        commands = ("osascript", "screencapture", "tesseract", "xcrun", "pbcopy", "pbpaste")
        return {
            name: {"available": self._command_available(name)}
            for name in commands
        }

    def _command_available(self, command: str) -> bool:
        result = self.runner.run(["command", "-v", command])
        return result.returncode == 0 and bool(result.stdout.strip())

    def _base_payload(self, status: str) -> dict[str, Any]:
        return {
            "schema_version": GUI_HARNESS_SCHEMA_VERSION,
            "status": status,
            "app_id": self.app_id,
            "harness_backend": self.harness_backend,
            "captured_at": _now_iso(),
        }


def _applescript_string_literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ensure_ascii_input_source(runner: SubprocessRunner) -> dict[str, Any]:
    before = _read_current_input_source(runner)
    before_id = str(before.get("input_source_id") or "")
    if before.get("status") == "ok" and _input_source_id_is_ascii(before_id):
        return {"status": "ok", "changed": False, "input_source_id": before_id}

    return _switch_ascii_input_source(runner, before_input_source_id=before_id or None)


def _switch_ascii_input_source(
    runner: SubprocessRunner,
    *,
    before_input_source_id: str | None = None,
) -> dict[str, Any]:
    result = runner.run(["osascript", "-e", 'tell application "System Events" to key code 49 using {control down}'])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "ascii_input_source_switch_failed",
            "before_input_source_id": before_input_source_id,
            "stderr": _short(result.stderr),
        }
    time.sleep(0.1)
    after = _read_current_input_source(runner)
    after_id = str(after.get("input_source_id") or "")
    payload = {
        "status": "ok",
        "changed": True,
        "before_input_source_id": before_input_source_id,
        "after_input_source_id": after_id or None,
    }
    if after.get("status") == "ok" and after_id and not _input_source_id_is_ascii(after_id):
        payload.update({"status": "blocked", "reason": "ascii_input_source_not_verified"})
    elif after.get("status") != "ok":
        payload["verification_status"] = after.get("status", "unknown")
    return payload


def _read_current_input_source(runner: SubprocessRunner) -> dict[str, Any]:
    result = runner.run(["defaults", "read", "com.apple.HIToolbox", "AppleCurrentKeyboardLayoutInputSourceID"])
    if result.returncode != 0:
        return {"status": "unknown", "stderr": _short(result.stderr)}
    input_source_id = result.stdout.strip()
    if not input_source_id:
        return {"status": "unknown"}
    return {"status": "ok", "input_source_id": input_source_id}


def _input_source_id_is_ascii(input_source_id: str) -> bool:
    normalized = input_source_id.strip().lower()
    return normalized in {
        "com.apple.keylayout.abc",
        "com.apple.keylayout.us",
        "com.apple.keylayout.british",
        "com.apple.keylayout.australian",
        "com.apple.keylayout.dvorak",
        "com.apple.keylayout.colemak",
    }


def _app_search_result_visible(
    screen: dict[str, Any],
    app_name: str,
    *,
    expected_app_labels: list[str] | None = None,
) -> bool:
    if screen.get("status") != "ok":
        return False
    normalized = _normalize_text(str(screen.get("text") or ""))
    labels = expected_app_labels or [app_name]
    for label in labels:
        app = str(label).strip().lower()
        if app and app in normalized:
            return True
    return False


def _default_screenshot_path() -> Path:
    return Path(tempfile.gettempdir()) / f"dating-boost-iphone-mirroring-{uuid4().hex}.png"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_mac_ios_process_probe(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    if text == "missing":
        return {"process_exists": False}
    match = re.search(r"^\s*(true|false),\s*(true|false),\s*(\d+)\s*$", text, re.IGNORECASE)
    if not match:
        return None
    return {
        "process_exists": True,
        "frontmost": match.group(1).lower() == "true",
        "visible": match.group(2).lower() == "true",
        "window_count": int(match.group(3)),
    }


def _parse_core_graphics_window_info(stdout: str) -> WindowInfo | None:
    line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    parts = line.split("\t", 5)
    if len(parts) != 6:
        return None
    try:
        x = int(parts[0])
        y = int(parts[1])
        width = int(parts[2])
        height = int(parts[3])
        window_id = int(parts[4])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return WindowInfo(
        frontmost=True,
        x=x,
        y=y,
        width=width,
        height=height,
        name=parts[5].strip() or "mac_ios_app",
        window_id=window_id,
    )


def _parse_mac_ios_active_application_probe(
    stdout: str,
    *,
    bundle_id: str,
    candidates: list[str],
) -> dict[str, Any]:
    front_name = ""
    front_bundle = ""
    target_name = ""
    target_bundle = ""
    target_pid: int | None = None
    target_active: bool | None = None
    target_running = False
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0] == "front":
            front_name = parts[1]
            front_bundle = parts[2]
        elif len(parts) >= 7 and parts[0] == "target":
            target_running = True
            target_name = parts[1]
            target_bundle = parts[2]
            try:
                target_pid = int(parts[3])
            except ValueError:
                target_pid = None
            target_active = parts[4].lower() == "true"
    if not front_name and not front_bundle and not target_running:
        return {"status": "unknown", "reason": "mac_ios_active_application_probe_unparsed"}
    payload: dict[str, Any] = {
        "frontmost_application": {
            "name": front_name,
            "bundle_id": front_bundle,
        },
        "target_application": {
            "name": target_name,
            "bundle_id": target_bundle,
            "pid": target_pid,
            "active": target_active,
            "running": target_running,
        },
    }
    if front_bundle == "com.apple.loginwindow" or front_name == "loginwindow":
        return {
            **payload,
            "status": "blocked",
            "reason": "mac_ios_app_gui_session_not_interactive",
        }
    if not target_running:
        return {**payload, "status": "blocked", "reason": "mac_ios_app_process_not_found"}
    candidate_names = {candidate.lower() for candidate in candidates if candidate}
    target_matches_front = bool(target_bundle and target_bundle == front_bundle)
    if not target_matches_front and target_name:
        target_matches_front = target_name.lower() == front_name.lower() or front_name.lower() in candidate_names
    if target_active is True and target_matches_front:
        return {**payload, "status": "ok"}
    return {**payload, "status": "blocked", "reason": "mac_ios_app_not_active"}


def _swift_string_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _mac_ios_running_application_lookup_script(*, bundle_id: str, candidates: list[str]) -> str:
    candidate_literal = ", ".join(_swift_string_literal(candidate) for candidate in candidates if candidate)
    bundle_literal = _swift_string_literal(bundle_id)
    return f"""
import AppKit
import Foundation

let targetBundleId = {bundle_literal}
let candidates = Set([{candidate_literal}].map {{ $0.lowercased() }})

func cleaned(_ value: String?) -> String {{
    return (value ?? "").replacingOccurrences(of: "\\t", with: " ").replacingOccurrences(of: "\\n", with: " ")
}}

let front = NSWorkspace.shared.frontmostApplication
print("front\\t\\(cleaned(front?.localizedName))\\t\\(cleaned(front?.bundleIdentifier))")

for app in NSWorkspace.shared.runningApplications {{
    let bundle = app.bundleIdentifier ?? ""
    let name = app.localizedName ?? ""
    let matchesBundle = !targetBundleId.isEmpty && bundle == targetBundleId
    let matchesName = candidates.contains(name.lowercased()) || candidates.contains(bundle.lowercased())
    if matchesBundle || matchesName {{
        print("target\\t\\(cleaned(name))\\t\\(cleaned(bundle))\\t\\(app.processIdentifier)\\t\\(app.isActive)\\t\\(app.isHidden)\\t\\(app.isTerminated)")
    }}
}}
"""


def _mac_ios_core_graphics_window_lookup_script(*, pids: list[int], candidates: list[str]) -> str:
    pid_literal = ", ".join(str(pid) for pid in pids)
    candidate_literal = ", ".join(_swift_string_literal(candidate) for candidate in candidates if candidate)
    return f"""
import CoreGraphics
import Foundation

let targetPids = Set<Int>([{pid_literal}])
let candidates = [{candidate_literal}].map {{ $0.lowercased() }}
let options = CGWindowListOption(arrayLiteral: [.optionOnScreenOnly, .excludeDesktopElements])
let windows = (CGWindowListCopyWindowInfo(options, CGWindowID(0)) as? [[String: Any]]) ?? []

func intValue(_ value: Any?) -> Int {{
    if let number = value as? NSNumber {{
        return Int(round(number.doubleValue))
    }}
    if let doubleValue = value as? Double {{
        return Int(round(doubleValue))
    }}
    if let intValue = value as? Int {{
        return intValue
    }}
    return 0
}}

func cleaned(_ value: String) -> String {{
    return value.replacingOccurrences(of: "\\t", with: " ").replacingOccurrences(of: "\\n", with: " ")
}}

for window in windows {{
    let layer = intValue(window[kCGWindowLayer as String])
    if layer != 0 {{
        continue
    }}
    let pid = intValue(window[kCGWindowOwnerPID as String])
    let owner = (window[kCGWindowOwnerName as String] as? String) ?? ""
    let title = (window[kCGWindowName as String] as? String) ?? ""
    let haystack = (owner + " " + title).lowercased()
    let pidMatches = targetPids.contains(pid)
    let nameMatches = candidates.contains {{ candidate in
        !candidate.isEmpty && haystack.contains(candidate)
    }}
    if !pidMatches && !nameMatches {{
        continue
    }}
    guard let bounds = window[kCGWindowBounds as String] as? [String: Any] else {{
        continue
    }}
    let x = intValue(bounds["X"])
    let y = intValue(bounds["Y"])
    let width = intValue(bounds["Width"])
    let height = intValue(bounds["Height"])
    let windowNumber = intValue(window[kCGWindowNumber as String])
    if width <= 0 || height <= 0 {{
        continue
    }}
    let name = cleaned(title.isEmpty ? owner : title)
    print("\\(x)\\t\\(y)\\t\\(width)\\t\\(height)\\t\\(windowNumber)\\t\\(name)")
    exit(0)
}}

exit(1)
"""


def _mac_ios_window_failure_reason(
    window_probe: dict[str, Any],
    *,
    activation: dict[str, Any] | None = None,
    default: str,
) -> str:
    if _contains_host_appleevents_unavailable_error(activation) or _contains_host_appleevents_unavailable_error(
        window_probe
    ):
        return "host_appleevents_unavailable"
    processes = window_probe.get("processes")
    if not isinstance(processes, list) or not processes:
        return default
    parsed = [process for process in processes if isinstance(process, dict) and "process_exists" in process]
    if parsed and not any(process.get("process_exists") for process in parsed):
        return "mac_ios_app_process_not_found"
    if any(
        process.get("process_exists") is True
        and process.get("visible") is True
        and process.get("window_count") == 0
        for process in parsed
    ):
        return "mac_ios_app_process_has_no_windows"
    return default


def mac_ios_window_failure_payload(
    session: Any,
    *,
    activation: dict[str, Any] | None = None,
    default: str = "mac_ios_app_window_not_found",
) -> dict[str, Any]:
    probe = session._mac_ios_window_probe() if hasattr(session, "_mac_ios_window_probe") else {}
    reason = _mac_ios_window_failure_reason(probe, activation=activation, default=default)
    payload: dict[str, Any] = {"reason": reason}
    if isinstance(probe, dict):
        payload["window_probe"] = probe
    if reason == "host_appleevents_unavailable":
        payload["diagnostic"] = _host_appleevents_unavailable_diagnostic()
    return payload


def _contains_host_appleevents_unavailable_error(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.lower()
        return any(
            marker in text
            for marker in (
                "-10827",
                "connection invalid",
                "hiservices-xpcservice",
            )
        )
    if isinstance(value, dict):
        return any(_contains_host_appleevents_unavailable_error(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_host_appleevents_unavailable_error(item) for item in value)
    return False


def _host_appleevents_unavailable_diagnostic() -> dict[str, Any]:
    return {
        "category": "host_appleevents_unavailable",
        "summary": (
            "The host process cannot query macOS System Events/AppleEvents. "
            "This is not evidence that the TaShuo mac-ios-app window is missing."
        ),
        "likely_causes": [
            "Host Automation permission for System Events is missing, stale, or broken.",
            "macOS AppleEvents/HiServices returned an environment-level connection error.",
            "The host app may need to be restarted, reinstalled, or re-authorized in Privacy & Security.",
        ],
        "do_not_infer": [
            "Do not treat this as a missing TaShuo window.",
            "Do not infer that Dating Booster needs a repo-level Computer Use execution backend.",
            "Do not infer that managed sessions need a persistent global background agent.",
        ],
    }


def _looks_like_iphone_mirroring_window(window: WindowInfo) -> bool:
    return window.width >= 200 and window.height >= 400 and bool(window.name.strip())


def _looks_like_mac_ios_app_window(window: WindowInfo) -> bool:
    return window.width >= 160 and window.height >= 300
