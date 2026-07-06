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
    '_tashuo_ax_text_area_value', '_tashuo_ax_static_text_values', '_tashuo_ax_text_value_is_useful', '_set_tashuo_ax_text_area_value',
    '_clear_tashuo_ax_text_area',
]
