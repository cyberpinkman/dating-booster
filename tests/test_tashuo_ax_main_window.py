from __future__ import annotations

from types import SimpleNamespace

import pytest

from dating_boost.apps.tashuo import send_input_ax
from dating_boost.apps.tashuo.ax_main_window import AX_MAIN_WINDOW_HANDLERS
from dating_boost.apps.tashuo.managed_composer_ax import guarded_stage, snapshot


@pytest.mark.parametrize("consumer,args", [
    (snapshot, ()),
    (guarded_stage, ("draft",)),
    (send_input_ax._tashuo_ax_text_area_value, ()),
    (send_input_ax._tashuo_ax_composer_geometry, ()),
    (send_input_ax._tashuo_ax_static_text_values, ()),
    (send_input_ax._tashuo_ax_conversation_snapshot, ()),
    (send_input_ax._set_tashuo_ax_text_area_value, ("draft",)),
    (send_input_ax._clear_tashuo_ax_text_area, ()),
    (send_input_ax._guarded_set_tashuo_ax_text_area_if_empty, ("draft",)),
    (send_input_ax._guarded_clear_tashuo_ax_text_area_if_exact, ("draft",)),
])
@pytest.mark.parametrize("code,reason", [
    ("window_missing", "tashuo_ax_window_not_found"),
    ("window_ambiguous", "tashuo_ax_main_window_ambiguous"),
    ("window_read_failed", "tashuo_ax_main_window_read_failed"),
])
def test_all_ax_consumers_share_main_window_selection_and_fixed_failure(consumer, args, code, reason):
    commands = []

    def run(command):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="__DATING_BOOST_AX_WINDOW_ERROR__" + code + "\n", stderr="")

    session = SimpleNamespace(runner=SimpleNamespace(run=run))
    assert consumer(session, *args) == {"status": "blocked", "reason": reason}
    assert len(commands) == 1
    script = commands[0][2]
    assert AX_MAIN_WINDOW_HANDLERS in script
    assert "window 1" not in script
    assert "set windowSelection to my selectTaShuoMainWindow()" in script
    assert "if item 1 of windowSelection is missing value then return" in script


def test_main_window_selection_uses_semantics_geometry_and_uniqueness_without_gui_mutations():
    script = AX_MAIN_WINDOW_HANDLERS
    assert 'windows of process "她说"' in script
    assert '(item 1 of candidateSize) >= 160 and (item 2 of candidateSize) >= 300' in script
    assert 'candidateRole is "AXWindow"' in script
    assert 'candidateSubrole is "AXStandardWindow" or candidateIdentifier is "SceneWindow"' in script
    assert script.index('(count of semanticWindows) > 1') < script.index('return {item 1 of semanticWindows, ""}')
    assert script.index('(count of compatibleWindows) > 1') < script.index('return {item 1 of compatibleWindows, ""}')
    for forbidden in ("AXRaise", "activate", "set position", "set size", "key code", "keystroke"):
        assert forbidden not in script
