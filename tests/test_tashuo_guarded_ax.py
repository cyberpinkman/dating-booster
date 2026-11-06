from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from dating_boost.apps.tashuo.managed_live_action import _observe_current_conversation_revision
from dating_boost.apps.tashuo.send_input_ax import (
    _guarded_clear_tashuo_ax_text_area_if_exact,
    _guarded_set_tashuo_ax_text_area_if_empty,
    _tashuo_ax_composer_geometry,
    _tashuo_ax_conversation_snapshot,
    _tashuo_ax_static_text_values,
)


class Result:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class GuardedRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.commands = []

    def run(self, command):
        self.commands.append(command)
        return self.responses.pop(0)


def _session(*responses):
    return SimpleNamespace(runner=GuardedRunner(responses))


def _script(session):
    command = session.runner.commands[-1]
    assert command[:2] == ["osascript", "-e"]
    return command[2]


def test_guarded_set_if_empty_uses_single_atomic_ax_script_and_returns_hash_only():
    session = _session(Result(stdout="set\n"))
    text = "你好\r\n下一行"

    result = _guarded_set_tashuo_ax_text_area_if_empty(session, text)

    assert result == {
        "status": "ok",
        "input_backend": "guarded_macos_accessibility",
        "expected_composer_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "expected_character_count": len(text),
    }
    script = _script(session)
    assert "DATING_BOOST_AX_GUARDED_SET_IF_EMPTY" in script
    assert 'if currentValue is not "" then' in script
    assert script.index('if currentValue is not "" then') < script.index("set value of e to newValue")
    assert "pbcopy" not in script
    assert "key code 9" not in script
    assert "key code 36" not in script
    assert "send-message" not in script


def test_guarded_set_if_empty_blocks_occupied_without_claiming_write():
    session = _session(Result(stdout="occupied\n"))

    result = _guarded_set_tashuo_ax_text_area_if_empty(session, "new draft")

    assert result["status"] == "blocked"
    assert result["reason"] == "candidate_composer_occupied"
    assert "expected_composer_text_hash" not in result


def test_guarded_set_compare_failure_and_not_found_are_structured():
    mismatch = _guarded_set_tashuo_ax_text_area_if_empty(_session(Result(stdout="compare_failed\n")), "draft")
    missing = _guarded_set_tashuo_ax_text_area_if_empty(_session(Result(stdout="not_found\n")), "draft")

    assert mismatch == {
        "status": "blocked",
        "reason": "tashuo_guarded_ax_set_compare_failed",
        "input_backend": "guarded_macos_accessibility",
    }
    assert missing["reason"] == "tashuo_ax_text_area_not_found"


@pytest.mark.parametrize("outcome", ["read_failed", "write_failed", "readback_failed"])
def test_guarded_set_preserves_failure_after_finding_composer_without_error_text(outcome):
    session = _session(Result(stdout=outcome + "\n", stderr="private AX error detail"))

    result = _guarded_set_tashuo_ax_text_area_if_empty(session, "private draft")

    assert result == {
        "status": "blocked",
        "reason": "tashuo_guarded_ax_" + outcome,
        "input_backend": "guarded_macos_accessibility",
    }
    script = _script(session)
    # Each operation owns its fixed error result. The traversal must propagate
    # that result instead of treating a found but unreadable field as absent.
    operation = {
        "read_failed": "set currentValue to value of e",
        "write_failed": "set value of e to newValue",
        "readback_failed": "set observedValue to value of e",
    }[outcome]
    assert f'try\n          {operation}\n        on error\n          return "{outcome}"\n        end try' in script
    assert 'if resultValue is not "not_found" then return resultValue' in script
    assert "private" not in str(result)
    assert len(session.runner.commands) == 1


def test_guarded_clear_if_exact_compares_exact_string_before_mutation():
    session = _session(Result(stdout="cleared\n"))
    exact = "draft  \n"

    result = _guarded_clear_tashuo_ax_text_area_if_exact(session, exact)

    assert result["status"] == "ok"
    assert result["cleared_exact_text_hash"] == hashlib.sha256(exact.encode("utf-8")).hexdigest()
    script = _script(session)
    assert "DATING_BOOST_AX_GUARDED_CLEAR_IF_EXACT" in script
    assert "if currentValue is not expectedValue then" in script
    assert script.index("if currentValue is not expectedValue then") < script.index('set value of e to ""')
    assert "pbcopy" not in script
    assert "key code 9" not in script
    assert "key code 36" not in script


def test_guarded_clear_never_clears_other_or_unknown_text():
    mismatch = _guarded_clear_tashuo_ax_text_area_if_exact(_session(Result(stdout="mismatch\n")), "ours")
    missing = _guarded_clear_tashuo_ax_text_area_if_exact(_session(Result(stdout="not_found\n")), "ours")
    failed = _guarded_clear_tashuo_ax_text_area_if_exact(
        _session(Result(returncode=1, stderr="private text must not leak")), "ours"
    )

    assert mismatch["status"] == "blocked"
    assert mismatch["reason"] == "composer_exact_mismatch"
    assert missing["reason"] == "tashuo_ax_text_area_not_found"
    assert failed["reason"] == "tashuo_guarded_ax_clear_failed"
    assert "private text" not in str(failed)


def test_conversation_snapshot_reads_revision_and_composer_in_one_ax_script():
    session = _session(
        Result(
            stdout=json.dumps(
                {
                    "values": ["旧消息", "新消息"],
                    "composer_found": True,
                    "composer_value": "准备发送",
                },
                ensure_ascii=False,
            )
        )
    )

    result = _tashuo_ax_conversation_snapshot(session)

    assert result["status"] == "ok"
    assert result["values"] == ["旧消息", "新消息"]
    assert result["composer_value"] == "准备发送"
    assert len(session.runner.commands) == 1
    assert "DATING_BOOST_AX_CONVERSATION_SNAPSHOT" in _script(session)


@pytest.mark.parametrize(
    "values",
    [
        ["第一行\n第二行", "后续消息"],
        ["第一行\r\n第二行", "引号\"和\\反斜杠\t😀"],
        ["同一条", "同一条", "[不是序列]"],
    ],
)
@pytest.mark.parametrize("legacy_array", [False, True])
def test_static_and_snapshot_readers_share_lossless_revision_contract(values, legacy_array):
    static_payload = values if legacy_array else {"values": values}
    composer = "尚未发送\n第二行"
    session = _session(
        Result(stdout=json.dumps(static_payload, ensure_ascii=False)),
        Result(stdout=json.dumps({"values": values, "composer_found": True, "composer_value": composer})),
    )

    binding = {"thread_evidence": {"managed_message_text_hashes": [
        hashlib.sha256(value.strip().encode("utf-8")).hexdigest() for value in values
    ]}}
    before = _observe_current_conversation_revision(session, target_binding=binding)
    staged = _observe_current_conversation_revision(session, target_binding=binding, expected_composer_text=composer)

    expected = "ax-static-v1:" + hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert before["status"] == staged["status"] == "ok"
    assert before["inbound_revision"] == staged["inbound_revision"] == expected
    assert before["value_count"] == staged["value_count"] == len(values)
    assert staged["composer_exact_match"] is True
    static_script, snapshot_script = [command[2] for command in session.runner.commands]
    assert 'return "{\\"values\\":" & my jsonArray(valuesList) & "}"' in static_script
    assert "set AppleScript's text item delimiters to linefeed" not in static_script
    assert static_script.split("-- DATING_BOOST_AX_STATIC_TEXT_VALUES")[0] == snapshot_script.split(
        "-- DATING_BOOST_AX_CONVERSATION_SNAPSHOT"
    )[0]


@pytest.mark.parametrize("legacy_array", [False, True])
def test_static_read_preserves_existing_empty_and_filter_contract(legacy_array):
    values = ["", "  ", "missing value", "  名字  ", "第一行\n第二行"]
    payload = values if legacy_array else {"values": values}
    result = _tashuo_ax_static_text_values(_session(Result(stdout=json.dumps(payload))))
    assert result["values"] == ["名字", "第一行\n第二行"]
    assert result["value_count"] == 2
    empty = [] if legacy_array else {"values": []}
    result = _tashuo_ax_static_text_values(_session(Result(stdout=json.dumps(empty))))
    assert result["status"] == "ok"
    assert result["values"] == []
    assert result["value_count"] == 0


@pytest.mark.parametrize("raw", ["", "第一行\n第二行\n", '"single string"', "null", '{"values":[1]}'])
def test_static_read_rejects_ambiguous_or_non_string_evidence(raw):
    result = _tashuo_ax_static_text_values(_session(Result(stdout=raw)))
    assert result == {"status": "blocked", "reason": "tashuo_ax_static_text_values_invalid"}


@pytest.mark.parametrize("values", [[None], [1], [False], "line"])
def test_snapshot_rejects_non_string_evidence_in_the_shared_contract(values):
    result = _tashuo_ax_conversation_snapshot(
        _session(Result(stdout=json.dumps({"values": values, "composer_found": False, "composer_value": ""})))
    )
    assert result == {"status": "blocked", "reason": "tashuo_ax_conversation_snapshot_invalid"}


def _geometry_payload(**overrides):
    return {
        "composer_position": [110, 800],
        "composer_size": [380, 60],
        "window_position": [100, 200],
        "window_size": [400, 700],
        **overrides,
    }


@pytest.mark.parametrize(
    "payload",
    [
        _geometry_payload(),
        _geometry_payload(composer_position=[-390.5, -10.25], window_position=[-400.5, -610.25]),
        _geometry_payload(composer_position=[100, 200], composer_size=[400, 700]),
    ],
)
def test_composer_geometry_reads_one_window_without_content_or_mutation(payload):
    session = _session(Result(stdout=json.dumps(payload)))

    result = _tashuo_ax_composer_geometry(session)

    assert result == {"status": "ok", **payload}
    assert len(session.runner.commands) == 1
    script = _script(session)
    assert "DATING_BOOST_AX_COMPOSER_GEOMETRY" in script
    assert "set targetWindow to item 1 of windowSelection" in script
    assert "window 1" not in script
    assert "my findComposer(targetWindow, 0)" in script
    assert "position of composer" in script and "size of composer" in script
    assert "position of targetWindow" in script and "size of targetWindow" in script
    for mutation_or_content in ("value of composer", "set position", "set size", "activate", "keystroke", "key code", "click", "pbcopy"):
        assert mutation_or_content not in script


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("process_not_found", "tashuo_ax_composer_geometry_process_not_found"),
        ("window_not_found", "tashuo_ax_composer_geometry_window_not_found"),
        ("composer_not_found", "tashuo_ax_text_area_not_found"),
        ("read_failed", "tashuo_ax_composer_geometry_read_failed"),
        ("private unknown AX detail", "tashuo_ax_composer_geometry_invalid"),
        (["private"], "tashuo_ax_composer_geometry_invalid"),
    ],
)
def test_composer_geometry_missing_and_read_errors_are_fixed_codes(error, reason):
    result = _tashuo_ax_composer_geometry(_session(Result(stdout=json.dumps({"error": error}))))
    assert result == {"status": "blocked", "reason": reason}


@pytest.mark.parametrize(
    "overrides",
    [
        {"composer_position": "110,800"},
        {"composer_position": [110]},
        {"composer_position": [110, 800, 0]},
        {"composer_position": ["110", 800]},
        {"window_position": [True, 200]},
        {"composer_size": [None, 60]},
        {"window_size": {"width": 400, "height": 700}},
        {"composer_position": [float("nan"), 800]},
        {"composer_position": [float("inf"), 800]},
        {"window_position": [float("-inf"), 200]},
        {"window_size": [10**400, 700]},
        {"composer_size": [0, 60]},
        {"composer_size": [380, -1]},
        {"window_size": [0, 700]},
        {"window_size": [400, -700]},
        {"composer_position": [99, 800]},
        {"composer_position": [110, 199]},
        {"composer_position": [121, 800]},
        {"composer_position": [110, 841]},
        {"composer_size": [401, 60]},
        {"composer_size": [380, 701]},
        {"private_text": "must not be returned"},
    ],
)
def test_composer_geometry_requires_exact_numeric_pairs_and_containment(overrides):
    result = _tashuo_ax_composer_geometry(_session(Result(stdout=json.dumps(_geometry_payload(**overrides)))))
    assert result == {"status": "blocked", "reason": "tashuo_ax_composer_geometry_invalid"}


@pytest.mark.parametrize(
    "raw",
    [
        "private invalid JSON",
        "",
        "null",
        "[]",
        '{"composer_position":[110,800]}',
        json.dumps(_geometry_payload())[:-1] + ',"composer_position":[110,800]}',
    ],
)
def test_composer_geometry_rejects_missing_malformed_and_duplicate_fields(raw):
    result = _tashuo_ax_composer_geometry(_session(Result(stdout=raw)))
    assert result == {"status": "blocked", "reason": "tashuo_ax_composer_geometry_invalid"}


def test_composer_geometry_does_not_expose_subprocess_error_details():
    result = _tashuo_ax_composer_geometry(
        _session(Result(returncode=1, stdout="private stdout", stderr="private stderr"))
    )
    assert result == {"status": "blocked", "reason": "tashuo_ax_composer_geometry_read_failed"}

    class FailingRunner:
        def run(self, command):
            raise RuntimeError("private subprocess failure")

    result = _tashuo_ax_composer_geometry(SimpleNamespace(runner=FailingRunner()))
    assert result == {"status": "blocked", "reason": "tashuo_ax_composer_geometry_read_failed"}
