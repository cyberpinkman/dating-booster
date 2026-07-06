from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4
import time

from dating_boost.apps.tashuo.screen_state import (
    TASHUO_FOREGROUND_STATES, classify_tashuo_screen_image, classify_tashuo_capture, tashuo_layout_hints,
    tashuo_message_list_top_anchor_present, tashuo_top_level_bottom_nav_present,
)
from dating_boost.apps.tashuo.steps import (
    TASHUO_MESSAGES_TAB_TAP_RATIO, TASHUO_MINE_TAB_TAP_RATIO, _has_tashuo_step_postcondition, _has_tashuo_step_precondition,
    _tap_ratio_option, _tashuo_action_steps, _tashuo_profile_field_coverage, _tashuo_step_expects_state,
    _tashuo_workflow_steps, _verify_tashuo_step_state,
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
from dating_boost.core.target_binding import (
    RowToThreadBindingSpec,
    finish_row_to_thread_screen_verification,
    row_to_thread_base_result,
    validate_row_to_thread_structural_evidence,
)
from dating_boost.harness.base import SubprocessRunner
from dating_boost.harness.screen_state import _read_png_pixels, normalize_text


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
TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO = {"x": 0.50, "y": 0.27}
TASHUO_CONVERSATION_NAVBACK_TAP_RATIO = {"x": 0.07, "y": 0.115}
TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO = {"x": 0.50, "y": 0.79}
TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO = {"x": 0.92, "y": 0.175}
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
TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION = {"x1": 0.0, "y1": 0.16, "x2": 1.0, "y2": 0.95}
TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE = 8
TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO = 0.90
TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y = 0.86
TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD = 0.80
TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD = 0.93
TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN = 0.025
TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX = 0.04
TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION = 0.28
TASHUO_PROFILE_BOTTOM_MAX_SCROLLS = 8



def _capture_tashuo_window(
    session: Any,
    *,
    output: Path | None = None,
    window: Any = None,
    ocr: bool | None = None,
) -> dict[str, Any]:
    use_ocr = not _is_mac_ios_app_session(session) if ocr is None else bool(ocr)
    capture_window = window
    activation = None
    if _is_mac_ios_app_session(session):
        activate = getattr(session, "_activate_window", None)
        if callable(activate):
            activation = activate()
            if activation.get("status") == "blocked":
                return {
                    "status": "blocked",
                    "reason": activation.get("reason") or "tashuo_capture_activation_failed",
                    "state": "unknown",
                    "ocr_status": "not_run",
                    "activation": activation,
                }
        refreshed_window = session._window_info()
        if refreshed_window is not None:
            capture_window = refreshed_window
    payload = session.capture_window(output=output, window=capture_window, ocr=use_ocr)
    if activation is not None:
        payload["activation"] = activation
    return payload

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

def _is_mac_ios_app_session(session: Any) -> bool:
    return getattr(session, "harness_backend", None) == "mac_ios_app"

def _tashuo_capture_prefix(session: Any) -> str:
    return "mac_ios_app.tashuo" if _is_mac_ios_app_session(session) else "iphone_mirroring.tashuo"

def _copy_tap_ratio(ratio: dict[str, float]) -> dict[str, float]:
    return {"x": float(ratio["x"]), "y": float(ratio["y"])}

def _applescript_literal(value: str) -> str:
    return json.dumps(value)

def _tashuo_window_missing_payload(
    session: Any,
    *,
    mac_reason: str = "mac_ios_app_window_not_found",
    iphone_reason: str = "iphone_mirroring_window_not_found",
) -> dict[str, Any]:
    if _is_mac_ios_app_session(session):
        return platform.mac_ios_window_failure_payload(session, default=mac_reason)
    return {"reason": iphone_reason}

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

__all__ = [
    'annotations', 'copy', 'hashlib', 'json',
    'Path', 're', 'Any', 'uuid4',
    'time', 'TASHUO_FOREGROUND_STATES', 'classify_tashuo_screen_image', 'classify_tashuo_capture',
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
]
