from __future__ import annotations

import time
from typing import Any
from pathlib import Path

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
from .launch_runtime import (
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
    observe_tashuo_screen, launch_tashuo, launch_tashuo_mac_ios_app, _open_tashuo_mac_ios_app_bundle,
    _tashuo_mac_ios_window_recoverable_reason, _recover_tashuo_mac_ios_app_window, _force_recover_tashuo_mac_ios_app_window,
)
from .message_page_runtime import (
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
    _force_recover_tashuo_mac_ios_app_window, _open_tashuo_mac_ios_app_bundle, _recover_tashuo_mac_ios_app_window, _tashuo_mac_ios_window_recoverable_reason,
    prepare_tashuo_message_page, _tashuo_prepare_message_page_steps, _open_preflight_capture_tashuo_message_page, _dismiss_tashuo_liked_you_modal_if_present,
    _return_tashuo_conversation_to_message_list_if_needed, _return_tashuo_secondary_page_if_needed, _settle_or_open_tashuo_messages_page, _tashuo_secondary_page_without_bottom_nav,
    _refresh_tashuo_mac_ios_window, _capture_tashuo_visual_screen, _tashuo_message_page_visual_ready, _tashuo_message_list_top_anchor_verified,
    _tashuo_scroll_top_attempt, scroll_tashuo_conversation_list_to_top, _wait_for_tashuo_message_page_ready, _click_tashuo_conversation_navback_button,
    _dismiss_tashuo_liked_you_modal, _dismiss_tashuo_notification_prompt, _click_tashuo_notification_prompt_close_button, _click_tashuo_liked_you_modal_later_button,
    _click_tashuo_messages_radio_button, _click_tashuo_mine_radio_button, _verify_tashuo_step_precondition, _verify_tashuo_step_postcondition,
    _recover_tashuo_notification_prompt_postcondition, _retry_tashuo_step_postcondition_after_transition, _tashuo_step_ocr_enabled,
)
from .profile_runtime import (
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
    _capture_tashuo_visual_screen, _click_tashuo_mine_radio_button, _refresh_tashuo_mac_ios_window, prepare_tashuo_message_page,
    prepare_tashuo_self_profile_page, open_tashuo_self_profile_detail, scroll_tashuo_profile_read_mac_ios_app, scroll_tashuo_profile_to_bottom_mac_ios_app,
    _tashuo_profile_read_screen_verified, _tashuo_profile_read_text_anchor_present, _tashuo_profile_bottom_anchor_present, _tashuo_profile_bottom_attempt,
    _tashuo_profile_bottom_success,
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
from .send_runtime import (
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
    _tashuo_marker_matches_text, _tashuo_cjk_marker_fuzzy_match, _bounded_edit_distance, _tashuo_ax_text_area_value,
    _tashuo_ax_static_text_values, _tashuo_ax_text_value_is_useful, _set_tashuo_ax_text_area_value, _clear_tashuo_ax_text_area,
    _verify_staged_tashuo_message_with_crop_ocr, _verify_staged_tashuo_message, _tashuo_input_crop_ocr, _redacted_tashuo_input_crop_ocr,
    _tashuo_host_visual_staged_verification_available, _tashuo_obvious_wrong_staged_text_visible, _tashuo_visual_staged_verification_request, _tashuo_host_visual_outbound_verification_available,
    _tashuo_visual_outbound_verification_request, _stage_only_tashuo_verification, _verify_tashuo_outbound_message, _tashuo_input_placeholder_visible,
    _cleanup_failed_tashuo_stage, _tashuo_outgoing_bubble_visual_visible, _tashuo_outbound_visual_commit_verification, _tashuo_screen_region_visual_delta,
    run_tashuo_workflow, stage_tashuo_draft, clear_tashuo_message_input, send_tashuo_message,
)


def install_tashuo_session_hooks(session: Any) -> None:
    session.app_screen_state_observer = classify_tashuo_capture
    session.app_foreground_states = set(TASHUO_FOREGROUND_STATES)
    session.app_verified_screen_key = "requires_verified_tashuo_screen"
    session.app_foreground_not_verified_reason = "tashuo_foreground_not_verified"
    session.app_step_precondition_verifier = _verify_tashuo_step_precondition
    session.app_step_postcondition_verifier = _verify_tashuo_step_postcondition
    session.app_profile_field_coverage = _tashuo_profile_field_coverage


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
    if action in {"prepare-self-profile-page", "prepare_self_profile_page"}:
        return prepare_tashuo_self_profile_page(session, dry_run=dry_run, output_dir=output_dir)
    if action in {"open-self-profile-detail", "open_self_profile_detail"}:
        return open_tashuo_self_profile_detail(session, dry_run=dry_run, output_dir=output_dir)
    if action in {"profile-scroll-to-bottom", "profile_scroll_to_bottom"} and _is_mac_ios_app_session(session):
        return scroll_tashuo_profile_to_bottom_mac_ios_app(
            session,
            dry_run=dry_run,
            output_dir=output_dir,
            max_scrolls=int(options.get("max_scrolls") or TASHUO_PROFILE_BOTTOM_MAX_SCROLLS),
        )
    if action in {"profile-scroll-down", "profile_scroll_down", "profile-scroll-up", "profile_scroll_up"} and _is_mac_ios_app_session(session):
        return scroll_tashuo_profile_read_mac_ios_app(session, action, dry_run=dry_run, output_dir=output_dir)
    if action in {"clear-message-input", "clear_message_input"}:
        return clear_tashuo_message_input(session, dry_run=dry_run, output_dir=output_dir)
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
        requires_visual_relocation = _tashuo_open_conversation_requires_visual_relocation(options)
        if not requires_visual_relocation:
            already_open = _tashuo_already_at_open_conversation_target(session, planned_steps, output_dir=output_dir)
            if already_open is not None:
                payload.update(already_open)
                return payload
        relocated = _try_tashuo_open_conversation_visual_relocation(
            session,
            payload,
            options=options,
            output_dir=output_dir,
        )
        if relocated is not None:
            return relocated
    return session._execute_planned_steps(payload, output_dir=output_dir)


__all__ = [
    'annotations', 'time', 'Any', 'Path',
    'copy', 'hashlib', 'json', 're',
    'uuid4', 'TASHUO_FOREGROUND_STATES', 'classify_tashuo_screen_image', 'classify_tashuo_capture',
    'tashuo_layout_hints', 'tashuo_message_list_top_anchor_present', 'tashuo_top_level_bottom_nav_present', 'TASHUO_MESSAGES_TAB_TAP_RATIO',
    'TASHUO_MINE_TAB_TAP_RATIO', '_has_tashuo_step_postcondition', '_has_tashuo_step_precondition', '_tap_ratio_option',
    '_tashuo_action_steps', '_tashuo_profile_field_coverage', '_tashuo_step_expects_state', '_tashuo_workflow_steps',
    '_verify_tashuo_step_state', 'platform', 'target_binding_specific_marker_present', 'target_binding_structural_evidence_present',
    'EvidencePayload', 'PostSendVerification', 'SendAttemptContext', 'StagingResult',
    'RowToThreadBindingSpec', 'finish_row_to_thread_screen_verification', 'row_to_thread_base_result', 'validate_row_to_thread_structural_evidence',
    'SubprocessRunner', '_read_png_pixels', 'normalize_text', 'TASHUO_BLOCKED_GUI_ACTIONS',
    'TASHUO_SEND_BLOCKED_GUI_ACTIONS', 'TASHUO_QUESTION_GATE_POLICY', 'TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO', 'TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO',
    'TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO', 'TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO', 'TASHUO_CONVERSATION_NAVBACK_TAP_RATIO', 'TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO',
    'TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO', 'TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS', 'TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS', 'TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION',
    'TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'TASHUO_MAC_IOS_APP_INPUT_OCR_REGION', 'TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED', 'TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION',
    'TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO', 'TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA', 'TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS', 'TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION',
    'TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE', 'TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO', 'TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y', 'TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD',
    'TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD', 'TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN', 'TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX', 'TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION',
    'TASHUO_PROFILE_BOTTOM_MAX_SCROLLS', '_capture_tashuo_window', '_tashuo_post_action_observation_delay_seconds', '_sleep_for_tashuo_post_action_observation',
    'tashuo_guardrails_payload', '_is_mac_ios_app_session', '_tashuo_capture_prefix', '_copy_tap_ratio',
    '_applescript_literal', '_tashuo_window_missing_payload', '_tashuo_message_input_tap_ratio', '_tashuo_input_coordinate_model',
    'observe_tashuo_screen', 'launch_tashuo', 'launch_tashuo_mac_ios_app', '_open_tashuo_mac_ios_app_bundle',
    '_tashuo_mac_ios_window_recoverable_reason', '_recover_tashuo_mac_ios_app_window', '_force_recover_tashuo_mac_ios_app_window', 'prepare_tashuo_message_page',
    '_tashuo_prepare_message_page_steps', '_open_preflight_capture_tashuo_message_page', '_dismiss_tashuo_liked_you_modal_if_present', '_return_tashuo_conversation_to_message_list_if_needed',
    '_return_tashuo_secondary_page_if_needed', '_settle_or_open_tashuo_messages_page', '_tashuo_secondary_page_without_bottom_nav', '_refresh_tashuo_mac_ios_window',
    '_capture_tashuo_visual_screen', '_tashuo_message_page_visual_ready', '_tashuo_message_list_top_anchor_verified', '_tashuo_scroll_top_attempt',
    'scroll_tashuo_conversation_list_to_top', '_wait_for_tashuo_message_page_ready', '_click_tashuo_conversation_navback_button', '_dismiss_tashuo_liked_you_modal',
    '_dismiss_tashuo_notification_prompt', '_click_tashuo_notification_prompt_close_button', '_click_tashuo_liked_you_modal_later_button', '_click_tashuo_messages_radio_button',
    '_click_tashuo_mine_radio_button', '_verify_tashuo_step_precondition', '_verify_tashuo_step_postcondition', '_recover_tashuo_notification_prompt_postcondition',
    '_retry_tashuo_step_postcondition_after_transition', '_tashuo_step_ocr_enabled', 'prepare_tashuo_self_profile_page', 'open_tashuo_self_profile_detail',
    'scroll_tashuo_profile_read_mac_ios_app', 'scroll_tashuo_profile_to_bottom_mac_ios_app', '_tashuo_profile_read_screen_verified', '_tashuo_profile_read_text_anchor_present',
    '_tashuo_profile_bottom_anchor_present', '_tashuo_profile_bottom_attempt', '_tashuo_profile_bottom_success', '_tashuo_open_conversation_requires_visual_relocation',
    '_try_tashuo_open_conversation_visual_relocation', '_retry_tashuo_message_list_open_after_postcondition_failure', '_tashuo_message_list_open_fallback_taps', '_tashuo_already_at_open_conversation_target',
    '_verify_tashuo_target_binding', '_tashuo_current_thread_visual_anchor', '_verify_tashuo_current_thread_visual_identity', '_recover_tashuo_current_thread_visual_identity_mismatch',
    '_ensure_tashuo_message_list_for_relocation', '_tashuo_message_list_relocation_evidence', '_normalize_tashuo_message_list_relocation_evidence', '_locate_tashuo_message_list_visual_target',
    '_tashuo_message_list_relocation_preserves_action_tap', '_safe_tashuo_message_list_visual_anchor_tap_ratio', '_tashuo_visual_anchor_region', '_tashuo_normalized_region',
    '_tashuo_int_in_range', '_tashuo_visual_anchor_max_distance', '_tashuo_visual_anchor_hash_for_path', '_tashuo_visual_anchor_hash_for_pixels',
    '_visual_anchor_hamming_distance', '_verify_tashuo_chat_list_row_target_binding', '_tashuo_header_text', '_tashuo_marker_matches_text',
    '_tashuo_cjk_marker_fuzzy_match', '_bounded_edit_distance', '_tashuo_ax_text_area_value', '_tashuo_ax_static_text_values',
    '_tashuo_ax_text_value_is_useful', '_set_tashuo_ax_text_area_value', '_clear_tashuo_ax_text_area', '_verify_staged_tashuo_message_with_crop_ocr',
    '_verify_staged_tashuo_message', '_tashuo_input_crop_ocr', '_redacted_tashuo_input_crop_ocr', '_tashuo_host_visual_staged_verification_available',
    '_tashuo_obvious_wrong_staged_text_visible', '_tashuo_visual_staged_verification_request', '_tashuo_host_visual_outbound_verification_available', '_tashuo_visual_outbound_verification_request',
    '_stage_only_tashuo_verification', '_verify_tashuo_outbound_message', '_tashuo_input_placeholder_visible', '_cleanup_failed_tashuo_stage',
    '_tashuo_outgoing_bubble_visual_visible', '_tashuo_outbound_visual_commit_verification', '_tashuo_screen_region_visual_delta', 'run_tashuo_workflow',
    'stage_tashuo_draft', 'clear_tashuo_message_input', 'send_tashuo_message', 'install_tashuo_session_hooks',
    'run_tashuo_action',
]
