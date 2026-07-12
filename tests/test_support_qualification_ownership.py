from __future__ import annotations

import pytest

from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.support import SupportLogRepository


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "support-owner-test-key")


def _owner(qualification_id="qual_1", phase="canary"):
    return {"qualification_id": qualification_id, "phase": phase}


def test_support_start_is_cas_owned_and_same_owner_is_idempotent(tmp_path):
    repository = SupportLogRepository(tmp_path / "data")
    first = repository.start_session(host="codex", app_id="tashuo", owner=_owner())
    replay = repository.start_session(host="codex", app_id="tashuo", owner=_owner())
    conflict = repository.start_session(host="codex", app_id="tashuo", owner=_owner("qual_2"))

    assert first["status"] == "active"
    assert first["support_owner"] == _owner()
    assert replay["session_id"] == first["session_id"]
    assert replay["reused"] is True
    assert conflict["status"] == "blocked"
    assert conflict["reason"] == "support_session_owner_conflict"
    assert repository.active_session()["session_id"] == first["session_id"]


def test_owned_support_stop_requires_exact_owner(tmp_path):
    repository = SupportLogRepository(tmp_path / "data")
    started = repository.start_session(host="codex", app_id="tashuo", owner=_owner())

    missing = repository.stop_session(session_id=started["session_id"])
    wrong = repository.stop_session(session_id=started["session_id"], owner=_owner("qual_2"))
    stopped = repository.stop_session(session_id=started["session_id"], owner=_owner())

    assert missing["reason"] == "support_session_owner_required"
    assert wrong["reason"] == "support_session_owner_mismatch"
    assert stopped["status"] == "stopped"


def test_explicit_command_context_binds_attempt_without_global_pointer_lookup(tmp_path):
    data_dir = tmp_path / "data"
    repository = SupportLogRepository(data_dir)
    started = repository.start_session(host="codex", app_id="tashuo", owner=_owner())
    context = {
        "support_session_id": started["session_id"],
        "qualification_id": "qual_1",
        "phase": "canary",
        "attempt_id": "attempt_1",
    }

    command = repository.record_command_started(["standalone-session", "tick"], context=context)
    repository.record_command_finished(
        command,
        argv=["standalone-session", "tick"],
        exit_code=0,
        duration_ms=10,
    )

    events = [
        item["payload"]
        for item in ProductionDataStore(data_dir).list_audit_events(
            stream=f"support/{started['session_id']}/events.jsonl"
        )
    ]
    starts = [item for item in events if item["event_type"] == "command_started"]
    finishes = [item for item in events if item["event_type"] == "command_finished"]
    assert starts[-1]["payload"]["attempt_id"] == "attempt_1"
    assert starts[-1]["payload"]["qualification_id"] == "qual_1"
    assert finishes[-1]["payload"]["started_event_id"] == starts[-1]["event_id"]


def test_explicit_command_context_rejects_wrong_owner_or_session(tmp_path):
    repository = SupportLogRepository(tmp_path / "data")
    started = repository.start_session(host="codex", app_id="tashuo", owner=_owner())

    wrong_owner = repository.record_command_started(
        ["command"],
        context={
            "support_session_id": started["session_id"],
            "qualification_id": "qual_2",
            "phase": "canary",
            "attempt_id": "attempt_1",
        },
    )
    missing = repository.record_command_started(
        ["command"],
        context={
            "support_session_id": "support_missing",
            "qualification_id": "qual_1",
            "phase": "canary",
            "attempt_id": "attempt_1",
        },
    )

    assert wrong_owner is None
    assert missing is None


def test_command_coverage_requires_finish_or_explicit_interruption(tmp_path):
    repository = SupportLogRepository(tmp_path / "data")
    started = repository.start_session(host="codex", app_id="tashuo", owner=_owner())

    first = repository.record_command_started(
        ["probe"],
        context={
            "support_session_id": started["session_id"],
            "qualification_id": "qual_1",
            "phase": "canary",
            "probe_id": "probe_1",
        },
    )
    assert repository.validate_command_coverage(
        session_id=started["session_id"], required_context_ids=["probe_1"]
    )["valid"] is False

    repository.record_command_interrupted(first, argv=["probe"], reason="worker_timeout_before_mutation")
    assert repository.validate_command_coverage(
        session_id=started["session_id"], required_context_ids=["probe_1"]
    )["valid"] is True
