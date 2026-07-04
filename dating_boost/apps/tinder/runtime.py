from __future__ import annotations

from dating_boost.apps.iphone_targeting import *
from .send_runtime import (
    stage_tinder_draft,
    send_tinder_message,
    _recover_tinder_subscription_paywall_for_send,
    _tinder_message_input_placeholder_visible,
    _verify_staged_tinder_message,
    _verify_tinder_outbound_message,
    _tinder_staged_text_requires_host_visual_verification,
    _tinder_visual_staged_verification_request,
    _tinder_send_marker_visible,
    _tinder_direct_type_fallback_allowed,
    _tinder_send_button_visual_visible,
    _apply_tinder_paywall_recovery_result,
)
from .targeting import (
    _open_tinder_conversation_by_visible_name,
    _open_tinder_conversation_by_visual_anchor,
    _dismiss_tinder_subscription_paywall,
    _dismiss_tinder_feedback_survey,
    _verify_tinder_target_binding,
    _recover_tinder_current_thread_visual_identity_mismatch,
)

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
    elif screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        payload["next_host_action"] = "dismiss_subscription_paywall_and_renavigate"
    elif screen.get("state") == TINDER_FEEDBACK_SURVEY_STATE:
        payload["next_host_action"] = "dismiss_feedback_survey_and_reobserve"
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
    if dry_run:
        return payload
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
    if action == "prepare-message-page":
        return self._prepare_iphone_message_page(
            payload,
            app_id="tinder",
            output_dir=output_dir,
            output_prefix="iphone_mirroring.tinder",
            chat_list_state="tinder_messages",
            returnable_states={"tinder_conversation"},
            foreground_states=TINDER_FOREGROUND_STATES,
            open_chats_step=_tinder_action_steps("open-chats")[0],
            return_to_chats_step=_tinder_action_steps("return-to-chats")[0],
            secondary_close_steps={"tinder_profile": _tinder_action_steps("close-preview")[0]},
            guardrails={"blocked_actions": list(BLOCKED_GUI_ACTIONS)},
            layout_hints_fn=_tinder_layout_hints,
            message_list_visual_anchor_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        )
    if action == "open-conversation":
        target_binding = options.get("target_binding")
        visual_evidence = _message_list_visual_anchor_evidence_from_options(
            options,
            target_binding=target_binding if isinstance(target_binding, dict) else None,
            default_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
            default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
        )
        if visual_evidence.get("status") == "ok":
            return self._open_tinder_conversation_by_visual_anchor(
                visual_evidence=visual_evidence,
                target_binding=target_binding if isinstance(target_binding, dict) else None,
                output_dir=output_dir,
            )
        if visual_evidence.get("status") == "blocked":
            payload.update(
                {
                    "status": "blocked",
                    "reason": visual_evidence.get("reason") or "message_list_visual_anchor_evidence_invalid",
                    "message_list_visual_anchor": visual_evidence,
                }
            )
            return payload
        visible_name = str(options.get("visible_name") or "").strip()
        if not visible_name and isinstance(target_binding, dict):
            visible_name = _target_binding_primary_visible_name(target_binding) or ""
        if visible_name:
            return self._open_tinder_conversation_by_visible_name(
                visible_name=visible_name,
                target_binding=target_binding if isinstance(target_binding, dict) else None,
                output_dir=output_dir,
            )
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

__all__ = [name for name in globals() if not name.startswith("__")]
