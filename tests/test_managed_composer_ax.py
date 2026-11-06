from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from dating_boost.apps.tashuo.managed_composer_ax import guarded_stage, snapshot


def _payload(**overrides):
    return {
        "value": "", "focused": True, "frontmost": True,
        "composer_position": [110, 800], "composer_size": [380, 60],
        "window_position": [100, 200], "window_size": [400, 700],
        "locator": [2, 1, 3], "process_pid": 4321, **overrides,
    }


class Runner:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        response = self.payloads.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, SimpleNamespace):
            return response
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")


def _session(*payloads):
    return SimpleNamespace(runner=Runner(payloads))


def test_snapshot_caches_only_locator_and_reads_each_state_again():
    first = _payload()
    second = _payload(value="新内容\r\n第二行", focused=False, frontmost=False, composer_position=[115, 810])
    session = _session(first, second)

    initial = snapshot(session)
    updated = snapshot(session)

    assert initial == {"status": "ok", **{k: v for k, v in first.items() if k != "locator"}}
    assert updated == {"status": "ok", **{k: v for k, v in second.items() if k != "locator"}}
    assert session.runner.commands[0][3:] == ["snapshot", ""]
    assert session.runner.commands[1][3:] == ["snapshot", "2,1,3"]
    assert vars(session).keys() == {"runner", "_managed_tashuo_composer_locator"}
    assert session._managed_tashuo_composer_locator == (2, 1, 3)


def test_stale_locator_is_rediscovered_in_same_script_and_replaced():
    session = _session(_payload(locator=[4, 2]), _payload(locator=[4, 2]))
    session._managed_tashuo_composer_locator = (2, 1, 3)
    assert snapshot(session)["status"] == "ok"
    assert session._managed_tashuo_composer_locator == (4, 2)
    assert snapshot(session)["status"] == "ok"
    assert [command[4] for command in session.runner.commands] == ["2,1,3", "4,2"]
    script = session.runner.commands[0][2]
    resolver = script.split("on resolveComposer(", 1)[1].split("end resolveComposer", 1)[0]
    assert "set currentElement to targetWindow" in resolver
    assert 'if role of currentElement is "AXTextArea" then return {currentElement, indices}' in resolver
    assert resolver.index("end try") < resolver.index("return my findComposer(targetWindow, 0, {})")
    assert len(session.runner.commands) == 2


@pytest.mark.parametrize("cached", ["1); private injection", [True], [0], [-1], [10001], [1.5], [1] * 25, {"index": 1}])
def test_invalid_cached_indices_trigger_discovery_without_embedding_untrusted_data(cached):
    session = _session(_payload())
    session._managed_tashuo_composer_locator = cached
    assert snapshot(session)["status"] == "ok"
    assert session.runner.commands[0][3:] == ["snapshot", ""]
    assert "private injection" not in session.runner.commands[0][2]


def test_missing_composer_is_distinct_from_empty_and_keeps_window_geometry():
    payload = _payload(value=None, focused=False, composer_position=None, composer_size=None, locator=[])
    session = _session(payload)
    session._managed_tashuo_composer_locator = (1,)
    result = snapshot(session)
    assert result == {"status": "ok", **{k: v for k, v in payload.items() if k != "locator"}}
    assert result["value"] is None and result["focused"] is False
    assert session._managed_tashuo_composer_locator == ()


def test_overlay_geometry_cannot_be_accepted_as_a_missing_composer_main_window():
    session = _session(_payload(
        value=None, focused=False, composer_position=None, composer_size=None,
        locator=[], window_position=[1079, 184], window_size=[66, 20],
    ))
    assert snapshot(session) == {"status": "blocked", "reason": "managed_composer_snapshot_invalid"}


def test_snapshot_selects_unique_main_window_before_resolving_cached_composer():
    session = _session(_payload())
    snapshot(session)
    script = session.runner.commands[0][2]
    assert "window 1" not in script
    assert script.index("set windowSelection to my selectTaShuoMainWindow()") < script.index(
        "set resolved to my resolveComposer(targetWindow, indices)"
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"value": 3}, {"focused": 1}, {"frontmost": "true"},
        {"process_pid": 0}, {"process_pid": -1}, {"process_pid": True}, {"process_pid": "4321"},
        {"composer_position": [True, 800]}, {"composer_position": [110]},
        {"composer_position": [float("nan"), 800]}, {"window_position": [float("inf"), 200]},
        {"window_size": [400, 0]}, {"composer_size": [380, -1]},
        {"composer_position": [99, 800]}, {"composer_position": [110, 841]},
        {"composer_size": [401, 60]}, {"composer_size": None},
        {"value": None}, {"locator": []}, {"locator": [0]}, {"locator": [1.0]},
        {"locator": [1] * 25}, {"extra": "PRIVATE value"},
    ],
)
def test_snapshot_validates_exact_types_geometry_and_locator(overrides):
    session = _session(_payload(**overrides))
    session._managed_tashuo_composer_locator = (1,)
    assert snapshot(session) == {"status": "blocked", "reason": "managed_composer_snapshot_invalid"}
    assert session._managed_tashuo_composer_locator == ()


@pytest.mark.parametrize("stdout", ["PRIVATE malformed", "null", "{}", '{"error":"occupied","error":"PRIVATE"}'])
def test_snapshot_rejects_invalid_json_and_duplicate_fields(stdout):
    session = _session(SimpleNamespace(returncode=0, stdout=stdout, stderr="PRIVATE stderr"))
    assert snapshot(session) == {"status": "blocked", "reason": "managed_composer_snapshot_invalid"}


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("process_missing", "tashuo_ax_process_not_found"),
        ("window_missing", "tashuo_ax_window_not_found"),
        ("composer_missing", "tashuo_ax_text_area_not_found"),
        ("not_frontmost", "managed_app_not_frontmost"),
        ("not_focused", "managed_composer_not_focused"),
        ("occupied", "candidate_composer_occupied"),
        ("write_failed", "tashuo_guarded_ax_write_failed"),
        ("compare_failed", "tashuo_guarded_ax_set_compare_failed"),
        ("read_failed", "tashuo_managed_composer_read_failed"),
        ("PRIVATE arbitrary error", "managed_composer_snapshot_invalid"),
    ],
)
def test_stage_errors_are_fixed_codes_and_clear_cached_locator(error, reason):
    session = _session({"error": error})
    session._managed_tashuo_composer_locator = (1,)
    assert guarded_stage(session, "draft") == {"status": "blocked", "reason": reason}
    assert session._managed_tashuo_composer_locator == ()
    assert len(session.runner.commands) == 1


def test_guarded_stage_uses_argv_and_one_script_for_fresh_guards_set_and_exact_readback():
    text = '你好\r\n"引号" $(private)'
    session = _session(_payload(value=text))
    session._managed_tashuo_composer_locator = (2, 1, 3)

    result = guarded_stage(session, text)

    assert result["status"] == "ok" and result["value"] == text
    assert result["staged_exact_text_ax_verified"] is True
    assert result["expected_composer_text_hash"] == hashlib.sha256(text.encode()).hexdigest()
    assert result["expected_character_count"] == len(text)
    assert len(session.runner.commands) == 1
    command = session.runner.commands[0]
    assert command[3:] == ["stage", "2,1,3", text]
    script = command[2]
    assert text not in script
    assert script.index("if currentFrontmost is not true") < script.index("set value of composer to newValue")
    assert script.index("if currentFocused is not true") < script.index("set value of composer to newValue")
    assert script.index('if currentValue is not ""') < script.index("set value of composer to newValue")
    assert script.index("set value of composer to newValue") < script.index("if currentValue is not newValue")
    assert 'set value of composer to ""' not in script
    for forbidden in ("key code", "keystroke", "activate", "pbcopy", "do shell script"):
        assert forbidden not in script


@pytest.mark.parametrize("overrides", [{"value": "different"}, {"focused": False}, {"frontmost": False}])
def test_stage_requires_exact_fresh_text_and_focus_even_for_success_payload(overrides):
    result = guarded_stage(_session(_payload(value="draft") | overrides), "draft")
    assert result["status"] == "blocked"
    assert result["reason"] in {"tashuo_guarded_ax_set_compare_failed", "managed_stage_focus_changed"}
    assert "value" not in result


@pytest.mark.parametrize("response", [RuntimeError("PRIVATE error"), SimpleNamespace(returncode=1, stdout="PRIVATE", stderr="PRIVATE")])
def test_runner_failure_never_exposes_raw_text(response):
    result = snapshot(_session(response))
    assert result == {"status": "blocked", "reason": "tashuo_managed_composer_read_failed"}


@pytest.mark.parametrize("text", [None, "", 1])
def test_stage_rejects_invalid_text_before_subprocess(text):
    session = _session()
    assert guarded_stage(session, text) == {"status": "blocked", "reason": "managed_stage_text_invalid"}
    assert session.runner.commands == []
