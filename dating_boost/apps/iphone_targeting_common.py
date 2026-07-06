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
    'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS',
]
