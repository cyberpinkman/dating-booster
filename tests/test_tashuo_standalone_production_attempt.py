from __future__ import annotations

from pathlib import Path

import pytest

from dating_boost.apps.tashuo.standalone_production_attempt import (
    AttemptProtocolViolation,
    ProductionAttemptProtocol,
    build_composer_plan,
    decide_attempt_recovery,
    record_observed_composer,
    stage_consumed_after_verified_cleanup,
    validate_pre_stage_revalidation,
)
from dating_boost.apps.tashuo.standalone_production_contract import QualificationBinding
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.operator import _work_items_from_decision
from dating_boost.core.standalone_session import StandaloneSessionRepository
from dating_boost.core.storage import JsonStorage


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-attempt-test-key")


def _binding(attempt_id="attempt_1", cycle_index=1):
    return QualificationBinding(
        qualification_id="qual_1",
        phase="canary",
        cycle_index=cycle_index,
        attempt_id=attempt_id,
        local_fencing_token=2,
        runtime_fencing_token=7,
    )


def _guard_ok():
    return {"status": "ok", "local_fencing_token": 2, "runtime_fencing_token": 7}


def test_composer_plan_separates_payload_normalized_text_and_exact_observed_hashes():
    payload_messages = [{"kind": "text", "text": "line one"}, {"kind": "text", "text": "line two"}]
    plan = build_composer_plan(payload_messages=payload_messages, composer_text="Cafe\u0301\r\nnext  ")

    assert plan["payload_hash"] != plan["planned_composer_text_hash"]
    assert plan["planned_composer_text"] == "Café\nnext  "
    observed = record_observed_composer(plan, "Café\nnext  ")
    assert observed["status"] == "verified"
    assert observed["exact_observed_composer_text"] == "Café\nnext  "
    assert observed["exact_observed_composer_text_hash"]
    assert observed["normalized_observed_composer_text_hash"] == plan["planned_composer_text_hash"]


def test_observed_composer_normalized_mismatch_blocks_cleanup_binding():
    plan = build_composer_plan(payload_messages=[{"kind": "text", "text": "one"}], composer_text="one")
    with pytest.raises(AttemptProtocolViolation, match="staged_text_mismatch"):
        record_observed_composer(plan, "one ")


def test_pre_stage_revalidation_requires_fresh_identical_target_tail_empty_composer_and_no_user_event():
    baseline = {
        "frontmost_app": "tashuo",
        "window_identity": "window_1",
        "target_binding_digest": "target_1",
        "tail_digest": "tail_1",
        "composer_text": "",
        "captured_monotonic_ns": 100,
        "user_event_count": 0,
    }
    refreshed = {**baseline, "captured_monotonic_ns": 1_000_000_000}
    assert validate_pre_stage_revalidation(baseline, refreshed, now_monotonic_ns=2_000_000_000)["status"] == "ok"

    for changes, reason in [
        ({"target_binding_digest": "other"}, "pre_stage_target_changed"),
        ({"tail_digest": "other"}, "pre_stage_tail_changed"),
        ({"composer_text": "user draft"}, "candidate_composer_occupied"),
        ({"frontmost_app": "codex"}, "pre_stage_frontmost_app_changed"),
        ({"window_identity": "window_2"}, "pre_stage_window_changed"),
        ({"user_event_count": 1}, "user_or_external_interference_detected"),
    ]:
        result = validate_pre_stage_revalidation(
            baseline,
            {**refreshed, **changes},
            now_monotonic_ns=2_000_000_000,
        )
        assert result["status"] == "blocked"
        assert result["reason"] == reason

    stale = validate_pre_stage_revalidation(baseline, refreshed, now_monotonic_ns=3_000_000_001)
    assert stale["reason"] == "pre_stage_evidence_stale"


def test_attempt_checkpoints_are_ordered_and_guarded_before_commit(tmp_path):
    ledger = ProductionQualificationLedger(tmp_path / "data")
    calls = []

    def guard():
        calls.append("guard")
        return _guard_ok()

    protocol = ProductionAttemptProtocol(ledger, _binding(), mutation_guard=guard, monotonic_ns=lambda: 100)
    started = protocol.start(precondition_digest="pre_1", target_hash="target_1")
    advanced = protocol.advance("surface_navigation_started", evidence_digest="evidence_1")

    assert started["mutation_phase"] == "not_started"
    assert advanced["mutation_phase"] == "surface_navigation_started"
    assert calls == ["guard", "guard", "guard", "guard"]
    assert ledger.validate_event_chain()["valid"] is True
    with pytest.raises(AttemptProtocolViolation, match="mutation_phase_transition_invalid"):
        protocol.advance("stage_mutation_intent", evidence_digest="skip")


def test_stale_fencing_guard_prevents_checkpoint_and_event_commit(tmp_path):
    ledger = ProductionQualificationLedger(tmp_path / "data")
    outcomes = iter([_guard_ok(), _guard_ok(), {"status": "blocked", "reason": "runtime_fencing_mismatch"}])
    protocol = ProductionAttemptProtocol(ledger, _binding(), mutation_guard=lambda: next(outcomes))
    protocol.start(precondition_digest="pre_1", target_hash="target_1")

    with pytest.raises(AttemptProtocolViolation, match="runtime_fencing_mismatch"):
        protocol.advance("surface_navigation_started", evidence_digest="evidence_1")

    attempt = ledger.read_record("standalone_production/attempts/attempt_1.json")
    assert attempt["mutation_phase"] == "not_started"
    assert ledger.validate_event_chain()["event_count"] == 1


def _stage_payload(binding):
    return {
        "action_request_id": f"action_{binding.attempt_id}",
        "target_match_id": "match_1",
        "payload_hash": "payload_1",
        "pre_action_observation_id": "obs_1",
        "precondition_hash": "pre_1",
        "result_status": "succeeded",
        "evidence": {"stage_mode": True, "live_send_executed": False},
        "stage_attempt_status": "completed",
        "staged_text_verified": True,
        "staged_text_verification": {"status": "verified"},
        "target_verification": {"status": "ok"},
        "qualification_binding": binding.to_dict(),
    }


def test_stage_audit_digest_and_dedup_include_full_qualification_binding(tmp_path):
    repository = ActionAuditRepository(tmp_path / "data")
    one = repository.append_stage_result(_stage_payload(_binding("attempt_1")), created_at="2026-07-13T00:00:00Z")
    replay = repository.append_stage_result(_stage_payload(_binding("attempt_1")), created_at="2026-07-13T00:00:00Z")
    two = repository.append_stage_result(_stage_payload(_binding("attempt_2")), created_at="2026-07-13T00:00:00Z")

    assert replay["duplicate"] is True
    assert one["event_id"] != two["event_id"]
    assert len(JsonStorage(tmp_path / "data").read_jsonl(Path("audit/stage_results.jsonl"))) == 2


def test_qualification_binding_is_persisted_in_standalone_session_events_and_work_items(tmp_path):
    binding = _binding()
    repository = StandaloneSessionRepository(tmp_path / "data")
    started = repository.start(
        app_id="tashuo",
        runtime="mac-ios-app",
        send_mode="stage",
        observation_source={"type": "live-gui"},
        backend={"type": "scripted"},
        scan_interval_seconds=1,
        qualification_binding=binding.to_dict(),
    )
    items = _work_items_from_decision(
        {
            "status": "ok",
            "action_requests": [{"schema_version": 1, "action_request_id": "action_1"}],
        },
        "session_1",
        qualification_binding=binding.to_dict(),
    )

    assert started["session"]["qualification_binding"] == binding.to_dict()
    events = JsonStorage(tmp_path / "data").read_jsonl(Path("standalone_session/events.jsonl"))
    assert events[0]["payload"]["qualification_binding"] == binding.to_dict()
    assert items[0]["qualification_binding"] == binding.to_dict()


def _seed_staged_state(data_dir, binding):
    work_item = {
        "schema_version": 1,
        "work_item_id": "work_1",
        "work_item_type": "send_message",
        "action_request_id": "action_1",
        "match_id": "match_1",
        "payload_hash": "payload_1",
        "qualification_binding": binding.to_dict(),
    }
    session = {
        "schema_version": 1,
        "session_id": "session_1",
        "status": "active",
        "current_work_item": work_item,
        "qualification_binding": binding.to_dict(),
    }
    state = {
        "schema_version": 1,
        "match_id": "match_1",
        "state": "staged_pending_user",
        "last_action_request_id": "action_1",
        "last_outbound_payload_hash": "payload_1",
        "last_precondition_hash": "pre_1",
        "last_pre_action_observation_id": "obs_1",
        "last_autonomous_audit_binding": {"binding_type": "autonomous_authorization"},
        "qualification_binding": binding.to_dict(),
    }
    storage = JsonStorage(data_dir)
    storage.write_json(Path("operator/session.json"), session)
    storage.write_json(Path("operator/current_work_item.json"), work_item)
    storage.write_json(Path("automation/states.json"), {"schema_version": 1, "states": [state]})


def test_stage_consumption_is_blocked_until_cleanup_and_negative_send_are_verified(tmp_path):
    data_dir = tmp_path / "data"
    binding = _binding()
    _seed_staged_state(data_dir, binding)

    with pytest.raises(AttemptProtocolViolation, match="cleanup_not_verified"):
        stage_consumed_after_verified_cleanup(
            data_dir,
            binding=binding,
            action_request_id="action_1",
            cleanup_verification={"status": "blocked"},
            negative_send_verification={"status": "verified"},
            predecessor_binding={"target_hash": "target_1"},
        )
    with pytest.raises(AttemptProtocolViolation, match="negative_send_not_verified"):
        stage_consumed_after_verified_cleanup(
            data_dir,
            binding=binding,
            action_request_id="action_1",
            cleanup_verification={"status": "verified", "composer_empty": True, "target_hash": "target_1"},
            negative_send_verification={"status": "blocked"},
            predecessor_binding={"target_hash": "target_1"},
        )
    session = JsonStorage(data_dir).read_json(Path("operator/session.json"), expected_schema_version=1)
    assert session["current_work_item"]["action_request_id"] == "action_1"


def test_verified_stage_consumption_atomically_releases_sticky_and_active_request(tmp_path):
    data_dir = tmp_path / "data"
    binding = _binding()
    _seed_staged_state(data_dir, binding)

    result = stage_consumed_after_verified_cleanup(
        data_dir,
        binding=binding,
        action_request_id="action_1",
        cleanup_verification={"status": "verified", "composer_empty": True, "target_hash": "target_1"},
        negative_send_verification={"status": "verified", "target_hash": "target_1"},
        predecessor_binding={"target_hash": "target_1", "target_binding_digest": "binding_1"},
    )

    assert result["status"] == "stage_consumed"
    storage = JsonStorage(data_dir)
    session = storage.read_json(Path("operator/session.json"), expected_schema_version=1)
    states = storage.read_json(Path("automation/states.json"), expected_schema_version=1)["states"]
    assert session["current_work_item"] is None
    assert not storage.exists(Path("operator/current_work_item.json"))
    assert states[0]["state"] == "draft_ready"
    assert "last_action_request_id" not in states[0]
    assert "last_outbound_payload_hash" not in states[0]
    assert states[0]["last_qualification_stage_consumed"]["attempt_id"] == "attempt_1"
    transition = ProductionQualificationLedger(data_dir).read_record(
        "standalone_production/stage_consumptions/attempt_1.json"
    )
    assert transition["predecessor_binding"]["target_hash"] == "target_1"

    replay = stage_consumed_after_verified_cleanup(
        data_dir,
        binding=binding,
        action_request_id="action_1",
        cleanup_verification={"status": "verified", "composer_empty": True, "target_hash": "target_1"},
        negative_send_verification={"status": "verified", "target_hash": "target_1"},
        predecessor_binding={"target_hash": "target_1", "target_binding_digest": "binding_1"},
    )
    assert replay["status"] == "replayed"


def test_stage_consumption_binding_mismatch_never_clears_user_state(tmp_path):
    data_dir = tmp_path / "data"
    binding = _binding()
    _seed_staged_state(data_dir, binding)

    with pytest.raises(AttemptProtocolViolation, match="qualification_binding_mismatch"):
        stage_consumed_after_verified_cleanup(
            data_dir,
            binding=_binding("attempt_other"),
            action_request_id="action_1",
            cleanup_verification={"status": "verified", "composer_empty": True, "target_hash": "target_1"},
            negative_send_verification={"status": "verified", "target_hash": "target_1"},
            predecessor_binding={"target_hash": "target_1"},
        )
    assert JsonStorage(data_dir).exists(Path("operator/current_work_item.json"))


@pytest.mark.parametrize(
    ("phase", "composer_state", "target_matches", "sentinel", "expected"),
    [
        ("pre_stage_revalidated", "empty", True, False, "abandon_before_mutation"),
        ("pre_stage_revalidated", "other", True, True, "block_and_pause"),
        ("stage_mutation_completed", "empty", True, True, "observe_negative_send"),
        ("stage_mutation_completed", "exact", True, True, "clear_exact_then_observe_negative_send"),
        ("stage_mutation_completed", "exact", True, False, "block_and_pause"),
        ("stage_mutation_completed", "other", True, True, "block_and_pause"),
        ("stage_mutation_completed", "unknown", True, True, "block_and_pause"),
        ("stage_mutation_completed", "exact", False, True, "block_and_pause"),
    ],
)
def test_recovery_decision_covers_pre_mutation_and_all_composer_states(
    phase, composer_state, target_matches, sentinel, expected
):
    result = decide_attempt_recovery(
        mutation_phase=phase,
        composer_state=composer_state,
        target_matches=target_matches,
        stage_mutation_completed=phase == "stage_mutation_completed",
        input_sentinel_coverage_complete=sentinel,
        user_event_count=0,
    )
    assert result["action"] == expected
    assert result["runtime_safety_pause_required"] is (expected == "block_and_pause")
