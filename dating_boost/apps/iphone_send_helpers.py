from __future__ import annotations

from dating_boost.apps.iphone_targeting_common import (
    annotations, hashlib, _platform, copy,
    csv, datetime, timezone, io,
    re, struct, sys, tempfile,
    time, zlib, Path, Any,
    uuid4, SubprocessRunner, WindowInfo, _parse_window_info,
    _short, _window_from_payload, _click_iphone_mirroring_view_menu_item_backend, _core_graphics_click_backend,
    _core_graphics_command_v_backend, _core_graphics_drag_backend, _core_graphics_wheel_backend, BUMBLE_FOREGROUND_STATES,
    TINDER_FOREGROUND_STATES, WECHAT_FOREGROUND_STATES, _bumble_layout_hints, _bumble_top_level_bottom_nav_present,
    classify_bumble_screen_text, classify_bumble_screen_image, classify_screen_image, classify_screen_text,
    classify_wechat_screen_text, _combine_bumble_screen_states, _combine_screen_states, _read_png_pixels_for_send_button,
    _region_stats_for_send_button, _redacted_screen, _tinder_layout_hints, _tinder_profile_danger_action_visible,
    _tinder_profile_expand_control_visible, _tinder_profile_field_coverage, _wechat_layout_hints, bumble_target_binding_specific_marker_present,
    target_binding_structural_evidence_present, _expected_text_observation_stats, _hash_text, _message_text_comparable,
    _message_text_matches, _normalize_text, _outbound_text_ocr_evidence, _staged_text_ocr_evidence,
    _staged_text_visual_verification_request, _text_fingerprint_fields, _harness_step_validation_reason, GUI_HARNESS_SCHEMA_VERSION,
    IPHONE_MIRRORING_HARNESS_BACKEND, MAC_IOS_APP_HARNESS_BACKEND, WECHAT_HARNESS_BACKEND, HARNESS_BACKEND,
    _contains_cjk_text, direct_text_entry_block_reason, NativeGuiHarness, _applescript_string_literal,
    _ensure_ascii_input_source, _switch_ascii_input_source, _read_current_input_source, _input_source_id_is_ascii,
    _app_search_result_visible, _default_screenshot_path, _now_iso, _parse_mac_ios_process_probe,
    _parse_core_graphics_window_info, _parse_mac_ios_active_application_probe, _swift_string_literal, _mac_ios_running_application_lookup_script,
    _mac_ios_core_graphics_window_lookup_script, _mac_ios_window_failure_reason, mac_ios_window_failure_payload, _contains_host_appleevents_unavailable_error,
    _host_appleevents_unavailable_diagnostic, _looks_like_iphone_mirroring_window, _looks_like_mac_ios_app_window, EvidencePayload,
    PostSendVerification, SendAttemptContext, StagingResult, BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
    IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION, _bumble_action_steps, _bumble_profile_field_coverage,
    _bumble_tap_step, _bumble_workflow_steps, _copy_tap_ratio, _has_bumble_step_postcondition,
    _has_bumble_step_precondition, _int_in_range, _launch_app_steps, _launch_tinder_steps,
    _message_list_visual_anchor_evidence_from_options, _normalized_visual_anchor_region, _redacted_iphone_prepare_message_page_payload, _redacted_message_list_visual_anchor_evidence,
    _redacted_target_binding, _target_binding_primary_visible_name, _target_binding_required_markers, _tap_ratio_option,
    _tap_step, _tinder_feedback_survey_dismiss_step, _tinder_action_steps, _tinder_subscription_paywall_dismiss_step,
    _tinder_workflow_steps, _verify_bumble_step_state, _visual_anchor_hamming_distance, harness_step_validation_reason,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    target_binding_specific_marker_present, BLOCKED_GUI_ACTIONS, WECHAT_BLOCKED_GUI_ACTIONS, BUMBLE_BLOCKED_GUI_ACTIONS,
    BUMBLE_SEND_BLOCKED_GUI_ACTIONS, BUMBLE_OPENING_MOVE_POLICY, TINDER_SUBSCRIPTION_PAYWALL_STATE, TINDER_FEEDBACK_SURVEY_STATE,
    DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y, IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS,
)
from dating_boost.apps.iphone_anchoring import _iphone_current_thread_visual_anchor

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


__all__ = [
    'annotations', 'hashlib', '_platform', 'copy',
    'csv', 'datetime', 'timezone', 'io',
    're', 'struct', 'sys', 'tempfile',
    'time', 'zlib', 'Path', 'Any',
    'uuid4', 'SubprocessRunner', 'WindowInfo', '_parse_window_info',
    '_short', '_window_from_payload', '_click_iphone_mirroring_view_menu_item_backend', '_core_graphics_click_backend',
    '_core_graphics_command_v_backend', '_core_graphics_drag_backend', '_core_graphics_wheel_backend', 'BUMBLE_FOREGROUND_STATES',
    'TINDER_FOREGROUND_STATES', 'WECHAT_FOREGROUND_STATES', '_bumble_layout_hints', '_bumble_top_level_bottom_nav_present',
    'classify_bumble_screen_text', 'classify_bumble_screen_image', 'classify_screen_image', 'classify_screen_text',
    'classify_wechat_screen_text', '_combine_bumble_screen_states', '_combine_screen_states', '_read_png_pixels_for_send_button',
    '_region_stats_for_send_button', '_redacted_screen', '_tinder_layout_hints', '_tinder_profile_danger_action_visible',
    '_tinder_profile_expand_control_visible', '_tinder_profile_field_coverage', '_wechat_layout_hints', 'bumble_target_binding_specific_marker_present',
    'target_binding_structural_evidence_present', '_expected_text_observation_stats', '_hash_text', '_message_text_comparable',
    '_message_text_matches', '_normalize_text', '_outbound_text_ocr_evidence', '_staged_text_ocr_evidence',
    '_staged_text_visual_verification_request', '_text_fingerprint_fields', '_harness_step_validation_reason', 'GUI_HARNESS_SCHEMA_VERSION',
    'IPHONE_MIRRORING_HARNESS_BACKEND', 'MAC_IOS_APP_HARNESS_BACKEND', 'WECHAT_HARNESS_BACKEND', 'HARNESS_BACKEND',
    '_contains_cjk_text', 'direct_text_entry_block_reason', 'NativeGuiHarness', '_applescript_string_literal',
    '_ensure_ascii_input_source', '_switch_ascii_input_source', '_read_current_input_source', '_input_source_id_is_ascii',
    '_app_search_result_visible', '_default_screenshot_path', '_now_iso', '_parse_mac_ios_process_probe',
    '_parse_core_graphics_window_info', '_parse_mac_ios_active_application_probe', '_swift_string_literal', '_mac_ios_running_application_lookup_script',
    '_mac_ios_core_graphics_window_lookup_script', '_mac_ios_window_failure_reason', 'mac_ios_window_failure_payload', '_contains_host_appleevents_unavailable_error',
    '_host_appleevents_unavailable_diagnostic', '_looks_like_iphone_mirroring_window', '_looks_like_mac_ios_app_window', 'EvidencePayload',
    'PostSendVerification', 'SendAttemptContext', 'StagingResult', 'BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION',
    'IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE', 'TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION', '_bumble_action_steps', '_bumble_profile_field_coverage',
    '_bumble_tap_step', '_bumble_workflow_steps', '_copy_tap_ratio', '_has_bumble_step_postcondition',
    '_has_bumble_step_precondition', '_int_in_range', '_launch_app_steps', '_launch_tinder_steps',
    '_message_list_visual_anchor_evidence_from_options', '_normalized_visual_anchor_region', '_redacted_iphone_prepare_message_page_payload', '_redacted_message_list_visual_anchor_evidence',
    '_redacted_target_binding', '_target_binding_primary_visible_name', '_target_binding_required_markers', '_tap_ratio_option',
    '_tap_step', '_tinder_feedback_survey_dismiss_step', '_tinder_action_steps', '_tinder_subscription_paywall_dismiss_step',
    '_tinder_workflow_steps', '_verify_bumble_step_state', '_visual_anchor_hamming_distance', 'harness_step_validation_reason',
    'RowToThreadBindingSpec', 'finish_row_to_thread_screen_verification', 'row_to_thread_base_result', 'validate_row_to_thread_structural_evidence',
    'target_binding_specific_marker_present', 'BLOCKED_GUI_ACTIONS', 'WECHAT_BLOCKED_GUI_ACTIONS', 'BUMBLE_BLOCKED_GUI_ACTIONS',
    'BUMBLE_SEND_BLOCKED_GUI_ACTIONS', 'BUMBLE_OPENING_MOVE_POLICY', 'TINDER_SUBSCRIPTION_PAYWALL_STATE', 'TINDER_FEEDBACK_SURVEY_STATE',
    'DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS', 'IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO', 'IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y', 'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION',
    'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS', '_iphone_current_thread_visual_anchor', '_iphone_already_sent_payload_update',
    '_iphone_already_sent_idempotency_allowed', '_iphone_stage_needs_user_verification', '_iphone_stage_draft_payload_update', '_iphone_pre_stage_input_guard',
    '_verify_outbound_message', '_screen_region_stats',
]
