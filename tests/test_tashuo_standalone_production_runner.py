from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


pytestmark = pytest.mark.nightly_lab

import dating_boost.apps.tashuo.standalone_production_runner as runner_module
from dating_boost.apps.tashuo.standalone_production_artifacts import (
    create_qualification_paths,
    validate_production_artifact,
)
from dating_boost.apps.tashuo.standalone_production_contract import MUTATION_PHASES, SOAK_INTERVAL_NS
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.apps.tashuo.standalone_production_runner import (
    ProductionQualificationRunner,
    RunnerBlocked,
    _execution_fingerprint,
)
from tests.test_tashuo_standalone_production_artifacts import _populate_source
from dating_boost.core.storage import JsonStorage
from dating_boost.core.support import SupportLogRepository


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-runner-test-key")


class FakeClock:
    def __init__(self):
        self.wall = datetime(2026, 7, 13, 0, 0, tzinfo=UTC)
        self.monotonic = 1_000_000_000
        self.boot = "boot_1"
        self.sleeps = []

    def now(self):
        return self.wall

    def monotonic_ns(self):
        return self.monotonic

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        delta_ns = int(seconds * 1_000_000_000)
        self.monotonic += delta_ns
        self.wall += timedelta(seconds=seconds)

    def advance(self, seconds):
        self.sleep(seconds)

    def boot_session_id(self):
        return self.boot


class FakePreflight:
    def __init__(self):
        self.calls = []
        self.environment = {
            "schema_version": 1,
            "tool_version": "test",
            "system": {"boot_session_id": "boot_1"},
            "model": {"provider_identifier": "deployment_1"},
        }

    def run(self, **kwargs):
        self.calls.append(kwargs)
        expected = kwargs.get("expected_environment_fingerprint")
        if expected is not None and expected != self.environment:
            return {"status": "blocked", "reason": "environment_drift"}
        return {
            "status": "ok",
            "environment_fingerprint": dict(self.environment),
            "config_hash": "config_hash_1",
            "provider_identifier": "deployment_1",
            "checks": {"direct_harness_scope": "executor_internal_only"},
        }


class FakeRuntime:
    def __init__(self):
        self.probes = []
        self.attempts = []
        self.phase_starts = []
        self.phase_ends = []
        self.inconclusive_probe_slots = set()
        self.fail_attempt_numbers = set()
        self.failure_reason = "model_timeout"

    def start_phase(self, context):
        self.phase_starts.append(context)
        return {"status": "ok"}

    def selection_probe(self, context):
        self.probes.append(context)
        if context["planned_slot_id"] in self.inconclusive_probe_slots:
            return {"status": "inconclusive", "reason": "no_eligible_empty_composer"}
        return {
            "status": "eligible",
            "target_hash": f"target_{context['planned_slot_id']}",
            "target_binding_digest": f"binding_{context['planned_slot_id']}",
            "precondition_digest": f"precondition_{context['probe_id']}",
            "probe_target_binding": {"kind": "fixture", "target_hash": f"target_{context['planned_slot_id']}"},
        }

    def execute_attempt(self, context):
        self.attempts.append(context)
        attempt_number = len(self.attempts)
        protocol = context.protocol
        if attempt_number in self.fail_attempt_numbers:
            protocol.advance("surface_navigation_started", evidence_digest=f"failure_{attempt_number}")
            protocol.record_terminal(
                status="failed",
                reason_code=self.failure_reason,
                terminal_evidence_digest=f"terminal_failure_{attempt_number}",
                receipt={"worker_nonce": f"worker_{attempt_number}"},
            )
            return {
                "status": "failed",
                "reason": self.failure_reason,
                "mutation_phase": "surface_navigation_started",
                "safe_recovery_complete": True,
                "terminal_evidence_digest": f"terminal_failure_{attempt_number}",
                "receipt": {"worker_nonce": f"worker_{attempt_number}"},
                "stage_result_payload": None,
                "predecessor_binding": None,
                "terminal_persisted": True,
                "safety_violations": 0,
            }
        for phase in MUTATION_PHASES[1:]:
            protocol.advance(phase, evidence_digest=f"{context.binding.attempt_id}_{phase}")
        stage_payload = {
            "action_request_id": f"action_{context.binding.attempt_id}",
            "target_match_id": f"match_{context.binding.cycle_index}",
            "payload_hash": f"payload_{context.binding.attempt_id}",
            "pre_action_observation_id": f"observation_{context.binding.attempt_id}",
            "precondition_hash": context.precondition_digest,
            "result_status": "succeeded",
            "evidence": {"stage_mode": True, "live_send_executed": False},
            "stage_attempt_status": "completed",
            "staged_text_verified": True,
            "staged_text_verification": {"status": "verified"},
            "target_verification": {"status": "ok"},
            "qualification_binding": context.binding.to_dict(),
        }
        target_hash = context.target["target_hash"]
        protocol.record_terminal(
            status="succeeded",
            reason_code=None,
            terminal_evidence_digest=f"terminal_{context.binding.attempt_id}",
            receipt={
                "worker_nonce": f"worker_{attempt_number}",
                "cleanup_digest": f"cleanup_{context.binding.attempt_id}",
                "negative_send_digest": f"negative_{context.binding.attempt_id}",
            },
        )
        return {
            "status": "succeeded",
            "reason": None,
            "mutation_phase": "attempt_terminal_committed",
            "safe_recovery_complete": True,
            "terminal_evidence_digest": f"terminal_{context.binding.attempt_id}",
            "receipt": {
                "worker_nonce": f"worker_{attempt_number}",
                "cleanup_digest": f"cleanup_{context.binding.attempt_id}",
                "negative_send_digest": f"negative_{context.binding.attempt_id}",
            },
            "stage_result_payload": stage_payload,
            "negative_send_verification": {"status": "verified", "target_hash": target_hash},
            "cleanup_verification": {"status": "verified", "composer_empty": True, "target_hash": target_hash},
            "predecessor_binding": {
                "target_hash": target_hash,
                "target_binding_digest": context.target["target_binding_digest"],
            },
            "evidence_certificate": {
                "attempt_id": context.binding.attempt_id,
                "negative_send_digest": f"negative_{context.binding.attempt_id}",
            },
            "terminal_persisted": True,
            "safety_violations": 0,
        }

    def recover_attempt(self, context):
        return {"status": "recovered", "safe_recovery_complete": True}

    def end_phase(self, context):
        self.phase_ends.append(context)
        return {"status": "ok", "orphan_count": 0}


class UnsafeMutationRuntime(FakeRuntime):
    def execute_attempt(self, context):
        self.attempts.append(context)
        for phase in MUTATION_PHASES[1 : MUTATION_PHASES.index("stage_mutation_intent") + 1]:
            context.protocol.advance(phase, evidence_digest=f"unsafe_{phase}")
        return {
            "status": "failed",
            "reason": "composer_state_unknown",
            "mutation_phase": "stage_mutation_intent",
            "safe_recovery_complete": False,
            "terminal_evidence_digest": "unsafe_terminal_not_persisted",
            "receipt": {},
            "stage_result_payload": None,
            "terminal_persisted": False,
            "safety_violations": 1,
        }


class AbruptPreMutationRuntime(FakeRuntime):
    def execute_attempt(self, context):
        self.attempts.append(context)
        raise KeyboardInterrupt("simulated_parent_crash")


class RecoverablePreMutationCrash(BaseException):
    pass


class RecoverablePreMutationRuntime(FakeRuntime):
    def __init__(self):
        super().__init__()
        self.recoveries = []

    def execute_attempt(self, context):
        self.attempts.append(context)
        context.protocol.advance("surface_navigation_started", evidence_digest="surface_before_crash")
        raise RecoverablePreMutationCrash("pre_mutation_parent_crash")

    def recover_attempt(self, context):
        self.recoveries.append(context)
        digest = f"recovery_terminal_{context.binding.attempt_id}"
        receipt = {"worker_nonce": "recovery_worker"}
        context.protocol.record_recovery_terminal(
            status="failed",
            reason_code="worker_timeout_before_mutation",
            terminal_evidence_digest=digest,
            receipt=receipt,
        )
        return {
            "status": "failed",
            "reason": "worker_timeout_before_mutation",
            "mutation_phase": "surface_navigation_started",
            "safe_recovery_complete": True,
            "terminal_evidence_digest": digest,
            "receipt": receipt,
            "stage_result_payload": None,
            "terminal_persisted": True,
            "safety_violations": 0,
        }


def _authorization(path):
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "authorization_id": "auth_1",
                "app_id": "tashuo",
                "scope": "send_chat_messages",
                "allowed_actions": ["send_message"],
                "allowed_match_ids": [],
                "goal_ids": [],
                "autonomous_send": True,
                "autonomous_nudge": False,
                "live_send": False,
                "requires_post_action_verification": True,
                "quiet_hours": [],
                "created_at": "2026-07-01T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "revoked_at": None,
            }
        ),
        encoding="utf-8",
    )


def _runner(tmp_path, runtime=None, clock=None, preflight=None):
    return ProductionQualificationRunner(
        root_dir=tmp_path / "qualifications",
        source_checkout=Path.cwd(),
        runtime=runtime or FakeRuntime(),
        preflight=preflight or FakePreflight(),
        clock=clock or FakeClock(),
        runtime_lock_state_root=tmp_path / "runtime-locks",
    )


def test_built_artifact_mode_requires_the_wheel_to_match_the_actually_loaded_package(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "dating_boost").mkdir()
    loaded = tmp_path / "site-packages" / "dating_boost"
    loaded.mkdir(parents=True)
    (loaded / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    wheel = tmp_path / "dating_booster-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("dating_boost/module.py", "VALUE = 1\n")

    fingerprint = _execution_fingerprint(
        source_checkout=source,
        built_artifact=wheel,
        loaded_package_root=loaded,
    )

    assert fingerprint["mode"] == "built_artifact"
    assert len(fingerprint["artifact_digest"]) == 64
    (loaded / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(RunnerBlocked, match="built_artifact_package_digest_mismatch"):
        _execution_fingerprint(
            source_checkout=source,
            built_artifact=wheel,
            loaded_package_root=loaded,
        )


def test_built_artifact_mode_rejects_source_checkout_import_even_when_content_matches(tmp_path):
    source = tmp_path / "source"
    loaded = source / "dating_boost"
    loaded.mkdir(parents=True)
    (loaded / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    wheel = tmp_path / "dating_booster-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("dating_boost/module.py", "VALUE = 1\n")

    with pytest.raises(RunnerBlocked, match="built_artifact_not_loaded"):
        _execution_fingerprint(
            source_checkout=source,
            built_artifact=wheel,
            loaded_package_root=loaded,
        )


def test_committed_cycle_resume_repairs_each_missing_chain_event_without_restaging(tmp_path):
    source = tmp_path / "source-cycle-repair"
    source.mkdir()
    paths = create_qualification_paths(
        tmp_path / "cycle-repair-root",
        source_data_dir=source,
        qualification_id="qual_cycle_repair",
    )
    ledger = ProductionQualificationLedger(paths.data_dir)
    binding = runner_module.QualificationBinding(
        qualification_id=paths.qualification_id,
        phase="canary",
        cycle_index=1,
        attempt_id="attempt_cycle_repair",
        local_fencing_token=1,
        runtime_fencing_token=1,
    )
    cycle = ledger.create_cycle(
        qualification_id=paths.qualification_id,
        phase="canary",
        cycle_index=1,
        planned_slot_id="slot_canary_001_repair",
        mode="message-list",
        actual_start_ns=100,
    )
    cycle = ledger.add_cycle_attempt(
        "canary", 1, binding.attempt_id, expected_version=cycle["ledger_version"]
    )
    ledger.create_attempt(binding, {"mutation_phase": "attempt_terminal_committed"})
    ledger.record_attempt_outcome(
        binding,
        {"status": "succeeded", "mutation_phase": "attempt_terminal_committed"},
    )
    ledger.record_receipt(
        binding,
        {
            "status": "succeeded",
            "mutation_phase": "attempt_terminal_committed",
            "cleanup_digest": "cleanup",
            "negative_send_digest": "negative",
        },
    )
    JsonStorage(paths.data_dir).append_jsonl(
        Path("audit/stage_results.jsonl"),
        {
            "event_id": "stage_cycle_repair",
            "qualification_binding": binding.to_dict(),
            "result_status": "succeeded",
        },
    )
    cycle = ledger.claim_final_attempt(
        "canary", 1, binding.attempt_id, expected_version=cycle["ledger_version"]
    )
    cycle = ledger.mark_attempt_terminal_committed(
        "canary", 1, expected_version=cycle["ledger_version"]
    )
    cycle = ledger.mark_cycle_commit_intent(
        "canary", 1, expected_version=cycle["ledger_version"]
    )
    predecessor = {"target_hash": "target_repair"}
    ledger.commit_cycle(
        "canary",
        1,
        expected_version=cycle["ledger_version"],
        success=True,
        actual_start_ns=100,
        commit_index=1,
        predecessor_binding=predecessor,
    )
    runner = _runner(tmp_path)

    repaired = runner._commit_cycle_terminal(
        paths=paths,
        ledger=ledger,
        phase="canary",
        cycle_index=1,
        final_attempt_id=binding.attempt_id,
        success=True,
        actual_start_ns=100,
        commit_index=1,
        predecessor_binding=predecessor,
        validate_all_attempts=False,
    )
    replay = runner._commit_cycle_terminal(
        paths=paths,
        ledger=ledger,
        phase="canary",
        cycle_index=1,
        final_attempt_id=binding.attempt_id,
        success=True,
        actual_start_ns=100,
        commit_index=1,
        predecessor_binding=predecessor,
        validate_all_attempts=False,
    )

    assert repaired["state"] == "cycle_committed_success"
    assert replay["ledger_version"] == repaired["ledger_version"]
    event_ids = [event["event_id"] for event in ledger.list_events()]
    assert event_ids == [
        "cycle_attempt_terminal_canary_1",
        "cycle_commit_intent_canary_1",
        "cycle_committed_canary_1",
    ]


def test_resume_after_phase_commit_reuses_persisted_support_and_does_not_restage(
    tmp_path,
    monkeypatch,
):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runner = _runner(tmp_path, runtime=runtime)
    original_validate = runner_module.validate_canary_metrics

    class SimulatedCrash(BaseException):
        pass

    monkeypatch.setattr(
        runner_module,
        "validate_canary_metrics",
        lambda metrics: (_ for _ in ()).throw(SimulatedCrash()),
    )
    with pytest.raises(SimulatedCrash):
        runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    monkeypatch.setattr(runner_module, "validate_canary_metrics", original_validate)
    qualifications = runner.status()["qualifications"]
    assert len(qualifications) == 1
    qualification_id = qualifications[0]["qualification_id"]
    assert qualifications[0]["status"] == "canary_running"
    attempts_before = len(runtime.attempts)
    phase_starts_before = len(runtime.phase_starts)

    resumed = runner.resume(qualification_id=qualification_id, authorization_path=auth)

    assert resumed["status"] == "canary_passed", resumed
    assert len(runtime.attempts) == attempts_before == 10
    assert len(runtime.phase_starts) == phase_starts_before == 1
    assert validate_production_artifact(Path(resumed["canary_certificate_path"]))[
        "artifact_valid"
    ] is True


@pytest.mark.parametrize(
    "boundary_method",
    ("mark_attempt_terminal_committed", "mark_cycle_commit_intent", "commit_cycle"),
)
def test_resume_repairs_each_cycle_commit_boundary_without_duplicate_staging(
    tmp_path,
    monkeypatch,
    boundary_method,
):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runner = _runner(tmp_path, runtime=runtime)
    original = getattr(ProductionQualificationLedger, boundary_method)
    injected = {"done": False}

    class SimulatedCrash(BaseException):
        pass

    def crash_after_cas(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if not injected["done"]:
            injected["done"] = True
            raise SimulatedCrash(boundary_method)
        return result

    monkeypatch.setattr(ProductionQualificationLedger, boundary_method, crash_after_cas)
    with pytest.raises(SimulatedCrash, match=boundary_method):
        runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    monkeypatch.setattr(ProductionQualificationLedger, boundary_method, original)
    qualification_id = runner.status()["qualifications"][0]["qualification_id"]
    assert len(runtime.attempts) == 1

    resumed = runner.resume(qualification_id=qualification_id, authorization_path=auth)

    assert resumed["status"] == "canary_passed", resumed
    assert len(runtime.attempts) == 10
    certificate = validate_production_artifact(Path(resumed["canary_certificate_path"]))
    assert certificate["artifact_valid"] is True


def test_resume_after_support_stop_finishes_bundle_without_restarting_runtime(
    tmp_path,
    monkeypatch,
):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runner = _runner(tmp_path, runtime=runtime)
    original_bundle = SupportLogRepository.bundle
    injected = {"done": False}

    class SimulatedCrash(BaseException):
        pass

    def crash_before_bundle(self, *args, **kwargs):
        if not injected["done"]:
            injected["done"] = True
            raise SimulatedCrash("support_bundle_boundary")
        return original_bundle(self, *args, **kwargs)

    monkeypatch.setattr(SupportLogRepository, "bundle", crash_before_bundle)
    with pytest.raises(SimulatedCrash, match="support_bundle_boundary"):
        runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    monkeypatch.setattr(SupportLogRepository, "bundle", original_bundle)
    qualification_id = runner.status()["qualifications"][0]["qualification_id"]
    assert len(runtime.attempts) == 10
    phase_starts = len(runtime.phase_starts)

    resumed = runner.resume(qualification_id=qualification_id, authorization_path=auth)

    assert resumed["status"] == "canary_passed", resumed
    assert len(runtime.attempts) == 10
    assert len(runtime.phase_starts) == phase_starts
    assert validate_production_artifact(Path(resumed["canary_certificate_path"]))[
        "artifact_valid"
    ] is True


def test_resume_reconciles_interrupted_support_and_recovery_terminal_before_canary_failure(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = RecoverablePreMutationRuntime()
    runner = _runner(tmp_path, runtime=runtime)
    with pytest.raises(RecoverablePreMutationCrash, match="pre_mutation_parent_crash"):
        runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    qualification_id = runner.status()["qualifications"][0]["qualification_id"]

    resumed = runner.resume(qualification_id=qualification_id, authorization_path=auth)

    assert resumed["status"] == "blocked_finalized", resumed
    assert resumed["reason"] == "worker_timeout_before_mutation"
    assert len(runtime.attempts) == 1
    assert len(runtime.recoveries) == 1
    validation = validate_production_artifact(Path(resumed["qualification_bundle_path"]))
    assert validation["artifact_valid"] is True
    assert validation["qualification_passed"] is False


def test_resume_blocks_authorization_drift_before_recovery_or_gui_work(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = RecoverablePreMutationRuntime()
    runner = _runner(tmp_path, runtime=runtime)
    with pytest.raises(RecoverablePreMutationCrash):
        runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    qualification_id = runner.status()["qualifications"][0]["qualification_id"]
    payload = json.loads(auth.read_text(encoding="utf-8"))
    payload["allowed_match_ids"] = ["changed-match"]
    auth.write_text(json.dumps(payload), encoding="utf-8")

    result = runner.resume(qualification_id=qualification_id, authorization_path=auth)

    assert result["status"] == "blocked_finalized"
    assert result["reason"] == "authorization_drift"
    assert len(runtime.recoveries) == 0


def _inputs(tmp_path):
    source = tmp_path / "source"
    _populate_source(source)
    auth = tmp_path / "auth.json"
    _authorization(auth)
    return source, auth


def test_canary_runs_fixed_ten_first_attempt_cycles_and_returns_nonpassing_certificate(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runner = _runner(tmp_path, runtime=runtime)

    result = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    assert result["status"] == "canary_passed"
    assert result["claim_code"] == "CANARY_PASSED_SOAK_NOT_RUN"
    assert result["metrics"]["committed_cycles"] == 10
    assert result["metrics"]["message_list_cycles"] == 8
    assert result["metrics"]["current_thread_cycles"] == 2
    assert len(runtime.attempts) == 10
    assert all(context.attempt_number == 1 for context in runtime.attempts)
    assert [context.slot["mode"] for context in runtime.attempts][2] == "current-thread"
    certificate = validate_production_artifact(Path(result["canary_certificate_path"]))
    assert certificate["artifact_valid"] is True
    assert certificate["qualification_passed"] is False
    assert "soak not run; qualification not passed" in result["claim_text"]


def test_canary_does_not_retry_even_retryable_first_attempt_failure(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runtime.fail_attempt_numbers.add(1)
    runner = _runner(tmp_path, runtime=runtime)

    result = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    assert result["status"] == "blocked_finalized"
    assert result["reason"] == "model_timeout"
    assert len(runtime.attempts) == 1


def test_unknown_mutation_is_retained_for_manual_recovery_without_terminal_fabrication(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = UnsafeMutationRuntime()
    runner = _runner(tmp_path, runtime=runtime)

    result = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    assert result["status"] == "recovery_required"
    assert result["reason"] == "composer_state_unknown"
    assert result["qualification_passed"] is False
    qualification_id = result["qualification_id"]
    data_dir = tmp_path / "qualifications" / qualification_id / "data"
    assert data_dir.is_dir()
    assert not (tmp_path / "qualifications" / qualification_id / "output" / "terminal_manifest.json").exists()
    assert runner.status(qualification_id=qualification_id)["status"] == "recovery_required"
    ledger = ProductionQualificationLedger(data_dir)
    attempt_id = ledger.list_records("standalone_production/attempts/")[0]["payload"]["attempt_id"]
    with pytest.raises(FileNotFoundError):
        ledger.read_attempt_outcome(attempt_id)
    with pytest.raises(FileNotFoundError):
        ledger.read_receipt(attempt_id)


@pytest.mark.parametrize(
    "boundary",
    (
        "seal_qualification_evidence",
        "validate_qualification_evidence",
        "purge_sensitive_qualification_state",
        "seal_qualification_bundle_from_evidence",
        "validate_production_artifact",
        "publish_terminal_manifest",
    ),
)
def test_finalization_boundary_failure_is_resumable_and_never_publishes_early(
    tmp_path,
    monkeypatch,
    boundary,
):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runtime.fail_attempt_numbers.add(1)
    runtime.failure_reason = "target_mismatch"
    runner = _runner(tmp_path, runtime=runtime)
    original = getattr(runner_module, boundary)
    calls = {"count": 0}

    def fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RunnerBlocked(f"injected_{boundary}_failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(runner_module, boundary, fail_once)
    first = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    assert first["status"] == "finalization_failed"
    qualification_id = first["qualification_id"]
    output = tmp_path / "qualifications" / qualification_id / "output"
    assert not (output / "terminal_manifest.json").exists()
    assert (output / "finalization_checkpoint.json").is_file()

    monkeypatch.setattr(runner_module, boundary, original)
    resumed = runner.finalize(qualification_id=qualification_id)

    assert resumed["status"] == "blocked_finalized", resumed
    assert (output / "terminal_manifest.json").is_file()
    assert not (output / "finalization_checkpoint.json").exists()
    replay = runner.finalize(qualification_id=qualification_id)
    assert replay["status"] == "blocked_finalized"
    assert replay["manifest_digest"] == resumed["manifest_digest"]


def test_status_is_read_only_and_janitor_finalizes_expired_canary(tmp_path):
    source, auth = _inputs(tmp_path)
    clock = FakeClock()
    runner = _runner(tmp_path, clock=clock)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    clock.advance(24 * 60 * 60 + 1)
    qualification_id = canary["qualification_id"]
    qualification_dir = tmp_path / "qualifications" / qualification_id

    status = runner.status(qualification_id=qualification_id)

    assert status["status"] == "qualification_expired_pending_cleanup"
    assert (qualification_dir / "data").is_dir()
    assert not (qualification_dir / "output" / "terminal_manifest.json").exists()
    janitor = runner.janitor()
    assert janitor["actions"] == [
        {"qualification_id": qualification_id, "status": "expired_finalized"}
    ]
    assert not (qualification_dir / "data").exists()


def test_janitor_retains_unknown_mutation_after_recovery_deadline(tmp_path):
    source, auth = _inputs(tmp_path)
    clock = FakeClock()
    runner = _runner(tmp_path, runtime=UnsafeMutationRuntime(), clock=clock)
    result = runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    clock.advance(60 * 60 + 1)

    janitor = runner.janitor()

    assert janitor["actions"][0]["status"] == "retained_for_manual_recovery"
    qualification_dir = tmp_path / "qualifications" / result["qualification_id"]
    assert (qualification_dir / "data").is_dir()
    assert not (qualification_dir / "output" / "terminal_manifest.json").exists()


def test_janitor_finalizes_stale_pre_mutation_crash_without_resuming_gui(tmp_path):
    source, auth = _inputs(tmp_path)
    clock = FakeClock()
    runner = _runner(tmp_path, runtime=AbruptPreMutationRuntime(), clock=clock)
    with pytest.raises(KeyboardInterrupt, match="simulated_parent_crash"):
        runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    clock.advance(60 * 60 + 1)

    janitor = runner.janitor()

    assert janitor["actions"][0]["status"] == "blocked_finalized"


def test_finalization_failure_retention_expires_and_purges_sensitive_directories(
    tmp_path,
    monkeypatch,
):
    source, auth = _inputs(tmp_path)
    clock = FakeClock()
    runtime = FakeRuntime()
    runtime.fail_attempt_numbers.add(1)
    runtime.failure_reason = "target_mismatch"
    runner = _runner(tmp_path, runtime=runtime, clock=clock)

    def always_fail(*args, **kwargs):
        raise RunnerBlocked("persistent_evidence_failure")

    monkeypatch.setattr(runner_module, "seal_qualification_evidence", always_fail)
    first = runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    assert first["status"] == "finalization_failed"
    qualification_dir = tmp_path / "qualifications" / first["qualification_id"]
    assert (qualification_dir / "data").is_dir()
    clock.advance(24 * 60 * 60)

    janitor = runner.janitor()

    assert janitor["actions"] == [
        {"qualification_id": first["qualification_id"], "status": "retention_expired"}
    ]
    for name in ("data", "work", "vault"):
        assert not (qualification_dir / name).exists()
    checkpoint = json.loads(
        (qualification_dir / "output" / "finalization_checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint["state"] == "retention_expired"


def test_finalization_sensitive_sentinel_blocks_publication_and_immediately_purges(tmp_path):
    source, auth = _inputs(tmp_path)
    sentinel = "HIGH_ENTROPY_FINALIZATION_SENTINEL_95b8d12e"
    storage = JsonStorage(source)
    profile = storage.read_json(Path("user_profile.json"), expected_schema_version=1)
    profile["style_examples"] = [sentinel]
    storage.write_json(Path("user_profile.json"), profile)
    runtime = FakeRuntime()
    runtime.fail_attempt_numbers.add(1)
    runtime.failure_reason = "target_mismatch"
    original_execute = runtime.execute_attempt

    def leak_then_fail(context):
        leak = context.paths.work_dir / "cache" / "debug.log"
        leak.parent.mkdir(parents=True, exist_ok=True)
        leak.write_text(sentinel, encoding="utf-8")
        return original_execute(context)

    runtime.execute_attempt = leak_then_fail
    runner = _runner(tmp_path, runtime=runtime)

    result = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    assert result["status"] == "finalization_failed"
    assert result["reason"] == "sensitive_sentinel_detected"
    assert sentinel not in str(result)
    qualification_dir = tmp_path / "qualifications" / result["qualification_id"]
    for name in ("data", "work", "vault"):
        assert not (qualification_dir / name).exists()
    assert not (qualification_dir / "output" / "terminal_manifest.json").exists()


def test_no_eligible_candidate_is_probe_only_and_blocks_after_three_scans(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runner = _runner(tmp_path, runtime=runtime)
    first_slot = "slot_canary_001_"
    original_probe = runtime.selection_probe

    def inconclusive(context):
        if context["planned_slot_id"].startswith(first_slot):
            runtime.probes.append(context)
            return {"status": "inconclusive", "reason": "no_eligible_empty_composer"}
        return original_probe(context)

    runtime.selection_probe = inconclusive

    result = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    assert result["status"] == "blocked_finalized"
    assert result["reason"] == "insufficient_eligible_targets"
    assert len(runtime.probes) == 3
    assert runtime.attempts == []


def test_soak_requires_exact_accept_token_and_explicit_call(tmp_path):
    source, auth = _inputs(tmp_path)
    runner = _runner(tmp_path)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    with pytest.raises(RunnerBlocked, match="canary_accept_token_mismatch"):
        runner.soak(
            qualification_id=canary["qualification_id"],
            accept_canary="wrong",
            authorization_path=auth,
        )
    status = runner.status(qualification_id=canary["qualification_id"])
    assert status["status"] == "canary_passed"
    assert "soak" in status["next_command"]


def test_soak_runs_fixed_hundred_cycles_over_at_least_eight_hours_and_finalizes(tmp_path):
    source, auth = _inputs(tmp_path)
    clock = FakeClock()
    runtime = FakeRuntime()
    runner = _runner(tmp_path, runtime=runtime, clock=clock)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    result = runner.soak(
        qualification_id=canary["qualification_id"],
        accept_canary=canary["canary_accept_token"],
        authorization_path=auth,
    )

    assert result["status"] == "protocol_passed", result
    assert result["qualification_passed"] is True
    assert result["metrics"]["committed_cycles"] == 100
    assert result["metrics"]["message_list_cycles"] == 80
    assert result["metrics"]["current_thread_cycles"] == 20
    starts = result["metrics"]["actual_start_ns"]
    assert starts[-1] - starts[0] >= 8 * 60 * 60 * 1_000_000_000
    assert all(current - previous >= SOAK_INTERVAL_NS for previous, current in zip(starts, starts[1:]))
    assert validate_production_artifact(Path(result["qualification_bundle_path"]))["qualification_passed"] is True
    assert runner.status(qualification_id=canary["qualification_id"])["status"] == "protocol_passed"
    replay = runner.finalize(qualification_id=canary["qualification_id"])
    assert replay["status"] == "protocol_passed"
    output_files = {
        path.name
        for path in (tmp_path / "qualifications" / canary["qualification_id"] / "output").iterdir()
        if path.is_file()
    }
    assert "qualification_evidence.zip" not in output_files
    assert "finalization_checkpoint.json" not in output_files
    assert "qualification_identity.json" not in output_files
    assert {"qualification_bundle.zip", "qualification_bundle.zip.sha256", "terminal_manifest.json"}.issubset(
        output_files
    )


def test_soak_allows_one_safely_retried_cycle_with_new_attempt_binding(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runtime.fail_attempt_numbers.add(11)
    runner = _runner(tmp_path, runtime=runtime)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    result = runner.soak(
        qualification_id=canary["qualification_id"],
        accept_canary=canary["canary_accept_token"],
        authorization_path=auth,
    )

    assert result["status"] == "protocol_passed", result
    assert result["metrics"]["retried_cycles"] == 1
    assert result["metrics"]["total_attempts"] == 101
    first = runtime.attempts[10]
    second = runtime.attempts[11]
    assert first.binding.attempt_id != second.binding.attempt_id
    assert first.binding.cycle_index == second.binding.cycle_index == 1


def test_soak_defers_current_thread_until_next_message_list_rebuilds_exact_predecessor(tmp_path):
    source, auth = _inputs(tmp_path)
    runtime = FakeRuntime()
    runtime.fail_attempt_numbers.add(14)
    runtime.failure_reason = "target_mismatch"
    runner = _runner(tmp_path, runtime=runtime)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    result = runner.soak(
        qualification_id=canary["qualification_id"],
        accept_canary=canary["canary_accept_token"],
        authorization_path=auth,
    )

    assert result["status"] == "protocol_passed", result
    soak_attempts = runtime.attempts[10:]
    assert [context.slot["planned_index"] for context in soak_attempts[:6]] == [1, 2, 3, 4, 6, 5]
    deferred = soak_attempts[5]
    assert deferred.slot["mode"] == "current-thread"
    assert deferred.predecessor_binding["source_planned_slot_id"] == soak_attempts[4].slot[
        "planned_slot_id"
    ]
    assert result["metrics"]["committed_cycles"] == 100
    assert result["metrics"]["terminal_cycle_successes"] == 99
    assert result["metrics"]["first_attempt_successes"] == 99
    assert result["metrics"]["message_list_cycles"] == 80
    assert result["metrics"]["current_thread_cycles"] == 20


def test_soak_expires_after_24_hours_or_boot_change(tmp_path):
    source, auth = _inputs(tmp_path)
    clock = FakeClock()
    runner = _runner(tmp_path, clock=clock)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)
    clock.advance(24 * 60 * 60 + 1)

    result = runner.soak(
        qualification_id=canary["qualification_id"],
        accept_canary=canary["canary_accept_token"],
        authorization_path=auth,
    )
    assert result["status"] == "expired_finalized"
    assert result["qualification_passed"] is False


def test_root_status_discovers_qualification_without_target_information(tmp_path):
    source, auth = _inputs(tmp_path)
    runner = _runner(tmp_path)
    canary = runner.canary(user_model_source_data_dir=source, authorization_path=auth)

    result = runner.status()

    assert result["status"] == "ok"
    assert result["qualifications"][0]["qualification_id"] == canary["qualification_id"]
    assert "target" not in json.dumps(result).lower()
    assert "chat" not in json.dumps(result).lower()
