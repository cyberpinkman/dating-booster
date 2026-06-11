from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4
import time

from dating_boost.apps.tashuo.screen_state import (
    TASHUO_FOREGROUND_STATES,
    classify_tashuo_screen_image,
    classify_tashuo_capture,
    tashuo_layout_hints,
    tashuo_top_level_bottom_nav_present,
)
from dating_boost.apps import native_gui_session as platform
from dating_boost.core.live_send_contract import (
    target_binding_specific_marker_present,
    target_binding_structural_evidence_present,
)


TASHUO_BLOCKED_GUI_ACTIONS = [
    "send",
    "like",
    "pass",
    "super_like",
    "unmatch",
    "report",
    "profile_edit",
    "premium_purchase",
    "flight_start_chat",
    "question_gate_enable",
    "question_gate_skip",
    "question_gate_decide_reply_satisfaction",
    "question_gate_send",
]
TASHUO_SEND_BLOCKED_GUI_ACTIONS = [
    "like",
    "pass",
    "super_like",
    "unmatch",
    "report",
    "profile_edit",
    "premium_purchase",
    "flight_start_chat",
    "question_gate_enable",
    "question_gate_skip",
    "question_gate_decide_reply_satisfaction",
    "question_gate_send",
    "question_gate_autonomous_send",
]
TASHUO_QUESTION_GATE_POLICY: dict[str, Any] = {
    "scope": "tashuo_question_gate",
    "female_user": {
        "agent_decision_authority": "none",
        "user_decision_required": [
            "enable_question",
            "skip_question_gate",
            "accept_male_reply",
            "reject_male_reply",
        ],
        "agent_allowed_actions": [
            "observe_question_prompt",
            "summarize_visible_reply",
            "ask_user_to_decide",
        ],
        "agent_disallowed_actions": [
            "enable_question",
            "skip_question_gate",
            "accept_male_reply",
            "reject_male_reply",
        ],
    },
    "male_user": {
        "agent_may_draft_reply": True,
        "requires_user_confirmation_before_send": True,
        "current_harness_stage_supported": False,
        "current_harness_send_supported": False,
        "autonomous_question_gate_send_supported": False,
        "agent_allowed_actions": ["draft_question_gate_reply"],
        "agent_disallowed_actions": [
            "send_question_gate_reply_without_user_confirmation",
            "autonomous_question_gate_send",
        ],
    },
}
TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO = {"x": 0.32, "y": 0.91}
TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO = {"x": 0.32, "y": 0.91}
TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO = {"x": 0.32, "y": 0.85}
TASHUO_MESSAGES_TAB_TAP_RATIO = {"x": 0.67, "y": 0.96}


def install_tashuo_session_hooks(session: Any) -> None:
    session.app_screen_state_observer = classify_tashuo_capture
    session.app_foreground_states = set(TASHUO_FOREGROUND_STATES)
    session.app_verified_screen_key = "requires_verified_tashuo_screen"
    session.app_foreground_not_verified_reason = "tashuo_foreground_not_verified"
    session.app_step_precondition_verifier = _verify_tashuo_step_precondition
    session.app_step_postcondition_verifier = _verify_tashuo_step_postcondition
    session.app_profile_field_coverage = _tashuo_profile_field_coverage


def tashuo_guardrails_payload() -> dict[str, Any]:
    return {
        "blocked_actions": list(TASHUO_BLOCKED_GUI_ACTIONS),
        "question_gate_policy": copy.deepcopy(TASHUO_QUESTION_GATE_POLICY),
    }


def observe_tashuo_screen(session: Any, *, output_dir: Path | None = None) -> dict[str, Any]:
    payload = {
        **session._base_payload("ok"),
        "target": "tashuo_screen",
        **tashuo_guardrails_payload(),
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = session.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    observe_name = "mac_ios_app.tashuo.observe.png" if _is_mac_ios_app_session(session) else "iphone_mirroring.tashuo.observe.png"
    output = output_dir / observe_name if output_dir is not None else None
    screen = session.capture_window(output=output, window=window)
    payload["screen"] = platform._redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    layout_hints = tashuo_layout_hints(screen)
    if _is_mac_ios_app_session(session):
        layout_hints.update(
            {
                "live_send_supported": False,
                "managed_live_send_supported": False,
                "live_send_status": "experimental_blocked_cjk_stage_verification",
                "live_send_block_reason": "cjk_stage_verification_not_stable",
            }
        )
    payload["layout_hints"] = layout_hints
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason")})
    elif screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        payload.update({"status": "blocked", "reason": screen.get("state")})
    elif screen.get("state") not in TASHUO_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tashuo_foreground_not_verified"})
    return payload


def launch_tashuo(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    if _is_mac_ios_app_session(session):
        return launch_tashuo_mac_ios_app(session, dry_run=dry_run, output_dir=output_dir)
    planned_steps = platform._launch_app_steps(
        app_name="tashu",
        expected_app_labels=["tashu", "她说", "TaShuo"],
        search_result_intent="tap_tashuo_search_result_icon",
    )
    payload = {
        **session._base_payload("ok"),
        "target": "tashuo_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "bundle_id": "com.intelcupid.tashuo",
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    doctor_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        doctor_output = output_dir / "iphone_mirroring.tashuo.before_launch.png"
    doctor = session.doctor(capture=True, output=doctor_output)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    state = doctor.get("screen", {}).get("state")
    if state in TASHUO_FOREGROUND_STATES:
        payload["reason"] = "tashuo_already_foreground"
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    executed_steps: list[dict[str, Any]] = []
    for step in planned_steps:
        result = session._execute_step(window, step)
        executed_steps.append({**step, "result": result})
        if result["status"] != "ok":
            payload.update({"status": "blocked", "reason": result["reason"], "executed_steps": executed_steps})
            return payload
        time.sleep(float(step.get("wait_after_seconds", 0.2)))
    payload["executed_steps"] = executed_steps
    verification_output = output_dir / "iphone_mirroring.tashuo.after_launch.png" if output_dir is not None else None
    verification = session.capture_window(output=verification_output, window=window)
    payload["verification"] = platform._redacted_screen(verification)
    if verification["state"] not in TASHUO_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tashuo_launch_not_verified"})
    return payload


def launch_tashuo_mac_ios_app(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    bundle_id = str(runtime_config.get("bundle_id") or "com.intelcupid.tashuo")
    process_name = str(runtime_config.get("process_name") or "tashuo")
    planned_steps = [
        {
            "intent": "open_tashuo_mac_ios_app_bundle",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "wait_after_seconds": 0.8,
        },
        {
            "intent": "activate_tashuo_mac_ios_process",
            "process_name": process_name,
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "target": "tashuo_mac_ios_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "bundle_id": bundle_id,
        "process_name": process_name,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    executed_steps: list[dict[str, Any]] = []
    open_result = session.runner.run(["open", "-b", bundle_id])
    open_payload = {
        "status": "ok" if open_result.returncode == 0 else "blocked",
        "stderr": platform._short(open_result.stderr),
    }
    executed_steps.append({**planned_steps[0], "result": open_payload})
    if open_payload["status"] != "ok":
        payload.update({"status": "blocked", "reason": "mac_ios_app_open_failed", "executed_steps": executed_steps})
        return payload
    time.sleep(float(planned_steps[0]["wait_after_seconds"]))

    activate_payload = session._activate_window()
    executed_steps.append({**planned_steps[1], "result": activate_payload})
    if activate_payload["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": "mac_ios_app_activation_failed",
            "executed_steps": executed_steps,
        })
        return payload
    time.sleep(float(planned_steps[1]["wait_after_seconds"]))

    verification_output = output_dir / "mac_ios_app.tashuo.after_launch.png" if output_dir is not None else None
    verification = session.doctor(capture=True, output=verification_output)
    payload["executed_steps"] = executed_steps
    payload["verification"] = verification
    if verification["status"] == "blocked":
        payload.update({"status": "blocked", "reason": verification.get("reason")})
    elif verification.get("screen", {}).get("state") not in TASHUO_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tashuo_mac_ios_app_launch_not_verified"})
    return payload


def _is_mac_ios_app_session(session: Any) -> bool:
    return getattr(session, "harness_backend", None) == "mac_ios_app"


def _tashuo_capture_prefix(session: Any) -> str:
    return "mac_ios_app.tashuo" if _is_mac_ios_app_session(session) else "iphone_mirroring.tashuo"


def _copy_tap_ratio(ratio: dict[str, float]) -> dict[str, float]:
    return {"x": float(ratio["x"]), "y": float(ratio["y"])}


def _tashuo_message_input_tap_ratio(session: Any, *, focused: bool) -> dict[str, float]:
    if focused and _is_mac_ios_app_session(session):
        return _copy_tap_ratio(TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO)
    if focused:
        return _copy_tap_ratio(TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO)
    return _copy_tap_ratio(TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO)


def _tashuo_input_coordinate_model(session: Any) -> dict[str, Any]:
    if _is_mac_ios_app_session(session):
        return {
            "runtime": "mac_ios_app",
            "coordinate_shift_after_focus": True,
            "unfocused_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
            "focused_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
        }
    return {
        "runtime": "iphone_mirroring",
        "coordinate_shift_after_focus": False,
        "unfocused_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
        "focused_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
    }


def run_tashuo_action(
    session: Any,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    if action in {"prepare-message-page", "prepare_message_page"}:
        return prepare_tashuo_message_page(session, dry_run=dry_run, output_dir=output_dir)
    try:
        planned_steps = _tashuo_action_steps(action, **options)
    except KeyError:
        return {
            **session._base_payload("blocked"),
            "action": action,
            "reason": "unknown_tashuo_harness_action",
            **tashuo_guardrails_payload(),
        }
    payload = {
        **session._base_payload("ok"),
        "action": action,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    return session._execute_planned_steps(payload, output_dir=output_dir)


def prepare_tashuo_message_page(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "prepare-message-page",
            "target": "tashuo_message_page",
            "reason": "tashuo_prepare_message_page_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    bundle_id = str(runtime_config.get("bundle_id") or "com.intelcupid.tashuo")
    planned_steps = [
        {
            "intent": "open_tashuo_mac_ios_app_bundle",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "wait_after_seconds": 0.8,
        },
        {
            "intent": "activate_tashuo_mac_ios_process",
            "process_name": str(runtime_config.get("process_name") or "tashuo"),
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "capture_tashuo_top_level_bottom_nav_visual",
            "risk": "visual_observation_only",
            "ocr_used": False,
        },
        {
            "intent": "click_tashuo_messages_tab_accessibility",
            "radio_button_index": 3,
            "risk": "navigation_only",
            "conditional_on_active_tab_not": "messages",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "tap_tashuo_messages_tab_fallback",
            "tap_ratio": _copy_tap_ratio(TASHUO_MESSAGES_TAB_TAP_RATIO),
            "risk": "navigation_only",
            "conditional_on_active_tab_not": "messages",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "handoff_to_visual_message_list_planning",
            "risk": "visual_observation_only",
            "does_not_open_conversation": True,
            "ocr_used": False,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "action": "prepare-message-page",
        "target": "tashuo_message_page",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "visual_only_navigation": True,
        "ocr_used": False,
        "message_page_followup": "visual_analysis_only",
        "next_host_action": "visual_plan_message_list",
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    executed_steps: list[dict[str, Any]] = []
    open_result = session.runner.run(["open", "-b", bundle_id])
    open_payload = {
        "status": "ok" if open_result.returncode == 0 else "blocked",
        "stderr": platform._short(open_result.stderr),
    }
    executed_steps.append({**planned_steps[0], "result": open_payload})
    if open_payload["status"] != "ok":
        payload.update({"status": "blocked", "reason": "mac_ios_app_open_failed", "executed_steps": executed_steps})
        return payload
    time.sleep(float(planned_steps[0]["wait_after_seconds"]))

    activate_payload = session._activate_window()
    executed_steps.append({**planned_steps[1], "result": activate_payload})
    if activate_payload["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": "mac_ios_app_activation_failed",
            "executed_steps": executed_steps,
        })
        return payload
    time.sleep(float(planned_steps[1]["wait_after_seconds"]))

    doctor = session.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason"), "executed_steps": executed_steps})
        return payload
    window = platform._window_from_payload(doctor.get("window") or {})
    initial_output = output_dir / "mac_ios_app.tashuo.prepare_message_page.initial.png" if output_dir is not None else None
    initial_screen = _capture_tashuo_visual_screen(session, window, output=initial_output)
    payload["initial_screen"] = platform._redacted_screen(initial_screen)
    payload["initial_visual_state"] = initial_screen.get("visual_state", "unknown")
    payload["initial_active_tab"] = initial_screen.get("visual_active_tab", "unknown")
    executed_steps.append({**planned_steps[2], "result": {"status": initial_screen.get("status", "blocked")}})
    if initial_screen.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": initial_screen.get("reason") or "tashuo_visual_capture_failed",
            "executed_steps": executed_steps,
        })
        return payload
    if not initial_screen.get("visual_bottom_nav_present"):
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_top_level_tab_bar_not_verified",
            "screen_state": initial_screen.get("state", "unknown"),
            "next_host_action": "visual_analyze_current_screen",
            "executed_steps": executed_steps,
        })
        return payload
    if initial_screen.get("visual_active_tab") == "messages":
        payload.update({
            "screen": platform._redacted_screen(initial_screen),
            "screen_state": "tashuo_chat_list",
            "executed_steps": executed_steps,
        })
        return payload

    ax_result = _click_tashuo_messages_radio_button(session)
    executed_steps.append({**planned_steps[3], "result": ax_result})
    if ax_result["status"] != "ok":
        tap_result = session._click_ratio(window, planned_steps[4]["tap_ratio"])
        executed_steps.append({**planned_steps[4], "result": tap_result})
        if tap_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": tap_result.get("reason"), "executed_steps": executed_steps})
            return payload
    time.sleep(float(planned_steps[3]["wait_after_seconds"]))

    final_output = output_dir / "mac_ios_app.tashuo.prepare_message_page.messages.png" if output_dir is not None else None
    final_screen = _capture_tashuo_visual_screen(session, window, output=final_output)
    payload["screen"] = platform._redacted_screen(final_screen)
    payload["screen_state"] = final_screen.get("state", "unknown")
    executed_steps.append({**planned_steps[5], "result": {"status": final_screen.get("status", "blocked")}})
    payload["executed_steps"] = executed_steps
    if final_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": final_screen.get("reason") or "tashuo_visual_capture_failed"})
    elif final_screen.get("visual_active_tab") != "messages":
        payload.update({"status": "needs_verification", "reason": "tashuo_messages_tab_not_verified"})
    return payload


def _capture_tashuo_visual_screen(session: Any, window: Any, *, output: Path | None = None) -> dict[str, Any]:
    output = (output or platform._default_screenshot_path()).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    result = session.runner.run(
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
            "stderr": platform._short(result.stderr),
            "state": "unknown",
            "text_state": "not_run",
            "visual_state": "unknown",
            "visual_status": "not_run",
            "visual_active_tab": "unknown",
            "visual_bottom_nav_present": False,
            "ocr_status": "skipped",
            "text": "",
        }
    visual = classify_tashuo_screen_image(output)
    visual_state = str(visual.get("state") or "unknown")
    return {
        "schema_version": 2,
        "status": "ok" if visual.get("status") == "ok" else "blocked",
        "path": str(output),
        "state": visual_state,
        "text_state": "not_run",
        "visual_state": visual_state,
        "visual_status": visual.get("status", "unknown"),
        "visual_active_tab": visual.get("active_tab", "unknown"),
        "visual_bottom_nav_present": visual.get("bottom_nav_present", False),
        "conversation_toolbar_present": visual.get("conversation_toolbar_present", False),
        "ocr_status": "skipped",
        "text": "",
    }


def run_tashuo_workflow(
    session: Any,
    workflow: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _tashuo_workflow_steps(workflow, **options)
    except KeyError:
        return {
            **session._base_payload("blocked"),
            "workflow": workflow,
            "reason": "unknown_tashuo_harness_workflow",
            **tashuo_guardrails_payload(),
        }
    payload = {
        **session._base_payload("ok"),
        "workflow": workflow,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    return session._execute_planned_steps(payload, output_dir=output_dir)


def stage_tashuo_draft(
    session: Any,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "stage_draft",
            "target": "tashuo_message_input",
            "reason": "tashuo_stage_draft_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    if not draft_text:
        return {
            **session._base_payload("blocked"),
            "action": "stage_draft",
            "target": "tashuo_message_input",
            "reason": "empty_draft",
            **tashuo_guardrails_payload(),
        }
    planned_steps = [
        {
            "intent": "tap_tashuo_message_input",
            "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
            "focus_state": "unfocused",
            "post_focus_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
            "risk": "draft_staging_only",
            "does_not_send": True,
            "requires_verified_tashuo_thread": True,
        },
        {
            "intent": "copy_draft_to_clipboard",
            "risk": "draft_staging_only",
            "does_not_send": True,
        },
        {
            "intent": "paste_clipboard_into_tashuo_message_input",
            "risk": "draft_staging_only",
            "does_not_send": True,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "action": "stage_draft",
        "target": "tashuo_message_input",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
        "draft_character_count": len(draft_text),
        **platform._text_fingerprint_fields("draft_clipboard", draft_text),
        "input_coordinate_model": _tashuo_input_coordinate_model(session),
        **tashuo_guardrails_payload(),
        "requires_user_confirmation_before_send": True,
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    before = output_dir / "mac_ios_app.tashuo.before_stage_draft.png" if output_dir is not None else None
    doctor = session.doctor(capture=True, output=before)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state == "tashuo_question_gate":
        payload.update({"status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"})
        return payload
    if screen_state != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified", "screen_state": screen_state})
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    previous_clipboard = session._read_clipboard()
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard["reason"]})
        return payload
    payload.update(platform._text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))

    executed_steps: list[dict[str, Any]] = []
    copy_result = {"status": "not_run"}
    paste_result = {"status": "not_run"}
    try:
        click_result = session._click_ratio(window, planned_steps[0]["tap_ratio"])
        executed_steps.append({**planned_steps[0], "result": click_result})
        if click_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": click_result["reason"]})
            return payload
        copy_result = session._copy_to_clipboard(draft_text)
        executed_steps.append({**planned_steps[1], "result": copy_result})
        if copy_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": copy_result["reason"]})
            return payload
        paste_result = session._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
        executed_steps.append({**planned_steps[2], "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result["reason"]})
            return payload
        time.sleep(0.35)
        after = output_dir / "mac_ios_app.tashuo.after_stage_draft.png" if output_dir is not None else None
        after_screen = session.capture_window(output=after, window=window)
        time.sleep(0.45)
        delayed_after = output_dir / "mac_ios_app.tashuo.after_stage_draft.delayed.png" if output_dir is not None else None
        delayed_screen = session.capture_window(output=delayed_after, window=window)
        payload["verification"] = platform._redacted_screen(delayed_screen)
        payload["stage_attempt_status"] = "completed"
        payload["staged_text_verification"] = _stage_only_tashuo_verification(
            delayed_screen,
            draft_text,
            baseline_screen=doctor.get("screen") if isinstance(doctor.get("screen"), dict) else None,
            first_screen=after_screen,
        )
        payload["staged_text_verified"] = payload["staged_text_verification"]["status"] == "verified"
        payload["next_host_action"] = "verify_staged_text_before_send"
    finally:
        payload["executed_steps"] = executed_steps
        restore_result = session._copy_to_clipboard(previous_clipboard.get("text", ""))
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


def _click_tashuo_messages_radio_button(session: Any) -> dict[str, Any]:
    process_name = str(getattr(session, "window_title", "") or "她说").replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "System Events" to tell process "{process_name}" '
        'to click radio button 3 of window 1'
    )
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_messages_radio_button_click_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    return {"status": "ok", "input_backend": "macos_accessibility", "radio_button_index": 3}


def send_tashuo_message(
    session: Any,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_step = {
        "intent": "tap_tashuo_message_input",
        "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
        "focus_state": "unfocused",
        "post_focus_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
        "risk": "live_send_precondition",
        "requires_verified_tashuo_thread": True,
    }
    focused_input_step = {
        "intent": "tap_tashuo_message_input_after_focus",
        "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
        "focus_state": "focused",
        "risk": "live_send_precondition",
        "requires_verified_tashuo_thread": True,
    }
    paste_step = {
        "intent": "paste_clipboard_into_tashuo_message_input",
        "risk": "live_send_precondition",
        "requires_exact_text_match": True,
    }
    type_fallback_step = {
        "intent": "type_tashuo_message_input_if_paste_did_not_stage",
        "risk": "live_send_precondition",
        "fallback_only": True,
        "requires_direct_type_safe_draft": True,
        "requires_exact_text_verification_after_direct_type": True,
    }
    ime_commit_step = {
        "intent": "commit_tashuo_message_input_ime_candidate_if_needed",
        "risk": "live_send_precondition",
        "fallback_only": True,
        "commits_direct_type_candidate": True,
        "requires_exact_text_verification_after_commit": True,
    }
    send_step = {
        "intent": "press_return_to_send_tashuo_message",
        "focus_state": "focused",
        "risk": "live_send",
        "requires_explicit_authorization": True,
        "visual_only_exact_verification_allowed": False,
        "requires_exact_text_verification_before_return": True,
    }
    payload = {
        **session._base_payload("ok"),
        "action": "send_message",
        "target": "tashuo_message_input",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": [input_step, paste_step, type_fallback_step, ime_commit_step, send_step],
        "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
        "draft_character_count": len(draft_text),
        **platform._text_fingerprint_fields("draft_clipboard", draft_text),
        "blocked_actions": list(TASHUO_SEND_BLOCKED_GUI_ACTIONS),
        "question_gate_policy": copy.deepcopy(TASHUO_QUESTION_GATE_POLICY),
        "input_coordinate_model": _tashuo_input_coordinate_model(session),
        "live_send": True,
        "requires_explicit_authorization": True,
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    capture_prefix = _tashuo_capture_prefix(session)
    preflight_output = output_dir / f"{capture_prefix}.before_send_message.png" if output_dir is not None else None
    preflight = session.doctor(capture=True, output=preflight_output)
    payload["preflight"] = preflight
    if preflight.get("status") != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "tashuo_preflight_not_verified"})
        return payload
    window = platform._window_from_payload(preflight.get("window") or {})
    preflight_screen = preflight.get("screen") if isinstance(preflight.get("screen"), dict) else {}
    if preflight_screen.get("state") == "tashuo_question_gate":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_question_gate_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_question_gate_reply",
        })
        return payload
    if preflight_screen.get("state") != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified"})
        return payload

    if target_binding is not None:
        target_verification = _verify_tashuo_target_binding(session, target_binding, output_dir=output_dir)
        payload["target_binding_verification"] = target_verification
        if target_verification.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": target_verification.get("reason") or "target_binding_mismatch",
            })
            return payload

    baseline_output = output_dir / f"{capture_prefix}.before_stage_message.png" if output_dir is not None else None
    baseline_screen = session.capture_window(output=baseline_output, window=window)
    payload["pre_stage_observation"] = platform._redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return payload
    if baseline_screen.get("state") == "tashuo_question_gate":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_question_gate_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_question_gate_reply",
        })
        return payload
    if baseline_screen.get("state") != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified"})
        return payload

    previous_clipboard = session._read_clipboard()
    payload["previous_clipboard_read"] = previous_clipboard["status"] == "ok"
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard.get("reason")})
        return payload
    payload.update(platform._text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))
    copy_result = session._copy_to_clipboard(draft_text)
    payload["draft_clipboard_copy"] = copy_result["status"] == "ok"
    if copy_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": copy_result.get("reason")})
        return payload

    executed_steps: list[dict[str, Any]] = []
    staged_screen = baseline_screen
    try:
        input_result = session._click_ratio(window, input_step["tap_ratio"])
        executed_steps.append({**input_step, "result": input_result})
        if input_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(0.45)

        paste_result = session._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
        executed_steps.append({**paste_step, "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(0.3)

        staged_output = output_dir / f"{capture_prefix}.after_stage_message.png" if output_dir is not None else None
        staged_screen = session.capture_window(output=staged_output, window=window)
        staged_verification = _verify_staged_tashuo_message(
            staged_screen,
            draft_text,
            baseline_screen=baseline_screen,
        )
        staged_text = str(staged_screen.get("text") or "")
        staged_input_placeholder_visible = _tashuo_input_placeholder_visible(staged_text)
        direct_type_fallback_candidate = (
            staged_verification.get("status") != "ok"
            and platform._direct_type_fallback_allowed(draft_text)
            and staged_input_placeholder_visible
        )
        if direct_type_fallback_candidate and _contains_cjk(draft_text):
            cleanup_result = _cleanup_failed_tashuo_stage(
                session,
                window,
                focused_input_step,
                expected_text=draft_text,
                output_dir=output_dir,
            )
            payload["failed_stage_cleanup"] = cleanup_result
            payload["staged_text_verification"] = staged_verification
            payload["staged_text_verified"] = False
            payload.update({
                "status": "blocked",
                "reason": "cjk_direct_type_not_supported",
                "executed_steps": executed_steps,
            })
            return payload
        if direct_type_fallback_candidate:
            type_result = session._type_text_into_frontmost_app(draft_text)
            executed_steps.append({**type_fallback_step, "result": type_result})
            if type_result["status"] != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": type_result.get("reason") or "direct_text_entry_failed",
                    "executed_steps": executed_steps,
                })
                return payload
            time.sleep(0.3)
            staged_output = output_dir / f"{capture_prefix}.after_type_message.png" if output_dir is not None else None
            staged_screen = session.capture_window(output=staged_output, window=window)
            staged_verification = _verify_staged_tashuo_message(
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
                trusted_direct_input=True,
            )
            direct_type_verification = staged_verification
            ime_commit_result = session._press_space_key()
            executed_steps.append({**ime_commit_step, "result": ime_commit_result})
            if ime_commit_result["status"] != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": ime_commit_result.get("reason") or "ime_commit_space_failed",
                    "executed_steps": executed_steps,
                })
                return payload
            time.sleep(0.3)
            staged_output = output_dir / f"{capture_prefix}.after_ime_commit_message.png" if output_dir is not None else None
            staged_screen = session.capture_window(output=staged_output, window=window)
            committed_verification = _verify_staged_tashuo_message(
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
                trusted_direct_input=True,
            )
            payload["direct_type_text_verification"] = direct_type_verification
            payload["ime_commit_text_verification"] = committed_verification
            if committed_verification.get("status") == "ok" or direct_type_verification.get("status") != "ok":
                staged_verification = committed_verification
            payload["staging_input_backend"] = type_result.get("input_backend")
        payload["staged_text_verification"] = staged_verification
        payload["staged_text_verified"] = staged_verification.get("status") == "ok"
        if staged_verification.get("status") != "ok":
            cleanup_result = _cleanup_failed_tashuo_stage(
                session,
                window,
                focused_input_step,
                expected_text=draft_text,
                output_dir=output_dir,
            )
            payload["failed_stage_cleanup"] = cleanup_result
            payload.update({
                "status": "blocked",
                "reason": staged_verification.get("reason") or "staged_text_not_verified",
                "executed_steps": executed_steps,
            })
            return payload
    finally:
        restore_result = session._copy_to_clipboard(previous_clipboard.get("text", ""))
        payload["clipboard_restored"] = restore_result["status"] == "ok"
        payload["clipboard_restore_status"] = restore_result["status"]
        if restore_result["status"] != "ok":
            payload["clipboard_restore_reason"] = restore_result.get("reason")

    if payload["clipboard_restored"] is not True:
        payload.update({
            "status": "blocked",
            "reason": "clipboard_restore_failed",
            "executed_steps": executed_steps,
        })
        return payload

    send_result = session._press_return_key()
    executed_steps.append({**send_step, "result": send_result})
    payload["executed_steps"] = executed_steps
    if send_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": send_result.get("reason")})
        return payload

    time.sleep(0.5)
    post_output = output_dir / f"{capture_prefix}.after_send_message.png" if output_dir is not None else None
    post_screen = session.capture_window(output=post_output, window=window)
    payload["post_action_observation"] = platform._redacted_screen(post_screen)
    post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or platform._now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    payload["post_action_observation_id"] = post_observation_id
    post_screen_captured = post_screen.get("status") == "ok"
    outbound_verification = _verify_tashuo_outbound_message(
        post_screen,
        draft_text,
        staged_screen=staged_screen,
        trusted_direct_input=payload.get("staging_input_backend") == "applescript_direct_keystroke",
    )
    payload["outbound_message_verification"] = outbound_verification
    outbound_verified = outbound_verification.get("status") == "ok"
    input_cleared = bool(outbound_verification.get("input_cleared_after_send"))
    payload["evidence"] = {
        "staged_text_verified": bool(payload.get("staged_text_verified")),
        "staged_exact_text_ocr_verified": bool(staged_verification.get("exact_text_ocr_verified")),
        "send_input_backend": send_result.get("input_backend"),
        "input_cleared_after_send": input_cleared,
        "post_action_screen_captured": post_screen_captured,
        "outbound_message_verified": outbound_verified,
        "outbound_exact_text_ocr_verified": bool(outbound_verification.get("exact_text_ocr_verified")),
        "visual_only_exact_verification_allowed": False,
        "post_action_observation_id": post_observation_id,
    }
    if not post_screen_captured:
        payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
    elif not input_cleared:
        payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
    elif not outbound_verified:
        payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
    return payload


def _verify_tashuo_target_binding(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        return _verify_tashuo_chat_list_row_target_binding(session, target_binding, output_dir=output_dir)
    if _is_mac_ios_app_session(session):
        return {
            "verification_method": "tashuo_mac_ios_app_structural_binding_required",
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "requires_header_marker": False,
            "requires_structural_binding": True,
            "status": "blocked",
            "reason": "target_binding_structural_evidence_required",
        }

    markers = platform._target_binding_required_markers(target_binding)
    base = {
        "verification_method": "tashuo_screen_ocr_required_visible_text",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "required_marker_hashes": [platform._hash_text(marker) for marker in markers],
        "requires_target_specific_marker": True,
        "requires_header_marker": True,
    }
    if not markers:
        return {**base, "status": "blocked", "reason": "target_binding_required"}
    if not target_binding_specific_marker_present("tashuo", target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_not_target_specific"}
    window = session._window_info()
    if window is None:
        reason = "mac_ios_app_window_not_found" if _is_mac_ios_app_session(session) else "iphone_mirroring_window_not_found"
        return {**base, "status": "blocked", "reason": reason}
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = session.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    header_text = _tashuo_header_text(observed_text)
    matched = [marker for marker in markers if _tashuo_marker_matches_text(observed_text, marker)]
    header_matched = [marker for marker in markers if _tashuo_marker_matches_text(header_text, marker)]
    result = {
        **base,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": platform._hash_text(observed_text) if observed_text else None,
        "matched_marker_hashes": [platform._hash_text(marker) for marker in matched],
        "header_marker_hashes": [platform._hash_text(marker) for marker in header_matched],
        "header_text_hash": platform._hash_text(header_text) if header_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    if screen.get("state") != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    if not header_matched:
        return {**result, "status": "blocked", "reason": "target_binding_header_mismatch"}
    return {**result, "status": "ok"}


def _verify_tashuo_chat_list_row_target_binding(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    selection_evidence = (
        target_binding.get("selection_evidence") if isinstance(target_binding.get("selection_evidence"), dict) else {}
    )
    row_index = selection_evidence.get("row_index")
    base = {
        "verification_method": "tashuo_chat_list_row_to_thread_structural_binding",
        "binding_type": target_binding.get("binding_type"),
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "row_index": row_index,
        "source_state": selection_evidence.get("source_state"),
        "opened_state": selection_evidence.get("opened_state"),
        "target_scope": selection_evidence.get("target_scope"),
        "open_action": selection_evidence.get("open_action"),
        "requires_target_specific_marker": True,
        "requires_header_marker": False,
        "emoji_nickname_supported": True,
        "visual_only_exact_verification_allowed": False,
    }
    if not target_binding_structural_evidence_present("tashuo", target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
    if selection_evidence.get("source_state") != "tashuo_chat_list":
        return {**base, "status": "blocked", "reason": "target_binding_source_state_mismatch"}
    if selection_evidence.get("opened_state") != "tashuo_conversation":
        return {**base, "status": "blocked", "reason": "target_binding_opened_state_mismatch"}
    if selection_evidence.get("open_action") != "open-conversation":
        return {**base, "status": "blocked", "reason": "target_binding_open_action_mismatch"}
    target_scope = selection_evidence.get("target_scope")
    if target_scope not in {None, "ordinary_conversation", "existing_conversation"}:
        return {**base, "status": "blocked", "reason": "target_binding_scope_not_ordinary_conversation"}
    window = session._window_info()
    if window is None:
        reason = "mac_ios_app_window_not_found" if _is_mac_ios_app_session(session) else "iphone_mirroring_window_not_found"
        return {**base, "status": "blocked", "reason": reason}
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = session.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    result = {
        **base,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": platform._hash_text(observed_text) if observed_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    if screen.get("state") != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    return {**result, "status": "ok"}


def _tashuo_header_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    filtered: list[str] = []
    for line in lines[:5]:
        if any(marker in line for marker in ("开启通知", "点击此处输入文字", "发送")):
            continue
        filtered.append(line)
        if len(filtered) >= 2:
            break
    return "\n".join(filtered)


def _tashuo_marker_matches_text(text: str, marker: str) -> bool:
    normalized_marker = platform._normalize_text(marker)
    normalized_text = platform._normalize_text(text)
    if normalized_marker and normalized_marker in normalized_text:
        return True
    return _tashuo_cjk_marker_fuzzy_match(text, marker)


def _tashuo_cjk_marker_fuzzy_match(text: str, marker: str) -> bool:
    marker_key = platform._message_text_comparable(marker)
    text_key = platform._message_text_comparable(text)
    if not marker_key or not text_key:
        return False
    cjk_count = sum(1 for char in marker_key if "\u4e00" <= char <= "\u9fff")
    if len(marker_key) < 6 or cjk_count < 4 or cjk_count * 2 < len(marker_key):
        return False
    if len(text_key) + 2 < len(marker_key):
        return False
    if not any(marker_key[index : index + 3] in text_key for index in range(max(len(marker_key) - 2, 0))):
        return False

    max_distance = 1 if len(marker_key) < 9 else 2
    min_window = max(1, len(marker_key) - max_distance)
    max_window = len(marker_key) + max_distance
    for width in range(min_window, max_window + 1):
        if width > len(text_key):
            continue
        for start in range(0, len(text_key) - width + 1):
            if _bounded_edit_distance(marker_key, text_key[start : start + width], max_distance) <= max_distance:
                return True
    return False


def _bounded_edit_distance(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        row_min = current[0]
        for right_index, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(
                previous[right_index] + 1,
                current[right_index - 1] + 1,
                previous[right_index - 1] + cost,
            )
            current.append(value)
            row_min = min(row_min, value)
        if row_min > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _verify_staged_tashuo_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    observed_stats = platform._expected_text_observation_stats(observed_text, expected_text)
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    baseline_stats = platform._expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    result = {
        "verification_method": "tashuo_staged_message_ocr_payload_text",
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": observed_stats["text_hash"],
        "observed_character_count": observed_stats["text_character_count"],
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "baseline_expected_text_occurrences": baseline_stats["expected_text_occurrences"] if baseline_stats else None,
        "baseline_text_hash": baseline_stats["text_hash"] if baseline_stats else None,
        "send_action": "press_return",
        "exact_text_ocr_verified": platform._message_text_matches(observed_text, expected_text),
        "visual_only_exact_verification_allowed": False,
        "screen": platform._redacted_screen(screen),
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    baseline_state = baseline_screen.get("state") if isinstance(baseline_screen, dict) else None
    if screen.get("state") != "tashuo_conversation" and baseline_state != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "tashuo_conversation_not_verified"}
    if not platform._message_text_matches(observed_text, expected_text):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    return {**result, "status": "ok"}


def _stage_only_tashuo_verification(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    first_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    low_level = _verify_staged_tashuo_message(screen, expected_text, baseline_screen=baseline_screen)
    observed_text = str(screen.get("text") or "")
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    first_text = str(first_screen.get("text") or "") if isinstance(first_screen, dict) else ""
    placeholder_visible = _tashuo_input_placeholder_visible(observed_text)
    baseline_placeholder_visible = _tashuo_input_placeholder_visible(baseline_text)
    first_placeholder_visible = _tashuo_input_placeholder_visible(first_text)
    evidence = {
        **low_level,
        "placeholder_visible": placeholder_visible,
        "baseline_placeholder_visible": baseline_placeholder_visible,
        "first_capture_placeholder_visible": first_placeholder_visible,
        "screen_text_character_count": len(observed_text),
        "baseline_text_character_count": len(baseline_text),
        "first_screen_text_character_count": len(first_text),
    }
    if low_level.get("status") == "ok":
        return {**evidence, "status": "verified"}
    if low_level.get("status") == "blocked":
        return {**evidence, "status": "failed"}
    if placeholder_visible:
        return {**evidence, "status": "failed", "reason": low_level.get("reason") or "staged_text_not_visible"}
    if len(observed_text) > len(baseline_text) or (baseline_placeholder_visible and not placeholder_visible):
        return {
            **evidence,
            "status": "needs_user_verification",
            "reason": low_level.get("reason") or "cjk_exact_text_not_automatically_verified",
        }
    return {
        **evidence,
        "status": "needs_user_verification",
        "reason": low_level.get("reason") or "stage_result_ambiguous",
    }


def _verify_tashuo_outbound_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    staged_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
) -> dict[str, Any]:
    result = platform._verify_outbound_message(screen, expected_text)
    observed_text = str(screen.get("text") or "")
    staged_text = str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    observed_stats = platform._expected_text_observation_stats(observed_text, expected_text)
    staged_stats = platform._expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    outgoing_bubble_visible = _tashuo_outgoing_bubble_visual_visible(screen)
    staged_outgoing_bubble_visible = (
        _tashuo_outgoing_bubble_visual_visible(staged_screen) if isinstance(staged_screen, dict) else False
    )
    extra = {
        "verification_method": "tashuo_post_send_ocr_payload_text_delta",
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
        "input_cleared_after_send": _tashuo_input_placeholder_visible(observed_text),
        "outgoing_bubble_visual_visible": outgoing_bubble_visible,
        "staged_outgoing_bubble_visual_visible": staged_outgoing_bubble_visible,
        "send_action": "press_return",
        "exact_text_ocr_verified": result.get("status") == "ok",
        "visual_only_exact_verification_allowed": False,
    }
    if result.get("status") != "ok":
        return {**result, **extra}
    if screen.get("state") != "tashuo_conversation":
        return {**result, **extra, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if extra["input_cleared_after_send"] is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}


def _tashuo_input_placeholder_visible(text: str) -> bool:
    normalized = platform._normalize_text(text)
    return "点击此处输入文字" in normalized or "输入文字" in normalized


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _cleanup_failed_tashuo_stage(
    session: Any,
    window: Any,
    input_step: dict[str, Any],
    *,
    expected_text: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    input_tap_ratio = _copy_tap_ratio(input_step["tap_ratio"])
    input_focus_state = str(input_step.get("focus_state") or "unknown")
    click_result = session._click_ratio(window, input_step["tap_ratio"])
    attempts.append({
        "intent": "refocus_tashuo_message_input_for_failed_stage_cleanup",
        "tap_ratio": input_tap_ratio,
        "focus_state": input_focus_state,
        "result": click_result,
    })
    if click_result.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": click_result.get("reason") or "failed_stage_cleanup_refocus_failed",
            "input_tap_ratio": input_tap_ratio,
            "input_focus_state": input_focus_state,
            "attempts": attempts,
        }

    escape_result = session._press_escape_key()
    attempts.append({"intent": "cancel_tashuo_input_candidate_for_failed_stage_cleanup", "result": escape_result})
    backspace_count = min(40, max(4, len(expected_text) + 4))
    for index in range(backspace_count):
        backspace_result = session._press_backspace_key()
        attempts.append({
            "intent": "backspace_tashuo_failed_stage_text",
            "index": index,
            "result": backspace_result,
        })
        if backspace_result.get("status") != "ok":
            return {
                "status": "blocked",
                "reason": backspace_result.get("reason") or "failed_stage_cleanup_backspace_failed",
                "attempts": attempts,
            }
    time.sleep(0.2)
    output = output_dir / f"{_tashuo_capture_prefix(session)}.after_failed_stage_cleanup.png" if output_dir is not None else None
    screen = session.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    expected_still_visible = platform._message_text_matches(observed_text, expected_text)
    input_placeholder_visible = _tashuo_input_placeholder_visible(observed_text)
    result = {
        "attempts": attempts,
        "input_tap_ratio": input_tap_ratio,
        "input_focus_state": input_focus_state,
        "screen": platform._redacted_screen(screen),
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_text_still_visible": expected_still_visible,
        "input_placeholder_visible": input_placeholder_visible,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_screen_not_captured"}
    if expected_still_visible or not input_placeholder_visible:
        return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_not_verified"}
    return {**result, "status": "ok"}


def _tashuo_outgoing_bubble_visual_visible(screen: dict[str, Any] | None) -> bool:
    if not isinstance(screen, dict):
        return False
    stats = platform._screen_region_stats(screen, 0.72, 0.26, 0.98, 0.66)
    if stats is None:
        return False
    return stats["color_ratio"] > 0.030 and stats["bright_ratio"] > 0.65


def _has_tashuo_step_precondition(step: dict[str, Any]) -> bool:
    return bool(step.get("requires_tashuo_top_level_tab_bar") or step.get("requires_tashuo_states"))


def _has_tashuo_step_postcondition(step: dict[str, Any]) -> bool:
    return bool(step.get("expected_tashuo_states"))


def _verify_tashuo_step_state(screen: dict[str, Any], step: dict[str, Any], *, key: str) -> dict[str, Any]:
    expected = step.get(key)
    if not expected:
        return {"status": "ok"}
    expected_states = [str(expected)] if isinstance(expected, str) else [str(state) for state in expected]
    actual = str(screen.get("state") or "unknown")
    if actual in expected_states:
        return {"status": "ok"}
    return {
        "status": "blocked",
        "expected_tashuo_states": expected_states,
        "actual_tashuo_state": actual,
    }


def _verify_tashuo_step_precondition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_tashuo_step_precondition(step):
        return {"status": "ok"}
    output = None
    if output_dir is not None:
        output = output_dir / f"iphone_mirroring.tashuo_precondition_{step_index:02d}.png"
    screen = session.capture_window(output=output, window=window)
    result = {
        "status": screen.get("status", "blocked"),
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "tashuo_precondition_capture_failed"
    elif step.get("requires_tashuo_top_level_tab_bar") and not tashuo_top_level_bottom_nav_present(screen):
        result.update({"status": "blocked", "reason": "tashuo_top_level_tab_bar_not_verified"})
    else:
        state_check = _verify_tashuo_step_state(screen, step, key="requires_tashuo_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "tashuo_step_precondition_not_verified"
    return result


def _verify_tashuo_step_postcondition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_tashuo_step_postcondition(step):
        return {"status": "ok", "checked": False}
    output = None
    if output_dir is not None:
        output = output_dir / f"iphone_mirroring.tashuo_postcondition_{step_index:02d}.png"
    screen = session.capture_window(output=output, window=window)
    result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "tashuo_postcondition_capture_failed"
    else:
        state_check = _verify_tashuo_step_state(screen, step, key="expected_tashuo_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "tashuo_step_postcondition_not_verified"
    return result


def _capture_tashuo_profile_read_step() -> dict[str, Any]:
    return {
        "intent": "capture_profile_read_step",
        "requires_verified_tashuo_screen": True,
        "requires_tashuo_states": ["tashuo_recommend", "tashuo_profile", "tashuo_self_profile"],
        "risk": "navigation_only",
        "wait_after_seconds": 0.0,
    }


def _tashuo_tap_step(
    intent: str,
    *,
    x: float,
    y: float,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = {
        "intent": intent,
        "tap_ratio": {"x": x, "y": y},
        "requires_verified_tashuo_screen": True,
        "risk": "navigation_only",
    }
    if requires_states is not None:
        step["requires_tashuo_states"] = requires_states
    if expected_states is not None:
        step["expected_tashuo_states"] = expected_states
    return step


def _tashuo_bottom_tab_step(intent: str, *, x: float, y: float, expected_state: str) -> dict[str, Any]:
    return {
        "intent": intent,
        "tap_ratio": {"x": x, "y": y},
        "requires_verified_tashuo_screen": True,
        "requires_tashuo_top_level_tab_bar": True,
        "expected_tashuo_states": [expected_state],
        "risk": "navigation_only",
    }


def _tashuo_wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = {
        "intent": intent,
        "wheel": {
            "x": x,
            "y": y,
            "delta_y": delta_y,
            "delta_x": delta_x,
            "repeats": repeats,
            "interval_us": 18000,
        },
        "requires_verified_tashuo_screen": True,
        "risk": "navigation_only",
    }
    if requires_states is not None:
        step["requires_tashuo_states"] = requires_states
    if expected_states is not None:
        step["expected_tashuo_states"] = expected_states
    return step


def _tashuo_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    gate_index = int(options.get("gate_index") or options.get("match_index") or 1)
    row_y = min(0.86, 0.52 + (max(row_index, 1) - 1) * 0.12)
    if options.get("y_ratio") is not None:
        row_y = max(0.16, min(0.88, float(options["y_ratio"])))
    gate_x = min(0.84, 0.15 + (max(gate_index, 1) - 1) * 0.22)
    profile_read_states = ["tashuo_profile", "tashuo_self_profile", "tashuo_recommend"]
    actions: dict[str, list[dict[str, Any]]] = {
        "open-recommend": [
            _tashuo_bottom_tab_step("tap_tashuo_recommend_tab", x=0.14, y=0.92, expected_state="tashuo_recommend")
        ],
        "open-flight": [
            _tashuo_bottom_tab_step("tap_tashuo_flight_tab", x=0.38, y=0.92, expected_state="tashuo_flight")
        ],
        "open-chats": [
            _tashuo_bottom_tab_step(
                "tap_tashuo_messages_tab",
                x=TASHUO_MESSAGES_TAB_TAP_RATIO["x"],
                y=TASHUO_MESSAGES_TAB_TAP_RATIO["y"],
                expected_state="tashuo_chat_list",
            )
        ],
        "open-profile-tab": [
            _tashuo_bottom_tab_step("tap_tashuo_mine_tab", x=0.86, y=0.92, expected_state="tashuo_self_profile")
        ],
        "conversation-list-scroll-down": [
            _tashuo_wheel_step(
                "wheel_tashuo_conversation_list_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=14,
                requires_states="tashuo_chat_list",
                expected_states="tashuo_chat_list",
            )
        ],
        "conversation-list-scroll-up": [
            _tashuo_wheel_step(
                "wheel_tashuo_conversation_list_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=14,
                requires_states="tashuo_chat_list",
                expected_states="tashuo_chat_list",
            )
        ],
        "open-conversation": [
            {
                **_tashuo_tap_step(
                    "tap_tashuo_conversation_row",
                    x=0.45,
                    y=row_y,
                    requires_states="tashuo_chat_list",
                    expected_states=["tashuo_conversation", "tashuo_question_gate"],
                ),
                "row_index": row_index,
            }
        ],
        "open-question-gate": [
            {
                **_tashuo_tap_step(
                    "tap_tashuo_waiting_question_card",
                    x=gate_x,
                    y=0.30,
                    requires_states="tashuo_chat_list",
                    expected_states=["tashuo_question_gate", "tashuo_conversation"],
                ),
                "gate_index": gate_index,
            }
        ],
        "open-thread-profile": [
            _tashuo_tap_step(
                "tap_tashuo_thread_name",
                x=0.50,
                y=0.13,
                requires_states="tashuo_conversation",
                expected_states="tashuo_profile",
            )
        ],
        "profile-scroll-down": [
            _tashuo_wheel_step(
                "wheel_tashuo_profile_read_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "profile-scroll-up": [
            _tashuo_wheel_step(
                "wheel_tashuo_profile_read_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "close-profile": [
            _tashuo_tap_step(
                "tap_tashuo_profile_back",
                x=0.09,
                y=0.13,
                requires_states="tashuo_profile",
                expected_states="tashuo_conversation",
            )
        ],
        "return-to-chats": [
            _tashuo_tap_step(
                "tap_tashuo_back_to_chats",
                x=0.09,
                y=0.13,
                requires_states=["tashuo_conversation", "tashuo_question_gate"],
                expected_states="tashuo_chat_list",
            )
        ],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]


def _tashuo_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "self-profile-read":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or options.get("scroll_steps") or 2))
        steps = []
        steps.extend(_tashuo_action_steps("open-profile-tab"))
        steps.append(_capture_tashuo_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tashuo_action_steps("profile-scroll-down"))
            steps.append(_capture_tashuo_profile_read_step())
        return steps
    if workflow == "recommend-profile-read":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or options.get("scroll_steps") or 2))
        steps = []
        steps.extend(_tashuo_action_steps("open-recommend"))
        steps.append(_capture_tashuo_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tashuo_action_steps("profile-scroll-down"))
            steps.append(_capture_tashuo_profile_read_step())
        return steps
    if workflow == "chat-read-match-profile":
        conversation_row = int(options.get("conversation_row") or 1)
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or 2))
        steps = []
        steps.extend(_tashuo_action_steps("open-chats"))
        steps.extend(_tashuo_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_tashuo_action_steps("open-thread-profile"))
        steps.append(_capture_tashuo_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tashuo_action_steps("profile-scroll-down"))
            steps.append(_capture_tashuo_profile_read_step())
        steps.extend(_tashuo_action_steps("close-profile"))
        return steps
    if workflow == "question-gate-open":
        gate_index = int(options.get("gate_index") or options.get("match_index") or 1)
        steps = []
        steps.extend(_tashuo_action_steps("open-chats"))
        steps.extend(_tashuo_action_steps("open-question-gate", gate_index=gate_index))
        return steps
    if workflow == "question-gate-reply-composer":
        gate_index = int(options.get("gate_index") or options.get("match_index") or 1)
        steps = []
        steps.extend(_tashuo_action_steps("open-chats"))
        steps.extend(_tashuo_action_steps("open-question-gate", gate_index=gate_index))
        return steps
    raise KeyError(workflow)


def _tashuo_profile_field_coverage(text: str) -> dict[str, bool]:
    normalized = platform._normalize_text(text)
    return {
        "about_me": any(marker in normalized for marker in ("关于我", "自我介绍")),
        "daily_life": any(marker in normalized for marker in ("我的日常", "日常")),
        "wishes": any(marker in normalized for marker in ("我的愿望", "愿望")),
        "basic_info": any(marker in normalized for marker in ("资料", "身高", "星座", "家乡")),
        "activity": "动态" in normalized,
    }
