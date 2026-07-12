from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO

from dating_boost.cli import main


def _run(args):
    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = main(args)
    return exit_code, json.loads(stdout.getvalue())


def test_runtime_safety_pause_status_and_exact_resume(monkeypatch, tmp_path):
    monkeypatch.setenv("DATING_BOOST_RUNTIME_LOCK_ROOT", str(tmp_path / "runtime"))
    scope = ["--app-id", "tashuo", "--runtime", "mac-ios-app", "--json"]

    pause_exit, paused = _run(["safety", "pause", *scope, "--reason", "composer_state_unknown"])
    status_exit, status = _run(["safety", "status", *scope])
    wrong_exit, wrong = _run(["safety", "resume", *scope, "--pause-id", "wrong"])
    resume_exit, resumed = _run(["safety", "resume", *scope, "--pause-id", paused["pause_id"]])

    assert pause_exit == 0
    assert paused["status"] == "paused"
    assert status_exit == 0
    assert status["safety_pause"]["pause_id"] == paused["pause_id"]
    assert wrong_exit == 2
    assert wrong["reason"] == "runtime_pause_id_mismatch"
    assert resume_exit == 0
    assert resumed["status"] == "active"


def test_runtime_safety_scope_rejects_other_app_or_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("DATING_BOOST_RUNTIME_LOCK_ROOT", str(tmp_path / "runtime"))
    exit_code, payload = _run(
        ["safety", "status", "--app-id", "tinder", "--runtime", "default", "--json"]
    )
    assert exit_code == 2
    assert payload["reason"] == "runtime_safety_scope_unsupported"
