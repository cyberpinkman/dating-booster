from __future__ import annotations

from .runtime_common import (
    annotations, copy, hashlib, json,
    Path, re, Any, uuid4,
    time, TASHUO_FOREGROUND_STATES, classify_tashuo_screen_image, classify_tashuo_capture,
    tashuo_layout_hints, tashuo_message_list_top_anchor_present, tashuo_top_level_bottom_nav_present, TASHUO_MESSAGES_TAB_TAP_RATIO,
    TASHUO_MINE_TAB_TAP_RATIO, _has_tashuo_step_postcondition, _has_tashuo_step_precondition, _tap_ratio_option,
    _tashuo_action_steps, _tashuo_profile_field_coverage, _tashuo_step_expects_state, _tashuo_workflow_steps,
    _verify_tashuo_step_state, platform, target_binding_specific_marker_present, target_binding_structural_evidence_present,
    EvidencePayload, PostSendVerification, SendAttemptContext, StagingResult,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    SubprocessRunner, _read_png_pixels, normalize_text, TASHUO_BLOCKED_GUI_ACTIONS,
    TASHUO_SEND_BLOCKED_GUI_ACTIONS, TASHUO_QUESTION_GATE_POLICY, TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO, TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO,
    TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO, TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO, TASHUO_CONVERSATION_NAVBACK_TAP_RATIO, TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO,
    TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO, TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS, TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS, TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_MAC_IOS_APP_INPUT_OCR_REGION, TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA, TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS, TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
    TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y, TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD,
    TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION,
    TASHUO_PROFILE_BOTTOM_MAX_SCROLLS, _capture_tashuo_window, _tashuo_post_action_observation_delay_seconds, _sleep_for_tashuo_post_action_observation,
    tashuo_guardrails_payload, _is_mac_ios_app_session, _tashuo_capture_prefix, _copy_tap_ratio,
    _applescript_literal, _tashuo_window_missing_payload, _tashuo_message_input_tap_ratio, _tashuo_input_coordinate_model,
)
from .targeting import (
    annotations, copy, hashlib, json,
    Path, re, Any, uuid4,
    time, TASHUO_FOREGROUND_STATES, classify_tashuo_screen_image, classify_tashuo_capture,
    tashuo_layout_hints, tashuo_message_list_top_anchor_present, tashuo_top_level_bottom_nav_present, TASHUO_MESSAGES_TAB_TAP_RATIO,
    TASHUO_MINE_TAB_TAP_RATIO, _has_tashuo_step_postcondition, _has_tashuo_step_precondition, _tap_ratio_option,
    _tashuo_action_steps, _tashuo_profile_field_coverage, _tashuo_step_expects_state, _tashuo_workflow_steps,
    _verify_tashuo_step_state, platform, target_binding_specific_marker_present, target_binding_structural_evidence_present,
    EvidencePayload, PostSendVerification, SendAttemptContext, StagingResult,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    SubprocessRunner, _read_png_pixels, normalize_text, TASHUO_BLOCKED_GUI_ACTIONS,
    TASHUO_SEND_BLOCKED_GUI_ACTIONS, TASHUO_QUESTION_GATE_POLICY, TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO, TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO,
    TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO, TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO, TASHUO_CONVERSATION_NAVBACK_TAP_RATIO, TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO,
    TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO, TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS, TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS, TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_MAC_IOS_APP_INPUT_OCR_REGION, TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA, TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS, TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
    TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y, TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD,
    TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION,
    TASHUO_PROFILE_BOTTOM_MAX_SCROLLS, _capture_tashuo_window, _tashuo_post_action_observation_delay_seconds, _sleep_for_tashuo_post_action_observation,
    tashuo_guardrails_payload, _is_mac_ios_app_session, _tashuo_capture_prefix, _copy_tap_ratio,
    _applescript_literal, _tashuo_window_missing_payload, _tashuo_message_input_tap_ratio, _tashuo_input_coordinate_model,
    _tashuo_open_conversation_requires_visual_relocation, _try_tashuo_open_conversation_visual_relocation, _retry_tashuo_message_list_open_after_postcondition_failure, _tashuo_message_list_open_fallback_taps,
    _tashuo_already_at_open_conversation_target, _verify_tashuo_target_binding, _tashuo_current_thread_visual_anchor, _verify_tashuo_current_thread_visual_identity,
    _recover_tashuo_current_thread_visual_identity_mismatch, _ensure_tashuo_message_list_for_relocation, _tashuo_message_list_relocation_evidence, _normalize_tashuo_message_list_relocation_evidence,
    _locate_tashuo_message_list_visual_target, _tashuo_message_list_relocation_preserves_action_tap, _safe_tashuo_message_list_visual_anchor_tap_ratio, _tashuo_visual_anchor_region,
    _tashuo_normalized_region, _tashuo_int_in_range, _tashuo_visual_anchor_max_distance, _tashuo_visual_anchor_hash_for_path,
    _tashuo_visual_anchor_hash_for_pixels, _visual_anchor_hamming_distance, _verify_tashuo_chat_list_row_target_binding, _tashuo_header_text,
    _tashuo_marker_matches_text, _tashuo_cjk_marker_fuzzy_match, _bounded_edit_distance,
)
from .send_input_ax import (
    annotations, copy, hashlib, json,
    Path, re, Any, uuid4,
    time, TASHUO_FOREGROUND_STATES, classify_tashuo_screen_image, classify_tashuo_capture,
    tashuo_layout_hints, tashuo_message_list_top_anchor_present, tashuo_top_level_bottom_nav_present, TASHUO_MESSAGES_TAB_TAP_RATIO,
    TASHUO_MINE_TAB_TAP_RATIO, _has_tashuo_step_postcondition, _has_tashuo_step_precondition, _tap_ratio_option,
    _tashuo_action_steps, _tashuo_profile_field_coverage, _tashuo_step_expects_state, _tashuo_workflow_steps,
    _verify_tashuo_step_state, platform, target_binding_specific_marker_present, target_binding_structural_evidence_present,
    EvidencePayload, PostSendVerification, SendAttemptContext, StagingResult,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    SubprocessRunner, _read_png_pixels, normalize_text, TASHUO_BLOCKED_GUI_ACTIONS,
    TASHUO_SEND_BLOCKED_GUI_ACTIONS, TASHUO_QUESTION_GATE_POLICY, TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO, TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO,
    TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO, TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO, TASHUO_CONVERSATION_NAVBACK_TAP_RATIO, TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO,
    TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO, TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS, TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS, TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_MAC_IOS_APP_INPUT_OCR_REGION, TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA, TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS, TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
    TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y, TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD,
    TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION,
    TASHUO_PROFILE_BOTTOM_MAX_SCROLLS, _capture_tashuo_window, _tashuo_post_action_observation_delay_seconds, _sleep_for_tashuo_post_action_observation,
    tashuo_guardrails_payload, _is_mac_ios_app_session, _tashuo_capture_prefix, _copy_tap_ratio,
    _applescript_literal, _tashuo_window_missing_payload, _tashuo_message_input_tap_ratio, _tashuo_input_coordinate_model,
    _tashuo_ax_text_area_value, _tashuo_ax_static_text_values, _tashuo_ax_text_value_is_useful, _set_tashuo_ax_text_area_value,
    _clear_tashuo_ax_text_area,
)
from .send_verification import (
    annotations, copy, hashlib, json,
    Path, re, Any, uuid4,
    time, TASHUO_FOREGROUND_STATES, classify_tashuo_screen_image, classify_tashuo_capture,
    tashuo_layout_hints, tashuo_message_list_top_anchor_present, tashuo_top_level_bottom_nav_present, TASHUO_MESSAGES_TAB_TAP_RATIO,
    TASHUO_MINE_TAB_TAP_RATIO, _has_tashuo_step_postcondition, _has_tashuo_step_precondition, _tap_ratio_option,
    _tashuo_action_steps, _tashuo_profile_field_coverage, _tashuo_step_expects_state, _tashuo_workflow_steps,
    _verify_tashuo_step_state, platform, target_binding_specific_marker_present, target_binding_structural_evidence_present,
    EvidencePayload, PostSendVerification, SendAttemptContext, StagingResult,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    SubprocessRunner, _read_png_pixels, normalize_text, TASHUO_BLOCKED_GUI_ACTIONS,
    TASHUO_SEND_BLOCKED_GUI_ACTIONS, TASHUO_QUESTION_GATE_POLICY, TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO, TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO,
    TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO, TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO, TASHUO_CONVERSATION_NAVBACK_TAP_RATIO, TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO,
    TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO, TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS, TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS, TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_MAC_IOS_APP_INPUT_OCR_REGION, TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA, TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS, TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
    TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y, TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD,
    TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION,
    TASHUO_PROFILE_BOTTOM_MAX_SCROLLS, _capture_tashuo_window, _tashuo_post_action_observation_delay_seconds, _sleep_for_tashuo_post_action_observation,
    tashuo_guardrails_payload, _is_mac_ios_app_session, _tashuo_capture_prefix, _copy_tap_ratio,
    _applescript_literal, _tashuo_window_missing_payload, _tashuo_message_input_tap_ratio, _tashuo_input_coordinate_model,
    _tashuo_ax_text_area_value, _tashuo_ax_static_text_values, _tashuo_ax_text_value_is_useful, _set_tashuo_ax_text_area_value,
    _clear_tashuo_ax_text_area, _verify_staged_tashuo_message_with_crop_ocr, _verify_staged_tashuo_message, _tashuo_input_crop_ocr,
    _redacted_tashuo_input_crop_ocr, _tashuo_host_visual_staged_verification_available, _tashuo_obvious_wrong_staged_text_visible, _tashuo_visual_staged_verification_request,
    _tashuo_host_visual_outbound_verification_available, _tashuo_visual_outbound_verification_request, _stage_only_tashuo_verification, _verify_tashuo_outbound_message,
    _tashuo_input_placeholder_visible, _cleanup_failed_tashuo_stage, _tashuo_outgoing_bubble_visual_visible, _tashuo_outbound_visual_commit_verification,
    _tashuo_screen_region_visual_delta,
)


def _tashuo_live_send_steps(session: Any) -> dict[str, Any]:
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
        "requires_printable_ascii_draft": True,
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
    return {
        "input": input_step,
        "focused_input": focused_input_step,
        "paste": paste_step,
        "ax_set_text": ax_set_text_step,
        "type_fallback": type_fallback_step,
        "ime_commit": ime_commit_step,
        "send": send_step,
        "planned": (input_step, paste_step, ax_set_text_step, type_fallback_step, ime_commit_step, send_step),
    }


def _initial_tashuo_live_send_payload(
    session: Any,
    *,
    draft_text: str,
    dry_run: bool,
    planned_steps: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return SendAttemptContext(
        action="send_message",
        target="tashuo_message_input",
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=planned_steps,
        blocked_actions=tuple(TASHUO_SEND_BLOCKED_GUI_ACTIONS),
        extra_fields={
            "question_gate_policy": copy.deepcopy(TASHUO_QUESTION_GATE_POLICY),
            "input_coordinate_model": _tashuo_input_coordinate_model(session),
        },
    ).initial_payload(session._base_payload("ok"))


def _prepare_tashuo_live_send_context(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        return {"return_payload": payload}

    capture_prefix = _tashuo_capture_prefix(session)
    preflight_output = output_dir / f"{capture_prefix}.before_send_message.png" if output_dir is not None else None
    preflight = session.doctor(capture=True, output=preflight_output, ocr=not _is_mac_ios_app_session(session))
    payload["preflight"] = preflight
    if preflight.get("status") != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "tashuo_preflight_not_verified"})
        return {"return_payload": payload}
    window = platform._window_from_payload(preflight.get("window") or {})
    preflight_screen = preflight.get("screen") if isinstance(preflight.get("screen"), dict) else {}
    if preflight_screen.get("state") == "tashuo_question_gate":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_question_gate_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_question_gate_reply",
        })
        return {"return_payload": payload}
    if preflight_screen.get("state") != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified"})
        return {"return_payload": payload}

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
                    return {"return_payload": payload}
            else:
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
                })
                return {"return_payload": payload}

    baseline_output = output_dir / f"{capture_prefix}.before_stage_message.png" if output_dir is not None else None
    baseline_screen = _capture_tashuo_window(session, output=baseline_output, window=window, ocr=not _is_mac_ios_app_session(session))
    payload["pre_stage_observation"] = platform._redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return {"return_payload": payload}
    if baseline_screen.get("state") == "tashuo_question_gate":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_question_gate_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_question_gate_reply",
        })
        return {"return_payload": payload}
    if baseline_screen.get("state") != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified"})
        return {"return_payload": payload}

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
        return {"return_payload": payload}

    return {
        "capture_prefix": capture_prefix,
        "window": window,
        "baseline_screen": baseline_screen,
    }


def _stage_tashuo_live_send_input(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    steps: dict[str, Any],
) -> dict[str, Any]:
    input_step = steps["input"]
    focused_input_step = steps["focused_input"]
    paste_step = steps["paste"]
    ax_set_text_step = steps["ax_set_text"]
    type_fallback_step = steps["type_fallback"]
    ime_commit_step = steps["ime_commit"]
    prepared = _prepare_tashuo_live_stage_clipboard(session, payload, draft_text)
    if prepared.get("return_payload") is not None:
        return prepared
    previous_clipboard = prepared["previous_clipboard"]

    executed_steps: list[dict[str, Any]] = []
    try:
        staged = _paste_and_verify_tashuo_live_stage_input(
            session,
            payload,
            draft_text,
            output_dir=output_dir,
            capture_prefix=capture_prefix,
            window=window,
            baseline_screen=baseline_screen,
            input_step=input_step,
            focused_input_step=focused_input_step,
            paste_step=paste_step,
            ax_set_text_step=ax_set_text_step,
            type_fallback_step=type_fallback_step,
            ime_commit_step=ime_commit_step,
            executed_steps=executed_steps,
        )
        if staged.get("return_payload") is not None:
            return staged
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
        return {"return_payload": payload}

    return {
        "executed_steps": executed_steps,
        "staged_screen": staged["staged_screen"],
        "staged_verification": staged["staged_verification"],
    }


def _prepare_tashuo_live_stage_clipboard(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
) -> dict[str, Any]:
    previous_clipboard = session._read_clipboard()
    payload["previous_clipboard_read"] = previous_clipboard["status"] == "ok"
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard.get("reason")})
        return {"return_payload": payload}
    payload.update(platform._text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))
    copy_result = session._copy_to_clipboard(draft_text)
    payload["draft_clipboard_copy"] = copy_result["status"] == "ok"
    if copy_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": copy_result.get("reason")})
        return {"return_payload": payload}
    return {"previous_clipboard": previous_clipboard}


def _paste_and_verify_tashuo_live_stage_input(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    input_step: dict[str, Any],
    focused_input_step: dict[str, Any],
    paste_step: dict[str, Any],
    ax_set_text_step: dict[str, Any],
    type_fallback_step: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    initial = _paste_tashuo_live_stage_input(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=capture_prefix,
        window=window,
        baseline_screen=baseline_screen,
        input_step=input_step,
        paste_step=paste_step,
        executed_steps=executed_steps,
    )
    if initial.get("return_payload") is not None:
        return initial
    ax_result = _tashuo_live_ax_set_if_needed(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=capture_prefix,
        window=window,
        baseline_screen=baseline_screen,
        staged_screen=initial["staged_screen"],
        staged_verification=initial["staged_verification"],
        ax_set_text_step=ax_set_text_step,
        executed_steps=executed_steps,
    )
    fallback = _tashuo_live_direct_type_fallback_if_needed(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=capture_prefix,
        window=window,
        baseline_screen=baseline_screen,
        focused_input_step=focused_input_step,
        staged_screen=ax_result["staged_screen"],
        staged_verification=ax_result["staged_verification"],
        staged_input_placeholder_visible=ax_result["staged_input_placeholder_visible"],
        type_fallback_step=type_fallback_step,
        ime_commit_step=ime_commit_step,
        executed_steps=executed_steps,
    )
    if fallback.get("return_payload") is not None:
        return fallback
    finish = _finish_tashuo_live_stage_verification(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        window=window,
        focused_input_step=focused_input_step,
        staged_screen=fallback["staged_screen"],
        staged_verification=fallback["staged_verification"],
        executed_steps=executed_steps,
    )
    if finish.get("return_payload") is not None:
        return finish
    return {
        "staged_screen": fallback["staged_screen"],
        "staged_verification": fallback["staged_verification"],
    }


def _paste_tashuo_live_stage_input(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    input_step: dict[str, Any],
    paste_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    input_result = session._click_ratio(window, input_step["tap_ratio"])
    executed_steps.append({**input_step, "result": input_result})
    if input_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
        return {"return_payload": payload}
    time.sleep(0.45)

    paste_result = session._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
    executed_steps.append({**paste_step, "result": paste_result})
    if paste_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
        return {"return_payload": payload}
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
    return {
        "staged_screen": staged_screen,
        "staged_verification": staged_verification,
        "staged_input_placeholder_visible": _tashuo_input_placeholder_visible(staged_text),
    }


def _tashuo_live_ax_set_if_needed(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    ax_set_text_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    staged_input_placeholder_visible = _tashuo_input_placeholder_visible(str(staged_screen.get("text") or ""))
    if not (staged_verification.get("status") != "ok" and _is_mac_ios_app_session(session)):
        return {
            "staged_screen": staged_screen,
            "staged_verification": staged_verification,
            "staged_input_placeholder_visible": staged_input_placeholder_visible,
        }
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
        staged_input_placeholder_visible = _tashuo_input_placeholder_visible(str(staged_screen.get("text") or ""))
    return {
        "staged_screen": staged_screen,
        "staged_verification": staged_verification,
        "staged_input_placeholder_visible": staged_input_placeholder_visible,
    }


def _tashuo_live_direct_type_fallback_if_needed(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    focused_input_step: dict[str, Any],
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    staged_input_placeholder_visible: bool,
    type_fallback_step: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    direct_type_input_candidate = staged_verification.get("status") != "ok" and staged_input_placeholder_visible
    direct_type_block_reason = platform.direct_text_entry_block_reason(draft_text)
    if direct_type_input_candidate and direct_type_block_reason is not None:
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
            "reason": direct_type_block_reason,
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    if not (direct_type_input_candidate and platform._direct_type_fallback_allowed(draft_text)):
        return {"staged_screen": staged_screen, "staged_verification": staged_verification}

    typed = _type_and_commit_tashuo_live_stage_input(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=capture_prefix,
        window=window,
        baseline_screen=baseline_screen,
        type_fallback_step=type_fallback_step,
        ime_commit_step=ime_commit_step,
        executed_steps=executed_steps,
    )
    if typed.get("return_payload") is not None:
        return typed
    return typed


def _type_and_commit_tashuo_live_stage_input(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    type_fallback_step: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    type_result = session._type_text_into_frontmost_app(draft_text)
    executed_steps.append({**type_fallback_step, "result": type_result})
    if type_result["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": type_result.get("reason") or "direct_text_entry_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(0.3)
    staged_output = output_dir / f"{capture_prefix}.after_type_message.png" if output_dir is not None else None
    staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
    direct_type_verification = _verify_staged_tashuo_message_with_crop_ocr(
        session,
        staged_screen,
        draft_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=True,
        output_dir=output_dir,
        label=f"{capture_prefix}.after_type_message.input_crop",
    )
    committed = _commit_tashuo_live_stage_ime_input(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=capture_prefix,
        window=window,
        baseline_screen=baseline_screen,
        ime_commit_step=ime_commit_step,
        executed_steps=executed_steps,
    )
    if committed.get("return_payload") is not None:
        return committed
    committed_verification = committed["staged_verification"]
    payload["direct_type_text_verification"] = direct_type_verification
    payload["ime_commit_text_verification"] = committed_verification
    staged_verification = direct_type_verification
    if committed_verification.get("status") == "ok" or direct_type_verification.get("status") != "ok":
        staged_verification = committed_verification
    payload["staging_input_backend"] = type_result.get("input_backend")
    return {"staged_screen": committed["staged_screen"], "staged_verification": staged_verification}


def _commit_tashuo_live_stage_ime_input(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    baseline_screen: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    ime_commit_result = session._press_space_key()
    executed_steps.append({**ime_commit_step, "result": ime_commit_result})
    if ime_commit_result["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": ime_commit_result.get("reason") or "ime_commit_space_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(0.3)
    staged_output = output_dir / f"{capture_prefix}.after_ime_commit_message.png" if output_dir is not None else None
    staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
    staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
        session,
        staged_screen,
        draft_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=True,
        output_dir=output_dir,
        label=f"{capture_prefix}.after_ime_commit_message.input_crop",
    )
    return {"staged_screen": staged_screen, "staged_verification": staged_verification}


def _finish_tashuo_live_stage_verification(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    window: Any,
    focused_input_step: dict[str, Any],
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    payload["staged_text_verification"] = staged_verification
    payload["staged_text_verified"] = staged_verification.get("status") == "ok"
    if staged_verification.get("status") == "ok":
        return {}
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
        return {"return_payload": payload}
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
    return {"return_payload": payload}


def _complete_tashuo_live_send(
    session: Any,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    capture_prefix: str,
    window: Any,
    steps: dict[str, Any],
    executed_steps: list[dict[str, Any]],
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
) -> dict[str, Any]:
    focused_input_step = steps["focused_input"]
    send_step = steps["send"]

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


def send_tashuo_message(
    session: Any,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    steps = _tashuo_live_send_steps(session)
    payload = _initial_tashuo_live_send_payload(
        session,
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=steps["planned"],
    )
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    prepared = _prepare_tashuo_live_send_context(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        target_binding=target_binding,
    )
    if prepared.get("return_payload") is not None:
        return prepared["return_payload"]

    staged = _stage_tashuo_live_send_input(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=str(prepared["capture_prefix"]),
        window=prepared["window"],
        baseline_screen=prepared["baseline_screen"],
        steps=steps,
    )
    if staged.get("return_payload") is not None:
        return staged["return_payload"]

    return _complete_tashuo_live_send(
        session,
        payload,
        draft_text,
        output_dir=output_dir,
        capture_prefix=str(prepared["capture_prefix"]),
        window=prepared["window"],
        steps=steps,
        executed_steps=staged["executed_steps"],
        staged_screen=staged["staged_screen"],
        staged_verification=staged["staged_verification"],
    )
