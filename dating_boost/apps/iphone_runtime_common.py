from __future__ import annotations

from dating_boost.apps.iphone_targeting_common import *

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
            "reason": "iphone_mirroring_window_not_found",
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
    app_observer = getattr(self, "app_screen_state_observer", None)
    if callable(app_observer):
        text = ocr_payload.get("text", "")
        observed = app_observer(output, text)
        text_state = observed["text_state"]
        visual = {
            "status": observed["visual_status"],
            "state": observed["visual_state"],
            "active_tab": observed.get("visual_active_tab", "unknown"),
            "bottom_nav_present": observed.get("visual_bottom_nav_present", False),
        }
        for key in (
            "chat_list_visual_present",
            "chat_list_visual_signal",
            "message_list_top_anchor_present",
            "message_list_top_anchor_signal",
            "recommend_card_visual_present",
            "recommend_card_visual_signal",
            "conversation_toolbar_present",
        ):
            if key in observed:
                visual[key] = observed[key]
        state = observed["state"]
    elif self.app_id == "wechat":
        text_state = classify_wechat_screen_text(ocr_payload.get("text", ""))
        visual = {"status": "not_applicable", "state": "unknown"}
        state = text_state
    elif self.app_id == "bumble":
        text = ocr_payload.get("text", "")
        text_state = classify_bumble_screen_text(text)
        visual = classify_bumble_screen_image(output)
        state = _combine_bumble_screen_states(
            text_state,
            visual["state"],
            text,
            visual_bottom_nav_present=bool(visual.get("bottom_nav_present")),
        )
    else:
        text = ocr_payload.get("text", "")
        text_state = classify_screen_text(text)
        visual = classify_screen_image(output)
        state = _combine_screen_states(text_state, visual["state"], text)
    payload = {
        "schema_version": GUI_HARNESS_SCHEMA_VERSION,
        "status": "ok",
        "path": str(output),
        "state": state,
        "text_state": text_state,
        "visual_state": visual["state"],
        "visual_status": visual["status"],
        "visual_active_tab": visual.get("active_tab", "unknown"),
        "visual_bottom_nav_present": visual.get("bottom_nav_present", False),
        "ocr_status": ocr_payload["status"],
        "ocr_error": ocr_payload.get("error"),
        "text": ocr_payload.get("text", ""),
    }
    for key in (
        "chat_list_visual_present",
        "chat_list_visual_signal",
        "message_list_top_anchor_present",
        "message_list_top_anchor_signal",
        "recommend_card_visual_present",
        "recommend_card_visual_signal",
        "conversation_toolbar_present",
    ):
        if key in visual:
            payload[key] = visual[key]
    return payload


def _execute_planned_steps(self, payload: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    capture_prefix = "mac_ios_app" if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND else "iphone_mirroring"
    use_ocr = self.harness_backend != MAC_IOS_APP_HARNESS_BACKEND
    before = output_dir / f"{capture_prefix}.before_action.png" if output_dir is not None else None
    doctor = self.doctor(capture=True, output=before, ocr=use_ocr)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    screen_state = doctor.get("screen", {}).get("state")
    window = _window_from_payload(doctor.get("window") or {})
    planned_steps = payload.get("planned_steps")
    if not isinstance(planned_steps, list):
        payload.update({"status": "blocked", "reason": "gui_planned_steps_not_list"})
        return payload
    for step_index, step in enumerate(planned_steps, start=1):
        validation_reason = harness_step_validation_reason(step)
        if validation_reason is not None:
            payload.update({"status": "blocked", "reason": validation_reason, "step_index": step_index, "step": step})
            return payload
    requires_paywall = any(step.get("requires_tinder_subscription_paywall") for step in planned_steps)
    requires_feedback_survey = any(step.get("requires_tinder_feedback_survey") for step in planned_steps)
    if requires_paywall:
        if screen_state != TINDER_SUBSCRIPTION_PAYWALL_STATE:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "tinder_subscription_paywall_not_visible",
                    "screen_state": screen_state,
                }
            )
            return payload
    elif requires_feedback_survey:
        if screen_state != TINDER_FEEDBACK_SURVEY_STATE:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "tinder_feedback_survey_not_visible",
                    "screen_state": screen_state,
                }
            )
            return payload
    elif screen_state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="pre_action",
        )
        payload["subscription_paywall_recovery"] = recovery
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
                }
            )
            return payload
        screen_state = recovery.get("verification", {}).get("state")
    if any(step.get("requires_verified_tinder_screen") for step in planned_steps):
        if screen_state not in TINDER_FOREGROUND_STATES:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "tinder_foreground_not_verified",
                    "screen_state": screen_state,
                }
            )
            return payload
    if any(step.get("requires_verified_bumble_screen") for step in planned_steps):
        if screen_state not in BUMBLE_FOREGROUND_STATES:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "bumble_foreground_not_verified",
                    "screen_state": screen_state,
                }
            )
            return payload
    app_verified_screen_key = getattr(self, "app_verified_screen_key", None)
    app_foreground_states = getattr(self, "app_foreground_states", None)
    if app_verified_screen_key and any(step.get(app_verified_screen_key) for step in planned_steps):
        if screen_state not in set(app_foreground_states or ()):
            payload.update(
                {
                    "status": "blocked",
                    "reason": getattr(self, "app_foreground_not_verified_reason", "app_foreground_not_verified"),
                    "screen_state": screen_state,
                }
            )
            return payload
    executed_steps: list[dict[str, Any]] = []
    profile_read_captures: list[dict[str, Any]] = []
    profile_read_texts: list[str] = []
    for step in planned_steps:
        precondition = self._verify_bumble_step_precondition(
            window,
            step,
            output_dir=output_dir,
            step_index=len(executed_steps) + 1,
        )
        if precondition["status"] == "ok":
            app_precondition_verifier = getattr(self, "app_step_precondition_verifier", None)
            if callable(app_precondition_verifier):
                precondition = app_precondition_verifier(
                    self,
                    window,
                    step,
                    output_dir=output_dir,
                    step_index=len(executed_steps) + 1,
                )
        if precondition["status"] != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": precondition["reason"],
                    "screen_state": precondition.get("screen_state"),
                    "precondition": precondition,
                }
            )
            return payload
        if step["intent"] == "capture_profile_read_step":
            output = None
            if output_dir is not None:
                output = output_dir / f"{capture_prefix}.profile_read_step_{len(profile_read_captures) + 1:02d}.png"
            screen = self.capture_window(output=output, window=window, ocr=use_ocr)
            result = {
                "status": screen.get("status", "blocked"),
                "screen": _redacted_screen(screen),
            }
            profile_read_captures.append(result["screen"])
            profile_read_texts.append(str(screen.get("text") or ""))
        elif step["intent"] == "safe_expand_visible_profile_section":
            output = None
            if output_dir is not None:
                output = output_dir / f"{capture_prefix}.profile_expand_check_{len(profile_read_captures) + 1:02d}.png"
            screen = self.capture_window(output=output, window=window, ocr=use_ocr)
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
        executed_step = {**step, "result": result}
        if result["status"] != "ok":
            executed_steps.append(executed_step)
            payload.update({"status": "blocked", "reason": result.get("reason", "tinder_action_step_failed"), "executed_steps": executed_steps})
            return payload
        time.sleep(max(DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(step.get("wait_after_seconds", 0.0))))
        postcondition = self._verify_bumble_step_postcondition(
            window,
            step,
            output_dir=output_dir,
            step_index=len(executed_steps) + 1,
        )
        if postcondition.get("status") == "ok" and postcondition.get("checked") is False:
            app_postcondition_verifier = getattr(self, "app_step_postcondition_verifier", None)
            if callable(app_postcondition_verifier):
                postcondition = app_postcondition_verifier(
                    self,
                    window,
                    step,
                    output_dir=output_dir,
                    step_index=len(executed_steps) + 1,
                )
        if postcondition["status"] != "ok":
            executed_step["postcondition"] = postcondition
            executed_steps.append(executed_step)
            payload.update(
                {
                    "status": "blocked",
                    "reason": postcondition["reason"],
                    "screen_state": postcondition.get("screen_state"),
                    "postcondition": postcondition,
                    "executed_steps": executed_steps,
                }
            )
            return payload
        if postcondition.get("status") == "ok" and postcondition.get("checked"):
            executed_step["postcondition"] = postcondition
        executed_steps.append(executed_step)
    payload["executed_steps"] = executed_steps
    if profile_read_captures:
        payload["profile_read_captures"] = profile_read_captures
        app_profile_field_coverage = getattr(self, "app_profile_field_coverage", None)
        if callable(app_profile_field_coverage):
            payload["field_coverage"] = app_profile_field_coverage("\n".join(profile_read_texts))
        elif self.app_id == "bumble":
            payload["field_coverage"] = _bumble_profile_field_coverage("\n".join(profile_read_texts))
        else:
            payload["field_coverage"] = _tinder_profile_field_coverage("\n".join(profile_read_texts))
    after = output_dir / f"{capture_prefix}.after_action.png" if output_dir is not None else None
    verification_screen = self.capture_window(output=after, window=window, ocr=use_ocr)
    payload["verification"] = _redacted_screen(verification_screen)
    if verification_screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="after_action",
        )
        _apply_tinder_paywall_recovery_result(payload, recovery)
    return payload


__all__ = [name for name in globals() if not name.startswith("__")]
