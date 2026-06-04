from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4
import zlib


GUI_HARNESS_SCHEMA_VERSION = 1
IPHONE_MIRRORING_HARNESS_BACKEND = "iphone_mirroring_macos"
WECHAT_HARNESS_BACKEND = "macos_wechat_desktop"
HARNESS_BACKEND = IPHONE_MIRRORING_HARNESS_BACKEND
BLOCKED_GUI_ACTIONS = ["send", "like", "super_like", "unmatch", "report", "profile_edit"]
WECHAT_BLOCKED_GUI_ACTIONS = ["send", "payments", "calls", "contact_exchange_without_user"]
TINDER_FOREGROUND_STATES = {
    "tinder_home",
    "tinder_messages",
    "tinder_conversation",
    "tinder_self_profile",
    "tinder_profile",
    "tinder_unknown",
}
WECHAT_FOREGROUND_STATES = {"wechat_chat", "wechat_chat_list", "wechat_unknown"}


@dataclass(frozen=True)
class WindowInfo:
    frontmost: bool
    x: int
    y: int
    width: int
    height: int
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "frontmost": self.frontmost,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "name": self.name,
        }


class SubprocessRunner:
    def run(self, command: list[str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["command", "-v"] and len(command) == 3:
            path = shutil.which(command[2])
            return subprocess.CompletedProcess(
                command,
                0 if path else 1,
                stdout=f"{path}\n" if path else "",
                stderr="",
            )
        return subprocess.run(command, input=input, capture_output=True, text=True, check=False)


class NativeGuiHarness:
    def __init__(
        self,
        *,
        app_id: str = "tinder",
        platform: str | None = None,
        runner: Any | None = None,
        window_title: str = "iPhone Mirroring",
    ):
        self.app_id = app_id
        self.platform = platform or sys.platform
        self.runner = runner or SubprocessRunner()
        self.window_title = window_title

    def doctor(self, *, capture: bool = True, output: Path | None = None) -> dict[str, Any]:
        if self.app_id == "wechat":
            return self.doctor_wechat(capture=capture, output=output)
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
        window = self._window_info()
        if window is None:
            payload.update({"status": "blocked", "reason": "iphone_mirroring_window_not_found"})
            return payload
        payload["window"] = window.to_dict()
        if not window.frontmost:
            payload.update({"status": "blocked", "reason": "iphone_mirroring_not_frontmost"})
            return payload

        if capture:
            screen = self.capture_window(output=output, window=window)
            payload["screen"] = _redacted_screen(screen)
            if screen["state"] in {"iphone_mirroring_locked", "screen_permission_prompt"}:
                payload.update({"status": "blocked", "reason": screen["state"]})
            elif screen["ocr_status"] == "unavailable":
                payload.update({"status": "degraded", "reason": "ocr_unavailable"})
        return payload

    def doctor_wechat(self, *, capture: bool = True, output: Path | None = None) -> dict[str, Any]:
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
        window = self._window_info()
        if window is None:
            payload.update({"status": "blocked", "reason": "wechat_window_not_found"})
            return payload
        payload["window"] = window.to_dict()
        if not window.frontmost:
            payload.update({"status": "blocked", "reason": "wechat_not_frontmost"})
            return payload

        if capture:
            screen = self.capture_window(output=output, window=window)
            payload["screen"] = _redacted_screen(screen)
            if screen["state"] == "screen_permission_prompt":
                payload.update({"status": "blocked", "reason": screen["state"]})
            elif screen["ocr_status"] == "unavailable":
                payload.update({"status": "degraded", "reason": "ocr_unavailable"})
        return payload

    def capture_window(self, *, output: Path | None = None, window: WindowInfo | None = None) -> dict[str, Any]:
        if window is None:
            window = self._window_info()
        if window is None:
            return {
                "status": "blocked",
                "reason": "iphone_mirroring_window_not_found",
                "state": "unknown",
                "ocr_status": "not_run",
            }
        output = (output or _default_screenshot_path()).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        result = self.runner.run(
            [
                "screencapture",
                "-x",
                "-R",
                f"{window.x},{window.y},{window.width},{window.height}",
                str(output),
            ]
        )
        if result.returncode != 0:
            return {
                "status": "blocked",
                "reason": "screenshot_failed",
                "stderr": _short(result.stderr),
                "state": "unknown",
                "ocr_status": "not_run",
            }
        ocr = self._ocr(output)
        if self.app_id == "wechat":
            text_state = classify_wechat_screen_text(ocr.get("text", ""))
            visual = {"status": "not_applicable", "state": "unknown"}
            state = text_state
        else:
            text_state = classify_screen_text(ocr.get("text", ""))
            visual = classify_screen_image(output)
            state = _combine_screen_states(text_state, visual["state"])
        return {
            "schema_version": GUI_HARNESS_SCHEMA_VERSION,
            "status": "ok",
            "path": str(output),
            "state": state,
            "text_state": text_state,
            "visual_state": visual["state"],
            "visual_status": visual["status"],
            "ocr_status": ocr["status"],
            "ocr_error": ocr.get("error"),
            "text": ocr.get("text", ""),
        }

    def launch_wechat(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        planned_steps = [
            {
                "intent": "activate_wechat_application",
                "application_name": self.window_title,
                "risk": "navigation_only",
                "wait_after_seconds": 0.6,
            }
        ]
        payload = {
            **self._base_payload("ok"),
            "target": "wechat_app",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
        }
        if dry_run:
            return payload
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        result = self._activate_window()
        payload["executed_steps"] = [{**planned_steps[0], "result": result}]
        if result["status"] != "ok":
            payload.update({"status": "blocked", "reason": "wechat_activation_failed"})
            return payload
        time.sleep(float(planned_steps[0]["wait_after_seconds"]))
        verification_output = output_dir / "wechat.after_launch.png" if output_dir is not None else None
        verification = self.doctor_wechat(capture=True, output=verification_output)
        payload["verification"] = verification
        if verification["status"] == "blocked":
            payload.update({"status": "blocked", "reason": verification.get("reason")})
        elif verification.get("screen", {}).get("state") not in WECHAT_FOREGROUND_STATES:
            payload.update({"status": "needs_verification", "reason": "wechat_foreground_not_verified"})
        return payload

    def observe_wechat_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        payload = {
            **self._base_payload("ok"),
            "target": "wechat_screen",
            "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
        }
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        doctor = self.doctor_wechat(capture=False)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload

        window = _window_from_payload(doctor.get("window") or {})
        output = output_dir / "wechat.observe.png" if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        payload["screen"] = _redacted_screen(screen)
        payload["screen_state"] = screen.get("state", "unknown")
        payload["layout_hints"] = _wechat_layout_hints(screen)
        if screen.get("status") != "ok":
            payload.update({"status": "blocked", "reason": screen.get("reason")})
        elif screen.get("state") == "screen_permission_prompt":
            payload.update({"status": "blocked", "reason": screen.get("state")})
        elif screen.get("state") not in WECHAT_FOREGROUND_STATES:
            payload.update({"status": "needs_verification", "reason": "wechat_foreground_not_verified"})
        return payload

    def stage_wechat_draft(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        require_accessibility_verification: bool = False,
    ) -> dict[str, Any]:
        if not draft_text:
            return {
                **self._base_payload("blocked"),
                "action": "stage_draft",
                "reason": "empty_draft",
                "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
            }
        planned_steps = [
            {
                "intent": "copy_draft_to_clipboard",
                "risk": "draft_staging_only",
            },
            {
                "intent": "paste_clipboard_into_wechat_input",
                "risk": "draft_staging_only",
                "does_not_send": True,
                "requires_verified_wechat_screen": True,
            },
        ]
        payload = {
            **self._base_payload("ok"),
            "action": "stage_draft",
            "target": "wechat_message_input",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
            "requires_user_confirmation_before_send": True,
        }
        if dry_run:
            return payload
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        before = output_dir / "wechat.before_stage_draft.png" if output_dir is not None else None
        doctor = self.doctor_wechat(capture=True, output=before)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        screen_state = doctor.get("screen", {}).get("state")
        if screen_state != "wechat_chat":
            payload.update({"status": "blocked", "reason": "wechat_chat_input_not_verified", "screen_state": screen_state})
            return payload

        executed_steps: list[dict[str, Any]] = []
        previous_clipboard = self._read_clipboard()
        if previous_clipboard["status"] != "ok":
            payload.update({"status": "blocked", "reason": previous_clipboard["reason"]})
            return payload

        copy_result = {"status": "not_run"}
        paste_result = {"status": "not_run"}
        try:
            copy_result = self._copy_to_clipboard(draft_text)
            executed_steps.append({**planned_steps[0], "result": copy_result})
            if copy_result["status"] != "ok":
                payload.update({"status": "blocked", "reason": copy_result["reason"]})
                return payload
            paste_result = self._paste_clipboard_into_frontmost_app()
            executed_steps.append({**planned_steps[1], "result": paste_result})
            if paste_result["status"] != "ok":
                payload.update({"status": "blocked", "reason": paste_result["reason"]})
                return payload
            if require_accessibility_verification:
                focused_text = self._read_wechat_focused_text()
                observed_text = str(focused_text.get("text") or "") if focused_text.get("status") == "ok" else ""
                text_matches = focused_text.get("status") == "ok" and observed_text == draft_text
                payload["staged_text_verification"] = {
                    "status": "ok" if text_matches else "blocked",
                    "verification_method": "macos_accessibility_focused_ui_value",
                    "expected_payload_hash": payload["draft_fingerprint"],
                    "observed_text_hash": hashlib.sha256(observed_text.encode("utf-8")).hexdigest()
                    if focused_text.get("status") == "ok"
                    else None,
                    "observed_character_count": len(observed_text)
                    if focused_text.get("status") == "ok"
                    else None,
                }
                if focused_text.get("status") != "ok":
                    payload["staged_text_verification"]["reason"] = focused_text.get("reason")
                    payload.update({"status": "blocked", "reason": "staged_text_accessibility_read_failed"})
                    return payload
                if not text_matches:
                    payload["staged_text_verification"]["reason"] = "focused_input_text_mismatch"
                    payload.update({"status": "blocked", "reason": "staged_text_mismatch"})
                    return payload
                payload["staged_text_verified"] = True

            window = _window_from_payload(doctor.get("window") or {})
            after = output_dir / "wechat.after_stage_draft.png" if output_dir is not None else None
            payload["verification"] = _redacted_screen(self.capture_window(output=after, window=window))
            payload["next_host_action"] = "verify_staged_text_before_send"
        finally:
            payload["executed_steps"] = executed_steps
            restore_result = self._copy_to_clipboard(previous_clipboard.get("text", ""))
            payload["clipboard_restored"] = restore_result["status"] == "ok"
            payload["clipboard_restore_status"] = restore_result["status"]
            if restore_result["status"] != "ok":
                payload["clipboard_restore_reason"] = restore_result.get("reason")
            if restore_result["status"] != "ok" and paste_result.get("status") == "ok":
                payload.update({
                    "status": "degraded",
                    "reason": "clipboard_restore_failed",
                    "next_host_action": "verify_staged_text_and_clear_clipboard",
                })
        return payload

    def send_wechat_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        planned_steps = [
            {
                "intent": "stage_draft_with_accessibility_verification",
                "risk": "live_send_precondition",
                "requires_exact_text_match": True,
            },
            {
                "intent": "press_return_to_send_wechat_message",
                "risk": "live_send",
                "requires_explicit_authorization": True,
            },
            {
                "intent": "verify_input_cleared_and_capture_post_action_screen",
                "risk": "post_action_verification",
            },
        ]
        payload = {
            **self._base_payload("ok"),
            "action": "send_message",
            "target": "wechat_message_input",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            "blocked_actions": ["payments", "calls", "contact_exchange_without_user"],
            "live_send": True,
            "requires_explicit_authorization": True,
        }
        if dry_run:
            return payload
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        if target_binding is not None:
            target_verification = self._verify_wechat_target_binding(target_binding, output_dir=output_dir)
            payload["target_binding_verification"] = target_verification
            if target_verification.get("status") != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
                })
                return payload

        stage_payload = self.stage_wechat_draft(
            draft_text,
            dry_run=False,
            output_dir=output_dir,
            require_accessibility_verification=True,
        )
        payload["stage_status"] = stage_payload.get("status")
        payload["staged_text_verification"] = stage_payload.get("staged_text_verification")
        payload["clipboard_restored"] = stage_payload.get("clipboard_restored")
        if stage_payload.get("status") != "ok":
            payload.update({"status": "blocked", "reason": stage_payload.get("reason") or "stage_failed"})
            return payload

        send_result = self._press_return_key()
        payload["executed_steps"] = [
            {"intent": planned_steps[0]["intent"], "result": {"status": "ok"}},
            {"intent": planned_steps[1]["intent"], "result": send_result},
        ]
        if send_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": send_result["reason"]})
            return payload

        time.sleep(0.4)
        focused_after = self._read_wechat_focused_text()
        after_text = str(focused_after.get("text") or "") if focused_after.get("status") == "ok" else ""
        input_cleared = focused_after.get("status") == "ok" and not after_text.strip()
        payload["post_send_verification"] = {
            "status": "ok" if input_cleared else "needs_verification",
            "verification_method": "macos_accessibility_focused_ui_value",
            "input_cleared_after_send": input_cleared,
            "observed_character_count": len(after_text) if focused_after.get("status") == "ok" else None,
            "reason": focused_after.get("reason") if focused_after.get("status") != "ok" else None,
        }
        window_payload = stage_payload.get("preflight", {}).get("window") or {}
        window = _window_from_payload(window_payload)
        after = output_dir / "wechat.after_send_message.png" if output_dir is not None else None
        post_screen = self.capture_window(output=after, window=window)
        payload["post_action_observation"] = _redacted_screen(post_screen)
        post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or _now_iso()}:{uuid4().hex}"
        post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
        payload["post_action_observation_id"] = post_observation_id
        post_screen_captured = post_screen.get("status") == "ok"
        outbound_verification = _verify_outbound_message(post_screen, draft_text)
        payload["outbound_message_verification"] = outbound_verification
        outbound_verified = outbound_verification.get("status") == "ok"
        payload["evidence"] = {
            "staged_text_verified": bool(stage_payload.get("staged_text_verified")),
            "send_input_backend": send_result.get("input_backend"),
            "input_cleared_after_send": input_cleared,
            "post_action_screen_captured": post_screen_captured,
            "outbound_message_verified": outbound_verified,
            "post_action_observation_id": post_observation_id,
        }
        if not input_cleared:
            payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
        elif not post_screen_captured:
            payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
        elif not outbound_verified:
            payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
        return payload

    def observe_tinder_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        payload = {
            **self._base_payload("ok"),
            "target": "tinder_screen",
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        doctor = self.doctor(capture=False)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload

        window = _window_from_payload(doctor.get("window") or {})
        output = output_dir / "iphone_mirroring.observe.png" if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        payload["screen"] = _redacted_screen(screen)
        payload["screen_state"] = screen.get("state", "unknown")
        payload["layout_hints"] = _tinder_layout_hints(screen)
        if screen.get("status") != "ok":
            payload.update({"status": "blocked", "reason": screen.get("reason")})
        elif screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
            payload.update({"status": "blocked", "reason": screen.get("state")})
        elif screen.get("state") not in TINDER_FOREGROUND_STATES:
            payload.update({"status": "needs_verification", "reason": "tinder_foreground_not_verified"})
        return payload

    def launch_tinder(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        planned_steps = _launch_tinder_steps()
        payload = {
            **self._base_payload("ok"),
            "target": "tinder_app",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }
        doctor_output = None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            doctor_output = output_dir / "iphone_mirroring.before_launch.png"
        doctor = self.doctor(capture=True, output=doctor_output)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        state = doctor.get("screen", {}).get("state")
        if state in TINDER_FOREGROUND_STATES:
            payload["reason"] = "tinder_already_foreground"
            return payload
        if dry_run:
            return payload

        window_payload = doctor.get("window") or {}
        window = _window_from_payload(window_payload)
        executed_steps: list[dict[str, Any]] = []
        for step in planned_steps:
            result = self._execute_step(window, step)
            executed_steps.append({**step, "result": result})
            if result["status"] != "ok":
                payload.update({"status": "blocked", "reason": result["reason"], "executed_steps": executed_steps})
                return payload
            time.sleep(float(step.get("wait_after_seconds", 0.2)))
        payload["executed_steps"] = executed_steps
        verification_output = output_dir / "iphone_mirroring.after_launch.png" if output_dir is not None else None
        verification = self.capture_window(output=verification_output, window=window)
        payload["verification"] = _redacted_screen(verification)
        if verification["state"] not in TINDER_FOREGROUND_STATES:
            payload.update({"status": "needs_verification", "reason": "tinder_launch_not_verified"})
        return payload

    def open_tinder_profile(
        self,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        launch_if_needed: bool = False,
    ) -> dict[str, Any]:
        profile_step = _tap_step("tap_tinder_profile_tab", x=0.88, y=0.94)
        planned_steps = [profile_step]
        payload = {
            **self._base_payload("ok"),
            "target": "self_profile",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }

        doctor_output = None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            doctor_output = output_dir / "iphone_mirroring.before.png"
        doctor = self.doctor(capture=True, output=doctor_output)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        state = doctor.get("screen", {}).get("state")
        if state not in TINDER_FOREGROUND_STATES and launch_if_needed:
            planned_steps = [*_launch_tinder_steps(), profile_step]
            payload["planned_steps"] = planned_steps
            if dry_run:
                return payload
            launch = self.launch_tinder(dry_run=False, output_dir=output_dir)
            payload["launch"] = launch
            if launch["status"] != "ok":
                payload.update({"status": "blocked", "reason": launch.get("reason")})
                return payload
            doctor = self.doctor(capture=True, output=doctor_output)
            payload["preflight_after_launch"] = doctor
            if doctor["status"] == "blocked":
                payload.update({"status": "blocked", "reason": doctor.get("reason")})
                return payload
            state = doctor.get("screen", {}).get("state")
        if state not in TINDER_FOREGROUND_STATES:
            payload.update({"status": "blocked", "reason": "tinder_foreground_not_verified"})
            return payload
        if dry_run:
            return payload

        window_payload = doctor.get("window") or {}
        window = _window_from_payload(window_payload)
        click_result = self._click_ratio(window, profile_step["tap_ratio"])
        payload["executed_steps"] = [{**profile_step, "result": click_result}]
        if click_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": click_result["reason"]})
            return payload

        time.sleep(0.8)
        verify_output = None
        if output_dir is not None:
            verify_output = output_dir / "iphone_mirroring.after_open_profile.png"
        verification = self.capture_window(output=verify_output, window=window)
        payload["verification"] = _redacted_screen(verification)
        if verification["state"] != "tinder_self_profile":
            payload.update({"status": "needs_verification", "reason": "profile_screen_not_verified"})
        return payload

    def run_tinder_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        try:
            planned_steps = _tinder_action_steps(action, **options)
        except KeyError:
            return {
                **self._base_payload("blocked"),
                "action": action,
                "reason": "unknown_tinder_harness_action",
                "blocked_actions": list(BLOCKED_GUI_ACTIONS),
            }
        payload = {
            **self._base_payload("ok"),
            "action": action,
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }
        if dry_run:
            return payload
        return self._execute_planned_steps(payload, output_dir=output_dir)

    def run_tinder_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        try:
            planned_steps = _tinder_workflow_steps(workflow, **options)
        except KeyError:
            return {
                **self._base_payload("blocked"),
                "workflow": workflow,
                "reason": "unknown_tinder_harness_workflow",
                "blocked_actions": list(BLOCKED_GUI_ACTIONS),
            }
        payload = {
            **self._base_payload("ok"),
            "workflow": workflow,
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }
        if dry_run:
            return payload
        return self._execute_planned_steps(payload, output_dir=output_dir)

    def send_tinder_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_step = {
            "intent": "tap_tinder_message_input",
            "tap_ratio": {"x": 0.45, "y": 0.92},
            "risk": "live_send_precondition",
            "requires_verified_tinder_thread": True,
        }
        paste_step = {
            "intent": "paste_clipboard_into_tinder_message_input",
            "risk": "live_send_precondition",
            "requires_exact_text_match": True,
        }
        send_step = {
            "intent": "tap_tinder_send_button",
            "tap_ratio": {"x": 0.90, "y": 0.92},
            "risk": "live_send",
            "requires_explicit_authorization": True,
        }
        payload = {
            **self._base_payload("ok"),
            "action": "send_message",
            "target": "tinder_message_input",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": [input_step, paste_step, send_step],
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            "blocked_actions": ["like", "super_like", "unmatch", "report", "profile_edit"],
            "live_send": True,
            "requires_explicit_authorization": True,
        }
        if dry_run:
            return payload
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        preflight_output = output_dir / "iphone_mirroring.tinder.before_send_message.png" if output_dir is not None else None
        preflight = self.doctor(capture=True, output=preflight_output)
        payload["preflight"] = preflight
        if preflight["status"] != "ok":
            payload.update({"status": "blocked", "reason": preflight.get("reason") or "tinder_preflight_not_verified"})
            return payload
        window = _window_from_payload(preflight.get("window") or {})

        if target_binding is not None:
            target_verification = self._verify_tinder_target_binding(target_binding, output_dir=output_dir)
            payload["target_binding_verification"] = target_verification
            if target_verification.get("status") != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
                })
                return payload

        baseline_output = output_dir / "iphone_mirroring.tinder.before_stage_message.png" if output_dir is not None else None
        baseline_screen = self.capture_window(output=baseline_output, window=window)
        payload["pre_stage_observation"] = _redacted_screen(baseline_screen)
        if baseline_screen.get("status") != "ok":
            payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
            return payload
        if baseline_screen.get("state") != "tinder_conversation":
            payload.update({"status": "blocked", "reason": "tinder_conversation_not_verified"})
            return payload

        previous_clipboard = self._read_clipboard()
        payload["previous_clipboard_read"] = previous_clipboard["status"] == "ok"
        if previous_clipboard["status"] != "ok":
            payload.update({"status": "blocked", "reason": previous_clipboard.get("reason")})
            return payload
        copy_result = self._copy_to_clipboard(draft_text)
        payload["draft_clipboard_copy"] = copy_result["status"] == "ok"
        if copy_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": copy_result.get("reason")})
            return payload

        executed_steps: list[dict[str, Any]] = []
        stage_ready = False
        try:
            input_result = self._click_ratio(window, input_step["tap_ratio"])
            executed_steps.append({**input_step, "result": input_result})
            if input_result["status"] != "ok":
                payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
                return payload
            time.sleep(0.2)

            paste_result = self._paste_clipboard_into_frontmost_app()
            executed_steps.append({**paste_step, "result": paste_result})
            if paste_result["status"] != "ok":
                payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
                return payload
            time.sleep(0.3)

            staged_output = output_dir / "iphone_mirroring.tinder.after_stage_message.png" if output_dir is not None else None
            staged_screen = self.capture_window(output=staged_output, window=window)
            staged_verification = _verify_staged_tinder_message(
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
            )
            payload["staged_text_verification"] = staged_verification
            payload["staged_text_verified"] = staged_verification.get("status") == "ok"
            if staged_verification.get("status") != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": staged_verification.get("reason") or "staged_text_not_verified",
                    "executed_steps": executed_steps,
                })
                return payload
            stage_ready = True
        finally:
            restore_result = self._copy_to_clipboard(previous_clipboard.get("text", ""))
            payload["clipboard_restored"] = restore_result["status"] == "ok"
            payload["clipboard_restore_status"] = restore_result["status"]
            if restore_result["status"] != "ok":
                payload["clipboard_restore_reason"] = restore_result.get("reason")

        if not stage_ready:
            return payload
        if payload["clipboard_restored"] is not True:
            payload.update({
                "status": "blocked",
                "reason": "clipboard_restore_failed",
                "executed_steps": executed_steps,
            })
            return payload

        send_result = self._click_ratio(window, send_step["tap_ratio"])
        executed_steps.append({**send_step, "result": send_result})
        payload["executed_steps"] = executed_steps
        if send_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": send_result.get("reason")})
            return payload

        time.sleep(0.5)
        post_output = output_dir / "iphone_mirroring.tinder.after_send_message.png" if output_dir is not None else None
        post_screen = self.capture_window(output=post_output, window=window)
        payload["post_action_observation"] = _redacted_screen(post_screen)
        post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or _now_iso()}:{uuid4().hex}"
        post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
        payload["post_action_observation_id"] = post_observation_id
        post_screen_captured = post_screen.get("status") == "ok"
        outbound_verification = _verify_tinder_outbound_message(
            post_screen,
            draft_text,
            staged_screen=staged_screen,
        )
        payload["outbound_message_verification"] = outbound_verification
        outbound_verified = outbound_verification.get("status") == "ok"
        payload["evidence"] = {
            "staged_text_verified": payload["staged_text_verified"],
            "send_input_backend": send_result.get("input_backend"),
            "post_action_screen_captured": post_screen_captured,
            "outbound_message_verified": outbound_verified,
            "post_action_observation_id": post_observation_id,
        }
        if not post_screen_captured:
            payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
        elif not outbound_verified:
            payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
        return payload

    def _execute_planned_steps(self, payload: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        before = output_dir / "iphone_mirroring.before_action.png" if output_dir is not None else None
        doctor = self.doctor(capture=True, output=before)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        screen_state = doctor.get("screen", {}).get("state")
        if any(step.get("requires_verified_tinder_screen") for step in payload["planned_steps"]):
            if screen_state not in TINDER_FOREGROUND_STATES:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "tinder_foreground_not_verified",
                        "screen_state": screen_state,
                    }
                )
                return payload
        window = _window_from_payload(doctor.get("window") or {})
        executed_steps: list[dict[str, Any]] = []
        profile_read_captures: list[dict[str, Any]] = []
        profile_read_texts: list[str] = []
        for step in payload["planned_steps"]:
            if step["intent"] == "capture_profile_read_step":
                output = None
                if output_dir is not None:
                    output = output_dir / f"iphone_mirroring.profile_read_step_{len(profile_read_captures) + 1:02d}.png"
                screen = self.capture_window(output=output, window=window)
                result = {
                    "status": screen.get("status", "blocked"),
                    "screen": _redacted_screen(screen),
                }
                profile_read_captures.append(result["screen"])
                profile_read_texts.append(str(screen.get("text") or ""))
            elif step["intent"] == "safe_expand_visible_profile_section":
                output = None
                if output_dir is not None:
                    output = output_dir / f"iphone_mirroring.profile_expand_check_{len(profile_read_captures) + 1:02d}.png"
                screen = self.capture_window(output=output, window=window)
                observed_text = str(screen.get("text") or "")
                result = {
                    "status": screen.get("status", "blocked"),
                    "screen": _redacted_screen(screen),
                    "skipped": False,
                }
                if result["status"] != "ok":
                    result["reason"] = screen.get("reason") or "profile_expand_check_failed"
                elif _tinder_profile_danger_action_visible(observed_text):
                    result.update({"status": "ok", "skipped": True, "reason": "dangerous_profile_action_visible"})
                elif not _tinder_profile_expand_control_visible(observed_text):
                    result.update({"status": "ok", "skipped": True, "reason": "profile_expand_control_not_visible"})
                else:
                    click_result = self._click_ratio(window, step["tap_ratio"])
                    result.update({"click_result": click_result, "status": click_result["status"]})
                    if click_result["status"] != "ok":
                        result["reason"] = click_result.get("reason") or "profile_expand_click_failed"
                profile_read_captures.append(result["screen"])
                profile_read_texts.append(observed_text)
            else:
                result = self._execute_step(window, step)
            executed_steps.append({**step, "result": result})
            if result["status"] != "ok":
                payload.update({"status": "blocked", "reason": result.get("reason", "tinder_action_step_failed"), "executed_steps": executed_steps})
                return payload
            time.sleep(float(step.get("wait_after_seconds", 0.2)))
        payload["executed_steps"] = executed_steps
        if profile_read_captures:
            payload["profile_read_captures"] = profile_read_captures
            payload["field_coverage"] = _tinder_profile_field_coverage("\n".join(profile_read_texts))
        after = output_dir / "iphone_mirroring.after_action.png" if output_dir is not None else None
        payload["verification"] = _redacted_screen(self.capture_window(output=after, window=window))
        return payload

    def _activate_window(self) -> dict[str, Any]:
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
        script = (
            f'tell application "System Events" to tell process "{self.window_title}" '
            "to get {frontmost, position of window 1, size of window 1, name of window 1}"
        )
        result = self.runner.run(["osascript", "-e", script])
        if result.returncode != 0:
            return None
        return _parse_window_info(result.stdout)

    def _click_ratio(self, window: WindowInfo, ratio: dict[str, float]) -> dict[str, Any]:
        x = round(window.x + window.width * float(ratio["x"]))
        y = round(window.y + window.height * float(ratio["y"]))
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
        script_path = _core_graphics_click_script_path()
        script_path.write_text(_CORE_GRAPHICS_CLICK_SWIFT, encoding="utf-8")
        result = self.runner.run(["xcrun", "swift", str(script_path), str(x), str(y)])
        if result.returncode != 0:
            return {"status": "blocked", "reason": "core_graphics_click_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "point": {"x": x, "y": y}, "input_backend": "core_graphics"}

    def _swipe_ratio(self, window: WindowInfo, swipe: dict[str, Any]) -> dict[str, Any]:
        if not self._command_available("xcrun"):
            return {"status": "blocked", "reason": "missing_core_graphics_swipe_backend"}
        start = swipe["from"]
        end = swipe["to"]
        start_x = round(window.x + window.width * float(start["x"]))
        start_y = round(window.y + window.height * float(start["y"]))
        end_x = round(window.x + window.width * float(end["x"]))
        end_y = round(window.y + window.height * float(end["y"]))
        script_path = _core_graphics_drag_script_path()
        script_path.write_text(_CORE_GRAPHICS_DRAG_SWIFT, encoding="utf-8")
        result = self.runner.run(
            [
                "xcrun",
                "swift",
                str(script_path),
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(int(swipe.get("duration_ms", 350))),
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "core_graphics_swipe_failed", "stderr": _short(result.stderr)}
        return {
            "status": "ok",
            "from": {"x": start_x, "y": start_y},
            "to": {"x": end_x, "y": end_y},
            "input_backend": "core_graphics",
        }

    def _wheel_ratio(self, window: WindowInfo, wheel: dict[str, Any]) -> dict[str, Any]:
        if not self._command_available("xcrun"):
            return {"status": "blocked", "reason": "missing_core_graphics_wheel_backend"}
        x = round(window.x + window.width * float(wheel.get("x", 0.5)))
        y = round(window.y + window.height * float(wheel.get("y", 0.5)))
        delta_y = int(wheel.get("delta_y", 0))
        delta_x = int(wheel.get("delta_x", 0))
        repeats = max(1, int(wheel.get("repeats", 1)))
        interval_us = max(1000, int(wheel.get("interval_us", 18000)))
        script_path = _core_graphics_wheel_script_path()
        script_path.write_text(_CORE_GRAPHICS_WHEEL_SWIFT, encoding="utf-8")
        result = self.runner.run(
            [
                "xcrun",
                "swift",
                str(script_path),
                str(x),
                str(y),
                str(delta_y),
                str(delta_x),
                str(repeats),
                str(interval_us),
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "core_graphics_wheel_failed", "stderr": _short(result.stderr)}
        return {
            "status": "ok",
            "point": {"x": x, "y": y},
            "delta": {"x": delta_x, "y": delta_y},
            "repeats": repeats,
            "input_backend": "core_graphics_wheel",
        }

    def _click_iphone_mirroring_view_menu_item(self, item_name: str) -> dict[str, Any]:
        result = self.runner.run(
            [
                "osascript",
                "-e",
                (
                    f'tell application "System Events" to tell process "{self.window_title}" '
                    f'to click menu item "{item_name}" of menu "View" of menu bar 1'
                ),
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "iphone_mirroring_view_menu_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "menu_item": item_name, "input_backend": "applescript_menu"}

    def _execute_step(self, window: WindowInfo, step: dict[str, Any]) -> dict[str, Any]:
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
        if step["intent"] == "type_app_name":
            result = self.runner.run(["osascript", "-e", 'tell application "System Events" to keystroke "Tinder"'])
            if result.returncode != 0:
                return {"status": "blocked", "reason": "text_entry_failed", "stderr": _short(result.stderr)}
            return {"status": "ok"}
        if step["intent"] == "press_return":
            result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
            if result.returncode != 0:
                return {"status": "blocked", "reason": "return_key_failed", "stderr": _short(result.stderr)}
            return {"status": "ok"}
        return {"status": "blocked", "reason": "unknown_gui_step"}

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

    def _paste_clipboard_into_frontmost_app(self) -> dict[str, Any]:
        result = self.runner.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using {command down}',
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "clipboard_paste_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_accessibility"}

    def _verify_tinder_target_binding(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        markers = _target_binding_required_markers(target_binding)
        base = {
            "verification_method": "tinder_screen_ocr_required_visible_text",
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "required_marker_hashes": [_hash_text(marker) for marker in markers],
        }
        if not markers:
            return {**base, "status": "blocked", "reason": "target_binding_required"}
        window = self._window_info()
        if window is None:
            return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
        output = output_dir / "iphone_mirroring.tinder.target_binding.png" if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        observed_text = str(screen.get("text") or "")
        normalized = _normalize_text(observed_text)
        matched = [marker for marker in markers if _normalize_text(marker) in normalized]
        result = {
            **base,
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
            "observed_text_hash": _hash_text(observed_text) if observed_text else None,
            "matched_marker_hashes": [_hash_text(marker) for marker in matched],
        }
        if screen.get("status") != "ok":
            return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
        if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
            return {**result, "status": "blocked", "reason": screen.get("state")}
        if screen.get("state") != "tinder_conversation":
            return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
        if len(matched) != len(markers):
            return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
        return {**result, "status": "ok"}

    def _verify_wechat_target_binding(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        markers = _target_binding_required_markers(target_binding)
        base = {
            "verification_method": "wechat_screen_ocr_required_visible_text",
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "required_marker_hashes": [_hash_text(marker) for marker in markers],
        }
        if not markers:
            return {**base, "status": "blocked", "reason": "target_binding_required"}
        window = self._window_info()
        if window is None:
            return {**base, "status": "blocked", "reason": "wechat_window_not_found"}
        output = output_dir / "wechat.target_binding.png" if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        observed_text = str(screen.get("text") or "")
        normalized = _normalize_text(observed_text)
        matched = [marker for marker in markers if _normalize_text(marker) in normalized]
        result = {
            **base,
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
            "observed_text_hash": _hash_text(observed_text) if observed_text else None,
            "matched_marker_hashes": [_hash_text(marker) for marker in matched],
        }
        if screen.get("status") != "ok":
            return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
        if screen.get("state") != "wechat_chat":
            return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
        if len(matched) != len(markers):
            return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
        return {**result, "status": "ok"}

    def _read_wechat_focused_text(self) -> dict[str, Any]:
        result = self.runner.run(
            [
                "osascript",
                "-e",
                (
                    f'tell application "System Events" to tell process "{self.window_title}" '
                    'to get value of focused UI element'
                ),
            ]
        )
        if result.returncode != 0:
            return {"status": "blocked", "reason": "focused_input_read_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "text": result.stdout.rstrip("\r\n")}

    def _press_return_key(self) -> dict[str, Any]:
        result = self.runner.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
        if result.returncode != 0:
            return {"status": "blocked", "reason": "return_key_failed", "stderr": _short(result.stderr)}
        return {"status": "ok", "input_backend": "applescript_accessibility"}

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
        commands = ("osascript", "screencapture", "tesseract", "xcrun")
        if self.app_id in {"tinder", "wechat"}:
            commands = (*commands, "pbcopy", "pbpaste")
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
            "harness_backend": WECHAT_HARNESS_BACKEND if self.app_id == "wechat" else IPHONE_MIRRORING_HARNESS_BACKEND,
            "captured_at": _now_iso(),
        }


def classify_screen_text(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return "unknown"
    if "iphone mirroring is locked" in normalized or "enter password" in normalized or "touch id" in normalized:
        return "iphone_mirroring_locked"
    if "requesting to bypass" in normalized and "private window picker" in normalized:
        return "screen_permission_prompt"
    if any(marker in normalized for marker in ("edit profile", "编辑资料", "编辑个人资料", "edit info")):
        return "tinder_self_profile"
    if "个人资料" in normalized and any(marker in normalized for marker in ("完善个人资料", "添加一条", "设置")):
        return "tinder_self_profile"
    if _looks_like_tinder_chat_list_text(normalized):
        return "tinder_messages"
    if _looks_like_tinder_conversation_text(normalized):
        return "tinder_conversation"
    if _looks_like_tinder_profile_text(normalized):
        return "tinder_profile"
    if "等你回应" in normalized or ("配对" in normalized and any(marker in normalized for marker in ("消息", "聊天"))):
        return "tinder_messages"
    if all(marker in normalized for marker in ("滑动", "探索", "聊天", "个人资料")):
        return "tinder_home"
    if "tinder" in normalized and any(marker in normalized for marker in ("siri", "建议", "搜索", "search")):
        return "ios_search"
    if any(marker in normalized for marker in ("matches", "messages", "配对", "消息")) and "tinder" in normalized:
        return "tinder_messages"
    if "tinder" in normalized:
        return "tinder_unknown"
    if any(marker in normalized for marker in ("搜索", "search", "chrome", "phone", "电话", "微信")):
        return "ios_home_screen"
    return "unknown"


def classify_wechat_screen_text(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return "unknown"
    if "requesting to bypass" in normalized and "private window picker" in normalized:
        return "screen_permission_prompt"
    wechat_marker = "wechat" in normalized or "微信" in normalized
    chat_input_marker = any(marker in normalized for marker in ("发送", "send", "按住说话", "enter"))
    chat_history_marker = any(marker in normalized for marker in ("昨天", "今天", "分钟前", ":", "am", "pm"))
    chat_list_marker = any(marker in normalized for marker in ("通讯录", "contacts", "订阅号", "群聊", "chats"))
    if wechat_marker and chat_list_marker:
        return "wechat_chat_list"
    if wechat_marker and chat_input_marker and chat_history_marker:
        return "wechat_chat"
    if chat_input_marker and chat_history_marker:
        return "wechat_chat"
    if wechat_marker:
        return "wechat_unknown"
    return "unknown"


def classify_screen_image(path: Path) -> dict[str, str]:
    try:
        pixels = _read_png_pixels(path)
    except (OSError, ValueError, zlib.error, struct.error):
        return {"status": "failed", "state": "unknown"}
    if _looks_like_tinder_self_profile_top(pixels):
        return {"status": "ok", "state": "tinder_self_profile"}
    return {"status": "ok", "state": "unknown"}


def _combine_screen_states(text_state: str, visual_state: str) -> str:
    if text_state in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return text_state
    if text_state not in {"unknown", "tinder_unknown"}:
        return text_state
    if visual_state == "tinder_self_profile":
        return visual_state
    return text_state


def _looks_like_tinder_self_profile_top(pixels: dict[str, Any]) -> bool:
    avatar = _region_stats(pixels, 0.04, 0.07, 0.22, 0.19)
    edit_button = _region_stats(pixels, 0.24, 0.11, 0.62, 0.21)
    settings = _region_stats(pixels, 0.82, 0.07, 0.97, 0.19)
    bottom_profile = _region_stats(pixels, 0.76, 0.88, 0.98, 0.99)
    top_structure = (
        avatar["dark_ratio"] > 0.35
        and avatar["color_ratio"] > 0.04
        and edit_button["bright_ratio"] > 0.10
        and settings["dark_ratio"] > 0.60
        and settings["bright_ratio"] > 0.01
    )
    profile_tab_active = bottom_profile["mid_ratio"] > 0.15 and bottom_profile["bright_ratio"] > 0.005
    return top_structure or profile_tab_active


def _region_stats(pixels: dict[str, Any], x1: float, y1: float, x2: float, y2: float) -> dict[str, float]:
    width = int(pixels["width"])
    height = int(pixels["height"])
    rows = pixels["rows"]
    channels = int(pixels["channels"])
    start_x = max(0, min(width - 1, int(x1 * width)))
    end_x = max(start_x + 1, min(width, int(x2 * width)))
    start_y = max(0, min(height - 1, int(y1 * height)))
    end_y = max(start_y + 1, min(height, int(y2 * height)))
    total = bright = dark = mid = color = 0
    for row in rows[start_y:end_y]:
        for x in range(start_x, end_x):
            r, g, b = row[x * channels : x * channels + 3]
            lum = (int(r) + int(g) + int(b)) / 3
            total += 1
            if lum > 210:
                bright += 1
            if lum < 45:
                dark += 1
            if 55 <= lum <= 150:
                mid += 1
            if max(r, g, b) - min(r, g, b) > 35 and lum > 45:
                color += 1
    return {
        "bright_ratio": bright / total,
        "dark_ratio": dark / total,
        "mid_ratio": mid / total,
        "color_ratio": color / total,
    }


def _read_png_pixels(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a png")
    pos = 8
    width = height = channels = color_type = bit_depth = None
    raw = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        pos += 4
        chunk_type = data[pos : pos + 4]
        pos += 4
        chunk = data[pos : pos + length]
        pos += length + 4
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB",
                chunk,
            )
            if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("unsupported png format")
            channels = {2: 3, 6: 4}.get(color_type)
            if channels is None:
                raise ValueError("unsupported png color type")
        elif chunk_type == b"IDAT":
            raw += chunk
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or channels is None:
        raise ValueError("missing png header")
    scanlines = zlib.decompress(raw)
    rows = []
    i = 0
    previous = [0] * (width * channels)
    for _ in range(height):
        filter_type = scanlines[i]
        i += 1
        row = list(scanlines[i : i + width * channels])
        i += width * channels
        decoded = _decode_png_scanline(row, previous, channels, filter_type)
        rows.append(decoded)
        previous = decoded
    return {"width": width, "height": height, "channels": channels, "rows": rows}


def _decode_png_scanline(row: list[int], previous: list[int], channels: int, filter_type: int) -> list[int]:
    decoded = [0] * len(row)
    for index, value in enumerate(row):
        left = decoded[index - channels] if index >= channels else 0
        up = previous[index]
        upper_left = previous[index - channels] if index >= channels else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        elif filter_type == 4:
            predictor = _paeth(left, up, upper_left)
        else:
            raise ValueError("unsupported png filter")
        decoded[index] = (value + predictor) & 0xFF
    return decoded


def _paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distances = ((abs(estimate - left), left), (abs(estimate - up), up), (abs(estimate - upper_left), upper_left))
    return min(distances, key=lambda item: item[0])[1]


def _parse_window_info(stdout: str) -> WindowInfo | None:
    match = re.search(
        r"^\s*(true|false),\s*(-?\d+),\s*(-?\d+),\s*(\d+),\s*(\d+),\s*(.+?)\s*$",
        stdout.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    return WindowInfo(
        frontmost=match.group(1).lower() == "true",
        x=int(match.group(2)),
        y=int(match.group(3)),
        width=int(match.group(4)),
        height=int(match.group(5)),
        name=match.group(6),
    )


def _redacted_screen(screen: dict[str, Any]) -> dict[str, Any]:
    text = str(screen.get("text") or "")
    result = {key: value for key, value in screen.items() if key != "text"}
    if text:
        result["text_fingerprint"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        result["text_character_count"] = len(text)
    return result


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _target_binding_required_markers(target_binding: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    value = target_binding.get("required_visible_text")
    if isinstance(value, list):
        markers.extend(str(item).strip() for item in value if str(item).strip())
    visible_name = target_binding.get("visible_name")
    if isinstance(visible_name, str) and visible_name.strip():
        markers.append(visible_name.strip())
    unique: list[str] = []
    for marker in markers:
        if marker not in unique:
            unique.append(marker)
    return unique


def _looks_like_tinder_chat_list_text(normalized_text: str) -> bool:
    has_chat_title = "聊天" in normalized_text or "messages" in normalized_text
    has_chat_sections = any(marker in normalized_text for marker in ("新的配对", "new matches", "消息", "messages"))
    return has_chat_title and has_chat_sections


def _looks_like_tinder_profile_text(normalized_text: str) -> bool:
    profile_sections = sum(
        1
        for marker in ("关于我", "关键信息", "兴趣", "我想要", "基本信息", "生活方式", "about me", "interests")
        if marker in normalized_text
    )
    has_identity_header = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\s+\d{2}\b", normalized_text)) or any(
        marker in normalized_text for marker in ("已认证", "verified")
    )
    return profile_sections >= 2 and not _tinder_message_input_marker_present(normalized_text) and (
        has_identity_header or profile_sections >= 3
    )


def _looks_like_tinder_conversation_text(normalized_text: str) -> bool:
    if _looks_like_tinder_chat_list_text(normalized_text):
        return False
    if _looks_like_tinder_profile_text(normalized_text):
        return False
    if not _tinder_message_input_marker_present(normalized_text):
        return False
    stable_thread_marker = any(marker in normalized_text for marker in ("gif", "send", "发送"))
    visible_name_marker = bool(re.search(r"\b[a-z][a-z0-9_ .'-]{1,30}\b", normalized_text))
    return stable_thread_marker or visible_name_marker


def _tinder_message_input_marker_present(normalized_text: str) -> bool:
    english_input = bool(re.search(r"\b(message|send)\b", normalized_text))
    chinese_input = any(marker in normalized_text for marker in ("发送", "输入消息", "发消息", "说点什么", "键入信息"))
    return english_input or chinese_input


def _verify_staged_tinder_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    text_matches = bool(
        expected_text
        and (expected_text in observed_text or _normalize_text(expected_text) in _normalize_text(observed_text))
    )
    observed_stats = _expected_text_observation_stats(observed_text, expected_text)
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    baseline_stats = _expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    result = {
        "verification_method": "tinder_staged_message_ocr_payload_text",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": observed_stats["text_hash"],
        "observed_character_count": observed_stats["text_character_count"],
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "baseline_expected_text_occurrences": baseline_stats["expected_text_occurrences"] if baseline_stats else None,
        "baseline_text_hash": baseline_stats["text_hash"] if baseline_stats else None,
        "screen": _redacted_screen(screen),
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if not text_matches:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    return {**result, "status": "ok"}


def _verify_tinder_outbound_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    staged_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _verify_outbound_message(screen, expected_text)
    if result.get("status") != "ok":
        return result
    observed_text = str(screen.get("text") or "")
    staged_text = str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    observed_stats = _expected_text_observation_stats(observed_text, expected_text)
    staged_stats = _expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    extra = {
        "verification_method": "tinder_post_send_ocr_payload_text_delta",
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
    }
    if staged_stats and observed_stats["normalized_text_hash"] == staged_stats["normalized_text_hash"]:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}


def _verify_outbound_message(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    text_matches = bool(
        expected_text
        and (expected_text in observed_text or _normalize_text(expected_text) in _normalize_text(observed_text))
    )
    result = {
        "verification_method": "wechat_post_send_ocr_payload_text",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        "observed_character_count": len(observed_text) if observed_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "post_action_screen_not_captured"}
    if not text_matches:
        return {**result, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, "status": "ok"}


def _expected_text_observation_stats(text: str, expected_text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    normalized_expected = _normalize_text(expected_text)
    return {
        "text_hash": _hash_text(text) if text else None,
        "normalized_text_hash": _hash_text(normalized_text) if normalized_text else None,
        "text_character_count": len(text) if text else None,
        "expected_text_occurrences": normalized_text.count(normalized_expected) if normalized_expected else 0,
    }


def _tinder_profile_field_coverage(text: str) -> dict[str, bool]:
    normalized = _normalize_text(text)
    return {
        "about_me": any(marker in normalized for marker in ("关于我", "about me")),
        "key_info": any(marker in normalized for marker in ("关键信息", "key info")),
        "interests": any(marker in normalized for marker in ("兴趣", "interests")),
        "looking_for": any(marker in normalized for marker in ("我想要", "looking for")),
        "basic_info": any(marker in normalized for marker in ("基本信息", "basic info")),
        "lifestyle": any(marker in normalized for marker in ("生活方式", "lifestyle")),
    }


def _tinder_profile_expand_control_visible(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(marker in normalized for marker in ("查看所有", "查看更多", "show all", "show more"))


def _tinder_profile_danger_action_visible(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(marker in normalized for marker in ("取消配对", "举报", "屏蔽", "unmatch", "report", "block"))


def _tinder_layout_hints(screen: dict[str, Any]) -> dict[str, Any]:
    state = str(screen.get("state") or "unknown")
    normalized = _normalize_text(str(screen.get("text") or ""))
    page = {
        "tinder_home": "home",
        "tinder_messages": "chats",
        "tinder_conversation": "conversation",
        "tinder_self_profile": "self_profile",
        "tinder_profile": "profile",
        "tinder_unknown": "unknown_tinder",
    }.get(state, "unknown")
    return {
        "page": page,
        "bottom_active_tab": _bottom_active_tab_hint(state),
        "self_profile_header_present": state == "tinder_self_profile"
        or any(marker in normalized for marker in ("edit profile", "编辑资料", "编辑个人资料")),
        "self_profile_edit_button_present": any(
            marker in normalized for marker in ("edit profile", "编辑资料", "编辑个人资料")
        ),
        "settings_marker_present": any(marker in normalized for marker in ("settings", "设置")),
        "new_matches_carousel_present": state == "tinder_messages"
        and any(marker in normalized for marker in ("matches", "match", "配对", "新的配对")),
        "conversation_list_present": state == "tinder_messages"
        and any(marker in normalized for marker in ("messages", "message", "消息", "聊天")),
        "reply_required_marker_present": any(marker in normalized for marker in ("等你回应", "your turn")),
        "profile_expand_control_marker_present": any(
            marker in normalized for marker in ("查看所有", "show all", "查看更多")
        ),
    }


def _wechat_layout_hints(screen: dict[str, Any]) -> dict[str, Any]:
    state = str(screen.get("state") or "unknown")
    normalized = _normalize_text(str(screen.get("text") or ""))
    page = {
        "wechat_chat": "conversation",
        "wechat_chat_list": "chat_list",
        "wechat_unknown": "unknown_wechat",
    }.get(state, "unknown")
    return {
        "page": page,
        "conversation_window_present": state == "wechat_chat",
        "chat_list_present": state == "wechat_chat_list"
        or any(marker in normalized for marker in ("通讯录", "contacts", "订阅号", "群聊", "chats")),
        "message_input_marker_present": any(marker in normalized for marker in ("发送", "send", "按住说话", "enter")),
        "unread_marker_present": any(marker in normalized for marker in ("未读", "new message", "unread")),
        "draft_staging_requires_user_verification": True,
    }


def _bottom_active_tab_hint(state: str) -> str:
    if state == "tinder_self_profile":
        return "profile"
    if state == "tinder_messages":
        return "chats"
    if state == "tinder_home":
        return "home"
    return "unknown"


def _tap_step(intent: str, *, x: float, y: float) -> dict[str, Any]:
    return {
        "intent": intent,
        "tap_ratio": {"x": x, "y": y},
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }


def _swipe_step(intent: str, *, from_x: float, from_y: float, to_x: float, to_y: float, duration_ms: int = 350) -> dict[str, Any]:
    return {
        "intent": intent,
        "swipe": {
            "from": {"x": from_x, "y": from_y},
            "to": {"x": to_x, "y": to_y},
            "duration_ms": duration_ms,
        },
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }


def _wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "wheel": {
            "x": x,
            "y": y,
            "delta_y": delta_y,
            "delta_x": delta_x,
            "repeats": repeats,
            "interval_us": 18000,
        },
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }


def _capture_profile_read_step() -> dict[str, Any]:
    return {
        "intent": "capture_profile_read_step",
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
        "wait_after_seconds": 0.0,
    }


def _safe_expand_step() -> dict[str, Any]:
    return {
        "intent": "safe_expand_visible_profile_section",
        "tap_ratio": {"x": 0.50, "y": 0.76},
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }


def _tinder_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    match_index = int(options.get("match_index") or 1)
    row_y = min(0.86, 0.30 + (max(row_index, 1) - 1) * 0.12)
    match_x = min(0.86, 0.42 + (max(match_index, 1) - 1) * 0.24)
    target = str(options.get("target") or "row")
    conversation_x = 0.14 if target == "avatar" else 0.50
    actions: dict[str, list[dict[str, Any]]] = {
        "open-chats": [_tap_step("tap_chats_tab", x=0.66, y=0.94)],
        "matches-carousel-next": [_wheel_step("wheel_new_matches_left", x=0.56, y=0.30, delta_x=-20, repeats=18)],
        "matches-carousel-previous": [_wheel_step("wheel_new_matches_right", x=0.56, y=0.30, delta_x=20, repeats=18)],
        "open-new-match": [{**_tap_step("tap_new_match_card", x=match_x, y=0.30), "match_index": match_index}],
        "open-conversation": [
            {**_tap_step("tap_conversation_row", x=conversation_x, y=row_y), "row_index": row_index, "target": target}
        ],
        "open-thread-profile": [_tap_step("tap_thread_profile_avatar", x=0.50, y=0.14)],
        "open-self-profile-preview": [_tap_step("tap_self_profile_avatar", x=0.14, y=0.13)],
        "profile-photo-next": [_tap_step("tap_photo_next", x=0.86, y=0.45)],
        "profile-photo-previous": [_tap_step("tap_photo_previous", x=0.14, y=0.45)],
        "open-full-profile": [_tap_step("tap_profile_up_arrow", x=0.90, y=0.82)],
        "profile-scroll-down": [_wheel_step("wheel_profile_read_down", x=0.50, y=0.86, delta_y=-20, repeats=18)],
        "profile-scroll-up": [_wheel_step("wheel_profile_read_up", x=0.50, y=0.46, delta_y=20, repeats=18)],
        "expand-visible-profile-section": [_safe_expand_step()],
        "close-full-profile": [_tap_step("tap_profile_down_arrow", x=0.90, y=0.08)],
        "close-preview": [_tap_step("tap_preview_done", x=0.90, y=0.08)],
        "return-to-chats": [_tap_step("tap_thread_back_to_chats", x=0.09, y=0.13)],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]


def _tinder_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "self-profile-read":
        photo_steps = max(0, int(options.get("photo_steps", 1)))
        scroll_steps = max(0, int(options.get("scroll_steps", 1)))
        steps: list[dict[str, Any]] = []
        steps.extend(_tinder_action_steps("open-self-profile-preview"))
        for _ in range(photo_steps):
            steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("profile-photo-previous"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        steps.extend(_tinder_action_steps("close-preview"))
        return steps
    if workflow == "chat-read-match-profile":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps", 1)))
        conversation_row = int(options.get("conversation_row", 1))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        steps.extend(_tinder_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_tinder_action_steps("open-thread-profile"))
        steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        return steps
    if workflow == "new-match-open":
        carousel_swipes = max(0, int(options.get("carousel_swipes", 0)))
        match_index = int(options.get("match_index", 1))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        for _ in range(carousel_swipes):
            steps.extend(_tinder_action_steps("matches-carousel-next"))
        steps.extend(_tinder_action_steps("open-new-match", match_index=match_index))
        return steps
    if workflow == "new-match-read-profile":
        carousel_swipes = max(0, int(options.get("carousel_swipes", 0)))
        match_index = int(options.get("match_index", 1))
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps", 1)))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        for _ in range(carousel_swipes):
            steps.extend(_tinder_action_steps("matches-carousel-next"))
        steps.extend(_tinder_action_steps("open-new-match", match_index=match_index))
        steps.extend(_tinder_action_steps("open-thread-profile"))
        steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        return steps
    raise KeyError(workflow)


def _launch_tinder_steps() -> list[dict[str, Any]]:
    return [
        {
            "intent": "open_iphone_home_screen",
            "risk": "navigation_only",
            "wait_after_seconds": 0.8,
        },
        {
            "intent": "open_ios_spotlight",
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "type_app_name",
            "text": "Tinder",
            "risk": "navigation_only",
            "wait_after_seconds": 0.2,
        },
        {
            "intent": "press_return",
            "risk": "navigation_only",
            "wait_after_seconds": 1.0,
        },
    ]


def _window_from_payload(payload: dict[str, Any]) -> WindowInfo:
    return WindowInfo(
        frontmost=bool(payload.get("frontmost")),
        x=int(payload["x"]),
        y=int(payload["y"]),
        width=int(payload["width"]),
        height=int(payload["height"]),
        name=str(payload["name"]),
    )


def _default_screenshot_path() -> Path:
    return Path(tempfile.gettempdir()) / f"dating-boost-iphone-mirroring-{uuid4().hex}.png"


def _core_graphics_click_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_click.swift"


def _core_graphics_drag_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_drag.swift"


def _core_graphics_wheel_script_path() -> Path:
    return Path(tempfile.gettempdir()) / "dating_boost_core_graphics_wheel.swift"


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _short(text: str, limit: int = 300) -> str:
    return text[:limit]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_CORE_GRAPHICS_CLICK_SWIFT = """\
import CoreGraphics
import Foundation

let x = Double(CommandLine.arguments[1])!
let y = Double(CommandLine.arguments[2])!
let point = CGPoint(x: x, y: y)
let down = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
let up = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
down?.post(tap: .cghidEventTap)
usleep(120000)
up?.post(tap: .cghidEventTap)
"""


_CORE_GRAPHICS_DRAG_SWIFT = """\
import CoreGraphics
import Foundation

let startX = Double(CommandLine.arguments[1])!
let startY = Double(CommandLine.arguments[2])!
let endX = Double(CommandLine.arguments[3])!
let endY = Double(CommandLine.arguments[4])!
let durationMs = max(1, Int(CommandLine.arguments[5])!)
let steps = 12
let source = CGEventSource(stateID: .hidSystemState)
let start = CGPoint(x: startX, y: startY)
let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: start, mouseButton: .left)
down?.post(tap: .cghidEventTap)
for index in 1...steps {
    let t = Double(index) / Double(steps)
    let point = CGPoint(x: startX + (endX - startX) * t, y: startY + (endY - startY) * t)
    let drag = CGEvent(mouseEventSource: source, mouseType: .leftMouseDragged, mouseCursorPosition: point, mouseButton: .left)
    drag?.post(tap: .cghidEventTap)
    usleep(useconds_t(durationMs * 1000 / steps))
}
let end = CGPoint(x: endX, y: endY)
let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: end, mouseButton: .left)
up?.post(tap: .cghidEventTap)
"""


_CORE_GRAPHICS_WHEEL_SWIFT = """\
import CoreGraphics
import Foundation

let x = Double(CommandLine.arguments[1])!
let y = Double(CommandLine.arguments[2])!
let deltaY = Int32(CommandLine.arguments[3])!
let deltaX = Int32(CommandLine.arguments[4])!
let repeats = max(1, Int(CommandLine.arguments[5])!)
let intervalUs = useconds_t(max(1000, Int(CommandLine.arguments[6])!))
let point = CGPoint(x: x, y: y)
let source = CGEventSource(stateID: .hidSystemState)
CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?
    .post(tap: .cghidEventTap)
usleep(50000)
for _ in 0..<repeats {
    CGEvent(scrollWheelEvent2Source: source, units: .pixel, wheelCount: 2, wheel1: deltaY, wheel2: deltaX, wheel3: 0)?
        .post(tap: .cghidEventTap)
    usleep(intervalUs)
}
"""
