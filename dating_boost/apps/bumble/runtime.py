from __future__ import annotations

from dating_boost.apps.iphone_targeting import *
from .send_runtime import (
    stage_bumble_draft,
    send_bumble_message,
    _verify_staged_bumble_message,
    _bumble_staged_text_requires_host_visual_verification,
    _bumble_visual_staged_verification_request,
    _verify_bumble_outbound_message,
    _bumble_send_marker_visible,
    _bumble_active_send_button_visual_visible,
    _bumble_outgoing_bubble_visual_visible,
    _bumble_direct_type_fallback_allowed,
)
from .targeting import (
    _open_bumble_conversation_by_visible_name,
    _open_bumble_conversation_by_visual_anchor,
    _verify_bumble_target_binding,
    _recover_bumble_current_thread_visual_identity_mismatch,
)

def _bumble_guardrails_payload() -> dict[str, Any]:
    return {
        "blocked_actions": list(BUMBLE_BLOCKED_GUI_ACTIONS),
        "opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY),
    }

def observe_bumble_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
    payload = {
        **self._base_payload("ok"),
        "target": "bumble_screen",
        **_bumble_guardrails_payload(),
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = self.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload

    window = _window_from_payload(doctor.get("window") or {})
    output = output_dir / "iphone_mirroring.bumble.observe.png" if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    payload["screen"] = _redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    payload["layout_hints"] = _bumble_layout_hints(screen)
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason")})
    elif screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        payload.update({"status": "blocked", "reason": screen.get("state")})
    elif screen.get("state") not in BUMBLE_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "bumble_foreground_not_verified"})
    return payload

def launch_bumble(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    planned_steps = _launch_app_steps(app_name="Bumble", search_result_intent="tap_bumble_search_result_icon")
    payload = {
        **self._base_payload("ok"),
        "target": "bumble_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **_bumble_guardrails_payload(),
    }
    if dry_run:
        return payload
    doctor_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        doctor_output = output_dir / "iphone_mirroring.bumble.before_launch.png"
    doctor = self.doctor(capture=True, output=doctor_output)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    state = doctor.get("screen", {}).get("state")
    if state in BUMBLE_FOREGROUND_STATES:
        payload["reason"] = "bumble_already_foreground"
        return payload

    window = _window_from_payload(doctor.get("window") or {})
    executed_steps: list[dict[str, Any]] = []
    for step in planned_steps:
        result = self._execute_step(window, step)
        executed_steps.append({**step, "result": result})
        if result["status"] != "ok":
            payload.update({"status": "blocked", "reason": result["reason"], "executed_steps": executed_steps})
            return payload
        time.sleep(float(step.get("wait_after_seconds", 0.2)))
    payload["executed_steps"] = executed_steps
    verification_output = output_dir / "iphone_mirroring.bumble.after_launch.png" if output_dir is not None else None
    verification = self.capture_window(output=verification_output, window=window)
    payload["verification"] = _redacted_screen(verification)
    if verification["state"] not in BUMBLE_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "bumble_launch_not_verified"})
    return payload

def run_bumble_action(
    self,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _bumble_action_steps(action, **options)
    except KeyError:
        return {
            **self._base_payload("blocked"),
            "action": action,
            "reason": "unknown_bumble_harness_action",
            **_bumble_guardrails_payload(),
        }
    payload = {
        **self._base_payload("ok"),
        "action": action,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **_bumble_guardrails_payload(),
    }
    if dry_run:
        return payload
    if action == "prepare-message-page":
        return self._prepare_iphone_message_page(
            payload,
            app_id="bumble",
            output_dir=output_dir,
            output_prefix="iphone_mirroring.bumble",
            chat_list_state="bumble_chat_list",
            returnable_states={"bumble_conversation", "bumble_opening_move"},
            foreground_states=BUMBLE_FOREGROUND_STATES,
            open_chats_step=_bumble_action_steps("open-chats")[0],
            return_to_chats_step=_bumble_action_steps("return-to-chats")[0],
            secondary_close_steps={"bumble_profile": _bumble_action_steps("close-profile")[0]},
            guardrails=_bumble_guardrails_payload(),
            layout_hints_fn=_bumble_layout_hints,
            message_list_visual_anchor_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        )
    if action == "open-conversation":
        target_binding = options.get("target_binding")
        visual_evidence = _message_list_visual_anchor_evidence_from_options(
            options,
            target_binding=target_binding if isinstance(target_binding, dict) else None,
            default_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
            default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
        )
        if visual_evidence.get("status") == "ok":
            return self._open_bumble_conversation_by_visual_anchor(
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
            return self._open_bumble_conversation_by_visible_name(
                visible_name=visible_name,
                target_binding=target_binding if isinstance(target_binding, dict) else None,
                output_dir=output_dir,
            )
    return self._execute_planned_steps(payload, output_dir=output_dir)

def run_bumble_workflow(
    self,
    workflow: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _bumble_workflow_steps(workflow, **options)
    except KeyError:
        return {
            **self._base_payload("blocked"),
            "workflow": workflow,
            "reason": "unknown_bumble_harness_workflow",
            **_bumble_guardrails_payload(),
        }
    payload = {
        **self._base_payload("ok"),
        "workflow": workflow,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **_bumble_guardrails_payload(),
    }
    if dry_run:
        return payload
    return self._execute_planned_steps(payload, output_dir=output_dir)

def _verify_bumble_step_precondition(
    self,
    window: WindowInfo,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_bumble_step_precondition(step):
        return {"status": "ok"}
    output = None
    if output_dir is not None:
        output = output_dir / f"iphone_mirroring.bumble_precondition_{step_index:02d}.png"
    screen = self.capture_window(output=output, window=window)
    result = {
        "status": screen.get("status", "blocked"),
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "bumble_precondition_capture_failed"
    elif step.get("requires_bumble_top_level_tab_bar") and not _bumble_top_level_bottom_nav_present(screen):
        result.update({"status": "blocked", "reason": "bumble_top_level_tab_bar_not_verified"})
    else:
        state_check = _verify_bumble_step_state(screen, step, key="requires_bumble_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "bumble_step_precondition_not_verified"
    return result

def _verify_bumble_step_postcondition(
    self,
    window: WindowInfo,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_bumble_step_postcondition(step):
        return {"status": "ok", "checked": False}
    output = None
    if output_dir is not None:
        output = output_dir / f"iphone_mirroring.bumble_postcondition_{step_index:02d}.png"
    screen = self.capture_window(output=output, window=window)
    result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "bumble_postcondition_capture_failed"
    else:
        state_check = _verify_bumble_step_state(screen, step, key="expected_bumble_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "bumble_step_postcondition_not_verified"
    return result

__all__ = [name for name in globals() if not name.startswith("__")]
