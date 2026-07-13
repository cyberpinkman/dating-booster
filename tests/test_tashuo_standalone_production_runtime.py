from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dating_boost.apps.tashuo.standalone_production_artifacts import create_qualification_paths
from dating_boost.apps.tashuo.standalone_production_attempt import (
    ProductionAttemptProtocol,
    build_composer_plan,
    record_observed_composer,
    stage_consumed_after_verified_cleanup,
)
from dating_boost.apps.tashuo.standalone_production_contract import QualificationBinding, canonical_digest
from dating_boost.apps.tashuo.standalone_production_evidence import (
    build_conversation_tail_v2,
    qualification_target_hash,
)
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.apps.tashuo.standalone_production_runtime import (
    ExistingStandaloneWorkItems,
    ProductionAttemptEngine,
    TaShuoProductionGui,
    TaShuoStandaloneProductionRuntime,
    _stable_target_binding,
    _tail_content_digest,
)
from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.storage import JsonStorage


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-runtime-test-key")


def _binding():
    return QualificationBinding(
        qualification_id="qual_runtime",
        phase="canary",
        cycle_index=1,
        attempt_id="attempt_runtime_1",
        local_fencing_token=3,
        runtime_fencing_token=7,
    )


def _guard():
    return {
        "status": "ok",
        "local_fencing_token": 3,
        "runtime_fencing_token": 7,
    }


def _paths(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    return create_qualification_paths(
        tmp_path / "root",
        source_data_dir=source,
        qualification_id="qual_runtime",
    )


def _target(salt="salt_runtime"):
    binding = {
        "schema_version": 1,
        "binding_type": "current_thread_visual_identity",
        "candidate_key": "candidate_1",
        "thread_evidence": {"visual_anchor_hash": "thread_anchor_1"},
        "message_list_evidence": {"visual_anchor_hash": "list_anchor_1"},
    }
    stable = _stable_target_binding(binding)
    return {
        "candidate_key": "candidate_1",
        "probe_target_binding": binding,
        "target_hash": qualification_target_hash(salt, stable),
        "target_binding_digest": canonical_digest(stable),
    }


def _tail(target, *, capture, observation, monotonic):
    return build_conversation_tail_v2(
        qualification_salt="salt_runtime",
        target_binding=_stable_target_binding(target["probe_target_binding"]),
        viewport_identity="viewport_1",
        capture_id=capture,
        observation_id=observation,
        captured_monotonic_ns=monotonic,
        bubbles=[
            {
                "direction": "inbound",
                "text": "你好",
                "bounds": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.1},
                "anchor": "bubble_1",
                "order": 1,
                "confidence": 0.99,
            }
        ],
    )


class FakeGui:
    def __init__(
        self,
        target,
        *,
        occupied=False,
        occupy_on_capture=None,
        target_mismatch_from_capture=None,
    ):
        self.target = target
        self.composer = "existing" if occupied else ""
        self.occupy_on_capture = occupy_on_capture
        self.target_mismatch_from_capture = target_mismatch_from_capture
        self.set_calls = []
        self.clear_calls = []
        self.capture_index = 0
        self.pauses = []

    def bind_target(self, target, *, slot):
        return {"status": "ok"}

    def capture_state(self, target):
        self.capture_index += 1
        if self.occupy_on_capture == self.capture_index:
            self.composer = "external draft"
        tail = _tail(
            self.target,
            capture=f"capture_{self.capture_index}",
            observation=f"observation_{self.capture_index}",
            monotonic=self.capture_index * 100,
        )
        return {
            "status": "ok",
            "frontmost_app": "tashuo",
            "window_identity": "window_1",
            "target_hash": (
                "different-target"
                if self.target_mismatch_from_capture is not None
                and self.capture_index >= self.target_mismatch_from_capture
                else self.target["target_hash"]
            ),
            "target_binding_digest": self.target["target_binding_digest"],
            "tail_digest": _tail_content_digest(tail),
            "tail": tail,
            "composer_text": self.composer,
            "captured_monotonic_ns": self.capture_index * 100,
            "user_event_count": 0,
        }

    def guarded_set_if_empty(self, text):
        self.set_calls.append(text)
        if self.composer:
            return {"status": "blocked", "reason": "candidate_composer_occupied"}
        self.composer = text
        return {"status": "ok"}

    def read_composer(self):
        return {"status": "ok", "value": self.composer}

    def guarded_clear_if_exact(self, text):
        self.clear_calls.append(text)
        if self.composer != text:
            return {"status": "blocked", "reason": "cleanup_state_unknown"}
        self.composer = ""
        return {"status": "ok"}

    def input_sentinel_snapshot(self):
        return {"status": "ok", "counts": {"1": 10, "2": 20}}

    def input_sentinel_status(self, baseline):
        return {
            "status": "ok",
            "user_event_count": 0,
            "current_counts": dict(baseline),
        }

    def pause_runtime(self, reason):
        self.pauses.append(reason)
        return {"status": "paused"}


class FakeWorkItems:
    def __init__(self, data_dir: Path, binding, target):
        self.data_dir = data_dir
        self.binding = binding
        self.target = target
        self.closed = False
        self.prepared = False

    def prepare(self, *, binding, target, slot, authorization_record_id):
        self.prepared = True
        work_item = {
            "schema_version": 1,
            "work_item_id": "work_1",
            "work_item_type": "send_message",
            "action_request_id": "action_1",
            "match_id": "match_1",
            "payload_text": "你好呀",
            "payload_hash": "payload_1",
            "payload_messages": [{"text": "你好呀"}],
            "pre_action_observation_id": "observation_before",
            "precondition_hash": "precondition_1",
            "target_binding": self.target["probe_target_binding"],
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
            "state": "draft_ready",
            "last_action_request_id": "action_1",
            "last_outbound_payload_hash": "payload_1",
            "last_precondition_hash": "precondition_1",
            "last_pre_action_observation_id": "observation_before",
            "last_autonomous_audit_binding": {"binding_type": "autonomous_authorization"},
            "qualification_binding": binding.to_dict(),
        }
        storage = JsonStorage(self.data_dir)
        storage.write_json(Path("operator/session.json"), session)
        storage.write_json(Path("operator/current_work_item.json"), work_item)
        storage.write_json(Path("automation/states.json"), {"schema_version": 1, "states": [state]})
        return {"status": "ok", "work_item": work_item, "provider_identity": {"model": "fixed"}}

    def record_stage(self, work_item, *, result_status, evidence):
        payload = {
            "action_request_id": work_item["action_request_id"],
            "target_match_id": work_item["match_id"],
            "payload_hash": work_item["payload_hash"],
            "pre_action_observation_id": work_item["pre_action_observation_id"],
            "result_status": result_status,
            "evidence": {"stage_mode": True, "live_send_executed": False},
            "stage_attempt_status": evidence["stage_attempt_status"],
            "staged_text_verified": evidence["staged_text_verified"],
            "staged_text_verification": evidence["staged_text_verification"],
            "target_verification": evidence["target_verification"],
            "qualification_binding": self.binding.to_dict(),
        }
        event = ActionAuditRepository(self.data_dir).append_stage_result(
            payload,
            created_at="2026-07-13T00:00:00Z",
        )
        storage = JsonStorage(self.data_dir)
        states = storage.read_json(Path("automation/states.json"), expected_schema_version=1)
        states["states"][0]["state"] = "staged_pending_user" if result_status == "succeeded" else "draft_ready"
        storage.write_json(Path("automation/states.json"), states)
        return {"status": "ok", "event_id": event["event_id"]}

    def close(self):
        self.closed = True


class FakeSelectionProvider:
    def __init__(self, recommendations):
        self.recommendations = list(recommendations)
        self.observed_candidates = []

    def observe_message_list(self, *, app_id, scan_cursor):
        return {
            "status": "ok",
            "candidates": [
                {"candidate_key": f"candidate_{index}"}
                for index in range(1, len(self.recommendations) + 1)
            ],
        }

    def precheck_payload(self, *, app_id):
        return {"status": "ok"}

    def observe_thread(self, *, app_id, candidate_key):
        self.observed_candidates.append(candidate_key)
        index = int(candidate_key.rsplit("_", 1)[1]) - 1
        return {
            "status": "ok",
            "assessment": {"recommended_next": self.recommendations[index]},
            "target_binding": {
                "schema_version": 1,
                "binding_type": "current_thread_visual_identity",
                "candidate_key": candidate_key,
                "thread_evidence": {"visual_anchor_hash": f"thread_{index}"},
                "message_list_evidence": {"visual_anchor_hash": f"list_{index}"},
            },
        }


def _selection_gui(recommendations):
    gui = TaShuoProductionGui.__new__(TaShuoProductionGui)
    gui.qualification_salt = "selection_test_salt"
    gui.provider = FakeSelectionProvider(recommendations)
    gui._provider_identity_valid = lambda: True
    gui.read_composer = lambda: {"status": "ok", "value": ""}
    gui._eligible_target = lambda candidate_key, target_binding: {
        "status": "eligible",
        "candidate_key": candidate_key,
        "probe_target_binding": dict(target_binding),
    }
    return gui


def test_message_list_selection_skips_planner_wait_candidate():
    gui = _selection_gui(["wait", "reply"])

    result = gui.select_target(
        {
            "slot": {"mode": "message-list"},
            "excluded_target_hashes": [],
        }
    )

    assert result["status"] == "eligible"
    assert result["candidate_key"] == "candidate_2"
    assert gui.provider.observed_candidates == ["candidate_1", "candidate_2"]


def test_message_list_selection_skips_deferred_nudge_candidate():
    gui = _selection_gui(["nudge_later", "reply"])

    result = gui.select_target(
        {
            "slot": {"mode": "message-list"},
            "excluded_target_hashes": [],
        }
    )

    assert result["status"] == "eligible"
    assert result["candidate_key"] == "candidate_2"
    assert gui.provider.observed_candidates == ["candidate_1", "candidate_2"]


def test_message_list_selection_reports_inconclusive_when_all_candidates_wait():
    gui = _selection_gui(["wait", "wait"])

    result = gui.select_target(
        {
            "slot": {"mode": "message-list"},
            "excluded_target_hashes": [],
        }
    )

    assert result == {"status": "inconclusive", "reason": "no_eligible_empty_composer"}
    assert gui.provider.observed_candidates == ["candidate_1", "candidate_2"]


def test_current_thread_selection_reports_inconclusive_when_predecessor_now_waits():
    gui = _selection_gui(["wait"])
    target_binding = {
        "schema_version": 1,
        "binding_type": "current_thread_visual_identity",
        "candidate_key": "candidate_1",
        "thread_evidence": {"visual_anchor_hash": "thread_0"},
        "message_list_evidence": {"visual_anchor_hash": "list_0"},
    }

    result = gui.select_target(
        {
            "slot": {"mode": "current-thread"},
            "predecessor_binding": {
                "candidate_key": "candidate_1",
                "target_binding": target_binding,
            },
        }
    )

    assert result == {"status": "inconclusive", "reason": "no_eligible_empty_composer"}


@pytest.mark.parametrize(
    "tick_result",
    [
        {"status": "no_work", "reason": "no_wake_condition"},
        {
            "status": "blocked",
            "reason": "qualification_bound_provider_requires_current_thread",
        },
        {"status": "work_consumed"},
    ],
)
def test_existing_work_items_classifies_missing_stage_work_as_precondition_mismatch(
    tmp_path,
    monkeypatch,
    tick_result,
):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    ledger.insert_if_absent(
        "standalone_production/config/authorization_1.json",
        {"schema_version": 1, "authorization": {"authorization_id": "auth_1"}},
    )
    ledger.insert_if_absent(
        "standalone_production/qualifications/qual_runtime.json",
        {
            "schema_version": 1,
            "qualification_id": "qual_runtime",
            "environment_fingerprint": {
                "model": {
                    "backend": "minimax",
                    "model_identifier": "MiniMax-M3",
                    "vision_backend": "minimax",
                    "vision_model_identifier": "MiniMax-M3",
                }
            },
        },
    )

    class FakeManagedSessionRepository:
        def __init__(self, root, harness_factory=None):
            pass

        def status(self):
            return {"status": "not_found"}

        def start(self, **kwargs):
            return {"status": "active"}

    class FakeStandaloneSessionRepository:
        def __init__(self, root):
            pass

        def status(self):
            return {"status": "not_found"}

        def start(self, **kwargs):
            return {"status": "active"}

        def record_tick(self, payload):
            return {"status": "ok"}

    class FakeStandaloneAgentRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def tick(self):
            return dict(tick_result)

    class FakeStandaloneDraftPlanner:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(
        "dating_boost.core.managed_session.ManagedSessionRepository",
        FakeManagedSessionRepository,
    )
    monkeypatch.setattr(
        "dating_boost.core.standalone_session.StandaloneSessionRepository",
        FakeStandaloneSessionRepository,
    )
    monkeypatch.setattr(
        "dating_boost.core.standalone_runtime.StandaloneAgentRuntime",
        FakeStandaloneAgentRuntime,
    )
    monkeypatch.setattr(
        "dating_boost.core.standalone_runtime.StandaloneDraftPlanner",
        FakeStandaloneDraftPlanner,
    )
    gui = type("DiagnosticGui", (), {"provider": object()})()

    result = ExistingStandaloneWorkItems(paths=paths, gui=gui).prepare(
        binding=_binding(),
        target=_target(),
        slot={"mode": "message-list"},
        authorization_record_id="authorization_1",
    )

    assert result == {
        "schema_version": 1,
        "status": "blocked",
        "reason": "precondition_mismatch",
    }


def _engine(
    tmp_path,
    *,
    occupied=False,
    occupy_on_capture=None,
    target_mismatch_from_capture=None,
):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    binding = _binding()
    target = _target()
    protocol = ProductionAttemptProtocol(ledger, binding, mutation_guard=_guard, monotonic_ns=lambda: 1)
    protocol.start(precondition_digest="precondition_1", target_hash=target["target_hash"])
    gui = FakeGui(
        target,
        occupied=occupied,
        occupy_on_capture=occupy_on_capture,
        target_mismatch_from_capture=target_mismatch_from_capture,
    )
    work_items = FakeWorkItems(paths.data_dir, binding, target)
    engine = ProductionAttemptEngine(
        paths=paths,
        binding=binding,
        capability={},
        gui=gui,
        work_items=work_items,
        worker_nonce="worker_1",
        monotonic_ns=lambda: 500,
        mutation_guard=_guard,
    )
    return engine, gui, work_items, ledger, target


def _recovery_engine(
    tmp_path,
    *,
    phase="staged_verified",
    sentinel_complete=True,
    stage_result_status=None,
):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    binding = _binding()
    target = _target()
    gui = FakeGui(target)
    work_items = FakeWorkItems(paths.data_dir, binding, target)
    protocol = ProductionAttemptProtocol(ledger, binding, mutation_guard=_guard, monotonic_ns=lambda: 1)
    protocol.start(
        precondition_digest="precondition_1",
        target_hash=target["target_hash"],
        target=target,
    )
    if phase == "not_started":
        work_item = None
        plan = None
        observed = None
    else:
        protocol.advance("surface_navigation_started", evidence_digest="surface")
        if phase == "surface_navigation_started":
            work_item = None
            plan = None
            observed = None
        else:
            baseline = gui.capture_state(target)
            protocol.advance(
                "target_bound",
                evidence_digest="target",
                updates={
                    "target_binding": target["probe_target_binding"],
                    "baseline_tail": baseline["tail"],
                    "baseline_state_digest": "baseline_state",
                },
            )
            if phase == "target_bound":
                work_item = None
                plan = None
                observed = None
            else:
                protocol.advance("composer_empty_verified", evidence_digest="empty")
                if phase == "composer_empty_verified":
                    work_item = None
                    plan = None
                    observed = None
                else:
                    work_item = work_items.prepare(
                        binding=binding,
                        target=target,
                        slot={"mode": "message-list"},
                        authorization_record_id="authorization_1",
                    )["work_item"]
                    plan = build_composer_plan(
                        payload_messages=work_item["payload_messages"],
                        composer_text=work_item["payload_text"],
                    )
                    protocol.advance(
                        "pre_stage_revalidated",
                        evidence_digest="revalidated",
                        updates={
                            "composer_plan": plan,
                            "action_request_id": work_item["action_request_id"],
                        },
                    )
                    observed = None
                    if phase != "pre_stage_revalidated":
                        protocol.advance(
                            "stage_mutation_intent",
                            evidence_digest="intent",
                            updates={
                                "input_sentinel_baseline": {"1": 10, "2": 20},
                                "input_sentinel_coverage_started": True,
                            },
                        )
                        gui.composer = work_item["payload_text"]
                        if phase != "stage_mutation_intent":
                            protocol.advance(
                                "stage_mutation_completed",
                                evidence_digest="mutated",
                                updates={"input_sentinel_coverage_complete": sentinel_complete},
                            )
                            if phase != "stage_mutation_completed":
                                observed = record_observed_composer(plan, gui.composer)
                                protocol.advance(
                                    "staged_verified",
                                    evidence_digest="staged",
                                    updates={"observed_composer": observed},
                                )
                                if phase != "staged_verified":
                                    protocol.advance("cleanup_started", evidence_digest="cleanup_started")
                                    if phase != "cleanup_started":
                                        gui.composer = ""
                                        cleanup = {
                                            "status": "verified",
                                            "composer_empty": True,
                                            "target_hash": target["target_hash"],
                                        }
                                        protocol.advance(
                                            "cleanup_verified",
                                            evidence_digest="cleanup",
                                            updates={"cleanup_verification": cleanup},
                                        )
                                        if phase != "cleanup_verified":
                                            negative = {
                                                "schema_version": 1,
                                                "status": "verified",
                                                "target_hash": target["target_hash"],
                                            }
                                            protocol.advance(
                                                "negative_send_verified",
                                                evidence_digest="negative",
                                                updates={"negative_send_verification": negative},
                                            )
                                            if phase in {"stage_consumed", "attempt_terminal_committed"}:
                                                if stage_result_status is None:
                                                    stage_result_status = "succeeded"
                                                work_items.record_stage(
                                                    work_item,
                                                    result_status=stage_result_status,
                                                    evidence={
                                                        "stage_attempt_status": "completed",
                                                        "staged_text_verified": True,
                                                        "staged_text_verification": {"status": "verified"},
                                                        "target_verification": {
                                                            "status": "ok",
                                                            "target_hash": target["target_hash"],
                                                        },
                                                    },
                                                )
                                                predecessor = {
                                                    "target_hash": target["target_hash"],
                                                    "target_binding_digest": target["target_binding_digest"],
                                                    "candidate_key": target["candidate_key"],
                                                    "target_binding": target["probe_target_binding"],
                                                }
                                                stage_consumed_after_verified_cleanup(
                                                    paths.data_dir,
                                                    binding=binding,
                                                    action_request_id=work_item["action_request_id"],
                                                    cleanup_verification=cleanup,
                                                    negative_send_verification=negative,
                                                    predecessor_binding=predecessor,
                                                )
                                                protocol.advance(
                                                    "stage_consumed",
                                                    evidence_digest="consumed",
                                                    updates={"predecessor_binding": predecessor},
                                                )
                                                if phase == "attempt_terminal_committed":
                                                    protocol.advance(
                                                        "attempt_terminal_committed",
                                                        evidence_digest="terminal",
                                                        updates={"terminal_evidence_digest": "terminal"},
                                                    )
    if stage_result_status is not None and phase not in {"stage_consumed", "attempt_terminal_committed"}:
        if work_item is None:
            raise AssertionError("stage result requires a prepared work item")
        work_items.record_stage(
            work_item,
            result_status=stage_result_status,
            evidence={
                "stage_attempt_status": "completed" if stage_result_status == "succeeded" else "failed",
                "staged_text_verified": stage_result_status == "succeeded",
                "staged_text_verification": {
                    "status": "verified" if stage_result_status == "succeeded" else "failed"
                },
                "target_verification": {"status": "ok", "target_hash": target["target_hash"]},
            },
        )
    engine = ProductionAttemptEngine(
        paths=paths,
        binding=binding,
        capability={"local_fencing_token": 3, "runtime_fencing_token": 7},
        gui=gui,
        work_items=work_items,
        worker_nonce="recovery_worker_1",
        monotonic_ns=lambda: 500,
        mutation_guard=_guard,
        recovery=True,
    )
    return engine, gui, work_items, ledger, target


def test_attempt_engine_uses_guarded_ax_cleans_exact_text_and_records_negative_send(tmp_path):
    engine, gui, work_items, ledger, target = _engine(tmp_path)

    result = engine.execute(
        {
            "target": target,
            "slot": {"mode": "message-list", "planned_slot_id": "slot_1"},
            "authorization_record_id": "authorization_1",
        }
    )

    assert result["status"] == "succeeded", result
    assert result["terminal_persisted"] is True
    assert gui.set_calls == ["你好呀"]
    assert gui.clear_calls == ["你好呀"]
    assert gui.composer == ""
    assert result["negative_send_verification"]["status"] == "verified"
    assert result["predecessor_binding"]["target_hash"] == target["target_hash"]
    assert work_items.closed is True
    assert ledger.read_attempt_outcome("attempt_runtime_1")["status"] == "succeeded"
    stages = JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl"))
    assert len(stages) == 1
    assert stages[0]["qualification_binding"] == _binding().to_dict()


def test_occupied_composer_blocks_before_work_item_and_never_calls_ax_set_or_clear(tmp_path):
    engine, gui, work_items, ledger, target = _engine(tmp_path, occupied=True)

    result = engine.execute(
        {
            "target": target,
            "slot": {"mode": "message-list", "planned_slot_id": "slot_1"},
            "authorization_record_id": "authorization_1",
        }
    )

    assert result["status"] == "failed"
    assert result["reason"] == "candidate_composer_occupied"
    assert result["mutation_phase"] == "target_bound"
    assert work_items.prepared is False
    assert gui.set_calls == []
    assert gui.clear_calls == []
    assert JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl")) == []
    assert ledger.read_attempt_outcome("attempt_runtime_1")["mutation_phase"] == "target_bound"


def test_external_composer_change_during_model_work_is_preserved_before_ax_mutation(tmp_path):
    engine, gui, work_items, ledger, target = _engine(
        tmp_path,
        occupy_on_capture=2,
    )

    result = engine.execute(
        {
            "target": target,
            "slot": {"mode": "message-list", "planned_slot_id": "slot_1"},
            "authorization_record_id": "authorization_1",
        }
    )

    assert result["status"] == "failed"
    assert result["reason"] == "candidate_composer_occupied"
    assert result["mutation_phase"] == "composer_empty_verified"
    assert gui.composer == "external draft"
    assert work_items.prepared is True
    assert gui.set_calls == []
    assert gui.clear_calls == []
    assert JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl")) == []
    assert ledger.read_attempt_outcome("attempt_runtime_1")["status"] == "failed"


def test_cleanup_target_mismatch_never_clears_staged_text_or_fabricates_terminal(tmp_path):
    engine, gui, _, ledger, target = _engine(
        tmp_path,
        target_mismatch_from_capture=3,
    )

    result = engine.execute(
        {
            "target": target,
            "slot": {"mode": "message-list", "planned_slot_id": "slot_1"},
            "authorization_record_id": "authorization_1",
        }
    )

    assert result["status"] == "failed"
    assert result["safe_recovery_complete"] is False
    assert result["terminal_persisted"] is False
    assert gui.clear_calls == []
    assert gui.composer == "你好呀"
    assert gui.pauses
    with pytest.raises(FileNotFoundError):
        ledger.read_attempt_outcome("attempt_runtime_1")
    with pytest.raises(FileNotFoundError):
        ledger.read_receipt("attempt_runtime_1")


def test_recovery_clears_exact_staged_text_and_records_one_failed_stage_result(tmp_path):
    engine, gui, _, ledger, target = _recovery_engine(tmp_path)

    result = engine.recover({"target": target})

    assert result["status"] == "failed"
    assert result["reason"] == "worker_timeout_after_mutation"
    assert result["safe_recovery_complete"] is True
    assert result["terminal_persisted"] is True
    assert gui.clear_calls == ["你好呀"]
    assert gui.composer == ""
    stages = JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl"))
    assert len(stages) == 1
    assert stages[0]["result_status"] == "failed"
    assert ledger.read_attempt_outcome("attempt_runtime_1")["recovery_terminal"] is True


def test_recovery_finishes_success_when_success_stage_exists_before_consumption(tmp_path):
    engine, gui, _, ledger, target = _recovery_engine(
        tmp_path,
        phase="negative_send_verified",
        stage_result_status="succeeded",
    )

    result = engine.recover({"target": target})

    assert result["status"] == "succeeded", result
    assert result["reason"] is None
    assert result["terminal_persisted"] is True
    assert result["predecessor_binding"]["target_hash"] == target["target_hash"]
    assert gui.clear_calls == []
    stages = JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl"))
    assert len(stages) == 1
    assert stages[0]["result_status"] == "succeeded"
    attempt = ledger.read_record("standalone_production/attempts/attempt_runtime_1.json")
    assert attempt["mutation_phase"] == "attempt_terminal_committed"
    assert ledger.read_attempt_outcome("attempt_runtime_1")["status"] == "succeeded"


def test_recovery_does_not_clear_or_fabricate_terminal_when_sentinel_has_gap(tmp_path):
    engine, gui, _, ledger, target = _recovery_engine(
        tmp_path,
        sentinel_complete=False,
    )

    result = engine.recover({"target": target})

    assert result["status"] == "failed"
    assert result["safe_recovery_complete"] is False
    assert result["terminal_persisted"] is False
    assert gui.clear_calls == []
    assert gui.pauses
    with pytest.raises(FileNotFoundError):
        ledger.read_attempt_outcome("attempt_runtime_1")
    with pytest.raises(FileNotFoundError):
        ledger.read_receipt("attempt_runtime_1")
    assert JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl")) == []


@pytest.mark.parametrize(
    ("phase", "expected_status", "safe", "terminal", "stage_count"),
    [
        ("not_started", "failed", True, True, 0),
        ("surface_navigation_started", "failed", True, True, 0),
        ("target_bound", "failed", True, True, 0),
        ("composer_empty_verified", "failed", True, True, 0),
        ("pre_stage_revalidated", "failed", True, True, 0),
        ("stage_mutation_intent", "failed", False, False, 0),
        ("stage_mutation_completed", "failed", False, False, 0),
        ("staged_verified", "failed", True, True, 1),
        ("cleanup_started", "failed", True, True, 1),
        ("cleanup_verified", "failed", True, True, 1),
        ("negative_send_verified", "failed", True, True, 1),
        ("stage_consumed", "succeeded", True, True, 1),
        ("attempt_terminal_committed", "succeeded", True, True, 1),
    ],
)
def test_recovery_contract_for_every_persisted_mutation_phase(
    tmp_path,
    phase,
    expected_status,
    safe,
    terminal,
    stage_count,
):
    engine, gui, _, ledger, target = _recovery_engine(tmp_path, phase=phase)

    result = engine.recover({"target": target})

    assert result["status"] == expected_status, result
    assert result["safe_recovery_complete"] is safe
    assert result["terminal_persisted"] is terminal
    stages = JsonStorage(engine.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl"))
    assert len(stages) == stage_count
    if terminal:
        assert ledger.read_attempt_outcome("attempt_runtime_1")["status"] == expected_status
        assert ledger.read_receipt("attempt_runtime_1")["status"] == expected_status
    else:
        assert gui.pauses
        with pytest.raises(FileNotFoundError):
            ledger.read_attempt_outcome("attempt_runtime_1")
        with pytest.raises(FileNotFoundError):
            ledger.read_receipt("attempt_runtime_1")


def test_worker_stdout_secret_is_blocked_and_temporary_output_is_destroyed(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "provider-key-for-output-test")
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    ledger.create_qualification(
        paths.qualification_id,
        {
            "environment_fingerprint": {
                "model": {"api_key_env": "MINIMAX_API_KEY"}
            }
        },
    )

    def leaking_launcher(_command, **kwargs):
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import os,time; "
                    "print(os.environ['DATING_BOOST_TEST_KEY'], flush=True); "
                    "time.sleep(0.2)"
                ),
            ],
            **kwargs,
        )

    runtime = TaShuoStandaloneProductionRuntime(
        worker_launcher=leaking_launcher,
        source_root=Path.cwd(),
    )
    assert runtime.start_phase(
        {
            "phase": "canary",
            "paths": paths,
            "support_session_id": "support_1",
            "lock_capability": {},
            "authorization_record_id": "authorization_1",
            "lock_renewer": lambda: {"qualification_id": paths.qualification_id},
        }
    )["status"] == "ok"

    result = runtime._run_worker(
        worker_kind="selection_probe",
        context_id="probe_sensitive_output",
        payload={"schema_version": 1},
        timeout_seconds=5,
        lock_capability={},
    )

    assert result["worker_status"] == "sensitive_output_detected"
    assert "production-runtime-test-key" not in str(result)
    io_dir = paths.work_dir / "worker-io"
    assert io_dir.is_dir()
    assert list(io_dir.iterdir()) == []
