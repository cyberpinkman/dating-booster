from __future__ import annotations

import hashlib

from dating_boost.core import gui_harness as _platform


for _name, _value in vars(_platform).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

del _name, _value

from dating_boost.core.send_pipeline import (  # noqa: E402
    EvidencePayload,
    PostSendVerification,
    SendAttemptContext,
    StagingResult,
)
from dating_boost.apps.iphone_planning import (  # noqa: E402
    BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
    IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
    _bumble_action_steps,
    _bumble_profile_field_coverage,
    _bumble_tap_step,
    _bumble_workflow_steps,
    _copy_tap_ratio,
    _has_bumble_step_postcondition,
    _has_bumble_step_precondition,
    _int_in_range,
    _launch_app_steps,
    _launch_tinder_steps,
    _message_list_visual_anchor_evidence_from_options,
    _normalized_visual_anchor_region,
    _redacted_iphone_prepare_message_page_payload,
    _redacted_message_list_visual_anchor_evidence,
    _redacted_target_binding,
    _target_binding_primary_visible_name,
    _target_binding_required_markers,
    _tap_ratio_option,
    _tap_step,
    _tinder_feedback_survey_dismiss_step,
    _tinder_action_steps,
    _tinder_subscription_paywall_dismiss_step,
    _tinder_workflow_steps,
    _verify_bumble_step_state,
    _visual_anchor_hamming_distance,
)
from dating_boost.core.harness_steps import (  # noqa: E402
    harness_step_validation_reason,
)
from dating_boost.core.target_binding import (  # noqa: E402
    RowToThreadBindingSpec,
    finish_row_to_thread_screen_verification,
    row_to_thread_base_result,
    validate_row_to_thread_structural_evidence,
)
from dating_boost.core.live_send_contract import (  # noqa: E402
    target_binding_specific_marker_present,
    target_binding_structural_evidence_present,
)


BLOCKED_GUI_ACTIONS = ["send", "like", "super_like", "unmatch", "report", "profile_edit"]
WECHAT_BLOCKED_GUI_ACTIONS = ["send", "payments", "calls", "contact_exchange_without_user"]
BUMBLE_BLOCKED_GUI_ACTIONS = [
    "send",
    "like",
    "superswipe",
    "pass",
    "unmatch",
    "report",
    "profile_edit",
    "premium_purchase",
    "opening_move_enable",
    "opening_move_skip",
    "opening_move_decide_reply_satisfaction",
    "opening_move_send",
]
BUMBLE_SEND_BLOCKED_GUI_ACTIONS = [
    "like",
    "superswipe",
    "pass",
    "unmatch",
    "report",
    "profile_edit",
    "premium_purchase",
    "opening_move_enable",
    "opening_move_skip",
    "opening_move_decide_reply_satisfaction",
    "opening_move_autonomous_send",
]
BUMBLE_OPENING_MOVE_POLICY: dict[str, Any] = {
    "scope": "bumble_opening_move",
    "female_user": {
        "agent_decision_authority": "none",
        "user_decision_required": [
            "enable_opening_move",
            "skip_opening_move",
            "accept_male_reply",
            "reject_male_reply",
        ],
        "agent_allowed_actions": [
            "observe_opening_move_prompt",
            "summarize_visible_reply",
            "ask_user_to_decide",
        ],
        "agent_disallowed_actions": [
            "enable_opening_move",
            "skip_opening_move",
            "accept_male_reply",
            "reject_male_reply",
        ],
    },
    "male_user": {
        "agent_may_draft_reply": True,
        "requires_user_confirmation_before_send": True,
        "current_harness_stage_supported": True,
        "current_harness_send_supported": True,
        "autonomous_opening_move_send_supported": False,
        "agent_allowed_actions": ["draft_opening_move_reply"],
        "agent_disallowed_actions": [
            "send_opening_move_reply_without_user_confirmation",
            "autonomous_opening_move_send",
        ],
    },
}
TINDER_SUBSCRIPTION_PAYWALL_STATE = "tinder_subscription_paywall"
TINDER_FEEDBACK_SURVEY_STATE = "tinder_feedback_survey"
DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS = 2.0
IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO = 0.90
IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y = 0.86
IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE = 12
IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS = 3



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
                return payload
            recovery_output = (
                output_dir / f"{output_prefix}.prepare_message_page.after_paywall_recovery_{attempt + 1:02d}.png"
                if output_dir is not None
                else None
            )
            screen = self.capture_window(output=recovery_output, window=window)
            continue
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
                return payload
            recovery_output = (
                output_dir / f"{output_prefix}.prepare_message_page.after_feedback_recovery_{attempt + 1:02d}.png"
                if output_dir is not None
                else None
            )
            screen = self.capture_window(output=recovery_output, window=window)
            continue
        if state == chat_list_state:
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
        if state in secondary_close_steps:
            step = secondary_close_steps[state]
        elif state in returnable_states:
            step = return_to_chats_step
        elif state in foreground_states:
            if app_id == "bumble" and not _bumble_top_level_bottom_nav_present(screen):
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "bumble_top_level_tab_bar_not_verified",
                        "screen_state": state,
                        "executed_steps": executed_steps,
                    }
                )
                return payload
            step = open_chats_step
        else:
            payload.update(
                {
                    "status": "blocked",
                    "reason": f"{app_id}_foreground_not_verified",
                    "screen_state": state,
                    "executed_steps": executed_steps,
                }
            )
            return payload

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
            return payload
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
            return payload

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
    before = output_dir / f"{output_prefix}.open_conversation.before.png" if output_dir is not None else None
    doctor = self.doctor(capture=True, output=before)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
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
            return payload
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
            return payload
        screen_state = recovery.get("verification", {}).get("state")

    executed_steps: list[dict[str, Any]] = []
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
            return payload
        time.sleep(float(return_to_chats_step.get("wait_after_seconds", 0.2)))
    elif screen_state != chat_list_state:
        if screen_state not in foreground_states:
            payload.update(
                {
                    "status": "blocked",
                    "reason": f"{app_id}_foreground_not_verified",
                    "screen_state": screen_state,
                }
            )
            return payload
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
            return payload
        time.sleep(float(open_chats_step.get("wait_after_seconds", 0.2)))

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
        return payload
    tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
    if tap_ratio is None:
        payload.update(
            {
                "status": "blocked",
                "reason": "target_relocation_tap_ratio_unavailable",
                "executed_steps": executed_steps,
            }
        )
        return payload
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
        return payload
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
        return payload
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


def _recover_iphone_current_thread_visual_identity_mismatch(
    self,
    *,
    app_id: str,
    target_binding: dict[str, Any],
    target_verification: dict[str, Any] | None,
    output_dir: Path | None,
    chat_list_state: str,
    conversation_state: str,
    foreground_states: set[str],
    open_chats_step: dict[str, Any],
    return_to_chats_step: dict[str, Any],
    secondary_close_steps: dict[str, dict[str, Any]],
    guardrails: dict[str, Any],
    layout_hints_fn: Any,
    message_list_visual_anchor_scan_region: dict[str, float],
    blocked_state_reasons: dict[str, str],
    tap_intent: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
    output_prefix: str,
    verify_target_binding: Any,
    max_attempts: int = IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS,
) -> dict[str, Any]:
    base = {
        "recovery_method": f"{app_id}_iphone_mirroring_message_list_visual_relocation",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "attempt_limit": max_attempts,
        "requires_message_list_visual_evidence": True,
        "uses_fixed_row_index": False,
        "uses_header_ocr": False,
    }
    if target_binding.get("binding_type") != "current_thread_visual_identity":
        return {
            **base,
            "status": "blocked",
            "reason": (target_verification or {}).get("reason") or "target_binding_visual_identity_required",
            "recovery_skipped": True,
        }
    if (target_verification or {}).get("reason") != "target_binding_visual_anchor_mismatch":
        return {
            **base,
            "status": "blocked",
            "reason": (target_verification or {}).get("reason") or "target_binding_mismatch",
            "recovery_skipped": True,
        }

    evidence = _message_list_visual_anchor_evidence_from_options(
        {},
        target_binding=target_binding,
        default_scan_region=message_list_visual_anchor_scan_region,
        default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    )
    if evidence.get("status") != "ok":
        return {
            **base,
            **evidence,
            "status": "blocked",
            "reason": evidence.get("reason") or "target_relocation_visual_evidence_required",
        }

    attempts: list[dict[str, Any]] = []
    for attempt_index in range(1, max_attempts + 1):
        prepare_payload = self._prepare_iphone_message_page(
            {
                **self._base_payload("ok"),
                "action": "recover-target-binding",
                "mode": "execute",
                "attempt_index": attempt_index,
                **guardrails,
            },
            app_id=app_id,
            output_dir=output_dir,
            output_prefix=output_prefix,
            chat_list_state=chat_list_state,
            returnable_states={conversation_state},
            foreground_states=foreground_states,
            open_chats_step=open_chats_step,
            return_to_chats_step=return_to_chats_step,
            secondary_close_steps=secondary_close_steps,
            guardrails=guardrails,
            layout_hints_fn=layout_hints_fn,
            message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region,
        )
        attempt: dict[str, Any] = {
            "attempt_index": attempt_index,
            "message_list_recovery": _redacted_iphone_prepare_message_page_payload(prepare_payload),
        }
        if prepare_payload.get("status") != "ok":
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": prepare_payload.get("reason") or "target_relocation_message_list_not_verified",
                "attempts": attempts,
            }

        window = self._window_info()
        if window is None:
            attempts.append(attempt)
            return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found", "attempts": attempts}
        list_output = output_dir / f"{output_prefix}.target_relocation_{attempt_index:02d}.message_list.png" if output_dir is not None else None
        list_screen = self.capture_window(output=list_output, window=window)
        location = _locate_iphone_message_list_visual_anchor_target(
            list_screen,
            evidence,
            chat_list_state=chat_list_state,
            tap_x=tap_x,
            tap_y_min=tap_y_min,
            tap_y_max=tap_y_max,
        )
        attempt["message_list_location"] = location
        if location.get("status") != "ok":
            attempts.append(attempt)
            if attempt_index < max_attempts:
                time.sleep(0.25)
                continue
            break

        tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
        if tap_ratio is None:
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": "target_relocation_tap_ratio_unavailable",
                "attempts": attempts,
            }
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
        click_result = self._execute_step(window, tap_step)
        attempt["open_target_click"] = {**tap_step, "result": click_result}
        if click_result.get("status") != "ok":
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": click_result.get("reason") or "target_relocation_open_click_failed",
                "attempts": attempts,
            }
        time.sleep(float(tap_step.get("wait_after_seconds", 0.2)))

        verification = verify_target_binding(target_binding, output_dir=output_dir)
        attempt["target_binding_verification"] = verification
        attempts.append(attempt)
        if verification.get("status") == "ok":
            return {
                **base,
                "status": "ok",
                "attempt_count": attempt_index,
                "attempts": attempts,
                "target_binding_verification": {
                    **verification,
                    "recovered_by": "message_list_visual_relocation",
                    "relocation_attempt_count": attempt_index,
                },
            }
        if verification.get("reason") != "target_binding_visual_anchor_mismatch":
            return {
                **base,
                "status": "blocked",
                "reason": verification.get("reason") or "target_relocation_target_verification_failed",
                "attempts": attempts,
            }

    return {
        **base,
        "status": "blocked",
        "reason": "target_binding_visual_relocation_exhausted",
        "last_reason": (
            attempts[-1].get("target_binding_verification", {}).get("reason")
            if attempts and isinstance(attempts[-1].get("target_binding_verification"), dict)
            else attempts[-1].get("message_list_location", {}).get("reason")
            if attempts and isinstance(attempts[-1].get("message_list_location"), dict)
            else None
        ),
        "attempts": attempts,
    }


def _verify_iphone_current_thread_visual_identity(
    self,
    *,
    app_id: str,
    target_binding: dict[str, Any],
    output_dir: Path | None,
    conversation_state: str,
    blocked_state_reasons: dict[str, str],
    output_name: str,
    verification_method: str,
) -> dict[str, Any]:
    thread_evidence = (
        target_binding.get("thread_evidence")
        if isinstance(target_binding.get("thread_evidence"), dict)
        else {}
    )
    expected_visual_hash = str(thread_evidence.get("visual_anchor_hash") or "").strip()
    visual_region = _normalized_visual_anchor_region(
        thread_evidence.get("visual_anchor_region"),
        fallback=IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    ) or dict(IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    max_distance = _int_in_range(
        thread_evidence.get("visual_anchor_max_hamming_distance"),
        default=IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE,
        minimum=0,
        maximum=32,
    )
    base = {
        "verification_method": verification_method,
        "binding_type": target_binding.get("binding_type"),
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "conversation_fingerprint_hash": _hash_text(str(target_binding.get("conversation_fingerprint") or "")),
        "pre_action_observation_id": thread_evidence.get("observation_id"),
        "latest_inbound_fingerprint_hash": _hash_text(str(thread_evidence.get("latest_inbound_fingerprint") or "")),
        "expected_visual_anchor_hash": expected_visual_hash or None,
        "visual_anchor_region": visual_region,
        "visual_anchor_max_hamming_distance": max_distance,
        "requires_visual_anchor": True,
        "requires_header_marker": False,
        "requires_fresh_conversation_screen": True,
        "uses_header_ocr": False,
        "visual_only_exact_verification_allowed": False,
    }
    if not target_binding_structural_evidence_present(app_id, target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
    window = self._window_info()
    if window is None:
        return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
    output = output_dir / output_name if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    screen_path = str(screen.get("path") or "")
    if screen_path:
        try:
            visual_hash_result = _iphone_visual_anchor_hash_for_pixels(
                _read_png_pixels_for_send_button(Path(screen_path)),
                region=visual_region,
            )
        except Exception as exc:
            visual_hash_result = {
                "status": "blocked",
                "reason": "target_binding_visual_anchor_read_failed",
                "error": str(exc)[:80],
            }
    else:
        visual_hash_result = {"status": "blocked", "reason": "target_binding_screen_path_missing"}
    observed_visual_hash = str(visual_hash_result.get("visual_anchor_hash") or "")
    visual_distance = (
        _visual_anchor_hamming_distance(expected_visual_hash, observed_visual_hash)
        if expected_visual_hash and observed_visual_hash
        else None
    )
    result = {
        **base,
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_hash_status": visual_hash_result.get("status"),
        "observed_visual_anchor_hash": observed_visual_hash or None,
        "visual_anchor_hamming_distance": visual_distance,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    blocked_reason = blocked_state_reasons.get(str(screen.get("state") or ""))
    if blocked_reason:
        return {**result, "status": "blocked", "reason": blocked_reason}
    if screen.get("state") != conversation_state:
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if visual_hash_result.get("status") != "ok":
        return {
            **result,
            "status": "blocked",
            "reason": visual_hash_result.get("reason") or "target_binding_visual_anchor_unavailable",
        }
    if visual_distance is None or visual_distance > max_distance:
        return {**result, "status": "blocked", "reason": "target_binding_visual_anchor_mismatch"}
    return {**result, "status": "ok"}


def _verify_chat_list_row_target_binding(
    self,
    *,
    app_id: str,
    target_binding: dict[str, Any],
    output_dir: Path | None,
    source_states: set[str],
    conversation_state: str,
    blocked_state_reasons: dict[str, str],
    output_name: str,
    verification_method: str,
) -> dict[str, Any]:
    spec = RowToThreadBindingSpec(
        app_id=app_id,
        verification_method=verification_method,
        source_states=frozenset(source_states),
        conversation_state=conversation_state,
        window_missing_reason="iphone_mirroring_window_not_found",
        blocked_state_reasons=dict(blocked_state_reasons),
    )
    base = row_to_thread_base_result(target_binding, spec=spec)
    structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
    if structural_block is not None:
        return structural_block
    window = self._window_info()
    if window is None:
        return base.with_status("blocked", spec.window_missing_reason)
    output = output_dir / output_name if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    return finish_row_to_thread_screen_verification(
        base,
        screen=screen,
        redacted_screen=_redacted_screen(screen),
        observed_text=observed_text,
        spec=spec,
    )


def _bumble_guardrails_payload() -> dict[str, Any]:
    return {
        "blocked_actions": list(BUMBLE_BLOCKED_GUI_ACTIONS),
        "opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY),
    }


def _locate_iphone_message_list_visual_anchor_target(
    list_screen: dict[str, Any],
    evidence: dict[str, Any],
    *,
    chat_list_state: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    if list_screen.get("status") != "ok":
        return {"status": "blocked", "reason": list_screen.get("reason") or "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != chat_list_state:
        return {
            "status": "blocked",
            "reason": "target_relocation_message_list_not_verified",
            "screen_state": list_screen.get("state", "unknown"),
        }
    expected_hash = str(evidence.get("visual_anchor_hash") or "").strip()
    source_region = evidence.get("visual_anchor_region") if isinstance(evidence.get("visual_anchor_region"), dict) else None
    scan_region = evidence.get("visual_anchor_scan_region") if isinstance(evidence.get("visual_anchor_scan_region"), dict) else None
    if not expected_hash or source_region is None or scan_region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_evidence_incomplete"}
    path = str(list_screen.get("path") or "")
    if not path:
        return {"status": "blocked", "reason": "target_relocation_message_list_screen_path_missing"}
    try:
        screen_pixels = _read_png_pixels_for_send_button(Path(path))
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "target_binding_visual_anchor_read_failed",
            "error": str(exc)[:80],
        }

    row_height = max(0.03, min(0.28, float(source_region["y2"]) - float(source_region["y1"])))
    row_width = max(0.05, min(1.0, float(source_region["x2"]) - float(source_region["x1"])))
    scan_y1 = max(0.0, min(1.0 - row_height, float(scan_region["y1"])))
    scan_y2 = max(scan_y1 + row_height, min(1.0, float(scan_region["y2"])))
    source_x1 = max(0.0, min(1.0 - row_width, float(source_region["x1"])))
    source_x2 = source_x1 + row_width
    tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
    tap_y_offset = 0.5
    prior_tap_y: float | None = None
    if tap_ratio is not None:
        tap_y_offset = (float(tap_ratio["y"]) - float(source_region["y1"])) / row_height
        prior_tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    tap_y_offset = max(0.05, min(0.95, tap_y_offset))
    max_distance = int(evidence.get("visual_anchor_max_hamming_distance") or IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE)
    step_y = max(0.004, min(0.012, row_height / 12.0))
    best: dict[str, Any] | None = None
    candidate_count = 0
    y = scan_y1
    while y <= scan_y2 - row_height + 0.0001:
        region = {"x1": source_x1, "y1": y, "x2": source_x2, "y2": y + row_height}
        hash_result = _iphone_visual_anchor_hash_for_pixels(screen_pixels, region=region)
        candidate_count += 1
        observed_hash = str(hash_result.get("visual_anchor_hash") or "")
        distance = (
            _visual_anchor_hamming_distance(expected_hash, observed_hash)
            if hash_result.get("status") == "ok" and observed_hash
            else None
        )
        candidate = {
            "status": hash_result.get("status"),
            "visual_anchor_region": region,
            "observed_visual_anchor_hash": observed_hash or None,
            "visual_anchor_hamming_distance": distance,
            "visual_anchor_tap_y_delta": (
                abs(max(0.0, min(1.0, y + row_height * tap_y_offset)) - prior_tap_y)
                if prior_tap_y is not None
                else None
            ),
        }
        if distance is not None and (
            best is None
            or distance < int(best["visual_anchor_hamming_distance"])
            or (
                distance == int(best["visual_anchor_hamming_distance"])
                and candidate["visual_anchor_tap_y_delta"] is not None
                and (
                    best.get("visual_anchor_tap_y_delta") is None
                    or float(candidate["visual_anchor_tap_y_delta"]) < float(best["visual_anchor_tap_y_delta"])
                )
            )
        ):
            best = candidate
        y += step_y
    if best is None:
        return {
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_unavailable",
            "candidate_count": candidate_count,
        }
    if int(best["visual_anchor_hamming_distance"]) > max_distance:
        return {
            **best,
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_not_found",
            "expected_visual_anchor_hash": expected_hash,
            "visual_anchor_max_hamming_distance": max_distance,
            "candidate_count": candidate_count,
        }
    matched_region = best["visual_anchor_region"]
    raw_tap_ratio = {
        "x": max(0.0, min(1.0, float(tap_ratio["x"]) if tap_ratio is not None else tap_x)),
        "y": max(0.0, min(1.0, float(matched_region["y1"]) + row_height * tap_y_offset)),
    }
    safe_tap = _safe_iphone_message_list_visual_anchor_tap_ratio(
        raw_tap_ratio,
        matched_region=matched_region,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
    )
    return {
        **best,
        "status": "ok",
        "location_method": "message_list_visual_anchor_scan",
        "expected_visual_anchor_hash": expected_hash,
        "visual_anchor_max_hamming_distance": max_distance,
        "candidate_count": candidate_count,
        "tap_ratio": safe_tap["tap_ratio"],
        "raw_tap_ratio": raw_tap_ratio,
        "tap_adjustment": safe_tap["tap_adjustment"],
        "uses_fixed_row_index": False,
        "visual_anchor_scanned": True,
    }


def _safe_iphone_message_list_visual_anchor_tap_ratio(
    tap_ratio: dict[str, float],
    *,
    matched_region: dict[str, Any],
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    try:
        region_y1 = float(matched_region["y1"])
        region_y2 = float(matched_region["y2"])
    except (KeyError, TypeError, ValueError):
        region_y1 = tap_y
        region_y2 = tap_y
    reasons: list[str] = []
    bottom_row = region_y2 >= IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO or tap_y >= tap_y_max
    if bottom_row:
        safe_y = min(tap_y, tap_y_max, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y)
        if safe_y < tap_y:
            tap_y = safe_y
            reasons.append("bottom_row_safe_tap_guard")
    else:
        tap_y = max(tap_y_min, min(tap_y_max, tap_y))
    if tap_y >= IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO:
        safe_y = min(tap_y, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y)
        if safe_y < tap_y:
            tap_y = safe_y
            reasons.append("bottom_nav_overlap_guard")
    if tap_y < tap_y_min:
        tap_y = tap_y_min
        reasons.append("row_top_safe_tap_guard")
    return {
        "tap_ratio": {
            "x": max(0.0, min(1.0, float(tap_ratio["x"]))),
            "y": round(tap_y, 4),
        },
        "tap_adjustment": {
            "adjusted": bool(reasons),
            "reason": "+".join(reasons) if reasons else None,
            "bottom_nav_top_ratio": IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO,
            "bottom_row_safe_tap_y": IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y,
            "bottom_row_detected": bottom_row,
            "matched_region_y2": region_y2,
        },
    }


def _iphone_visual_anchor_hash_for_pixels(
    pixels: dict[str, Any],
    *,
    region: dict[str, float],
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        width = int(pixels["width"])
        height = int(pixels["height"])
        channels = int(pixels["channels"])
        rows = pixels["rows"]
        x1 = max(0, min(width - 1, int(float(region["x1"]) * width)))
        x2 = max(x1 + 1, min(width, int(float(region["x2"]) * width)))
        y1 = max(0, min(height - 1, int(float(region["y1"]) * height)))
        y2 = max(y1 + 1, min(height, int(float(region["y2"]) * height)))
        values: list[float] = []
        for cell_y in range(grid_size):
            start_y = y1 + int((y2 - y1) * cell_y / grid_size)
            end_y = y1 + int((y2 - y1) * (cell_y + 1) / grid_size)
            for cell_x in range(grid_size):
                start_x = x1 + int((x2 - x1) * cell_x / grid_size)
                end_x = x1 + int((x2 - x1) * (cell_x + 1) / grid_size)
                total = 0.0
                count = 0
                for y in range(start_y, max(start_y + 1, end_y)):
                    row = rows[y]
                    for x in range(start_x, max(start_x + 1, end_x)):
                        offset = x * channels
                        r, g, b = row[offset : offset + 3]
                        total += (0.299 * int(r)) + (0.587 * int(g)) + (0.114 * int(b))
                        count += 1
                values.append(total / max(1, count))
        average = sum(values) / len(values)
        bits = "".join("1" if value >= average else "0" for value in values)
        return {
            "status": "ok",
            "visual_anchor_hash": f"{int(bits, 2):0{grid_size * grid_size // 4}x}",
            "grid_size": grid_size,
        }
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_hash_failed", "error": str(exc)[:80]}


def _iphone_visual_anchor_hash_for_path(
    path: Path,
    *,
    region: dict[str, float],
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels_for_send_button(path)
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_read_failed", "error": str(exc)[:80]}
    return _iphone_visual_anchor_hash_for_pixels(pixels, region=region, grid_size=grid_size)


def _iphone_current_thread_visual_anchor(
    screen: dict[str, Any],
    *,
    conversation_state: str,
    region: dict[str, float] | None = None,
) -> dict[str, Any]:
    anchor_region = region or dict(IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    base = {
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_region": anchor_region,
        "uses_header_ocr": False,
    }
    if screen.get("status") != "ok":
        return {**base, "status": "blocked", "reason": screen.get("reason") or "screen_not_captured"}
    if screen.get("state") != conversation_state:
        return {**base, "status": "blocked", "reason": f"{conversation_state}_not_verified"}
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {**base, "status": "blocked", "reason": "target_binding_screen_path_missing"}
    return {
        **base,
        **_iphone_visual_anchor_hash_for_path(Path(screen_path), region=anchor_region),
    }


def _iphone_already_sent_payload_update(
    payload: dict[str, Any],
    *,
    screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    conversation_state: str,
) -> dict[str, Any]:
    post_id_source = f"{payload['draft_fingerprint']}:{screen.get('path') or _now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    exact_text_ocr_verified = bool(outbound_verification.get("exact_text_ocr_verified"))
    return {
        "post_action_observation": _redacted_screen(screen),
        "post_action_observation_id": post_observation_id,
        "outbound_message_verification": outbound_verification,
        "current_thread_visual_anchor": _iphone_current_thread_visual_anchor(
            screen,
            conversation_state=conversation_state,
        ),
        "already_sent": True,
        "staged_text_verified": False,
        "executed_steps": [],
        "evidence": {
            "staged_text_verified": False,
            "staged_exact_text_verified": False,
            "staged_exact_text_ocr_verified": False,
            "send_input_backend": "already_sent_idempotent_skip",
            "input_cleared_after_send": bool(outbound_verification.get("input_cleared_after_send")),
            "post_action_screen_captured": screen.get("status") == "ok",
            "outbound_message_verified": True,
            "outbound_exact_text_verified": exact_text_ocr_verified,
            "outbound_exact_text_ocr_verified": exact_text_ocr_verified,
            "visual_only_exact_verification_allowed": False,
            "post_action_observation_id": post_observation_id,
        },
    }


def _iphone_already_sent_idempotency_allowed(target_binding: dict[str, Any] | None) -> bool:
    return (
        isinstance(target_binding, dict)
        and target_binding.get("binding_type") == "current_thread_visual_identity"
    )


def _iphone_stage_needs_user_verification(
    staged_verification: dict[str, Any],
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    verification = copy.deepcopy(staged_verification)
    verification["status"] = "needs_user_verification"
    verification["reason"] = reason or verification.get("reason") or "staged_text_not_verified"
    return verification


def _iphone_stage_draft_payload_update(
    *,
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    executed_steps: list[dict[str, Any]],
    conversation_state: str,
    send_input_backend: Any,
) -> dict[str, Any]:
    staged_text_verified = staged_verification.get("status") == "ok"
    return {
        "status": "ok",
        "stage_attempt_status": "completed",
        "staged_text_verification": staged_verification,
        "staged_text_verified": staged_text_verified,
        "verification": _redacted_screen(staged_screen),
        "current_thread_visual_anchor": _iphone_current_thread_visual_anchor(
            staged_screen,
            conversation_state=conversation_state,
        ),
        "executed_steps": executed_steps,
        "send_action_executed": False,
        "requires_user_confirmation_before_send": True,
        "next_host_action": "verify_staged_text_before_send",
        "evidence": EvidencePayload(
            staging=StagingResult.from_verification(
                staged_verification,
                staged_text_verified=staged_text_verified,
            ),
            post_send=PostSendVerification(
                post_action_observation_id="stage_only_no_post_action",
                input_cleared_after_send=False,
                post_action_screen_captured=False,
                outbound_message_verified=False,
            ),
            send_input_backend=send_input_backend,
            extra_fields={
                "stage_mode": True,
                "live_send_executed": False,
                "outbound_exact_text_ocr_verified": False,
                "visual_only_exact_verification_allowed": False,
            },
        ).to_dict(),
    }


def _verify_open_conversation_target_binding_against_screen(
    app_id: str,
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
    conversation_state: str,
    source_states: set[str],
    blocked_state_reasons: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(target_binding, dict):
        return {
            "verification_method": verification_method,
            "status": "blocked",
            "reason": "target_binding_required",
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
        }
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        spec = RowToThreadBindingSpec(
            app_id=app_id,
            verification_method=f"{verification_method}_structural_binding",
            source_states=frozenset(source_states),
            conversation_state=conversation_state,
            window_missing_reason="iphone_mirroring_window_not_found",
            blocked_state_reasons=dict(blocked_state_reasons),
        )
        base = row_to_thread_base_result(target_binding, spec=spec)
        structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
        if structural_block is not None:
            return structural_block
        return finish_row_to_thread_screen_verification(
            base,
            screen=screen,
            redacted_screen=_redacted_screen(screen),
            observed_text=str(screen.get("text") or ""),
            spec=spec,
        )
    return _verify_target_binding_against_screen(
        target_binding,
        screen,
        fallback_marker=fallback_marker,
        verification_method=verification_method,
        conversation_state=conversation_state,
        blocked_state_reasons=blocked_state_reasons,
    )


def _verify_target_binding_against_screen(
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
    conversation_state: str = "tinder_conversation",
    blocked_state_reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    markers = _target_binding_required_markers(target_binding or {})
    if not markers and fallback_marker.strip():
        markers = [fallback_marker.strip()]
    observed_text = str(screen.get("text") or "")
    matched = [marker for marker in markers if _visible_text_contains_marker(observed_text, marker)]
    result = {
        "verification_method": verification_method,
        "target_match_id": target_binding.get("target_match_id") if isinstance(target_binding, dict) else None,
        "candidate_key": target_binding.get("candidate_key") if isinstance(target_binding, dict) else None,
        "required_marker_hashes": [_hash_text(marker) for marker in markers],
        "matched_marker_hashes": [_hash_text(marker) for marker in matched],
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "target_binding_screen_capture_failed"}
    blocked_reason = (blocked_state_reasons or {}).get(str(screen.get("state") or ""))
    if blocked_reason:
        return {**result, "status": "blocked", "reason": blocked_reason}
    if screen.get("state") != conversation_state:
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if not markers:
        return {**result, "status": "blocked", "reason": "target_binding_required"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    return {**result, "status": "ok"}


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


def _visible_text_contains_marker(observed_text: str, marker: str) -> bool:
    marker = marker.strip()
    if not marker:
        return False
    return _normalize_text(marker) in _normalize_text(observed_text) or _message_text_comparable(marker) in _message_text_comparable(observed_text)


def _iphone_pre_stage_input_guard(
    *,
    app_id: str,
    screen: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    guard: dict[str, Any] = {
        "status": "ok",
        "app_id": app_id,
        "verification_method": f"{app_id}_pre_stage_input_occupied_guard",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        "observed_character_count": len(observed_text) if observed_text else None,
        "screen": _redacted_screen(screen),
    }
    if app_id == "bumble":
        from dating_boost.apps.bumble.runtime import _bumble_active_send_button_visual_visible

        active_send_button_visible = _bumble_active_send_button_visual_visible(screen)
        guard["active_send_button_visual_visible"] = active_send_button_visible
        if active_send_button_visible:
            guard.update({
                "status": "blocked",
                "reason": "message_input_not_empty_before_staging",
            })
        return guard
    if app_id == "tinder":
        from dating_boost.apps.tinder.runtime import (
            _tinder_message_input_placeholder_visible,
            _tinder_send_button_visual_visible,
            _tinder_send_marker_visible,
        )

        send_button_visual_visible = _tinder_send_button_visual_visible(screen)
        send_marker_visible = _tinder_send_marker_visible(observed_text)
        placeholder_visible = _tinder_message_input_placeholder_visible(observed_text)
        guard.update({
            "send_button_visual_visible": send_button_visual_visible,
            "send_marker_visible": send_marker_visible,
            "message_input_placeholder_visible": placeholder_visible,
        })
        if send_button_visual_visible and send_marker_visible and not placeholder_visible:
            guard.update({
                "status": "blocked",
                "reason": "message_input_not_empty_before_staging",
            })
        return guard
    return guard


def _verify_outbound_message(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    result = _outbound_text_ocr_evidence(
        verification_method="wechat_post_send_ocr_payload_text",
        observed_text=observed_text,
        expected_text=expected_text,
    )
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "post_action_screen_not_captured"}
    if not result["exact_text_ocr_verified"]:
        return {**result, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, "status": "ok"}


def _screen_region_stats(screen: dict[str, Any], x1: float, y1: float, x2: float, y2: float) -> dict[str, float] | None:
    path = screen.get("path")
    if not isinstance(path, str) or not path:
        return None
    try:
        pixels = _read_png_pixels_for_send_button(Path(path))
    except (OSError, ValueError, zlib.error, struct.error):
        return None
    return _region_stats_for_send_button(pixels, x1, y1, x2, y2)


def _direct_type_fallback_allowed(text: str) -> bool:
    return direct_text_entry_block_reason(text) is None


__all__ = [name for name in globals() if not name.startswith("__")]
