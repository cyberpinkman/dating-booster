"""Fresh composer evidence using a session-local AX structural locator."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .send_input_ax import _AX_JSON_HANDLERS
from .ax_main_window import (
    AX_MAIN_WINDOW_HANDLERS, AX_MAIN_WINDOW_SELECTION,
    MIN_MAIN_WINDOW_WIDTH, MIN_MAIN_WINDOW_HEIGHT, window_selection_failure,
)


_LOCATOR_ATTRIBUTE = "_managed_tashuo_composer_locator"
_FIELDS = {
    "value", "focused", "frontmost", "composer_position", "composer_size",
    "window_position", "window_size", "locator", "process_pid",
}
_REASONS = {
    "process_missing": "tashuo_ax_process_not_found",
    "window_missing": "tashuo_ax_window_not_found",
    "composer_missing": "tashuo_ax_text_area_not_found",
    "not_frontmost": "managed_app_not_frontmost",
    "not_focused": "managed_composer_not_focused",
    "occupied": "candidate_composer_occupied",
    "read_failed": "tashuo_managed_composer_read_failed",
    "write_failed": "tashuo_guarded_ax_write_failed",
    "compare_failed": "tashuo_guarded_ax_set_compare_failed",
    "argument_invalid": "managed_composer_arguments_invalid",
}

_SCRIPT = _AX_JSON_HANDLERS + AX_MAIN_WINDOW_HANDLERS + r'''
-- DATING_BOOST_MANAGED_COMPOSER_AX
on parseLocator(encoded)
  if encoded is "" then return {}
  set previousDelimiters to AppleScript's text item delimiters
  set AppleScript's text item delimiters to ","
  set parts to text items of encoded
  set AppleScript's text item delimiters to previousDelimiters
  if (count of parts) > 24 then error
  set indices to {}
  repeat with partValue in parts
    set indexValue to partValue as integer
    if indexValue < 1 or indexValue > 10000 then error
    set end of indices to indexValue
  end repeat
  return indices
end parseLocator

on findComposer(e, depth, indices)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then return {e, indices}
      if depth < 24 then
        set children to UI elements of e
        repeat with childIndex from 1 to count of children
          try
            set found to my findComposer(item childIndex of children, depth + 1, indices & {childIndex})
            if item 1 of found is not missing value then return found
          on error number axErrorNumber
            if axErrorNumber is not -1719 then error number axErrorNumber
          end try
        end repeat
      end if
    on error number axErrorNumber
      if axErrorNumber is not -1719 then error number axErrorNumber
    end try
  end tell
  return {missing value, {}}
end findComposer

on resolveComposer(targetWindow, indices)
  if (count of indices) > 0 then
    try
      set currentElement to targetWindow
      tell application "System Events"
        repeat with childIndex in indices
          set currentElement to UI element (childIndex as integer) of currentElement
        end repeat
        if role of currentElement is "AXTextArea" then return {currentElement, indices}
      end tell
    end try
  end if
  return my findComposer(targetWindow, 0, {})
end resolveComposer

on jsonNumber(numberValue)
  if class of numberValue is not integer and class of numberValue is not real then error
  return my replaceText(numberValue as text, ",", ".")
end jsonNumber

on jsonNumbers(numericItems)
  set encodedItems to {}
  repeat with numberValue in numericItems
    set end of encodedItems to my jsonNumber(numberValue)
  end repeat
  set previousDelimiters to AppleScript's text item delimiters
  set AppleScript's text item delimiters to ","
  set encoded to encodedItems as text
  set AppleScript's text item delimiters to previousDelimiters
  return "[" & encoded & "]"
end jsonNumbers

on jsonBoolean(flag)
  if class of flag is not boolean then error
  if flag then return "true"
  return "false"
end jsonBoolean

on run argv
  try
    if (count of argv) < 2 then return "{\"error\":\"argument_invalid\"}"
    set operation to item 1 of argv
    if operation is not "snapshot" and operation is not "stage" then return "{\"error\":\"argument_invalid\"}"
    if operation is "stage" and (count of argv) is not 3 then return "{\"error\":\"argument_invalid\"}"
    set indices to my parseLocator(item 2 of argv)
    tell application "System Events"
      if not (exists process "她说") then return "{\"error\":\"process_missing\"}"
      tell process "她说"
        __SELECT_MAIN_WINDOW__
        set resolved to my resolveComposer(targetWindow, indices)
        set composer to item 1 of resolved
        set indices to item 2 of resolved
        if operation is "stage" then
          if composer is missing value then return "{\"error\":\"composer_missing\"}"
          set currentFrontmost to frontmost
          set currentFocused to value of attribute "AXFocused" of composer
          if class of currentFrontmost is not boolean or class of currentFocused is not boolean then error
          if currentFrontmost is not true then return "{\"error\":\"not_frontmost\"}"
          if currentFocused is not true then return "{\"error\":\"not_focused\"}"
          set currentValue to value of composer
          if currentValue is missing value then set currentValue to ""
          if currentValue is not "" then return "{\"error\":\"occupied\"}"
          set newValue to item 3 of argv
          try
            set value of composer to newValue
          on error
            return "{\"error\":\"write_failed\"}"
          end try
        end if
        set valueJSON to "null"
        set focusedJSON to "false"
        set positionJSON to "null"
        set sizeJSON to "null"
        if composer is not missing value then
          set currentValue to value of composer
          if currentValue is missing value then set currentValue to ""
          if operation is "stage" then
            if currentValue is not newValue then return "{\"error\":\"compare_failed\"}"
          end if
          set valueJSON to my jsonString(currentValue)
          set focusedJSON to my jsonBoolean(value of attribute "AXFocused" of composer)
          set positionJSON to my jsonNumbers(position of composer)
          set sizeJSON to my jsonNumbers(size of composer)
        end if
        set frontmostJSON to my jsonBoolean(frontmost)
        set processPIDJSON to my jsonNumber(unix id)
        set windowPositionJSON to my jsonNumbers(position of targetWindow)
        set windowSizeJSON to my jsonNumbers(size of targetWindow)
        return "{\"process_pid\":" & processPIDJSON & ",\"value\":" & valueJSON & ",\"focused\":" & focusedJSON & ",\"frontmost\":" & frontmostJSON & ",\"composer_position\":" & positionJSON & ",\"composer_size\":" & sizeJSON & ",\"window_position\":" & windowPositionJSON & ",\"window_size\":" & windowSizeJSON & ",\"locator\":" & my jsonNumbers(indices) & "}"
      end tell
    end tell
  on error
    return "{\"error\":\"read_failed\"}"
  end try
end run
'''.replace("__SELECT_MAIN_WINDOW__", AX_MAIN_WINDOW_SELECTION)


def snapshot(session: Any) -> dict[str, Any]:
    """Read live values/geometry/focus; only the structural locator is cached."""
    return _execute(session, "snapshot")


def guarded_stage(session: Any, text: str) -> dict[str, Any]:
    """Stage into a freshly empty, focused composer without Return or clearing."""
    if not isinstance(text, str) or not text:
        return _blocked("managed_stage_text_invalid")
    result = _execute(session, "stage", text)
    if result["status"] != "ok":
        return result
    if result["value"] != text:
        return _blocked("tashuo_guarded_ax_set_compare_failed")
    if not result["frontmost"] or not result["focused"]:
        return _blocked("managed_stage_focus_changed")
    return {
        **result,
        "staged_exact_text_ax_verified": True,
        "expected_composer_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "expected_character_count": len(text),
    }


def _execute(session: Any, operation: str, text: str | None = None) -> dict[str, Any]:
    cached = getattr(session, _LOCATOR_ATTRIBUTE, ())
    locator = cached if _valid_locator(cached) else ()
    command = ["osascript", "-e", _SCRIPT, operation, ",".join(str(index) for index in locator)]
    if operation == "stage":
        if text is None:
            return _blocked(_REASONS["argument_invalid"])
        command.append(text)
    try:
        response = session.runner.run(command)
    except Exception:  # noqa: BLE001 - raw AX/subprocess diagnostics may contain text.
        _cache_locator(session, ())
        return _blocked(_REASONS["read_failed"])
    selection_failure = window_selection_failure(response.stdout)
    if selection_failure is not None:
        _cache_locator(session, ())
        return selection_failure
    if response.returncode != 0:
        _cache_locator(session, ())
        return _blocked(_REASONS["read_failed"])
    try:
        payload = json.loads(response.stdout or "", object_pairs_hook=_unique_fields)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict) and set(payload) == {"error"} and isinstance(payload["error"], str):
        _cache_locator(session, ())
        return _blocked(_REASONS.get(payload["error"], "managed_composer_snapshot_invalid"))
    if not _valid_snapshot(payload):
        _cache_locator(session, ())
        return _blocked("managed_composer_snapshot_invalid")
    _cache_locator(session, tuple(payload["locator"]))
    return {"status": "ok", **{key: value for key, value in payload.items() if key != "locator"}}


def _valid_locator(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple)) and len(value) <= 24
        and all(type(index) is int and 1 <= index <= 10000 for index in value)
    )


def _numeric_pair(value: Any, *, positive: bool = False) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    try:
        return all(
            type(number) in (int, float) and math.isfinite(number) and (not positive or number > 0)
            for number in value
        )
    except OverflowError:
        return False


def _valid_snapshot(payload: Any) -> bool:
    if not isinstance(payload, dict) or set(payload) != _FIELDS or not _valid_locator(payload["locator"]):
        return False
    if type(payload["process_pid"]) is not int or payload["process_pid"] <= 0:
        return False
    if type(payload["focused"]) is not bool or type(payload["frontmost"]) is not bool:
        return False
    if not _numeric_pair(payload["window_position"]) or not _numeric_pair(payload["window_size"], positive=True):
        return False
    if payload["window_size"][0] < MIN_MAIN_WINDOW_WIDTH or payload["window_size"][1] < MIN_MAIN_WINDOW_HEIGHT:
        return False
    if payload["value"] is None:
        return (
            payload["focused"] is False and not payload["locator"]
            and payload["composer_position"] is None and payload["composer_size"] is None
        )
    if not isinstance(payload["value"], str) or not payload["locator"]:
        return False
    if not _numeric_pair(payload["composer_position"]) or not _numeric_pair(payload["composer_size"], positive=True):
        return False
    cx, cy = payload["composer_position"]
    cw, ch = payload["composer_size"]
    wx, wy = payload["window_position"]
    ww, wh = payload["window_size"]
    return 0 <= cx - wx <= ww - cw and 0 <= cy - wy <= wh - ch


def _cache_locator(session: Any, value: tuple[int, ...]) -> None:
    try:
        setattr(session, _LOCATOR_ATTRIBUTE, value)
    except (AttributeError, TypeError):
        pass  # Sessions that cannot hold a cache still use fresh full discovery.


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "blocked", "reason": reason}
