from __future__ import annotations

from dating_boost.apps.iphone_targeting_common import *
from dating_boost.apps.iphone_anchoring import (
    _locate_iphone_message_list_visual_anchor_target,
    _verify_open_conversation_target_binding_against_screen,
    _visible_text_contains_marker,
)

def _prepare_iphone_message_page(
    self,
    payload: dict[str, Any],
    *,
    app_id: str,
    output_dir: Path | None,
    output_prefix: str,
    chat_list_state: str,
    returnable_states: set[str],
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    secondary_close_steps: dict[str, dict[str, Any]],
    guardrails: dict[str, Any],
    layout_hints_fn: Any,
    message_list_visual_anchor_scan_region: dict[str, float],
) -> dict[str, Any]:
    payload.update(guardrails)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = self.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor.get("status") == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    window = _window_from_payload(doctor.get("window") or {})
    initial_output = output_dir / f"{output_prefix}.prepare_message_page.initial.png" if output_dir is not None else None
    screen = self.capture_window(output=initial_output, window=window)
    payload["initial_observation"] = _redacted_screen(screen)
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason") or "prepare_message_page_initial_capture_failed"})
        return payload
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        payload.update({"status": "blocked", "reason": screen.get("state")})
        return payload

    executed_steps: list[dict[str, Any]] = []
    recoveries: list[dict[str, Any]] = []
    for attempt in range(4):
        state = str(screen.get("state") or "unknown")
        recovery_result = _recover_iphone_prepare_message_page_blocker(
            self,
            payload,
            app_id=app_id,
            state=state,
            window=window,
            output_dir=output_dir,
            output_prefix=output_prefix,
            attempt=attempt,
            recoveries=recoveries,
            executed_steps=executed_steps,
        )
        if recovery_result.get("return_payload") is not None:
            return recovery_result["return_payload"]
        if recovery_result.get("screen") is not None:
            screen = recovery_result["screen"]
            continue

        if state == chat_list_state:
            return _finish_iphone_message_page_ready(
                payload,
                screen,
                state=state,
                layout_hints_fn=layout_hints_fn,
                message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region,
                executed_steps=executed_steps,
                recoveries=recoveries,
            )

        step_result = _select_iphone_prepare_message_page_step(
            payload,
            app_id=app_id,
            state=state,
            screen=screen,
            returnable_states=returnable_states,
            foreground_states=foreground_states,
            open_chats_step=open_chats_step,
            return_to_chats_step=return_to_chats_step,
            secondary_close_steps=secondary_close_steps,
            executed_steps=executed_steps,
        )
        if step_result.get("return_payload") is not None:
            return step_result["return_payload"]

        execution = _execute_iphone_prepare_message_page_step(
            self,
            payload,
            step_result["step"],
            window=window,
            output_dir=output_dir,
            output_prefix=output_prefix,
            attempt=attempt,
            executed_steps=executed_steps,
        )
        if execution.get("return_payload") is not None:
            return execution["return_payload"]
        screen = execution["screen"]

    payload.update(
        {
            "status": "blocked",
            "reason": f"{chat_list_state}_not_verified",
            "screen_state": screen.get("state", "unknown"),
            "executed_steps": executed_steps,
        }
    )
    if recoveries:
        payload["recoveries"] = recoveries
    return payload


def _recover_iphone_prepare_message_page_blocker(
    self,
    payload: dict[str, Any],
    *,
    app_id: str,
    state: str,
    window: Any,
    output_dir: Path | None,
    output_prefix: str,
    attempt: int,
    recoveries: list[dict[str, Any]],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if app_id == "tinder" and state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label=f"prepare_message_page_{attempt + 1:02d}",
        )
        recoveries.append({"kind": "subscription_paywall", "result": recovery})
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
                    "recoveries": recoveries,
                    "executed_steps": executed_steps,
                }
            )
            return {"return_payload": payload}
        recovery_output = (
            output_dir / f"{output_prefix}.prepare_message_page.after_paywall_recovery_{attempt + 1:02d}.png"
            if output_dir is not None
            else None
        )
        return {"screen": self.capture_window(output=recovery_output, window=window)}
    if app_id == "tinder" and state == TINDER_FEEDBACK_SURVEY_STATE:
        recovery = self._dismiss_tinder_feedback_survey(
            window,
            output_dir=output_dir,
            label=f"prepare_message_page_{attempt + 1:02d}",
        )
        recoveries.append({"kind": "feedback_survey", "result": recovery})
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_feedback_survey_recovery_failed",
                    "recoveries": recoveries,
                    "executed_steps": executed_steps,
                }
            )
            return {"return_payload": payload}
        recovery_output = (
            output_dir / f"{output_prefix}.prepare_message_page.after_feedback_recovery_{attempt + 1:02d}.png"
            if output_dir is not None
            else None
        )
        return {"screen": self.capture_window(output=recovery_output, window=window)}
    return {}


def _finish_iphone_message_page_ready(
    payload: dict[str, Any],
    screen: dict[str, Any],
    *,
    state: str,
    layout_hints_fn: Any,
    message_list_visual_anchor_scan_region: dict[str, float],
    executed_steps: list[dict[str, Any]],
    recoveries: list[dict[str, Any]],
) -> dict[str, Any]:
    payload["prepared_message_page_observation"] = _redacted_screen(screen)
    payload["screen_state"] = state
    payload["layout_hints"] = layout_hints_fn(screen)
    payload["next_host_action"] = "visual_plan_message_list"
    payload["message_list_planning_contract"] = {
        "source": "fresh_message_list_observation",
        "use_visual_row_anchor_for_non_ocr_rows": True,
        "message_list_visual_anchor_scan_region": dict(message_list_visual_anchor_scan_region),
        "record_tap_ratio_from_visual_plan": True,
        "allowed_target_bindings": ["chat_list_row_to_thread", "current_thread_visual_identity"],
        "visible_name_navigation_allowed": True,
        "generic_ui_markers_are_not_target_binding": True,
        "fixed_row_index_only_compatibility_fallback": True,
    }
    if executed_steps:
        payload["executed_steps"] = executed_steps
    if recoveries:
        payload["recoveries"] = recoveries
    return payload


def _select_iphone_prepare_message_page_step(
    payload: dict[str, Any],
    *,
    app_id: str,
    state: str,
    screen: dict[str, Any],
    returnable_states: set[str],
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    secondary_close_steps: dict[str, dict[str, Any]],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if state in secondary_close_steps:
        return {"step": secondary_close_steps[state]}
    if state in returnable_states:
        return {"step": return_to_chats_step}
    if state in foreground_states:
        if app_id == "bumble" and not _bumble_top_level_bottom_nav_present(screen):
            payload.update(
                {
                    "status": "blocked",
                    "reason": "bumble_top_level_tab_bar_not_verified",
                    "screen_state": state,
                    "executed_steps": executed_steps,
                }
            )
            return {"return_payload": payload}
        return {"step": open_chats_step}
    payload.update(
        {
            "status": "blocked",
            "reason": f"{app_id}_foreground_not_verified",
            "screen_state": state,
            "executed_steps": executed_steps,
        }
    )
    return {"return_payload": payload}


def _execute_iphone_prepare_message_page_step(
    self,
    payload: dict[str, Any],
    step: dict[str, Any],
    *,
    window: Any,
    output_dir: Path | None,
    output_prefix: str,
    attempt: int,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    result = self._execute_step(window, step)
    executed_steps.append({**step, "result": result})
    if result.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": result.get("reason") or "prepare_message_page_step_failed",
                "executed_steps": executed_steps,
            }
        )
        return {"return_payload": payload}
    time.sleep(float(step.get("wait_after_seconds", 0.2)))
    output = output_dir / f"{output_prefix}.prepare_message_page.after_step_{attempt + 1:02d}.png" if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    if screen.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": screen.get("reason") or "prepare_message_page_step_capture_failed",
                "executed_steps": executed_steps,
            }
        )
        return {"return_payload": payload}
    return {"screen": screen}


def _open_conversation_by_message_list_visual_anchor(
    self,
    *,
    app_id: str,
    visual_evidence: dict[str, Any],
    target_binding: dict[str, Any] | None,
    output_dir: Path | None,
    chat_list_state: str,
    conversation_state: str,
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    planned_steps: list[dict[str, Any]],
    tap_intent: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
    output_prefix: str,
    verification_method: str,
    source_states: set[str],
    blocked_state_reasons: dict[str, str],
    guardrails: dict[str, Any],
) -> dict[str, Any]:
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        **self._base_payload("ok"),
        "action": "open-conversation",
        "mode": "execute",
        "open_mode": "message_list_visual_anchor",
        "message_list_visual_anchor": _redacted_message_list_visual_anchor_evidence(visual_evidence),
        "target_binding": _redacted_target_binding(target_binding) if target_binding is not None else None,
        "planned_steps": planned_steps,
        **guardrails,
    }
    executed_steps: list[dict[str, Any]] = []

    preflight = _preflight_iphone_visual_anchor_open_conversation(
        self,
        payload,
        app_id=app_id,
        output_dir=output_dir,
        output_prefix=output_prefix,
    )
    if preflight.get("return_payload") is not None:
        return preflight["return_payload"]

    navigation = _navigate_iphone_to_visual_anchor_source(
        self,
        payload,
        app_id=app_id,
        window=preflight["window"],
        screen_state=preflight["screen_state"],
        chat_list_state=chat_list_state,
        conversation_state=conversation_state,
        foreground_states=foreground_states,
        open_chats_step=open_chats_step,
        return_to_chats_step=return_to_chats_step,
        executed_steps=executed_steps,
    )
    if navigation.get("return_payload") is not None:
        return navigation["return_payload"]

    opened = _relocate_and_tap_iphone_visual_anchor_target(
        self,
        payload,
        app_id=app_id,
        visual_evidence=visual_evidence,
        window=preflight["window"],
        output_dir=output_dir,
        output_prefix=output_prefix,
        chat_list_state=chat_list_state,
        conversation_state=conversation_state,
        tap_intent=tap_intent,
        tap_x=tap_x,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
        executed_steps=executed_steps,
    )
    if opened.get("return_payload") is not None:
        return opened["return_payload"]

    return _verify_iphone_visual_anchor_open_conversation_target(
        payload,
        app_id=app_id,
        target_binding=target_binding,
        verification_screen=opened["verification_screen"],
        conversation_state=conversation_state,
        verification_method=verification_method,
        source_states=source_states,
        blocked_state_reasons=blocked_state_reasons,
    )


def _preflight_iphone_visual_anchor_open_conversation(
    self,
    payload: dict[str, Any],
    *,
    app_id: str,
    output_dir: Path | None,
    output_prefix: str,
) -> dict[str, Any]:
    before = output_dir / f"{output_prefix}.open_conversation.before.png" if output_dir is not None else None
    doctor = self.doctor(capture=True, output=before)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return {"return_payload": payload}
    window = _window_from_payload(doctor.get("window") or {})
    screen_state = doctor.get("screen", {}).get("state")
    if app_id == "tinder" and screen_state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="open_conversation_visual_anchor",
        )
        payload["subscription_paywall_recovery"] = recovery
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
                }
            )
            return {"return_payload": payload}
        screen_state = recovery.get("verification", {}).get("state")
    if app_id == "tinder" and screen_state == TINDER_FEEDBACK_SURVEY_STATE:
        recovery = self._dismiss_tinder_feedback_survey(
            window,
            output_dir=output_dir,
            label="open_conversation_visual_anchor",
        )
        payload["feedback_survey_recovery"] = recovery
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_feedback_survey_recovery_failed",
                }
            )
            return {"return_payload": payload}
        screen_state = recovery.get("verification", {}).get("state")
    return {"window": window, "screen_state": screen_state}


def _navigate_iphone_to_visual_anchor_source(
    self,
    payload: dict[str, Any],
    *,
    app_id: str,
    window: Any,
    screen_state: str,
    chat_list_state: str,
    conversation_state: str,
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if screen_state == conversation_state:
        back_result = self._execute_step(window, return_to_chats_step)
        executed_steps.append({**return_to_chats_step, "result": back_result})
        if back_result.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": back_result.get("reason") or "return_to_chats_failed",
                    "executed_steps": executed_steps,
                }
            )
            return {"return_payload": payload}
        time.sleep(float(return_to_chats_step.get("wait_after_seconds", 0.2)))
        return {}
    if screen_state == chat_list_state:
        return {}
    if screen_state not in foreground_states:
        payload.update(
            {
                "status": "blocked",
                "reason": f"{app_id}_foreground_not_verified",
                "screen_state": screen_state,
            }
        )
        return {"return_payload": payload}
    open_result = self._execute_step(window, open_chats_step)
    executed_steps.append({**open_chats_step, "result": open_result})
    if open_result.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": open_result.get("reason") or "open_chats_failed",
                "executed_steps": executed_steps,
            }
        )
        return {"return_payload": payload}
    time.sleep(float(open_chats_step.get("wait_after_seconds", 0.2)))
    return {}


def _relocate_and_tap_iphone_visual_anchor_target(
    self,
    payload: dict[str, Any],
    *,
    app_id: str,
    visual_evidence: dict[str, Any],
    window: Any,
    output_dir: Path | None,
    output_prefix: str,
    chat_list_state: str,
    conversation_state: str,
    tap_intent: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    list_output = output_dir / f"{output_prefix}.conversation_visual_anchor_list.png" if output_dir is not None else None
    list_screen = self.capture_window(output=list_output, window=window)
    location = _locate_iphone_message_list_visual_anchor_target(
        list_screen,
        visual_evidence,
        chat_list_state=chat_list_state,
        tap_x=tap_x,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
    )
    relocation = {
        "status": location.get("status"),
        "message_list_screen": _redacted_screen(list_screen),
        "message_list_location": location,
    }
    payload["message_list_relocation"] = relocation
    if location.get("status") != "ok":
        relocation["reason"] = location.get("reason") or "target_relocation_visual_anchor_not_found"
        payload.update(
            {
                "status": "blocked",
                "reason": relocation["reason"],
                "executed_steps": executed_steps,
            }
        )
        return {"return_payload": payload}
    tap_step_result = _iphone_visual_anchor_tap_step(
        app_id,
        location,
        tap_intent=tap_intent,
        chat_list_state=chat_list_state,
        conversation_state=conversation_state,
    )
    if tap_step_result.get("return_payload") is not None:
        payload.update(tap_step_result["return_payload"])
        payload["executed_steps"] = executed_steps
        return {"return_payload": payload}
    tap_step = tap_step_result["tap_step"]
    tap_result = self._execute_step(window, tap_step)
    executed_steps.append({**tap_step, "result": tap_result})
    payload["executed_steps"] = executed_steps
    if tap_result.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": tap_result.get("reason") or "tap_visual_anchor_conversation_row_failed",
            }
        )
        return {"return_payload": payload}
    time.sleep(float(tap_step.get("wait_after_seconds", 0.2)))
    verification_output = output_dir / f"{output_prefix}.open_conversation.after_visual_anchor_tap.png" if output_dir is not None else None
    verification_screen = self.capture_window(output=verification_output, window=window)
    payload["verification"] = _redacted_screen(verification_screen)
    if verification_screen.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": verification_screen.get("reason") or "open_conversation_verification_failed",
            }
        )
        return {"return_payload": payload}
    return {"verification_screen": verification_screen}


def _iphone_visual_anchor_tap_step(
    app_id: str,
    location: dict[str, Any],
    *,
    tap_intent: str,
    chat_list_state: str,
    conversation_state: str,
) -> dict[str, Any]:
    tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
    if tap_ratio is None:
        return {"return_payload": {"status": "blocked", "reason": "target_relocation_tap_ratio_unavailable"}}
    if app_id == "bumble":
        tap_step = {
            **_bumble_tap_step(
                tap_intent,
                x=float(tap_ratio["x"]),
                y=float(tap_ratio["y"]),
                requires_states=chat_list_state,
                expected_states=conversation_state,
            ),
            "location_method": location.get("location_method"),
            "message_list_location": location,
        }
    else:
        tap_step = {
            **_tap_step(tap_intent, x=float(tap_ratio["x"]), y=float(tap_ratio["y"])),
            "location_method": location.get("location_method"),
            "message_list_location": location,
        }
    return {"tap_step": tap_step}


def _verify_iphone_visual_anchor_open_conversation_target(
    payload: dict[str, Any],
    *,
    app_id: str,
    target_binding: dict[str, Any] | None,
    verification_screen: dict[str, Any],
    conversation_state: str,
    verification_method: str,
    source_states: set[str],
    blocked_state_reasons: dict[str, str],
) -> dict[str, Any]:
    blocked_reason = blocked_state_reasons.get(str(verification_screen.get("state") or ""))
    if blocked_reason:
        payload.update(
            {
                "status": "blocked",
                "reason": blocked_reason,
                "next_host_action": "ask_user_to_confirm_opening_move_reply"
                if blocked_reason == "bumble_opening_move_requires_user_confirmation"
                else None,
            }
        )
        return payload
    if verification_screen.get("state") != conversation_state:
        payload.update(
            {
                "status": "blocked",
                "reason": "target_conversation_not_verified",
                "screen_state": verification_screen.get("state"),
            }
        )
        return payload
    target_result = _verify_open_conversation_target_binding_against_screen(
        app_id,
        target_binding,
        verification_screen,
        fallback_marker="",
        verification_method=verification_method,
        conversation_state=conversation_state,
        source_states=source_states,
        blocked_state_reasons=blocked_state_reasons,
    )
    payload["target_binding_verification"] = target_result
    if target_result.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": target_result.get("reason") or "target_binding_mismatch",
            }
        )
        return payload
    return payload


def _locate_visible_text_y_ratio(self, screen: dict[str, Any], marker: str) -> dict[str, Any]:
    marker_hash = _hash_text(marker)
    path = screen.get("path")
    if screen.get("status") != "ok":
        return {"status": "blocked", "reason": screen.get("reason") or "screen_not_captured", "target_marker_hash": marker_hash}
    if not isinstance(path, str) or not path:
        return {"status": "blocked", "reason": "screen_path_required", "target_marker_hash": marker_hash}
    tsv = self._ocr_tsv(Path(path))
    if tsv.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": tsv.get("reason") or "visible_text_ocr_tsv_failed",
            "target_marker_hash": marker_hash,
        }
    return _visible_text_location_from_tsv(str(tsv.get("text") or ""), marker, Path(path))


def _ocr_tsv(self, image_path: Path) -> dict[str, str]:
    if not self._command_available("tesseract"):
        return {"status": "unavailable", "text": "", "reason": "ocr_unavailable"}
    result = self.runner.run(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "-l",
            "eng+chi_sim",
            "--psm",
            "6",
            "tsv",
        ]
    )
    if result.returncode != 0:
        fallback = self.runner.run(["tesseract", str(image_path), "stdout", "--psm", "6", "tsv"])
        if fallback.returncode != 0:
            return {"status": "failed", "text": "", "error": _short(fallback.stderr or result.stderr)}
        return {"status": "ok", "text": fallback.stdout}
    return {"status": "ok", "text": result.stdout}


def _visible_text_location_from_tsv(tsv_text: str, marker: str, image_path: Path) -> dict[str, Any]:
    marker_hash = _hash_text(marker)
    try:
        image_height = int(_read_png_pixels_for_send_button(image_path)["height"])
    except (OSError, ValueError, zlib.error, struct.error):
        image_height = 0
    if image_height <= 0:
        return {"status": "blocked", "reason": "locator_image_dimensions_unavailable", "target_marker_hash": marker_hash}
    lines: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        key = (
            str(row.get("block_num") or ""),
            str(row.get("par_num") or ""),
            str(row.get("line_num") or ""),
        )
        lines.setdefault(key, []).append(row)
    for rows in lines.values():
        line_text = " ".join(str(row.get("text") or "").strip() for row in rows if str(row.get("text") or "").strip())
        if not _visible_text_contains_marker(line_text, marker):
            continue
        bounds: list[tuple[int, int]] = []
        for row in rows:
            try:
                top = int(float(str(row.get("top") or "0")))
                height = int(float(str(row.get("height") or "0")))
            except ValueError:
                continue
            bounds.append((top, top + height))
        if not bounds:
            continue
        y_ratio = (min(top for top, _bottom in bounds) + max(bottom for _top, bottom in bounds)) / 2 / image_height
        return {
            "status": "ok",
            "target_marker_hash": marker_hash,
            "line_hash": _hash_text(line_text),
            "line_character_count": len(line_text),
            "y_ratio": round(y_ratio, 4),
        }
    return {"status": "not_found", "reason": "visible_text_marker_not_found", "target_marker_hash": marker_hash}


__all__ = [name for name in globals() if not name.startswith("__")]
