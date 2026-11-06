"""Shared read-only AX main-window selection for TaShuo's native runtime."""

from __future__ import annotations

from typing import Any


# Match the native runtime's minimum usable app-window geometry, not a row or
# screen coordinate. Small floating windows must never become conversation roots.
MIN_MAIN_WINDOW_WIDTH = 160
MIN_MAIN_WINDOW_HEIGHT = 300
_WINDOW_ERROR_PREFIX = "__DATING_BOOST_AX_WINDOW_ERROR__"
_WINDOW_REASONS = {
    "process_missing": "tashuo_ax_process_not_found",
    "window_missing": "tashuo_ax_window_not_found",
    "window_ambiguous": "tashuo_ax_main_window_ambiguous",
    "window_read_failed": "tashuo_ax_main_window_read_failed",
}

AX_MAIN_WINDOW_HANDLERS = r'''
on selectTaShuoMainWindow()
  tell application "System Events"
    try
      if not (exists process "她说") then return {missing value, "process_missing"}
      set semanticWindows to {}
      set compatibleWindows to {}
      repeat with candidateWindow in windows of process "她说"
        set candidateSize to size of candidateWindow
        if (count of candidateSize) is not 2 then error
        if (item 1 of candidateSize) >= 160 and (item 2 of candidateSize) >= 300 then
          set candidateRole to role of candidateWindow
          set candidateSubrole to ""
          set candidateIdentifier to ""
          try
            set candidateSubrole to subrole of candidateWindow as text
          end try
          try
            set candidateIdentifier to value of attribute "AXIdentifier" of candidateWindow as text
          end try
          if candidateRole is "AXWindow" then
            if candidateSubrole is "AXStandardWindow" or candidateIdentifier is "SceneWindow" then
              set end of semanticWindows to contents of candidateWindow
            else if candidateSubrole is "" or candidateSubrole is "AXUnknown" or candidateSubrole is "missing value" then
              set end of compatibleWindows to contents of candidateWindow
            end if
          end if
        end if
      end repeat
      if (count of semanticWindows) > 1 then return {missing value, "window_ambiguous"}
      if (count of semanticWindows) is 1 then return {item 1 of semanticWindows, ""}
      if (count of compatibleWindows) > 1 then return {missing value, "window_ambiguous"}
      if (count of compatibleWindows) is 1 then return {item 1 of compatibleWindows, ""}
      return {missing value, "window_missing"}
    on error
      return {missing value, "window_read_failed"}
    end try
  end tell
end selectTaShuoMainWindow
'''


AX_MAIN_WINDOW_SELECTION = r'''
set windowSelection to my selectTaShuoMainWindow()
if item 1 of windowSelection is missing value then return "__DATING_BOOST_AX_WINDOW_ERROR__" & item 2 of windowSelection
set targetWindow to item 1 of windowSelection
'''


def window_selection_failure(output: Any) -> dict[str, str] | None:
    """Decode only bounded selector errors, without exposing any AX text."""
    if not isinstance(output, str) or not output.startswith(_WINDOW_ERROR_PREFIX):
        return None
    code = output[len(_WINDOW_ERROR_PREFIX):].strip()
    return {"status": "blocked", "reason": _WINDOW_REASONS.get(code, "tashuo_ax_main_window_read_failed")}
