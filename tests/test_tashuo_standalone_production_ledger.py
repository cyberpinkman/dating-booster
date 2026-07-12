from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dating_boost.apps.tashuo.standalone_production_contract import QualificationBinding
from dating_boost.apps.tashuo.standalone_production_ledger import (
    LedgerConflict,
    LedgerCorruption,
    ProductionQualificationLedger,
)
from dating_boost.core.production_store import ProductionDataStore


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-ledger-test-key")


@pytest.fixture
def ledger(tmp_path):
    return ProductionQualificationLedger(tmp_path / "data")


def _binding(attempt_id="attempt_1", cycle_index=1):
    return QualificationBinding(
        qualification_id="qual_1",
        phase="canary",
        cycle_index=cycle_index,
        attempt_id=attempt_id,
        local_fencing_token=3,
        runtime_fencing_token=9,
    )


def test_insert_if_absent_replays_same_digest_and_rejects_conflict(ledger):
    path = "standalone_production/receipts/attempt_1.json"
    first = ledger.insert_if_absent(path, {"schema_version": 1, "attempt_id": "attempt_1", "status": "ok"})
    replay = ledger.insert_if_absent(path, {"status": "ok", "attempt_id": "attempt_1", "schema_version": 1})

    assert first["status"] == "inserted"
    assert replay == {**first, "status": "replayed"}
    with pytest.raises(LedgerConflict, match="immutable_record_conflict"):
        ledger.insert_if_absent(path, {"schema_version": 1, "attempt_id": "attempt_1", "status": "failed"})


def test_immutable_records_exist_only_in_encrypted_sqlite(ledger):
    path = "standalone_production/attempts/attempt_1.json"
    ledger.insert_if_absent(path, {"schema_version": 1, "attempt_id": "attempt_1"})

    assert not (ledger.data_dir / path).exists()
    assert (ledger.data_dir / "dating_boost.sqlite3").is_file()
    assert ledger.read_record(path)["attempt_id"] == "attempt_1"


def test_versioned_compare_and_swap_is_monotonic_and_conflict_safe(ledger):
    path = "standalone_production/qualifications/qual_1.json"
    created = ledger.create_versioned(path, {"schema_version": 1, "qualification_id": "qual_1", "state": "created"})
    updated = ledger.compare_and_swap(
        path,
        expected_version=created["ledger_version"],
        changes={"state": "preflight_passed"},
    )

    assert created["ledger_version"] == 1
    assert updated["ledger_version"] == 2
    assert updated["state"] == "preflight_passed"
    with pytest.raises(LedgerConflict, match="ledger_version_conflict"):
        ledger.compare_and_swap(path, expected_version=1, changes={"state": "canary_running"})


def test_only_one_concurrent_cas_writer_wins(ledger):
    path = "standalone_production/cycles/canary/1.json"
    ledger.create_versioned(path, {"schema_version": 1, "cycle_index": 1, "state": "running"})

    def update(final_attempt_id):
        try:
            return ledger.compare_and_swap(
                path,
                expected_version=1,
                changes={"final_attempt_id": final_attempt_id},
            )["final_attempt_id"]
        except LedgerConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["attempt_1", "attempt_2"]))

    assert results.count("conflict") == 1
    assert len({value for value in results if value != "conflict"}) == 1


def test_append_event_builds_and_validates_hash_chain(ledger):
    first = ledger.append_event(
        event_id="event_1",
        event_type="attempt_started",
        binding=_binding(),
        reason_code=None,
        mutation_phase="not_started",
        evidence_digest="evidence_1",
    )
    second = ledger.append_event(
        event_id="event_2",
        event_type="pre_stage_revalidated",
        binding=_binding(),
        reason_code=None,
        mutation_phase="pre_stage_revalidated",
        evidence_digest="evidence_2",
    )

    assert first["sequence"] == 1
    assert first["previous_hash"] is None
    assert second["sequence"] == 2
    assert second["previous_hash"] == first["event_hash"]
    assert ledger.validate_event_chain()["valid"] is True
    assert ledger.validate_event_chain()["chain_root"] == second["event_hash"]


def test_append_event_is_idempotent_only_for_identical_event(ledger):
    kwargs = {
        "event_id": "event_1",
        "event_type": "attempt_started",
        "binding": _binding(),
        "reason_code": None,
        "mutation_phase": "not_started",
        "evidence_digest": "evidence_1",
    }
    first = ledger.append_event(**kwargs)
    replay = ledger.append_event(**kwargs)
    assert replay == first

    with pytest.raises(LedgerConflict, match="event_conflict"):
        ledger.append_event(**{**kwargs, "evidence_digest": "different"})


def test_hash_chain_validator_rejects_tampered_encrypted_event(ledger):
    ledger.append_event(
        event_id="event_1",
        event_type="attempt_started",
        binding=_binding(),
        reason_code=None,
        mutation_phase="not_started",
        evidence_digest="evidence_1",
    )
    store = ProductionDataStore(ledger.data_dir)
    event = store.list_audit_events(stream="standalone_production/events.jsonl")[0]["payload"]
    store.append_audit_event(
        "standalone_production/events.jsonl",
        {**event, "evidence_digest": "tampered"},
    )

    result = ledger.validate_event_chain()
    assert result["valid"] is False
    assert result["reason"] == "event_hash_mismatch"


def test_event_rejects_incomplete_binding_and_unknown_mutation_phase(ledger):
    with pytest.raises((TypeError, LedgerCorruption, ValueError)):
        ledger.append_event(
            event_id="event_1",
            event_type="attempt_started",
            binding={"qualification_id": "qual_1"},
            reason_code=None,
            mutation_phase="not_started",
            evidence_digest="evidence_1",
        )
    with pytest.raises(LedgerCorruption, match="mutation_phase_unknown"):
        ledger.append_event(
            event_id="event_2",
            event_type="attempt_started",
            binding=_binding(),
            reason_code=None,
            mutation_phase="unknown",
            evidence_digest="evidence_1",
        )


def test_same_payload_in_different_attempts_is_not_deduplicated(ledger):
    payload = {"schema_version": 1, "payload_hash": "same", "status": "ok"}
    one = ledger.record_receipt(_binding("attempt_1"), payload)
    two = ledger.record_receipt(_binding("attempt_2"), payload)

    assert one["digest"] != two["digest"]
    assert ledger.read_receipt("attempt_1")["qualification_binding"]["attempt_id"] == "attempt_1"
    assert ledger.read_receipt("attempt_2")["qualification_binding"]["attempt_id"] == "attempt_2"


def test_cycle_final_attempt_is_selected_once_by_cas(ledger):
    ledger.create_cycle(
        qualification_id="qual_1",
        phase="canary",
        cycle_index=1,
        planned_slot_id="slot_1",
        mode="message-list",
    )
    ledger.add_cycle_attempt("canary", 1, "attempt_1", expected_version=1)
    cycle = ledger.claim_final_attempt("canary", 1, "attempt_1", expected_version=2)
    assert cycle["final_attempt_id"] == "attempt_1"

    with pytest.raises(LedgerConflict):
        ledger.claim_final_attempt("canary", 1, "attempt_2", expected_version=cycle["ledger_version"])


def test_cycle_commit_boundaries_replay_exactly_and_reject_conflicting_resume(ledger):
    cycle = ledger.create_cycle(
        qualification_id="qual_1",
        phase="canary",
        cycle_index=1,
        planned_slot_id="slot_1",
        mode="message-list",
        actual_start_ns=100,
    )
    cycle = ledger.add_cycle_attempt(
        "canary",
        1,
        "attempt_1",
        expected_version=cycle["ledger_version"],
    )
    cycle = ledger.claim_final_attempt(
        "canary",
        1,
        "attempt_1",
        expected_version=cycle["ledger_version"],
    )
    cycle = ledger.mark_attempt_terminal_committed(
        "canary",
        1,
        expected_version=cycle["ledger_version"],
    )
    assert ledger.mark_attempt_terminal_committed(
        "canary", 1, expected_version=1
    )["ledger_version"] == cycle["ledger_version"]
    cycle = ledger.mark_cycle_commit_intent(
        "canary",
        1,
        expected_version=cycle["ledger_version"],
    )
    assert ledger.mark_cycle_commit_intent(
        "canary", 1, expected_version=1
    )["ledger_version"] == cycle["ledger_version"]
    predecessor = {"target_hash": "target_1"}
    committed = ledger.commit_cycle(
        "canary",
        1,
        expected_version=cycle["ledger_version"],
        success=True,
        actual_start_ns=100,
        commit_index=1,
        predecessor_binding=predecessor,
    )
    replay = ledger.commit_cycle(
        "canary",
        1,
        expected_version=1,
        success=True,
        actual_start_ns=100,
        commit_index=1,
        predecessor_binding=predecessor,
    )
    assert replay["ledger_version"] == committed["ledger_version"]
    with pytest.raises(LedgerConflict, match="cycle_final_commit_conflict"):
        ledger.commit_cycle(
            "canary",
            1,
            expected_version=committed["ledger_version"],
            success=True,
            actual_start_ns=101,
            commit_index=1,
            predecessor_binding=predecessor,
        )


def test_attempt_graph_requires_one_outcome_receipt_and_phase_dependent_stage_result(ledger):
    binding = _binding()
    ledger.create_attempt(binding, {"mutation_phase": "attempt_terminal_committed"})
    ledger.record_attempt_outcome(binding, {"status": "succeeded", "mutation_phase": "attempt_terminal_committed"})
    ledger.record_receipt(binding, {"status": "succeeded", "mutation_phase": "attempt_terminal_committed"})

    missing_stage = ledger.validate_attempt_graph([binding.attempt_id], stage_results=[])
    assert missing_stage["valid"] is False
    assert "stage_result_cardinality_invalid" in missing_stage["reasons"]

    stage_result = {
        "event_id": "stage_1",
        "qualification_binding": binding.to_dict(),
        "result_status": "succeeded",
        "stage_attempt_status": "completed",
    }
    assert ledger.validate_attempt_graph([binding.attempt_id], stage_results=[stage_result])["valid"] is True


def test_pre_mutation_attempt_requires_zero_stage_results(ledger):
    binding = _binding()
    ledger.create_attempt(binding, {"mutation_phase": "pre_stage_revalidated"})
    ledger.record_attempt_outcome(binding, {"status": "failed", "mutation_phase": "pre_stage_revalidated"})
    ledger.record_receipt(binding, {"status": "failed", "mutation_phase": "pre_stage_revalidated"})

    assert ledger.validate_attempt_graph([binding.attempt_id], stage_results=[])["valid"] is True
    invalid = ledger.validate_attempt_graph(
        [binding.attempt_id],
        stage_results=[{"event_id": "unexpected", "qualification_binding": binding.to_dict()}],
    )
    assert invalid["valid"] is False


def test_attempt_graph_rejects_orphan_and_binding_mismatch(ledger):
    binding = _binding()
    ledger.create_attempt(binding, {"mutation_phase": "pre_stage_revalidated"})
    ledger.record_attempt_outcome(binding, {"status": "failed", "mutation_phase": "pre_stage_revalidated"})
    ledger.record_receipt(binding, {"status": "failed", "mutation_phase": "pre_stage_revalidated"})

    assert ledger.validate_attempt_graph([], stage_results=[])["valid"] is False
    wrong = _binding(attempt_id="attempt_1", cycle_index=2)
    store = ProductionDataStore(ledger.data_dir)
    receipt = ledger.read_receipt("attempt_1")
    store.upsert_document(
        "standalone_production/receipts/attempt_1.json",
        {**receipt, "qualification_binding": wrong.to_dict()},
    )
    result = ledger.validate_attempt_graph(["attempt_1"], stage_results=[])
    assert result["valid"] is False
    assert "qualification_binding_mismatch" in result["reasons"]


def test_sqlite_quick_check_is_exposed_without_paths_or_secrets(ledger):
    ledger.insert_if_absent("standalone_production/records/one.json", {"schema_version": 1})
    result = ledger.quick_check()

    assert result == {"status": "ok", "sqlite_quick_check": "ok"}
    assert "DATING_BOOST_TEST_KEY" not in str(result)
    assert str(ledger.data_dir) not in str(result)
