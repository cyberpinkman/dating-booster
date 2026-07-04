from __future__ import annotations

from .runtime_common import *

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


__all__ = [name for name in globals() if not name.startswith("__")]
