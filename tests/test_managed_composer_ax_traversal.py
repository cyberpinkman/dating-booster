"""Exercise the actual traversal handler against synthetic, non-GUI AX nodes."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from dating_boost.apps.tashuo.managed_composer_ax import _SCRIPT


_MOCK_ACCESSORS = '''
on nodeRole(e)
  if item 3 of e is not 0 then error number (item 3 of e)
  return item 1 of e
end nodeRole
on nodeChildren(e)
  if item 4 of e is not 0 then error number (item 4 of e)
  return item 2 of e
end nodeChildren
'''


def _run_traversal(children):
    if sys.platform != "darwin" or shutil.which("osascript") is None:
        pytest.skip("Pure AppleScript interpreter is available on macOS only")
    handler = "on findComposer(" + _SCRIPT.split("on findComposer(", 1)[1].split("end findComposer", 1)[0] + "end findComposer"
    # Execute the production control flow, replacing only its AX access boundary.
    handler = handler.replace('tell application "System Events"', "").replace("end tell", "")
    handler = handler.replace("role of e", "my nodeRole(e)").replace("UI elements of e", "my nodeChildren(e)")
    script = _MOCK_ACCESSORS + handler + '''
on run
  try
    set found to my findComposer({"AXGroup", CHILDREN, 0, 0}, 0, {})
    if item 1 of found is missing value then return "missing"
    set AppleScript's text item delimiters to ","
    return "found:" & ((item 2 of found) as text)
  on error number errorNumber
    return "error:" & (errorNumber as text)
  end try
end run
'''.replace("CHILDREN", children)
    assert "System Events" not in script
    response = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10, check=True)
    return response.stdout.strip()


@pytest.mark.parametrize("unavailable", [
    '{"AXGroup", {}, -1719, 0}',
    '{"AXGroup", {}, 0, -1719}',
    '{"AXGroup", {{"AXGroup", {}, -1719, 0}}, 0, 0}',
])
def test_invalid_ax_node_does_not_hide_a_valid_composer_sibling(unavailable):
    assert _run_traversal("{" + unavailable + ', {"AXTextArea", {}, 0, 0}}') == "found:2"


def test_all_unavailable_branches_leave_composer_missing_before_any_stage_write():
    assert _run_traversal('{{"AXGroup", {}, -1719, 0}, {"AXGroup", {}, 0, -1719}}') == "missing"
    assert _SCRIPT.index('if composer is missing value then return') < _SCRIPT.index("set value of composer to newValue")


@pytest.mark.parametrize("role_error,children_error", [(-1728, 0), (0, -1743)])
def test_other_ax_errors_are_not_treated_as_missing_nodes(role_error, children_error):
    children = '{{"AXGroup", {}, ROLE_ERROR, CHILDREN_ERROR}, {"AXTextArea", {}, 0, 0}}'
    children = children.replace("ROLE_ERROR", str(role_error)).replace("CHILDREN_ERROR", str(children_error))
    assert _run_traversal(children) == "error:" + str(role_error or children_error)
