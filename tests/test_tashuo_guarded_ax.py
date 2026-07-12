from __future__ import annotations

import hashlib
from types import SimpleNamespace

from dating_boost.apps.tashuo.send_input_ax import (
    _guarded_clear_tashuo_ax_text_area_if_exact,
    _guarded_set_tashuo_ax_text_area_if_empty,
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
