from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4
import time

from dating_boost.apps.tashuo.screen_state import (
    TASHUO_FOREGROUND_STATES,
    classify_tashuo_screen_image,
    classify_tashuo_capture,
    tashuo_layout_hints,
    tashuo_message_list_top_anchor_present,
    tashuo_top_level_bottom_nav_present,
)
from dating_boost.apps import native_gui_session as platform
from dating_boost.core.live_send_contract import (
    target_binding_specific_marker_present,
    target_binding_structural_evidence_present,
)
from dating_boost.core.send_pipeline import (
    EvidencePayload,
    PostSendVerification,
    SendAttemptContext,
    StagingResult,
)
from dating_boost.core.harness_steps import (
    marker_step as _harness_marker_step,
    tap_step as _harness_tap_step,
    wheel_step as _harness_wheel_step,
)
from dating_boost.core.target_binding import (
    RowToThreadBindingSpec,
    finish_row_to_thread_screen_verification,
    row_to_thread_base_result,
    validate_row_to_thread_structural_evidence,
)
from dating_boost.harness.base import SubprocessRunner
from dating_boost.harness.screen_state import _read_png_pixels


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
TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO = {"x": 0.32, "y": 0.90}
TASHUO_MESSAGES_TAB_TAP_RATIO = {"x": 0.67, "y": 0.96}
TASHUO_CONVERSATION_NAVBACK_TAP_RATIO = {"x": 0.07, "y": 0.115}
TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS = 3.0
TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS = 0.35
TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE = 12
TASHUO_MAC_IOS_APP_INPUT_OCR_REGION = {"x1": 0.035, "y1": 0.772, "x2": 0.905, "y2": 0.906}
TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED = True
TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION = {"x1": 0.56, "y1": 0.22, "x2": 0.98, "y2": 0.84}
TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO = 0.012
TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA = 4.0
TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS = 3
TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION = {"x1": 0.0, "y1": 0.16, "x2": 1.0, "y2": 0.88}
TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE = 8


def install_tashuo_session_hooks(session: Any) -> None:
    session.app_screen_state_observer = classify_tashuo_capture
    session.app_foreground_states = set(TASHUO_FOREGROUND_STATES)
    session.app_verified_screen_key = "requires_verified_tashuo_screen"
    session.app_foreground_not_verified_reason = "tashuo_foreground_not_verified"
    session.app_step_precondition_verifier = _verify_tashuo_step_precondition
    session.app_step_postcondition_verifier = _verify_tashuo_step_postcondition
    session.app_profile_field_coverage = _tashuo_profile_field_coverage


def _capture_tashuo_window(
    session: Any,
    *,
    output: Path | None = None,
    window: Any = None,
    ocr: bool | None = None,
) -> dict[str, Any]:
    use_ocr = not _is_mac_ios_app_session(session) if ocr is None else bool(ocr)
    return session.capture_window(output=output, window=window, ocr=use_ocr)


def _tashuo_post_action_observation_delay_seconds(session: Any, *, fallback: float) -> float:
    if _is_mac_ios_app_session(session):
        return max(platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(fallback))
    return float(fallback)


def _sleep_for_tashuo_post_action_observation(session: Any, *, fallback: float) -> None:
    delay = _tashuo_post_action_observation_delay_seconds(session, fallback=fallback)
    runner = getattr(session, "runner", None)
    if isinstance(runner, SubprocessRunner):
        time.sleep(delay)
    else:
        time.sleep(min(delay, float(fallback)))


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
    screen = _capture_tashuo_window(session, output=output, window=window)
    payload["screen"] = platform._redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    payload["layout_hints"] = tashuo_layout_hints(screen)
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
    verification = _capture_tashuo_window(session, output=verification_output, window=window)
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
        if _tashuo_mac_ios_window_recoverable_reason(verification.get("reason")):
            recovery_steps = _recover_tashuo_mac_ios_app_window(
                session,
                bundle_id=bundle_id,
                process_name=process_name,
            )
            payload["recovery_steps"] = recovery_steps
            recovery_output = output_dir / "mac_ios_app.tashuo.after_launch_recovered.png" if output_dir is not None else None
            verification = session.doctor(capture=True, output=recovery_output)
            if verification["status"] == "blocked" and _tashuo_mac_ios_window_recoverable_reason(verification.get("reason")):
                force_recovery_steps = _force_recover_tashuo_mac_ios_app_window(
                    session,
                    bundle_id=bundle_id,
                    process_name=process_name,
                )
                payload["force_recovery_steps"] = force_recovery_steps
                force_recovery_output = (
                    output_dir / "mac_ios_app.tashuo.after_launch_force_recovered.png"
                    if output_dir is not None
                    else None
                )
                verification = session.doctor(capture=True, output=force_recovery_output)
            payload["verification"] = verification
            if verification["status"] == "blocked":
                payload.update({"status": "blocked", "reason": verification.get("reason")})
            elif verification.get("screen", {}).get("state") not in TASHUO_FOREGROUND_STATES:
                payload.update({"status": "needs_verification", "reason": "tashuo_mac_ios_app_launch_not_verified"})
        else:
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


def _applescript_literal(value: str) -> str:
    return json.dumps(value)


def _tashuo_mac_ios_window_recoverable_reason(reason: Any) -> bool:
    return str(reason or "") in {"mac_ios_app_process_has_no_windows", "mac_ios_app_window_not_found"}


def _recover_tashuo_mac_ios_app_window(session: Any, *, bundle_id: str, process_name: str) -> list[dict[str, Any]]:
    recovery_steps: list[dict[str, Any]] = []
    quit_result = session.runner.run(
        ["osascript", "-e", f"tell application id {_applescript_literal(bundle_id)} to quit"]
    )
    recovery_steps.append(
        {
            "intent": "quit_tashuo_mac_ios_app_without_windows",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if quit_result.returncode == 0 else "blocked",
                "stderr": platform._short(quit_result.stderr),
            },
        }
    )
    if quit_result.returncode != 0:
        fallback_script = "\n".join(
            [
                'tell application "System Events"',
                f"if exists process {_applescript_literal(process_name)} then",
                f"tell process {_applescript_literal(process_name)} to quit",
                "end if",
                "end tell",
            ]
        )
        fallback_result = session.runner.run(["osascript", "-e", fallback_script])
        recovery_steps.append(
            {
                "intent": "quit_tashuo_mac_ios_process_without_windows",
                "process_name": process_name,
                "risk": "navigation_only",
                "result": {
                    "status": "ok" if fallback_result.returncode == 0 else "blocked",
                    "stderr": platform._short(fallback_result.stderr),
                },
            }
        )
    time.sleep(0.8)
    reopen_result = session.runner.run(["open", "-b", bundle_id])
    recovery_steps.append(
        {
            "intent": "reopen_tashuo_mac_ios_app_after_no_window",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if reopen_result.returncode == 0 else "blocked",
                "stderr": platform._short(reopen_result.stderr),
            },
        }
    )
    time.sleep(0.8)
    activate_payload = session._activate_window()
    recovery_steps.append(
        {
            "intent": "reactivate_tashuo_mac_ios_app_after_no_window",
            "process_name": process_name,
            "risk": "navigation_only",
            "result": activate_payload,
        }
    )
    time.sleep(0.4)
    return recovery_steps


def _force_recover_tashuo_mac_ios_app_window(session: Any, *, bundle_id: str, process_name: str) -> list[dict[str, Any]]:
    recovery_steps: list[dict[str, Any]] = []
    kill_result = session.runner.run(["pkill", "-x", process_name])
    recovery_steps.append(
        {
            "intent": "force_quit_tashuo_mac_ios_process_without_windows",
            "process_name": process_name,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if kill_result.returncode in {0, 1} else "blocked",
                "stderr": platform._short(kill_result.stderr),
                "returncode": kill_result.returncode,
            },
        }
    )
    time.sleep(1.0)
    reopen_result = session.runner.run(["open", "-b", bundle_id])
    recovery_steps.append(
        {
            "intent": "reopen_tashuo_mac_ios_app_after_force_quit",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if reopen_result.returncode == 0 else "blocked",
                "stderr": platform._short(reopen_result.stderr),
            },
        }
    )
    time.sleep(1.2)
    activate_payload = session._activate_window()
    recovery_steps.append(
        {
            "intent": "reactivate_tashuo_mac_ios_app_after_force_quit",
            "process_name": process_name,
            "risk": "navigation_only",
            "result": activate_payload,
        }
    )
    time.sleep(0.5)
    return recovery_steps


def _tap_ratio_option(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = max(0.0, min(1.0, float(value["x"])))
        y = max(0.0, min(1.0, float(value["y"])))
    except (KeyError, TypeError, ValueError):
        return None
    return {"x": x, "y": y}


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
    if action in {"conversation-list-scroll-to-top", "conversation-list-return-to-top"}:
        return scroll_tashuo_conversation_list_to_top(
            session,
            dry_run=dry_run,
            output_dir=output_dir,
            max_scrolls=int(options.get("max_scrolls") or 8),
        )
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
    if action == "open-conversation":
        already_open = _tashuo_already_at_open_conversation_target(session, planned_steps, output_dir=output_dir)
        if already_open is not None:
            payload.update(already_open)
            return payload
    return session._execute_planned_steps(payload, output_dir=output_dir)


def _tashuo_already_at_open_conversation_target(
    session: Any,
    planned_steps: list[dict[str, Any]],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any] | None:
    if not planned_steps:
        return None
    expected_states = planned_steps[0].get("expected_tashuo_states")
    expected = set(expected_states if isinstance(expected_states, list) else [expected_states])
    expected.discard(None)
    if not expected:
        return None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    before = output_dir / f"{_tashuo_capture_prefix(session)}.before_action.png" if output_dir is not None else None
    doctor = session.doctor(capture=True, output=before, ocr=not _is_mac_ios_app_session(session))
    if doctor.get("status") == "blocked":
        return {
            "preflight": doctor,
            "status": "blocked",
            "reason": doctor.get("reason") or "tashuo_preflight_not_verified",
        }
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state not in expected:
        return None
    return {
        "preflight": doctor,
        "screen_state": screen_state,
        "already_at_expected_state": True,
        "target_binding_created": False,
        "next_host_action": "observe_current_thread",
    }


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
            "intent": "click_tashuo_conversation_navback_accessibility",
            "ax_description": "thin left navback",
            "risk": "navigation_only",
            "conditional_on_visual_state": "tashuo_conversation",
            "wait_after_seconds": 0.45,
        },
        {
            "intent": "tap_tashuo_conversation_navback_visual_fallback",
            "tap_ratio": _copy_tap_ratio(TASHUO_CONVERSATION_NAVBACK_TAP_RATIO),
            "risk": "navigation_only",
            "conditional_on_visual_state": "tashuo_conversation",
            "fallback_for": "click_tashuo_conversation_navback_accessibility",
            "wait_after_seconds": 0.45,
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
            "intent": "wait_tashuo_messages_page_content_visual_settle",
            "risk": "visual_observation_only",
            "conditional_on_active_tab": "messages",
            "ocr_used": False,
            "timeout_seconds": TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS,
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
        if _tashuo_mac_ios_window_recoverable_reason(doctor.get("reason")):
            recovery_steps = _recover_tashuo_mac_ios_app_window(
                session,
                bundle_id=bundle_id,
                process_name=str(runtime_config.get("process_name") or "tashuo"),
            )
            payload["recovery_steps"] = recovery_steps
            doctor = session.doctor(capture=False)
            if doctor["status"] == "blocked" and _tashuo_mac_ios_window_recoverable_reason(doctor.get("reason")):
                force_recovery_steps = _force_recover_tashuo_mac_ios_app_window(
                    session,
                    bundle_id=bundle_id,
                    process_name=str(runtime_config.get("process_name") or "tashuo"),
                )
                payload["force_recovery_steps"] = force_recovery_steps
                doctor = session.doctor(capture=False)
            payload["preflight"] = doctor
            if doctor["status"] == "blocked":
                payload.update({"status": "blocked", "reason": doctor.get("reason"), "executed_steps": executed_steps})
                return payload
        else:
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
    if initial_screen.get("visual_state") == "tashuo_conversation":
        navback_result = _click_tashuo_conversation_navback_button(session)
        executed_steps.append({**planned_steps[3], "result": navback_result})
        if navback_result.get("status") != "ok":
            fallback_result = session._click_ratio(window, planned_steps[4]["tap_ratio"])
            executed_steps.append({
                **planned_steps[4],
                "accessibility_result": navback_result,
                "result": fallback_result,
            })
            if fallback_result.get("status") != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": fallback_result.get("reason") or navback_result.get("reason") or "tashuo_conversation_navback_failed",
                    "screen_state": initial_screen.get("state", "unknown"),
                    "next_host_action": "inspect_tashuo_conversation_navback",
                    "executed_steps": executed_steps,
                })
                return payload
            time.sleep(float(planned_steps[4]["wait_after_seconds"]))
        else:
            time.sleep(float(planned_steps[3]["wait_after_seconds"]))
        returned_output = (
            output_dir / "mac_ios_app.tashuo.prepare_message_page.after_navback.png"
            if output_dir is not None
            else None
        )
        returned_screen = _capture_tashuo_visual_screen(session, window, output=returned_output)
        payload["after_navback_screen"] = platform._redacted_screen(returned_screen)
        if returned_screen.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": returned_screen.get("reason") or "tashuo_visual_capture_failed",
                "screen_state": returned_screen.get("state", "unknown"),
                "executed_steps": executed_steps,
            })
            return payload
        initial_screen = returned_screen
        payload["post_navback_visual_state"] = returned_screen.get("visual_state", "unknown")
        payload["post_navback_active_tab"] = returned_screen.get("visual_active_tab", "unknown")

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
        settled_screen, settle_result = _wait_for_tashuo_message_page_ready(
            session,
            window,
            output_dir=output_dir,
            output_stem="mac_ios_app.tashuo.prepare_message_page.messages",
            initial_screen=initial_screen,
        )
        payload["message_page_settle"] = settle_result
        executed_steps.append({**planned_steps[7], "result": settle_result})
        payload.update({
            "screen": platform._redacted_screen(settled_screen),
            "screen_state": settled_screen.get("state", "unknown"),
            "executed_steps": executed_steps,
        })
        if settle_result.get("status") != "ok":
            payload.update({
                "status": "needs_verification",
                "reason": "tashuo_message_page_content_not_settled",
                "next_host_action": "visual_analyze_current_screen",
            })
        else:
            executed_steps.append({**planned_steps[8], "result": {"status": "ok"}})
        return payload

    ax_result = _click_tashuo_messages_radio_button(session)
    executed_steps.append({**planned_steps[5], "result": ax_result})
    if ax_result["status"] != "ok":
        tap_result = session._click_ratio(window, planned_steps[6]["tap_ratio"])
        executed_steps.append({**planned_steps[6], "result": tap_result})
        if tap_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": tap_result.get("reason"), "executed_steps": executed_steps})
            return payload
    time.sleep(float(planned_steps[5]["wait_after_seconds"]))

    final_screen, settle_result = _wait_for_tashuo_message_page_ready(
        session,
        window,
        output_dir=output_dir,
        output_stem="mac_ios_app.tashuo.prepare_message_page.messages",
    )
    payload["message_page_settle"] = settle_result
    payload["screen"] = platform._redacted_screen(final_screen)
    payload["screen_state"] = final_screen.get("state", "unknown")
    executed_steps.append({**planned_steps[7], "result": settle_result})
    payload["executed_steps"] = executed_steps
    if final_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": final_screen.get("reason") or "tashuo_visual_capture_failed"})
    elif settle_result.get("status") != "ok":
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_message_page_content_not_settled",
            "next_host_action": "visual_analyze_current_screen",
        })
    elif final_screen.get("visual_active_tab") != "messages":
        payload.update({"status": "needs_verification", "reason": "tashuo_messages_tab_not_verified"})
    else:
        executed_steps.append({**planned_steps[8], "result": {"status": "ok"}})
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
            "chat_list_visual_present": False,
            "recommend_card_visual_present": False,
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
        "chat_list_visual_present": visual.get("chat_list_visual_present", False),
        "chat_list_visual_signal": visual.get("chat_list_visual_signal", {}),
        "message_list_top_anchor_present": visual.get("message_list_top_anchor_present", False),
        "message_list_top_anchor_signal": visual.get("message_list_top_anchor_signal", {}),
        "recommend_card_visual_present": visual.get("recommend_card_visual_present", False),
        "recommend_card_visual_signal": visual.get("recommend_card_visual_signal", {}),
        "conversation_toolbar_present": visual.get("conversation_toolbar_present", False),
        "ocr_status": "skipped",
        "text": "",
    }


def _tashuo_message_page_visual_ready(screen: dict[str, Any]) -> bool:
    return (
        screen.get("status") == "ok"
        and screen.get("visual_active_tab") == "messages"
        and bool(screen.get("chat_list_visual_present"))
        and not bool(screen.get("recommend_card_visual_present"))
    )


def _tashuo_message_list_top_anchor_verified(screen: dict[str, Any]) -> bool:
    return (
        screen.get("status") == "ok"
        and screen.get("state") == "tashuo_chat_list"
        and tashuo_message_list_top_anchor_present(screen)
    )


def _tashuo_scroll_top_attempt(
    *,
    attempt: int,
    screen: dict[str, Any],
    scroll_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "attempt": attempt,
        "top_anchor_verified": _tashuo_message_list_top_anchor_verified(screen),
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "message_list_top_anchor_present": bool(screen.get("message_list_top_anchor_present")),
        "message_list_top_anchor_signal": screen.get("message_list_top_anchor_signal") or {},
    }
    if scroll_result is not None:
        payload["scroll_result"] = scroll_result
    return payload


def scroll_tashuo_conversation_list_to_top(
    session: Any,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    max_scrolls: int = 8,
) -> dict[str, Any]:
    scroll_step = _tashuo_action_steps("conversation-list-scroll-up")[0]
    payload = {
        **session._base_payload("ok"),
        "action": "conversation-list-scroll-to-top",
        "target": "tashuo_message_list_top",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": [
            {
                **scroll_step,
                "repeat_until": "message_list_top_anchor_verified",
                "max_scrolls": max(0, max_scrolls),
                "post_action_observation_delay_seconds": platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS,
            }
        ],
        "visual_only_navigation": _is_mac_ios_app_session(session),
        "ocr_used": not _is_mac_ios_app_session(session),
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    doctor = session.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    window = platform._window_from_payload(doctor.get("window") or {})
    use_ocr = not _is_mac_ios_app_session(session)
    initial_output = (
        output_dir / f"{_tashuo_capture_prefix(session)}.message_list_top_check.initial.png"
        if output_dir is not None
        else None
    )
    initial_screen = _capture_tashuo_window(session, output=initial_output, window=window, ocr=use_ocr)
    attempts = [_tashuo_scroll_top_attempt(attempt=0, screen=initial_screen)]
    payload["attempts"] = attempts
    if initial_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": initial_screen.get("reason") or "tashuo_top_check_capture_failed"})
        return payload
    if initial_screen.get("state") != "tashuo_chat_list":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_chat_list_not_verified",
            "screen_state": initial_screen.get("state", "unknown"),
        })
        return payload
    if attempts[-1]["top_anchor_verified"]:
        payload.update({
            "top_anchor_verified": True,
            "screen": platform._redacted_screen(initial_screen),
            "screen_state": initial_screen.get("state", "unknown"),
            "executed_steps": [],
            "next_host_action": "visual_plan_message_list_from_top",
        })
        return payload

    executed_steps: list[dict[str, Any]] = []
    for attempt in range(1, max(0, max_scrolls) + 1):
        scroll_result = session._execute_step(window, scroll_step)
        executed_steps.append({**scroll_step, "result": scroll_result, "attempt": attempt})
        if scroll_result.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": scroll_result.get("reason") or "tashuo_conversation_list_scroll_up_failed",
                "executed_steps": executed_steps,
            })
            return payload
        time.sleep(max(platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(scroll_step.get("wait_after_seconds", 0.0))))
        output = (
            output_dir / f"{_tashuo_capture_prefix(session)}.message_list_top_check.{attempt:02d}.png"
            if output_dir is not None
            else None
        )
        screen = _capture_tashuo_window(session, output=output, window=window, ocr=use_ocr)
        attempt_payload = _tashuo_scroll_top_attempt(attempt=attempt, screen=screen, scroll_result=scroll_result)
        attempts.append(attempt_payload)
        if screen.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": screen.get("reason") or "tashuo_top_check_capture_failed",
                "executed_steps": executed_steps,
            })
            return payload
        if screen.get("state") != "tashuo_chat_list":
            payload.update({
                "status": "blocked",
                "reason": "tashuo_chat_list_not_verified_after_scroll",
                "screen_state": screen.get("state", "unknown"),
                "executed_steps": executed_steps,
            })
            return payload
        if attempt_payload["top_anchor_verified"]:
            payload.update({
                "top_anchor_verified": True,
                "screen": platform._redacted_screen(screen),
                "screen_state": screen.get("state", "unknown"),
                "executed_steps": executed_steps,
                "next_host_action": "visual_plan_message_list_from_top",
            })
            return payload

    payload.update({
        "status": "needs_host_visual_verification",
        "reason": "tashuo_message_list_top_anchor_not_verified",
        "top_anchor_verified": False,
        "executed_steps": executed_steps,
        "next_host_action": "visual_confirm_message_list_top_or_continue_scroll",
    })
    return payload


def _wait_for_tashuo_message_page_ready(
    session: Any,
    window: Any,
    *,
    output_dir: Path | None,
    output_stem: str,
    initial_screen: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    last_screen: dict[str, Any] = initial_screen or {
        "status": "blocked",
        "reason": "tashuo_visual_capture_not_started",
        "state": "unknown",
    }
    start = time.monotonic()
    if initial_screen is not None:
        ready = _tashuo_message_page_visual_ready(initial_screen)
        attempts.append({
            "attempt": 0,
            "source": "initial_screen",
            "ready": ready,
            "screen": platform._redacted_screen(initial_screen),
        })
        if ready:
            return initial_screen, {
                "status": "ok",
                "attempt_count": 0,
                "settled": True,
                "attempts": attempts,
            }

    attempt = 0
    while time.monotonic() - start <= TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS:
        attempt += 1
        output = None
        if output_dir is not None:
            suffix = "" if attempt == 1 else f".wait_{attempt}"
            output = output_dir / f"{output_stem}{suffix}.png"
        screen = _capture_tashuo_visual_screen(session, window, output=output)
        last_screen = screen
        ready = _tashuo_message_page_visual_ready(screen)
        attempts.append({
            "attempt": attempt,
            "ready": ready,
            "screen": platform._redacted_screen(screen),
        })
        if screen.get("status") != "ok":
            return screen, {
                "status": "blocked",
                "reason": screen.get("reason") or "tashuo_visual_capture_failed",
                "attempt_count": attempt,
                "settled": False,
                "attempts": attempts,
            }
        if ready:
            return screen, {
                "status": "ok",
                "attempt_count": attempt,
                "settled": True,
                "attempts": attempts,
            }
        if time.monotonic() - start >= TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS:
            break
        time.sleep(TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS)

    return last_screen, {
        "status": "timeout",
        "reason": "tashuo_message_page_content_not_settled",
        "attempt_count": attempt,
        "settled": False,
        "attempts": attempts,
    }


def _click_tashuo_conversation_navback_button(session: Any) -> dict[str, Any]:
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    process_name = str(runtime_config.get("process_name") or "tashuo")
    script = f'''
tell application "System Events"
  tell process "{process_name}"
    set elems to entire contents of window 1
    repeat with e in elems
      try
        if (class of e as text) is "button" and (description of e as text) is "thin left navback" then
          click e
          return "clicked"
        end if
      end try
    end repeat
    return "not_found"
  end tell
end tell
'''.strip()
    result = session.runner.run(["osascript", "-e", script])
    stdout = (result.stdout or "").strip()
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_conversation_navback_ax_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    if stdout != "clicked":
        return {
            "status": "blocked",
            "reason": "tashuo_conversation_navback_not_found",
            "stdout": platform._short(stdout),
            "input_backend": "macos_accessibility",
        }
    return {
        "status": "ok",
        "input_backend": "macos_accessibility",
        "ax_description": "thin left navback",
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
            "intent": "clear_existing_tashuo_message_input_if_present",
            "risk": "draft_staging_only",
            "does_not_send": True,
            "fallback_ok": True,
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
    doctor = session.doctor(capture=True, output=before, ocr=not _is_mac_ios_app_session(session))
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
    baseline = output_dir / "mac_ios_app.tashuo.before_stage_draft.baseline.png" if output_dir is not None else None
    baseline_screen = _capture_tashuo_window(session, output=baseline, window=window, ocr=not _is_mac_ios_app_session(session))
    payload["pre_stage_observation"] = platform._redacted_screen(baseline_screen)

    executed_steps: list[dict[str, Any]] = []
    copy_result = {"status": "not_run"}
    paste_result = {"status": "not_run"}
    clear_result = {"status": "not_run"}
    try:
        click_result = session._click_ratio(window, planned_steps[0]["tap_ratio"])
        executed_steps.append({**planned_steps[0], "result": click_result})
        if click_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": click_result["reason"]})
            return payload
        clear_result = _clear_tashuo_ax_text_area(session)
        payload["pre_stage_clear_result"] = clear_result
        executed_steps.append({**planned_steps[1], "result": clear_result})
        if clear_result.get("status") == "ok":
            time.sleep(0.1)
        copy_result = session._copy_to_clipboard(draft_text)
        executed_steps.append({**planned_steps[2], "result": copy_result})
        if copy_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": copy_result["reason"]})
            return payload
        paste_result = session._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
        executed_steps.append({**planned_steps[3], "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result["reason"]})
            return payload
        time.sleep(0.35)
        after = output_dir / "mac_ios_app.tashuo.after_stage_draft.png" if output_dir is not None else None
        after_screen = _capture_tashuo_window(session, output=after, window=window, ocr=not _is_mac_ios_app_session(session))
        time.sleep(0.45)
        delayed_after = output_dir / "mac_ios_app.tashuo.after_stage_draft.delayed.png" if output_dir is not None else None
        delayed_screen = _capture_tashuo_window(session, output=delayed_after, window=window, ocr=not _is_mac_ios_app_session(session))
        payload["verification"] = platform._redacted_screen(delayed_screen)
        payload["stage_attempt_status"] = "completed"
        stage_ax_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
        payload["staged_text_verification"] = _stage_only_tashuo_verification(
            delayed_screen,
            draft_text,
            baseline_screen=baseline_screen if isinstance(baseline_screen, dict) else None,
            first_screen=after_screen,
            trusted_direct_input=clear_result.get("status") == "ok",
            ax_text_area_value=stage_ax_value,
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
    ax_set_text_step = {
        "intent": "set_tashuo_message_input_with_accessibility_if_paste_did_not_stage",
        "risk": "live_send_precondition",
        "fallback_only": True,
        "requires_exact_text_verification_after_ax_set": True,
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
        "visual_only_exact_verification_allowed": _is_mac_ios_app_session(session),
        "requires_exact_text_verification_before_return": True,
    }
    payload = SendAttemptContext(
        action="send_message",
        target="tashuo_message_input",
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=(input_step, paste_step, ax_set_text_step, type_fallback_step, ime_commit_step, send_step),
        blocked_actions=tuple(TASHUO_SEND_BLOCKED_GUI_ACTIONS),
        extra_fields={
            "question_gate_policy": copy.deepcopy(TASHUO_QUESTION_GATE_POLICY),
            "input_coordinate_model": _tashuo_input_coordinate_model(session),
        },
    ).initial_payload(session._base_payload("ok"))
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    if (
        target_binding is not None
        and _is_mac_ios_app_session(session)
        and not target_binding_structural_evidence_present("tashuo", target_binding)
    ):
        payload.update({
            "status": "blocked",
            "reason": "target_binding_structural_evidence_required",
            "target_binding_verification": {
                "verification_method": "tashuo_mac_ios_app_structural_binding_required",
                "status": "blocked",
                "reason": "target_binding_structural_evidence_required",
                "requires_header_marker": False,
                "requires_structural_binding": True,
            },
        })
        return payload

    capture_prefix = _tashuo_capture_prefix(session)
    preflight_output = output_dir / f"{capture_prefix}.before_send_message.png" if output_dir is not None else None
    preflight = session.doctor(capture=True, output=preflight_output, ocr=not _is_mac_ios_app_session(session))
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
            can_relocate_anchor_mismatch = (
                _is_mac_ios_app_session(session)
                and target_binding.get("binding_type") == "current_thread_visual_identity"
                and target_verification.get("reason") == "target_binding_visual_anchor_mismatch"
                and target_verification.get("screen_state") == "tashuo_conversation"
            )
            if can_relocate_anchor_mismatch:
                relocation = _recover_tashuo_current_thread_visual_identity_mismatch(
                    session,
                    target_binding,
                    output_dir=output_dir,
                )
                payload["target_binding_relocation"] = relocation
                if relocation.get("status") == "ok":
                    payload["target_binding_verification"] = relocation.get("target_binding_verification") or {
                        **target_verification,
                        "status": "ok",
                        "recovered_by": "message_list_visual_relocation",
                    }
                else:
                    payload.update({
                        "status": "blocked",
                        "reason": relocation.get("reason") or target_verification.get("reason") or "target_binding_mismatch",
                    })
                    return payload
            else:
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
                })
                return payload

    baseline_output = output_dir / f"{capture_prefix}.before_stage_message.png" if output_dir is not None else None
    baseline_screen = _capture_tashuo_window(session, output=baseline_output, window=window, ocr=not _is_mac_ios_app_session(session))
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

    already_sent_ax_static_text_values = _tashuo_ax_static_text_values(session) if _is_mac_ios_app_session(session) else None
    already_sent_ax_text_area_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    already_sent_verification = _verify_tashuo_outbound_message(
        baseline_screen,
        draft_text,
        ax_static_text_values=already_sent_ax_static_text_values,
        ax_text_area_value=already_sent_ax_text_area_value,
        visual_commit_allowed=False,
        ocr_disabled_after_message_page=_is_mac_ios_app_session(session),
    )
    if already_sent_verification.get("status") == "ok":
        post_id_source = f"{payload['draft_fingerprint']}:{baseline_screen.get('path') or platform._now_iso()}:{uuid4().hex}"
        post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
        current_thread_anchor = _tashuo_current_thread_visual_anchor(baseline_screen)
        payload["post_action_observation"] = platform._redacted_screen(baseline_screen)
        payload["post_action_observation_id"] = post_observation_id
        payload["outbound_message_verification"] = already_sent_verification
        payload["current_thread_visual_anchor"] = current_thread_anchor
        payload["already_sent"] = True
        payload["staged_text_verified"] = False
        payload["executed_steps"] = []
        payload["evidence"] = {
            "staged_text_verified": False,
            "staged_exact_text_verified": False,
            "staged_exact_text_ax_verified": False,
            "staged_exact_text_ocr_verified": False,
            "send_input_backend": "already_sent_idempotent_skip",
            "input_cleared_after_send": bool(already_sent_verification.get("input_cleared_after_send")),
            "post_action_screen_captured": baseline_screen.get("status") == "ok",
            "outbound_message_verified": True,
            "outbound_exact_text_verified": bool(already_sent_verification.get("exact_text_verified")),
            "outbound_exact_text_ax_verified": bool(already_sent_verification.get("exact_text_ax_verified")),
            "outbound_exact_text_ocr_verified": bool(already_sent_verification.get("exact_text_ocr_verified")),
            "outbound_exact_text_visual_verified": bool(already_sent_verification.get("exact_text_visual_verified")),
            "outbound_visual_commit_verified": bool(already_sent_verification.get("visual_commit_verified")),
            "visual_only_exact_verification_allowed": bool(already_sent_verification.get("visual_only_exact_verification_allowed")),
            "post_action_observation_id": post_observation_id,
        }
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
        staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
        staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
            session,
            staged_screen,
            draft_text,
            baseline_screen=baseline_screen,
            output_dir=output_dir,
            label=f"{capture_prefix}.after_stage_message.input_crop",
        )
        staged_text = str(staged_screen.get("text") or "")
        staged_input_placeholder_visible = _tashuo_input_placeholder_visible(staged_text)
        if staged_verification.get("status") != "ok" and _is_mac_ios_app_session(session):
            ax_set_result = _set_tashuo_ax_text_area_value(session, draft_text)
            executed_steps.append({**ax_set_text_step, "result": ax_set_result})
            payload["ax_set_text_area_result"] = ax_set_result
            if ax_set_result.get("status") == "ok":
                time.sleep(0.25)
                staged_output = output_dir / f"{capture_prefix}.after_ax_set_message.png" if output_dir is not None else None
                staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
                staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
                    session,
                    staged_screen,
                    draft_text,
                    baseline_screen=baseline_screen,
                    output_dir=output_dir,
                    label=f"{capture_prefix}.after_ax_set_message.input_crop",
                )
                payload["ax_set_text_verification"] = staged_verification
                payload["staging_input_backend"] = ax_set_result.get("input_backend")
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
            staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
            staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
                session,
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
                trusted_direct_input=True,
                output_dir=output_dir,
                label=f"{capture_prefix}.after_type_message.input_crop",
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
            staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
            committed_verification = _verify_staged_tashuo_message_with_crop_ocr(
                session,
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
                trusted_direct_input=True,
                output_dir=output_dir,
                label=f"{capture_prefix}.after_ime_commit_message.input_crop",
            )
            payload["direct_type_text_verification"] = direct_type_verification
            payload["ime_commit_text_verification"] = committed_verification
            if committed_verification.get("status") == "ok" or direct_type_verification.get("status") != "ok":
                staged_verification = committed_verification
            payload["staging_input_backend"] = type_result.get("input_backend")
        payload["staged_text_verification"] = staged_verification
        payload["staged_text_verified"] = staged_verification.get("status") == "ok"
        if staged_verification.get("status") != "ok":
            if _tashuo_host_visual_staged_verification_available(staged_screen, staged_verification, draft_text):
                payload["visual_verification_request"] = _tashuo_visual_staged_verification_request(
                    staged_screen,
                    staged_verification,
                    draft_text,
                )
                payload.update({
                    "status": "needs_host_visual_verification",
                    "reason": "staged_text_requires_visual_verification",
                    "next_host_action": "visually_verify_staged_text_before_live_send",
                    "executed_steps": executed_steps,
                })
                return payload
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

    if payload.get("staging_input_backend") == "macos_accessibility":
        refocus_step = {
            **focused_input_step,
            "intent": "focus_tashuo_message_input_after_accessibility_set",
        }
        refocus_result = session._click_ratio(window, refocus_step["tap_ratio"])
        executed_steps.append({**refocus_step, "result": refocus_result})
        payload["ax_set_refocus_result"] = refocus_result
        if refocus_result.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": refocus_result.get("reason") or "tashuo_input_refocus_after_ax_set_failed",
                "executed_steps": executed_steps,
            })
            return payload
        time.sleep(0.2)

    send_result = session._press_return_key()
    executed_steps.append({**send_step, "result": send_result})
    payload["executed_steps"] = executed_steps
    if send_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": send_result.get("reason")})
        return payload

    _sleep_for_tashuo_post_action_observation(session, fallback=0.5)
    post_output = output_dir / f"{capture_prefix}.after_send_message.png" if output_dir is not None else None
    post_screen = _capture_tashuo_window(session, output=post_output, window=window, ocr=not _is_mac_ios_app_session(session))
    payload["post_action_observation"] = platform._redacted_screen(post_screen)
    payload["current_thread_visual_anchor"] = _tashuo_current_thread_visual_anchor(post_screen)
    post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or platform._now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    payload["post_action_observation_id"] = post_observation_id
    post_screen_captured = post_screen.get("status") == "ok"
    post_ax_static_text_values = _tashuo_ax_static_text_values(session) if _is_mac_ios_app_session(session) else None
    post_ax_text_area_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    staged_exact_text_verified = bool(
        staged_verification.get("exact_text_ax_verified")
        or (not _is_mac_ios_app_session(session) and staged_verification.get("exact_text_ocr_verified"))
    )
    outbound_verification = _verify_tashuo_outbound_message(
        post_screen,
        draft_text,
        staged_screen=staged_screen,
        ax_static_text_values=post_ax_static_text_values,
        ax_text_area_value=post_ax_text_area_value,
        trusted_direct_input=payload.get("staging_input_backend") == "applescript_direct_keystroke",
        staged_exact_text_verified=staged_exact_text_verified,
        visual_commit_allowed=False,
        ocr_disabled_after_message_page=_is_mac_ios_app_session(session),
    )
    payload["outbound_message_verification"] = outbound_verification
    outbound_verified = outbound_verification.get("status") == "ok"
    input_cleared = bool(outbound_verification.get("input_cleared_after_send"))
    payload["evidence"] = EvidencePayload(
        staging=StagingResult.from_verification(
            staged_verification,
            staged_text_verified=bool(payload.get("staged_text_verified")),
        ),
        post_send=PostSendVerification(
            post_action_observation_id=post_observation_id,
            input_cleared_after_send=input_cleared,
            post_action_screen_captured=post_screen_captured,
            outbound_message_verified=outbound_verified,
        ),
        send_input_backend=send_result.get("input_backend"),
        extra_fields={
            "staged_exact_text_verified": staged_exact_text_verified,
            "outbound_exact_text_verified": bool(outbound_verification.get("exact_text_verified")),
            "outbound_exact_text_ax_verified": bool(outbound_verification.get("exact_text_ax_verified")),
            "outbound_exact_text_ocr_verified": bool(outbound_verification.get("exact_text_ocr_verified")),
            "outbound_exact_text_visual_verified": bool(outbound_verification.get("exact_text_visual_verified")),
            "outbound_visual_commit_verified": bool(outbound_verification.get("visual_commit_verified")),
            "visual_only_exact_verification_allowed": bool(outbound_verification.get("visual_only_exact_verification_allowed")),
        },
    ).to_dict()
    if not post_screen_captured:
        payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
    elif not input_cleared:
        payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
    elif _is_mac_ios_app_session(session) and not outbound_verified and _tashuo_host_visual_outbound_verification_available(
        post_screen,
        outbound_verification,
        draft_text,
        staged_exact_text_verified=staged_exact_text_verified,
        input_cleared=input_cleared,
    ):
        payload["visual_verification_request"] = _tashuo_visual_outbound_verification_request(
            staged_screen,
            post_screen,
            outbound_verification,
            draft_text,
            post_action_observation_id=post_observation_id,
        )
        payload.update({
            "status": "needs_host_visual_verification",
            "reason": "outbound_message_requires_visual_verification",
            "next_host_action": "visually_verify_outbound_message_after_live_send",
        })
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
    if target_binding.get("binding_type") == "current_thread_visual_identity":
        return _verify_tashuo_current_thread_visual_identity(session, target_binding, output_dir=output_dir)
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
    screen = _capture_tashuo_window(session, output=output, window=window)
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


def _tashuo_current_thread_visual_anchor(
    screen: dict[str, Any],
    *,
    region: dict[str, float] | None = None,
) -> dict[str, Any]:
    anchor_region = region or dict(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    base = {
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_region": anchor_region,
        "uses_header_ocr": False,
    }
    if screen.get("status") != "ok":
        return {**base, "status": "blocked", "reason": screen.get("reason") or "screen_not_captured"}
    if screen.get("state") != "tashuo_conversation":
        return {**base, "status": "blocked", "reason": "tashuo_conversation_not_verified"}
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {**base, "status": "blocked", "reason": "target_binding_screen_path_missing"}
    return {
        **base,
        **_tashuo_visual_anchor_hash_for_path(Path(screen_path), region=anchor_region),
    }


def _verify_tashuo_current_thread_visual_identity(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    thread_evidence = (
        target_binding.get("thread_evidence") if isinstance(target_binding.get("thread_evidence"), dict) else {}
    )
    expected_visual_hash = str(thread_evidence.get("visual_anchor_hash") or "").strip()
    visual_region = _tashuo_visual_anchor_region(thread_evidence)
    max_distance = _tashuo_visual_anchor_max_distance(thread_evidence)
    base = {
        "verification_method": "tashuo_current_thread_visual_identity",
        "binding_type": target_binding.get("binding_type"),
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "conversation_fingerprint_hash": platform._hash_text(str(target_binding.get("conversation_fingerprint") or "")),
        "pre_action_observation_id": thread_evidence.get("observation_id"),
        "latest_inbound_fingerprint_hash": platform._hash_text(str(thread_evidence.get("latest_inbound_fingerprint") or "")),
        "expected_visual_anchor_hash": expected_visual_hash or None,
        "visual_anchor_region": visual_region,
        "visual_anchor_max_hamming_distance": max_distance,
        "requires_visual_anchor": True,
        "requires_header_marker": False,
        "requires_fresh_conversation_screen": True,
        "uses_header_ocr": False,
        "visual_only_exact_verification_allowed": _is_mac_ios_app_session(session),
    }
    if not target_binding_structural_evidence_present("tashuo", target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
    window = session._window_info()
    if window is None:
        reason = "mac_ios_app_window_not_found" if _is_mac_ios_app_session(session) else "iphone_mirroring_window_not_found"
        return {**base, "status": "blocked", "reason": reason}
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window)
    screen_path = str(screen.get("path") or "")
    visual_hash_result = _tashuo_visual_anchor_hash_for_path(Path(screen_path), region=visual_region) if screen_path else {
        "status": "blocked",
        "reason": "target_binding_screen_path_missing",
    }
    observed_visual_hash = str(visual_hash_result.get("visual_anchor_hash") or "")
    visual_distance = (
        _visual_anchor_hamming_distance(expected_visual_hash, observed_visual_hash)
        if expected_visual_hash and observed_visual_hash
        else None
    )
    result = {
        **base,
        "screen": platform._redacted_screen(screen),
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
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    if screen.get("state") != "tashuo_conversation":
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


def _recover_tashuo_current_thread_visual_identity_mismatch(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
    max_attempts: int = TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS,
) -> dict[str, Any]:
    evidence = _tashuo_message_list_relocation_evidence(target_binding)
    base = {
        "recovery_method": "tashuo_mac_ios_app_message_list_visual_relocation",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "attempt_limit": max_attempts,
        "requires_message_list_visual_evidence": True,
        "uses_fixed_row_index": False,
        "uses_header_ocr": False,
    }
    if evidence.get("status") != "ok":
        return {**base, **evidence, "status": "blocked"}
    window = session._window_info()
    if window is None:
        return {**base, "status": "blocked", "reason": "mac_ios_app_window_not_found"}

    attempts: list[dict[str, Any]] = []
    for attempt_index in range(1, max_attempts + 1):
        list_screen_result = _ensure_tashuo_message_list_for_relocation(
            session,
            window,
            output_dir=output_dir,
            attempt_index=attempt_index,
        )
        attempt: dict[str, Any] = {
            "attempt_index": attempt_index,
            "message_list_recovery": list_screen_result,
        }
        if list_screen_result.get("status") != "ok":
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": list_screen_result.get("reason") or "target_relocation_message_list_not_verified",
                "attempts": attempts,
            }

        list_screen = list_screen_result.get("screen_payload") if isinstance(list_screen_result.get("screen_payload"), dict) else {}
        location = _locate_tashuo_message_list_visual_target(list_screen, evidence)
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
        click_result = session._click_ratio(window, tap_ratio)
        attempt["open_target_click"] = {
            "intent": "tap_tashuo_relocated_visual_conversation_target",
            "tap_ratio": _copy_tap_ratio(tap_ratio),
            "result": click_result,
        }
        if click_result.get("status") != "ok":
            attempts.append(attempt)
            return {
                **base,
                "status": "blocked",
                "reason": click_result.get("reason") or "target_relocation_open_click_failed",
                "attempts": attempts,
            }
        _sleep_for_tashuo_post_action_observation(session, fallback=0.45)

        verification = _verify_tashuo_current_thread_visual_identity(session, target_binding, output_dir=output_dir)
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
            if isinstance(attempts[-1].get("target_binding_verification"), dict)
            else attempts[-1].get("message_list_location", {}).get("reason")
            if isinstance(attempts[-1].get("message_list_location"), dict)
            else None
        ) if attempts else None,
        "attempts": attempts,
    }


def _ensure_tashuo_message_list_for_relocation(
    session: Any,
    window: Any,
    *,
    output_dir: Path | None,
    attempt_index: int,
) -> dict[str, Any]:
    prefix = _tashuo_capture_prefix(session)
    current_output = (
        output_dir / f"{prefix}.target_relocation_{attempt_index:02d}.current.png"
        if output_dir is not None
        else None
    )
    current = _capture_tashuo_window(session, output=current_output, window=window, ocr=not _is_mac_ios_app_session(session))
    result: dict[str, Any] = {
        "status": current.get("status", "blocked"),
        "screen": platform._redacted_screen(current),
        "screen_state": current.get("state", "unknown"),
    }
    if result["status"] != "ok":
        return {**result, "reason": current.get("reason") or "target_relocation_current_screen_not_captured"}
    if current.get("state") == "tashuo_chat_list":
        return {**result, "screen_payload": current}
    if current.get("state") not in {"tashuo_conversation", "tashuo_question_gate"}:
        return {**result, "status": "blocked", "reason": "target_relocation_requires_thread_or_message_list"}

    return_step = _tashuo_action_steps("return-to-chats")[0]
    click_result = session._click_ratio(window, return_step["tap_ratio"])
    result["return_to_chats"] = {
        "intent": return_step["intent"],
        "tap_ratio": _copy_tap_ratio(return_step["tap_ratio"]),
        "result": click_result,
    }
    if click_result.get("status") != "ok":
        return {**result, "status": "blocked", "reason": click_result.get("reason") or "target_relocation_back_failed"}
    _sleep_for_tashuo_post_action_observation(session, fallback=0.45)

    list_output = (
        output_dir / f"{prefix}.target_relocation_{attempt_index:02d}.message_list.png"
        if output_dir is not None
        else None
    )
    list_screen = _capture_tashuo_window(session, output=list_output, window=window, ocr=not _is_mac_ios_app_session(session))
    result["message_list_screen"] = platform._redacted_screen(list_screen)
    result["message_list_screen_state"] = list_screen.get("state", "unknown")
    if list_screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": list_screen.get("reason") or "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != "tashuo_chat_list":
        return {**result, "status": "blocked", "reason": "target_relocation_message_list_not_verified"}
    return {**result, "status": "ok", "screen_payload": list_screen}


def _tashuo_message_list_relocation_evidence(target_binding: dict[str, Any]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for key in ("message_list_evidence", "selection_evidence", "target_selection_evidence"):
        value = target_binding.get(key)
        if isinstance(value, dict):
            sources.append(value)
    sources.append(target_binding)
    for source in sources:
        evidence = _normalize_tashuo_message_list_relocation_evidence(source)
        if evidence.get("status") == "ok":
            return evidence
    return {
        "status": "blocked",
        "reason": "target_relocation_visual_evidence_required",
        "accepted_evidence": [
            "message_list_evidence.visual_anchor_hash + visual_anchor_region",
            "selection_evidence.visual_anchor_hash + visual_anchor_region",
            "selection_evidence.tap_ratio as fallback only",
        ],
    }


def _normalize_tashuo_message_list_relocation_evidence(source: dict[str, Any]) -> dict[str, Any]:
    tap_ratio = _tap_ratio_option(
        source.get("tap_ratio")
        or source.get("visual_tap_ratio")
        or source.get("target_tap_ratio")
    )
    visual_hash = str(
        source.get("visual_anchor_hash")
        or source.get("row_visual_anchor_hash")
        or source.get("message_list_visual_anchor_hash")
        or ""
    ).strip()
    region = _tashuo_normalized_region(
        source.get("visual_anchor_region")
        or source.get("row_visual_anchor_region")
        or source.get("message_list_visual_anchor_region"),
        fallback=None,
    )
    if visual_hash and region is not None:
        max_distance = _tashuo_int_in_range(
            source.get("visual_anchor_max_hamming_distance")
            or source.get("row_visual_anchor_max_hamming_distance"),
            default=TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
            minimum=0,
            maximum=32,
        )
        scan_region = _tashuo_normalized_region(
            source.get("visual_anchor_scan_region") or source.get("scan_region"),
            fallback=TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
        )
        return {
            "status": "ok",
            "evidence_type": "message_list_visual_anchor",
            "visual_anchor_hash": visual_hash,
            "visual_anchor_region": region,
            "visual_anchor_max_hamming_distance": max_distance,
            "visual_anchor_scan_region": scan_region,
            "tap_ratio": tap_ratio,
            "source_state": source.get("source_state"),
            "selection_method": source.get("selection_method") or "message_list_visual_anchor_scan",
        }
    if tap_ratio is not None:
        return {
            "status": "ok",
            "evidence_type": "visual_tap_ratio_fallback",
            "tap_ratio": tap_ratio,
            "selection_method": source.get("selection_method") or "host_visual_tap_ratio",
            "visual_anchor_hash": None,
        }
    return {"status": "blocked", "reason": "target_relocation_visual_evidence_required"}


def _locate_tashuo_message_list_visual_target(
    list_screen: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if list_screen.get("status") != "ok":
        return {"status": "blocked", "reason": "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != "tashuo_chat_list":
        return {"status": "blocked", "reason": "target_relocation_message_list_not_verified"}
    if evidence.get("evidence_type") == "visual_tap_ratio_fallback":
        tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
        if tap_ratio is None:
            return {"status": "blocked", "reason": "target_relocation_tap_ratio_unavailable"}
        return {
            "status": "ok",
            "location_method": "visual_tap_ratio_fallback",
            "tap_ratio": _copy_tap_ratio(tap_ratio),
            "uses_fixed_row_index": False,
            "visual_anchor_scanned": False,
        }
    expected_hash = str(evidence.get("visual_anchor_hash") or "").strip()
    source_region = evidence.get("visual_anchor_region") if isinstance(evidence.get("visual_anchor_region"), dict) else None
    scan_region = evidence.get("visual_anchor_scan_region") if isinstance(evidence.get("visual_anchor_scan_region"), dict) else None
    if not expected_hash or source_region is None or scan_region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_evidence_incomplete"}
    path = str(list_screen.get("path") or "")
    if not path:
        return {"status": "blocked", "reason": "target_relocation_message_list_screen_path_missing"}

    row_height = max(0.03, min(0.28, float(source_region["y2"]) - float(source_region["y1"])))
    row_width = max(0.05, min(1.0, float(source_region["x2"]) - float(source_region["x1"])))
    scan_y1 = max(0.0, min(1.0 - row_height, float(scan_region["y1"])))
    scan_y2 = max(scan_y1 + row_height, min(1.0, float(scan_region["y2"])))
    source_x1 = max(0.0, min(1.0 - row_width, float(source_region["x1"])))
    source_x2 = source_x1 + row_width
    tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
    tap_y_offset = 0.5
    if tap_ratio is not None:
        tap_y_offset = (float(tap_ratio["y"]) - float(source_region["y1"])) / row_height
    tap_y_offset = max(0.05, min(0.95, tap_y_offset))
    tap_x = float(tap_ratio["x"]) if tap_ratio is not None else (source_x1 + source_x2) / 2.0
    max_distance = int(evidence.get("visual_anchor_max_hamming_distance") or TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE)
    step_y = max(0.004, min(0.012, row_height / 12.0))
    best: dict[str, Any] | None = None
    candidate_count = 0
    y = scan_y1
    while y <= scan_y2 - row_height + 0.0001:
        region = {"x1": source_x1, "y1": y, "x2": source_x2, "y2": y + row_height}
        hash_result = _tashuo_visual_anchor_hash_for_path(Path(path), region=region)
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
        }
        if distance is not None and (best is None or distance < int(best["visual_anchor_hamming_distance"])):
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
    return {
        **best,
        "status": "ok",
        "location_method": "message_list_visual_anchor_scan",
        "expected_visual_anchor_hash": expected_hash,
        "visual_anchor_max_hamming_distance": max_distance,
        "candidate_count": candidate_count,
        "tap_ratio": {
            "x": max(0.0, min(1.0, tap_x)),
            "y": max(0.0, min(1.0, float(matched_region["y1"]) + row_height * tap_y_offset)),
        },
        "uses_fixed_row_index": False,
        "visual_anchor_scanned": True,
    }


def _tashuo_visual_anchor_region(thread_evidence: dict[str, Any]) -> dict[str, float]:
    raw = thread_evidence.get("visual_anchor_region")
    return _tashuo_normalized_region(raw, fallback=TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION) or dict(
        TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION
    )


def _tashuo_normalized_region(
    raw: Any,
    *,
    fallback: dict[str, float] | None,
) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return dict(fallback) if fallback is not None else None
    fallback_values = fallback or {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
    region: dict[str, float] = {}
    for key, default in fallback_values.items():
        value = raw.get(key)
        try:
            region[key] = float(value)
        except (TypeError, ValueError):
            if fallback is None:
                return None
            region[key] = default
    if region["x2"] <= region["x1"] or region["y2"] <= region["y1"]:
        return dict(fallback) if fallback is not None else None
    return {
        "x1": max(0.0, min(0.99, region["x1"])),
        "y1": max(0.0, min(0.99, region["y1"])),
        "x2": max(0.01, min(1.0, region["x2"])),
        "y2": max(0.01, min(1.0, region["y2"])),
    }


def _tashuo_int_in_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))



def _tashuo_visual_anchor_max_distance(thread_evidence: dict[str, Any]) -> int:
    try:
        value = int(thread_evidence.get("visual_anchor_max_hamming_distance"))
    except (TypeError, ValueError):
        return TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE
    return max(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, min(16, value))


def _tashuo_visual_anchor_hash_for_path(
    path: Path,
    *,
    region: dict[str, float] | None = None,
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels(path)
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_read_failed", "error": str(exc)[:80]}
    try:
        width = int(pixels["width"])
        height = int(pixels["height"])
        channels = int(pixels["channels"])
        rows = pixels["rows"]
        anchor_region = region or TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION
        x1 = max(0, min(width - 1, int(float(anchor_region["x1"]) * width)))
        x2 = max(x1 + 1, min(width, int(float(anchor_region["x2"]) * width)))
        y1 = max(0, min(height - 1, int(float(anchor_region["y1"]) * height)))
        y2 = max(y1 + 1, min(height, int(float(anchor_region["y2"]) * height)))
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


def _visual_anchor_hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right)) * 4
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return max(len(left), len(right)) * 4


def _verify_tashuo_chat_list_row_target_binding(
    session: Any,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    spec = RowToThreadBindingSpec(
        app_id="tashuo",
        verification_method="tashuo_chat_list_row_to_thread_structural_binding",
        source_states=frozenset({"tashuo_chat_list"}),
        conversation_state="tashuo_conversation",
        window_missing_reason="mac_ios_app_window_not_found"
        if _is_mac_ios_app_session(session)
        else "iphone_mirroring_window_not_found",
        blocked_state_reasons={"tashuo_question_gate": "tashuo_question_gate_requires_user_confirmation"},
        visual_only_exact_verification_allowed=_is_mac_ios_app_session(session),
    )
    base = row_to_thread_base_result(target_binding, spec=spec)
    structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
    if structural_block is not None:
        return structural_block
    window = session._window_info()
    if window is None:
        return base.with_status("blocked", spec.window_missing_reason)
    output = output_dir / f"{_tashuo_capture_prefix(session)}.target_binding.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
    observed_text = str(screen.get("text") or "")
    return finish_row_to_thread_screen_verification(
        base,
        screen=screen,
        redacted_screen=platform._redacted_screen(screen),
        observed_text=observed_text,
        spec=spec,
    )


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


def _verify_staged_tashuo_message_with_crop_ocr(
    session: Any,
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    output_dir: Path | None = None,
    label: str = "tashuo.input_crop",
) -> dict[str, Any]:
    ax_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    ocr_disabled_after_message_page = _is_mac_ios_app_session(session)
    result = _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        ax_text_area_value=ax_value,
        ocr_disabled_after_message_page=ocr_disabled_after_message_page,
    )
    if result.get("status") == "ok" or screen.get("status") != "ok":
        return result
    if ocr_disabled_after_message_page:
        return {
            **result,
            "ocr_fallback_skipped": True,
            "ocr_fallback_skip_reason": "mac_ios_app_visual_first_after_message_page",
        }
    crop_ocr = _tashuo_input_crop_ocr(
        session,
        screen,
        expected_text=expected_text,
        output_dir=output_dir,
        label=label,
    )
    return _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        input_crop_ocr=crop_ocr,
        ax_text_area_value=ax_value,
        ocr_disabled_after_message_page=False,
    )


def _verify_staged_tashuo_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    input_crop_ocr: dict[str, Any] | None = None,
    ax_text_area_value: dict[str, Any] | None = None,
    ocr_disabled_after_message_page: bool = False,
) -> dict[str, Any]:
    observed_text = "" if ocr_disabled_after_message_page else str(screen.get("text") or "")
    crop_text = (
        str(input_crop_ocr.get("text") or "")
        if not ocr_disabled_after_message_page
        and isinstance(input_crop_ocr, dict)
        and input_crop_ocr.get("status") == "ok"
        else ""
    )
    combined_text = "\n".join(item for item in (observed_text, crop_text) if item)
    observed_stats = platform._expected_text_observation_stats(combined_text or observed_text, expected_text)
    baseline_text = (
        ""
        if ocr_disabled_after_message_page
        else str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    )
    baseline_stats = platform._expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    screen_exact = platform._message_text_matches(observed_text, expected_text)
    crop_exact = bool(crop_text) and platform._message_text_matches(crop_text, expected_text)
    ax_text = (
        str(ax_text_area_value.get("value") or "")
        if isinstance(ax_text_area_value, dict) and ax_text_area_value.get("status") == "ok"
        else ""
    )
    ax_exact = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
    result = platform._staged_text_ocr_evidence(
        verification_method=(
            "tashuo_staged_message_ax_then_host_visual_payload_text"
            if ocr_disabled_after_message_page
            else "tashuo_staged_message_ax_then_ocr_payload_text"
        ),
        observed_text=combined_text or observed_text,
        expected_text=expected_text,
        baseline_text=baseline_text,
        screen=screen,
        redact_screen=platform._redacted_screen,
        exact_text_ocr_verified=screen_exact or crop_exact,
        extra={
            "ocr_disabled_after_message_page": ocr_disabled_after_message_page,
            "send_action": "press_return",
            "exact_text_ax_verified": ax_exact,
            "ax_text_area_value_hash": platform._hash_text(ax_text) if ax_text else None,
            "ax_text_area_character_count": len(ax_text) if ax_text else 0,
            "screen_exact_text_ocr_verified": screen_exact,
            "input_crop_exact_text_ocr_verified": crop_exact,
        },
    )
    possible_append_to_existing = (
        bool(baseline_stats)
        and int(baseline_stats.get("expected_text_occurrences") or 0) > 0
        and int(observed_stats.get("text_character_count") or 0)
        > int(baseline_stats.get("text_character_count") or 0) + max(4, len(expected_text) // 3)
    )
    result["possible_append_to_existing_staged_text"] = possible_append_to_existing
    if ax_text_area_value is not None and ax_text_area_value.get("status") != "ok":
        result["ax_text_area_status"] = ax_text_area_value.get("status")
        result["ax_text_area_reason"] = ax_text_area_value.get("reason")
    if input_crop_ocr is not None and not ocr_disabled_after_message_page:
        result["input_crop_ocr"] = _redacted_tashuo_input_crop_ocr(input_crop_ocr, expected_text)
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    baseline_state = baseline_screen.get("state") if isinstance(baseline_screen, dict) else None
    if screen.get("state") != "tashuo_conversation" and baseline_state != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "tashuo_conversation_not_verified"}
    if not (result["exact_text_ocr_verified"] or result["exact_text_ax_verified"]):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if possible_append_to_existing and not trusted_direct_input and not result["exact_text_ax_verified"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_may_have_been_appended"}
    if not result["exact_text_ax_verified"] and baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
        if trusted_direct_input:
            return {**result, "status": "ok"}
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    return {**result, "status": "ok"}


def _tashuo_input_crop_ocr(
    session: Any,
    screen: dict[str, Any],
    *,
    expected_text: str,
    output_dir: Path | None,
    label: str,
) -> dict[str, Any]:
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {"status": "blocked", "reason": "input_crop_screen_path_missing"}
    source = Path(screen_path)
    try:
        pixels = _read_png_pixels(source)
        width = int(pixels["width"])
        height = int(pixels["height"])
    except Exception as exc:
        return {"status": "blocked", "reason": "input_crop_dimensions_unavailable", "error": str(exc)[:80]}
    region = dict(TASHUO_MAC_IOS_APP_INPUT_OCR_REGION)
    x = max(0, min(width - 1, int(region["x1"] * width)))
    y = max(0, min(height - 1, int(region["y1"] * height)))
    crop_width = max(1, min(width - x, int((region["x2"] - region["x1"]) * width)))
    crop_height = max(1, min(height - y, int((region["y2"] - region["y1"]) * height)))
    base_dir = output_dir if output_dir is not None else source.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    crop_path = base_dir / f"{label}.png"
    resized_path = base_dir / f"{label}.2x.png"
    crop = session.runner.run(
        [
            "sips",
            "--cropToHeightWidth",
            str(crop_height),
            str(crop_width),
            "--cropOffset",
            str(y),
            str(x),
            str(source),
            "--out",
            str(crop_path),
        ]
    )
    if crop.returncode != 0:
        return {"status": "blocked", "reason": "input_crop_failed", "stderr": platform._short(crop.stderr)}
    resize = session.runner.run(
        [
            "sips",
            "--resampleWidth",
            str(crop_width * 2),
            str(crop_path),
            "--out",
            str(resized_path),
        ]
    )
    if resize.returncode != 0:
        return {"status": "blocked", "reason": "input_crop_resize_failed", "stderr": platform._short(resize.stderr)}
    best: dict[str, Any] | None = None
    for psm in ("6", "11"):
        ocr = session.runner.run(
            [
                "tesseract",
                str(resized_path),
                "stdout",
                "-l",
                "chi_sim+eng",
                "--psm",
                psm,
            ]
        )
        item = {
            "status": "ok" if ocr.returncode == 0 else "blocked",
            "reason": None if ocr.returncode == 0 else "input_crop_ocr_failed",
            "text": ocr.stdout if ocr.returncode == 0 else "",
            "stderr": platform._short(ocr.stderr) if ocr.returncode != 0 else None,
            "psm": psm,
            "path": str(crop_path),
            "resized_path": str(resized_path),
            "region": region,
        }
        best = item
        if item["status"] == "ok" and platform._message_text_matches(str(item.get("text") or ""), expected_text):
            return item
    return best or {"status": "blocked", "reason": "input_crop_ocr_not_run"}


def _redacted_tashuo_input_crop_ocr(payload: dict[str, Any], expected_text: str) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    stats = platform._expected_text_observation_stats(text, expected_text) if text else {}
    return {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "psm": payload.get("psm"),
        "path": payload.get("path"),
        "resized_path": payload.get("resized_path"),
        "region": payload.get("region"),
        "text_hash": stats.get("text_hash"),
        "text_character_count": stats.get("text_character_count"),
        "expected_text_occurrences": stats.get("expected_text_occurrences", 0),
        "exact_text_ocr_verified": bool(text) and platform._message_text_matches(text, expected_text),
        "stderr": payload.get("stderr"),
    }


def _tashuo_ax_text_area_value(session: Any) -> dict[str, Any]:
    script = r'''
-- DATING_BOOST_AX_TEXT_AREA_VALUE
on findTextAreaValue(e, depth)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then
        return value of e as text
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set found to my findTextAreaValue(child, depth + 1)
          if found is not missing value then return found
        end repeat
      end if
    end try
  end tell
  return missing value
end findTextAreaValue

tell application "System Events"
  tell process "她说"
    set found to my findTextAreaValue(window 1, 0)
    if found is missing value then
      return "__DATING_BOOST_TEXT_AREA_NOT_FOUND__"
    end if
    return found
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_read_failed",
            "stderr": platform._short(result.stderr),
        }
    value = str(result.stdout or "").rstrip("\n")
    if value == "__DATING_BOOST_TEXT_AREA_NOT_FOUND__":
        return {"status": "blocked", "reason": "tashuo_ax_text_area_not_found"}
    if value == "missing value":
        value = ""
    return {"status": "ok", "value": value, "input_backend": "macos_accessibility"}


def _tashuo_ax_static_text_values(session: Any) -> dict[str, Any]:
    script = r'''
-- DATING_BOOST_AX_STATIC_TEXT_VALUES
on collectStaticTexts(e, depth)
  set foundValues to {}
  tell application "System Events"
    try
      if role of e is "AXStaticText" then
        try
          set v to value of e as text
          if v is not "" then set end of foundValues to v
        end try
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set childValues to my collectStaticTexts(child, depth + 1)
          repeat with itemValue in childValues
            set end of foundValues to itemValue as text
          end repeat
        end repeat
      end if
    end try
  end tell
  return foundValues
end collectStaticTexts

tell application "System Events"
  tell process "她说"
    set valuesList to my collectStaticTexts(window 1, 0)
    set AppleScript's text item delimiters to linefeed
    return valuesList as text
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_static_text_read_failed",
            "stderr": platform._short(result.stderr),
        }
    raw = str(result.stdout or "").strip()
    values: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            values = [str(item).strip() for item in parsed if _tashuo_ax_text_value_is_useful(str(item))]
        else:
            values = [line.strip() for line in raw.splitlines() if _tashuo_ax_text_value_is_useful(line)]
    return {
        "status": "ok",
        "value_count": len(values),
        "values": values,
        "input_backend": "macos_accessibility",
    }


def _tashuo_ax_text_value_is_useful(value: str) -> bool:
    stripped = str(value).strip()
    return bool(stripped) and stripped != "missing value"


def _set_tashuo_ax_text_area_value(session: Any, text: str) -> dict[str, Any]:
    escaped_text = json.dumps(text, ensure_ascii=False)
    script = f'''
-- DATING_BOOST_AX_SET_TEXT_AREA_VALUE
on setTextAreaValue(e, depth, newValue)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then
        set value of e to newValue
        return true
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set changed to my setTextAreaValue(child, depth + 1, newValue)
          if changed is true then return true
        end repeat
      end if
    end try
  end tell
  return false
end setTextAreaValue

tell application "System Events"
  tell process "她说"
    set changed to my setTextAreaValue(window 1, 0, {escaped_text})
    if changed is true then
      return "set"
    end if
    return "not_found"
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_set_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    if str(result.stdout or "").strip() != "set":
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_not_found",
            "input_backend": "macos_accessibility",
        }
    return {
        "status": "ok",
        "input_backend": "macos_accessibility",
        "expected_payload_hash": platform._hash_text(text),
        "expected_character_count": len(text),
    }


def _clear_tashuo_ax_text_area(session: Any) -> dict[str, Any]:
    script = r'''
-- DATING_BOOST_AX_CLEAR_TEXT_AREA
on clearTextAreas(e, depth)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then
        set value of e to ""
        return true
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set cleared to my clearTextAreas(child, depth + 1)
          if cleared is true then return true
        end repeat
      end if
    end try
  end tell
  return false
end clearTextAreas

tell application "System Events"
  tell process "她说"
    set cleared to my clearTextAreas(window 1, 0)
    if cleared is true then
      return "cleared"
    end if
    return "not_found"
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_clear_failed",
            "stderr": platform._short(result.stderr),
        }
    if str(result.stdout or "").strip() != "cleared":
        return {"status": "blocked", "reason": "tashuo_ax_text_area_not_found"}
    return {"status": "ok", "input_backend": "macos_accessibility"}


def _tashuo_host_visual_staged_verification_available(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> bool:
    if screen.get("status") != "ok" or not screen.get("path"):
        return False
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt", "tashuo_question_gate"}:
        return False
    observed_text = str(screen.get("text") or "")
    if _tashuo_input_placeholder_visible(observed_text):
        return False
    if _tashuo_obvious_wrong_staged_text_visible(observed_text, expected_text):
        return False
    crop_ocr = staged_verification.get("input_crop_ocr")
    return not isinstance(crop_ocr, dict) or crop_ocr.get("status") in {None, "ok", "blocked"}


def _tashuo_obvious_wrong_staged_text_visible(observed_text: str, expected_text: str) -> bool:
    if platform._message_text_matches(observed_text, expected_text):
        return False
    normalized_lines = [line.strip().lower() for line in observed_text.splitlines() if line.strip()]
    if any(line in {"v", "发送v", "v发送"} for line in normalized_lines):
        return True
    comparable = platform._message_text_comparable(observed_text)
    expected = platform._message_text_comparable(expected_text)
    if expected and expected in comparable:
        return False
    return comparable.endswith("v发送") or comparable.endswith("vsend")


def _tashuo_visual_staged_verification_request(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    crop_ocr = staged_verification.get("input_crop_ocr")
    crop = crop_ocr if isinstance(crop_ocr, dict) else {}
    return platform._staged_text_visual_verification_request(
        screen=screen,
        staged_verification=staged_verification,
        expected_text=expected_text,
        extra={
            "input_crop_path": crop.get("path"),
            "input_crop_resized_path": crop.get("resized_path"),
            "input_crop_region": crop.get("region") or TASHUO_MAC_IOS_APP_INPUT_OCR_REGION,
            "ocr_status": "skipped" if staged_verification.get("ocr_disabled_after_message_page") else crop.get("status"),
            "ocr_text_hash": None if staged_verification.get("ocr_disabled_after_message_page") else crop.get("text_hash"),
            "ocr_text_character_count": None
            if staged_verification.get("ocr_disabled_after_message_page")
            else crop.get("text_character_count"),
        },
        instructions="Use visual inspection of the screenshot to compare the staged input with the expected payload held by the current action request. Do not use OCR and do not press Return unless the visual comparison is exact.",
    )


def _tashuo_host_visual_outbound_verification_available(
    post_screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    expected_text: str,
    *,
    staged_exact_text_verified: bool,
    input_cleared: bool,
) -> bool:
    if not expected_text.strip():
        return False
    if staged_exact_text_verified is not True or input_cleared is not True:
        return False
    if post_screen.get("status") != "ok" or not post_screen.get("path"):
        return False
    if post_screen.get("state") != "tashuo_conversation":
        return False
    if outbound_verification.get("exact_text_ax_verified") is True:
        return False
    return True


def _tashuo_visual_outbound_verification_request(
    staged_screen: dict[str, Any] | None,
    post_screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    expected_text: str,
    *,
    post_action_observation_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "verification_type": "outbound_message_visual",
        "status": "needs_host_visual_verification",
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "staged_screen_path": staged_screen.get("path") if isinstance(staged_screen, dict) else None,
        "post_screen_path": post_screen.get("path"),
        "screen_state": post_screen.get("state"),
        "post_action_observation_id": post_action_observation_id,
        "input_cleared_after_send": bool(outbound_verification.get("input_cleared_after_send")),
        "staged_exact_text_verified": bool(outbound_verification.get("staged_exact_text_verified")),
        "outbound_visual_region": dict(TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION),
        "ocr_status": "skipped",
        "next_host_action": "visually_verify_outbound_message_after_live_send",
        "instructions": "Use visual inspection of the post-send screenshot to confirm the latest outbound bubble exactly matches the current action request payload. Do not use OCR; if the screenshot does not visibly confirm the sent text, record unknown rather than succeeded.",
    }


def _stage_only_tashuo_verification(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    first_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    ax_text_area_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    low_level = _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        ax_text_area_value=ax_text_area_value,
        ocr_disabled_after_message_page=bool(ax_text_area_value is not None),
    )
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
        "trusted_direct_input": trusted_direct_input,
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
    ax_static_text_values: dict[str, Any] | None = None,
    ax_text_area_value: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    staged_exact_text_verified: bool = False,
    visual_commit_allowed: bool = False,
    ocr_disabled_after_message_page: bool = False,
) -> dict[str, Any]:
    result = (
        {
            "verification_method": "tashuo_post_send_ax_then_host_visual_payload_text",
            "expected_payload_hash": platform._hash_text(expected_text),
            "expected_character_count": len(expected_text),
            "observed_text_hash": platform._hash_text(""),
            "observed_character_count": 0,
            "status": "needs_verification",
            "reason": "post_send_requires_visual_verification",
        }
        if ocr_disabled_after_message_page
        else platform._verify_outbound_message(screen, expected_text)
    )
    observed_text = "" if ocr_disabled_after_message_page else str(screen.get("text") or "")
    staged_text = (
        ""
        if ocr_disabled_after_message_page
        else str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    )
    observed_stats = platform._expected_text_observation_stats(observed_text, expected_text)
    staged_stats = platform._expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    ax_values = (
        [str(item) for item in ax_static_text_values.get("values", []) if str(item).strip()]
        if isinstance(ax_static_text_values, dict) and isinstance(ax_static_text_values.get("values"), list)
        else []
    )
    ax_text = "\n".join(ax_values)
    ax_stats = platform._expected_text_observation_stats(ax_text, expected_text) if ax_text else None
    ax_text_area = (
        str(ax_text_area_value.get("value") or "")
        if isinstance(ax_text_area_value, dict) and ax_text_area_value.get("status") == "ok"
        else None
    )
    input_cleared = (
        ax_text_area.strip() == ""
        if ax_text_area is not None
        else _tashuo_input_placeholder_visible(observed_text)
    )
    outgoing_bubble_visible = _tashuo_outgoing_bubble_visual_visible(screen)
    staged_outgoing_bubble_visible = (
        _tashuo_outgoing_bubble_visual_visible(staged_screen) if isinstance(staged_screen, dict) else False
    )
    exact_text_ocr_verified = False if ocr_disabled_after_message_page else result.get("status") == "ok"
    exact_text_ax_verified = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
    visual_commit = (
        _tashuo_outbound_visual_commit_verification(
            staged_screen,
            screen,
            input_cleared=input_cleared,
            staged_exact_text_verified=staged_exact_text_verified,
        )
        if visual_commit_allowed
        else {
            "status": "not_applicable",
            "reason": "visual_commit_not_allowed_for_runtime",
            "visual_only_exact_verification_allowed": False,
            "requires_ocr": True,
        }
    )
    exact_text_visual_verified = False
    exact_text_verified = exact_text_ocr_verified or exact_text_ax_verified
    extra = {
        "verification_method": (
            "tashuo_post_send_ax_then_host_visual_payload_text"
            if ocr_disabled_after_message_page
            else "tashuo_post_send_ax_static_text_then_ocr_payload_text"
            if ax_static_text_values is not None
            else "tashuo_post_send_ocr_payload_text_delta"
        ),
        "ocr_disabled_after_message_page": ocr_disabled_after_message_page,
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
        "ax_static_text_status": ax_static_text_values.get("status") if isinstance(ax_static_text_values, dict) else None,
        "ax_static_text_count": ax_static_text_values.get("value_count") if isinstance(ax_static_text_values, dict) else None,
        "ax_expected_text_occurrences": ax_stats["expected_text_occurrences"] if ax_stats else None,
        "ax_text_hash": ax_stats["text_hash"] if ax_stats else None,
        "ax_text_area_status": ax_text_area_value.get("status") if isinstance(ax_text_area_value, dict) else None,
        "ax_text_area_value_hash": platform._hash_text(ax_text_area) if ax_text_area else None,
        "input_cleared_after_send": input_cleared,
        "outgoing_bubble_visual_visible": outgoing_bubble_visible,
        "staged_outgoing_bubble_visual_visible": staged_outgoing_bubble_visible,
        "visual_delta_diagnostics": visual_commit,
        "visual_commit_verification": visual_commit,
        "visual_commit_verified": False,
        "send_action": "press_return",
        "staged_exact_text_verified": staged_exact_text_verified,
        "exact_text_verified": exact_text_verified,
        "exact_text_ax_verified": exact_text_ax_verified,
        "exact_text_ocr_verified": exact_text_ocr_verified,
        "exact_text_visual_verified": exact_text_visual_verified,
        "visual_only_exact_verification_allowed": visual_commit_allowed,
    }
    if screen.get("state") != "tashuo_conversation":
        return {**result, **extra, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if input_cleared is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    if exact_text_verified is not True:
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

    if _is_mac_ios_app_session(session):
        ax_clear_result = _clear_tashuo_ax_text_area(session)
        attempts.append({"intent": "clear_tashuo_text_area_for_failed_stage_cleanup", "result": ax_clear_result})
        if ax_clear_result.get("status") == "ok":
            time.sleep(0.2)
            output = output_dir / f"{_tashuo_capture_prefix(session)}.after_failed_stage_cleanup.png" if output_dir is not None else None
            screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
            ax_value = _tashuo_ax_text_area_value(session)
            ax_text = (
                str(ax_value.get("value") or "")
                if isinstance(ax_value, dict) and ax_value.get("status") == "ok"
                else ""
            )
            expected_still_visible = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
            input_placeholder_visible = ax_text.strip() == ""
            result = {
                "attempts": attempts,
                "input_tap_ratio": input_tap_ratio,
                "input_focus_state": input_focus_state,
                "screen": platform._redacted_screen(screen),
                "expected_payload_hash": platform._hash_text(expected_text),
                "expected_text_still_visible": expected_still_visible,
                "input_placeholder_visible": input_placeholder_visible,
                "cleanup_backend": "macos_accessibility",
                "ax_text_area_status": ax_value.get("status") if isinstance(ax_value, dict) else None,
                "ax_text_area_value_hash": platform._hash_text(ax_text) if ax_text else None,
            }
            if screen.get("status") != "ok":
                return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_screen_not_captured"}
            if not expected_still_visible and input_placeholder_visible:
                return {**result, "status": "ok"}

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
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
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
    region = TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION
    stats = platform._screen_region_stats(screen, region["x1"], region["y1"], region["x2"], region["y2"])
    if stats is None:
        return False
    return (
        stats["bright_ratio"] > 0.70
        and (
            stats["color_ratio"] > 0.030
            or (stats["color_ratio"] > 0.002 and stats["mid_ratio"] > 0.025)
        )
    )


def _tashuo_outbound_visual_commit_verification(
    staged_screen: dict[str, Any] | None,
    post_screen: dict[str, Any],
    *,
    input_cleared: bool,
    staged_exact_text_verified: bool,
) -> dict[str, Any]:
    base = {
        "verification_method": "tashuo_mac_ios_app_visual_commit_after_exact_stage",
        "staged_exact_text_verified": staged_exact_text_verified,
        "input_cleared_after_send": input_cleared,
        "visual_only_exact_verification_allowed": TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED,
        "visual_region": dict(TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION),
        "requires_ocr": False,
    }
    if not staged_exact_text_verified:
        return {**base, "status": "needs_verification", "reason": "staged_exact_text_not_verified"}
    if input_cleared is not True:
        return {**base, "status": "needs_verification", "reason": "post_send_input_not_clear"}
    if post_screen.get("status") != "ok":
        return {**base, "status": "needs_verification", "reason": post_screen.get("reason") or "post_action_screen_not_captured"}
    if post_screen.get("state") != "tashuo_conversation":
        return {**base, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if not _tashuo_outgoing_bubble_visual_visible(post_screen):
        return {**base, "status": "needs_verification", "reason": "outgoing_bubble_visual_not_visible"}

    delta = _tashuo_screen_region_visual_delta(
        staged_screen,
        post_screen,
        TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    )
    if delta.get("status") != "ok":
        return {**base, **delta, "status": "needs_verification", "reason": delta.get("reason") or "visual_delta_unavailable"}
    changed_ratio = float(delta.get("changed_pixel_ratio") or 0.0)
    average_delta = float(delta.get("average_channel_delta") or 0.0)
    if (
        changed_ratio < TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO
        or average_delta < TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA
    ):
        return {
            **base,
            **delta,
            "status": "needs_verification",
            "reason": "outgoing_bubble_visual_delta_too_small",
            "min_changed_pixel_ratio": TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO,
            "min_average_channel_delta": TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA,
        }
    return {**base, **delta, "status": "ok"}


def _tashuo_screen_region_visual_delta(
    before_screen: dict[str, Any] | None,
    after_screen: dict[str, Any],
    region: dict[str, float],
) -> dict[str, Any]:
    if not isinstance(before_screen, dict):
        return {"status": "blocked", "reason": "before_screen_missing"}
    before_path = str(before_screen.get("path") or "")
    after_path = str(after_screen.get("path") or "")
    if not before_path or not after_path:
        return {"status": "blocked", "reason": "visual_delta_screen_path_missing"}
    try:
        before_pixels = _read_png_pixels(Path(before_path))
        after_pixels = _read_png_pixels(Path(after_path))
    except Exception as exc:
        return {"status": "blocked", "reason": "visual_delta_read_failed", "error": str(exc)[:80]}
    try:
        before_width = int(before_pixels["width"])
        before_height = int(before_pixels["height"])
        after_width = int(after_pixels["width"])
        after_height = int(after_pixels["height"])
        before_channels = int(before_pixels["channels"])
        after_channels = int(after_pixels["channels"])
        if before_width != after_width or before_height != after_height:
            return {
                "status": "blocked",
                "reason": "visual_delta_size_mismatch",
                "before_size": [before_width, before_height],
                "after_size": [after_width, after_height],
            }
        x1 = max(0, min(before_width - 1, int(float(region["x1"]) * before_width)))
        x2 = max(x1 + 1, min(before_width, int(float(region["x2"]) * before_width)))
        y1 = max(0, min(before_height - 1, int(float(region["y1"]) * before_height)))
        y2 = max(y1 + 1, min(before_height, int(float(region["y2"]) * before_height)))
        changed_pixels = 0
        total_pixels = 0
        total_delta = 0.0
        for y in range(y1, y2):
            before_row = before_pixels["rows"][y]
            after_row = after_pixels["rows"][y]
            for x in range(x1, x2):
                before_offset = x * before_channels
                after_offset = x * after_channels
                before_rgb = before_row[before_offset : before_offset + 3]
                after_rgb = after_row[after_offset : after_offset + 3]
                delta = sum(abs(int(after_rgb[index]) - int(before_rgb[index])) for index in range(3)) / 3.0
                total_delta += delta
                total_pixels += 1
                if delta >= 10.0:
                    changed_pixels += 1
        return {
            "status": "ok",
            "changed_pixel_ratio": changed_pixels / max(1, total_pixels),
            "average_channel_delta": total_delta / max(1, total_pixels),
            "visual_region": dict(region),
        }
    except Exception as exc:
        return {"status": "blocked", "reason": "visual_delta_failed", "error": str(exc)[:80]}


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
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_precondition_{step_index:02d}.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
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
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_postcondition_{step_index:02d}.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
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
            retry = _retry_tashuo_step_postcondition_after_transition(
                session,
                window,
                step,
                first_result=result,
                output_dir=output_dir,
                step_index=step_index,
            )
            if retry is not None:
                return retry
            result.update(state_check)
            result["reason"] = "tashuo_step_postcondition_not_verified"
    return result


def _retry_tashuo_step_postcondition_after_transition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    first_result: dict[str, Any],
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any] | None:
    retry_after = float(step.get("postcondition_retry_after_seconds") or 0)
    if retry_after <= 0:
        return None
    if first_result.get("screen_state") not in {"unknown", "tashuo_unknown"}:
        return None
    time.sleep(retry_after)
    output = None
    if output_dir is not None:
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_postcondition_{step_index:02d}.retry.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
    retry_result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "retried_after_transition": True,
        "first_screen_state": first_result.get("screen_state"),
        "first_screen": first_result.get("screen"),
    }
    if retry_result["status"] != "ok":
        retry_result["reason"] = screen.get("reason") or "tashuo_postcondition_retry_capture_failed"
        return retry_result
    state_check = _verify_tashuo_step_state(screen, step, key="expected_tashuo_states")
    if state_check["status"] != "ok":
        retry_result.update(state_check)
        retry_result["reason"] = "tashuo_step_postcondition_not_verified"
    return retry_result


def _capture_tashuo_profile_read_step() -> dict[str, Any]:
    return _harness_marker_step(
        "capture_profile_read_step",
        requires_verified_tashuo_screen=True,
        requires_tashuo_states=["tashuo_recommend", "tashuo_profile", "tashuo_self_profile"],
        wait_after_seconds=0.0,
    )


def _tashuo_tap_step(
    intent: str,
    *,
    x: float,
    y: float,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = _harness_tap_step(intent, x=x, y=y, requires_verified_tashuo_screen=True)
    if requires_states is not None:
        step["requires_tashuo_states"] = requires_states
    if expected_states is not None:
        step["expected_tashuo_states"] = expected_states
    return step


def _tashuo_bottom_tab_step(intent: str, *, x: float, y: float, expected_state: str) -> dict[str, Any]:
    return _harness_tap_step(
        intent,
        x=x,
        y=y,
        requires_verified_tashuo_screen=True,
        requires_tashuo_top_level_tab_bar=True,
        expected_tashuo_states=[expected_state],
    )


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
    step = _harness_wheel_step(
        intent,
        x=x,
        y=y,
        delta_y=delta_y,
        delta_x=delta_x,
        repeats=repeats,
        requires_verified_tashuo_screen=True,
    )
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
    visual_tap_ratio = _tap_ratio_option(options.get("tap_ratio"))
    visual_target_label = str(options.get("visual_target_label") or "").strip()
    visual_target_preview = str(options.get("visual_target_preview") or "").strip()
    gate_x = min(0.84, 0.15 + (max(gate_index, 1) - 1) * 0.22)
    profile_read_states = ["tashuo_profile", "tashuo_self_profile", "tashuo_recommend"]
    open_conversation_steps = [
        {
            **_tashuo_tap_step(
                "tap_tashuo_visual_conversation_target",
                x=visual_tap_ratio["x"],
                y=visual_tap_ratio["y"],
                requires_states="tashuo_chat_list",
                expected_states=["tashuo_conversation", "tashuo_question_gate"],
            ),
            "selection_method": "host_visual_tap_ratio",
            **({"visual_target_label": visual_target_label} if visual_target_label else {}),
            **({"visual_target_preview": visual_target_preview} if visual_target_preview else {}),
        }
    ] if visual_tap_ratio is not None else [
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
    ]
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
        "open-conversation": open_conversation_steps,
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
            {
                **_tashuo_tap_step(
                    "tap_tashuo_profile_back",
                    x=0.09,
                    y=0.13,
                    requires_states="tashuo_profile",
                    expected_states="tashuo_conversation",
                ),
                "postcondition_retry_after_seconds": 0.8,
            }
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
