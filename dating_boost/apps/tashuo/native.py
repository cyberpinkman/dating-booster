from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4
import time

from dating_boost.apps.tashuo.screen_state import (
    TASHUO_FOREGROUND_STATES,
    classify_tashuo_capture,
    tashuo_layout_hints,
    tashuo_top_level_bottom_nav_present,
)
from dating_boost.apps import native_gui_session as platform
from dating_boost.core.live_send_contract import target_binding_specific_marker_present


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
    output = output_dir / "iphone_mirroring.tashuo.observe.png" if output_dir is not None else None
    screen = session.capture_window(output=output, window=window)
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


def run_tashuo_action(
    session: Any,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
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
        "tap_ratio": {"x": 0.45, "y": 0.88},
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
        "intent": "tap_tashuo_send_button",
        "tap_ratio": {"x": 0.91, "y": 0.88},
        "risk": "live_send",
        "requires_explicit_authorization": True,
        "visual_only_exact_verification_allowed": False,
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
        "live_send": True,
        "requires_explicit_authorization": True,
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    preflight_output = output_dir / "iphone_mirroring.tashuo.before_send_message.png" if output_dir is not None else None
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

    baseline_output = output_dir / "iphone_mirroring.tashuo.before_stage_message.png" if output_dir is not None else None
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

        staged_output = output_dir / "iphone_mirroring.tashuo.after_stage_message.png" if output_dir is not None else None
        staged_screen = session.capture_window(output=staged_output, window=window)
        staged_verification = _verify_staged_tashuo_message(
            staged_screen,
            draft_text,
            baseline_screen=baseline_screen,
        )
        if (
            staged_verification.get("status") != "ok"
            and platform._direct_type_fallback_allowed(draft_text)
            and not _tashuo_active_send_button_visual_visible(staged_screen)
        ):
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
            staged_output = output_dir / "iphone_mirroring.tashuo.after_type_message.png" if output_dir is not None else None
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
            staged_output = output_dir / "iphone_mirroring.tashuo.after_ime_commit_message.png" if output_dir is not None else None
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

    send_result = session._click_ratio(window, send_step["tap_ratio"])
    executed_steps.append({**send_step, "result": send_result})
    payload["executed_steps"] = executed_steps
    if send_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": send_result.get("reason")})
        return payload

    time.sleep(0.5)
    post_output = output_dir / "iphone_mirroring.tashuo.after_send_message.png" if output_dir is not None else None
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
        return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
    output = output_dir / "iphone_mirroring.tashuo.target_binding.png" if output_dir is not None else None
    screen = session.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    normalized = platform._normalize_text(observed_text)
    header_text = _tashuo_header_text(observed_text)
    header_normalized = platform._normalize_text(header_text)
    matched = [marker for marker in markers if platform._normalize_text(marker) in normalized]
    header_matched = [marker for marker in markers if platform._normalize_text(marker) in header_normalized]
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
    active_send_button_visible = _tashuo_active_send_button_visual_visible(screen)
    result = {
        "verification_method": "tashuo_staged_message_ocr_payload_text",
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": observed_stats["text_hash"],
        "observed_character_count": observed_stats["text_character_count"],
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "baseline_expected_text_occurrences": baseline_stats["expected_text_occurrences"] if baseline_stats else None,
        "baseline_text_hash": baseline_stats["text_hash"] if baseline_stats else None,
        "active_send_button_visual_visible": active_send_button_visible,
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
    if not _tashuo_send_marker_visible(observed_text) and not active_send_button_visible:
        return {**result, "status": "needs_verification", "reason": "tashuo_send_button_not_verified_after_staging"}
    return {**result, "status": "ok"}


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
        "input_cleared_after_send": not _tashuo_send_marker_visible(observed_text)
        and not _tashuo_active_send_button_visual_visible(screen),
        "outgoing_bubble_visual_visible": outgoing_bubble_visible,
        "staged_outgoing_bubble_visual_visible": staged_outgoing_bubble_visible,
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


def _tashuo_send_marker_visible(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped in {"send", "发送"}:
            return True
    return False


def _tashuo_active_send_button_visual_visible(screen: dict[str, Any]) -> bool:
    stats = platform._screen_region_stats(screen, 0.82, 0.84, 0.96, 0.92)
    if stats is None:
        return False
    return stats["color_ratio"] > 0.08 and stats["bright_ratio"] > 0.45


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
            _tashuo_bottom_tab_step("tap_tashuo_messages_tab", x=0.62, y=0.92, expected_state="tashuo_chat_list")
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
