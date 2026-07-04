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




__all__ = [name for name in globals() if not name.startswith("__")]
