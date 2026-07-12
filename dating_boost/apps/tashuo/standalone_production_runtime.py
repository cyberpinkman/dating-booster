from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from dating_boost.apps.tashuo.standalone_production_artifacts import (
    QualificationPaths,
    build_child_environment,
)
from dating_boost.apps.tashuo.standalone_production_attempt import ProductionAttemptProtocol
from dating_boost.apps.tashuo.standalone_production_attempt import (
    abandon_action_request_before_mutation,
    build_composer_plan,
    decide_attempt_recovery,
    record_observed_composer,
    stage_consumed_after_verified_cleanup,
    validate_pre_stage_revalidation,
)
from dating_boost.apps.tashuo.standalone_production_contract import (
    ATTEMPT_TIMEOUT_SECONDS,
    HEARTBEAT_SECONDS,
    MUTATION_PHASE_INDEX,
    SELECTION_PROBE_TIMEOUT_SECONDS,
    REGISTERED_REASONS,
    QualificationBinding,
    canonical_digest,
)
from dating_boost.apps.tashuo.standalone_production_evidence import evaluate_negative_send
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.apps.tashuo.standalone_production_lock import (
    ProductionLockSet,
    WorkerIdentityConflict,
    WorkerProcessRegistry,
)
from dating_boost.core.gui_runtime_lock import GuiRuntimeLock, process_identity
from dating_boost.core.storage import JsonStorage


WORKER_INPUT_PREFIX = "standalone_production/worker_inputs/"
WORKER_RESULT_PREFIX = "standalone_production/worker_results/"
WORKER_HEARTBEAT_POLL_SECONDS = 0.25
WORKER_TERMINATION_GRACE_SECONDS = 3.0
MAX_WORKER_OUTPUT_BYTES = 4 * 1024 * 1024
WORKER_OUTPUT_LIMIT_MARKER = b"__DATING_BOOST_WORKER_OUTPUT_LIMIT_EXCEEDED__"


class ProductionRuntimeError(RuntimeError):
    pass


class ProductionRuntimeBlocked(ProductionRuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class WorkerLauncher(Protocol):
    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]: ...


class TaShuoStandaloneProductionRuntime:
    def __init__(
        self,
        *,
        worker_launcher: WorkerLauncher | None = None,
        runtime_lock_state_root: Path | None = None,
        source_root: Path | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.worker_launcher = worker_launcher or _launch_worker
        self.runtime_lock_state_root = runtime_lock_state_root
        self.source_root = (source_root or Path(__file__).resolve().parents[3]).resolve()
        self.monotonic = monotonic
        self.sleep = sleep
        self._phase: dict[str, Any] | None = None
        self._probe_exclusions: dict[str, set[str]] = {}

    def start_phase(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        paths = context.get("paths")
        if not isinstance(paths, QualificationPaths):
            return _blocked("qualification_paths_invalid")
        if context.get("phase") not in {"canary", "soak"}:
            return _blocked("qualification_phase_invalid")
        if not callable(context.get("lock_renewer")):
            return _blocked("qualification_lock_renewer_missing")
        self._phase = dict(context)
        self._probe_exclusions = {}
        return {"schema_version": 1, "status": "ok"}

    def selection_probe(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        phase = self._required_phase()
        slot_id = str(context.get("planned_slot_id") or "")
        payload = {
            "schema_version": 1,
            "worker_kind": "selection_probe",
            "phase": phase["phase"],
            "slot": dict(context.get("slot") or {}),
            "selection_probe_binding": dict(context.get("selection_probe_binding") or {}),
            "lock_capability": dict(context.get("lock_capability") or {}),
            "predecessor_binding": (
                dict(context["predecessor_binding"])
                if isinstance(context.get("predecessor_binding"), Mapping)
                else None
            ),
            "excluded_target_hashes": sorted(self._probe_exclusions.setdefault(slot_id, set())),
            "authorization_record_id": phase["authorization_record_id"],
        }
        result = self._run_worker(
            worker_kind="selection_probe",
            context_id=str(context.get("probe_id") or ""),
            payload=payload,
            timeout_seconds=SELECTION_PROBE_TIMEOUT_SECONDS,
            lock_capability=dict(context.get("lock_capability") or {}),
        )
        if result.get("worker_status") == "timeout":
            return {"status": "failed", "reason": "vision_timeout"}
        excluded = result.get("excluded_target_hash")
        if isinstance(excluded, str) and excluded:
            self._probe_exclusions[slot_id].add(excluded)
        return result

    def execute_attempt(self, context: Any) -> Mapping[str, Any]:
        phase = self._required_phase()
        binding = context.binding
        payload = {
            "schema_version": 1,
            "worker_kind": "attempt",
            "phase": phase["phase"],
            "qualification_binding": binding.to_dict(),
            "slot": dict(context.slot),
            "target": dict(context.target),
            "precondition_digest": context.precondition_digest,
            "attempt_number": context.attempt_number,
            "lock_capability": dict(context.lock_capability),
            "support_session_id": context.support_session_id,
            "authorization_record_id": context.authorization_record_id,
            "predecessor_binding": (
                dict(context.predecessor_binding) if context.predecessor_binding is not None else None
            ),
        }
        result = self._run_worker(
            worker_kind="attempt",
            context_id=binding.attempt_id,
            payload=payload,
            timeout_seconds=ATTEMPT_TIMEOUT_SECONDS,
            lock_capability=context.lock_capability,
        )
        if result.get("worker_status") != "timeout" and result.get("status"):
            return result
        return self._run_recovery_worker(context, prior_result=result)

    def recover_attempt(self, context: Any) -> Mapping[str, Any]:
        return self._run_recovery_worker(context, prior_result={"worker_status": "resume_recovery"})

    def end_phase(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        phase = self._required_phase()
        paths = phase["paths"]
        from dating_boost.core.managed_session import ManagedSessionRepository
        from dating_boost.core.standalone_session import StandaloneSessionRepository

        try:
            StandaloneSessionRepository(paths.data_dir).stop(reason="qualification_phase_complete")
        except Exception:
            pass
        try:
            ManagedSessionRepository(paths.data_dir).stop(reason="qualification_phase_complete")
        except Exception:
            pass
        ledger = ProductionQualificationLedger(paths.data_dir)
        workers = ledger.list_records("standalone_production/workers/")
        orphan_count = sum(
            1
            for item in workers
            if (item.get("payload") or {}).get("status") in {"registered_waiting_barrier", "running"}
        )
        if orphan_count == 0:
            _clear_directory_contents(paths.work_dir)
        self._phase = None
        return {"schema_version": 1, "status": "ok" if orphan_count == 0 else "blocked", "orphan_count": orphan_count}

    def _run_recovery_worker(self, context: Any, *, prior_result: Mapping[str, Any]) -> Mapping[str, Any]:
        recovery_id = f"recovery_{context.binding.attempt_id}_{uuid4().hex[:10]}"
        payload = {
            "schema_version": 1,
            "worker_kind": "recovery",
            "qualification_binding": context.binding.to_dict(),
            "target": dict(context.target),
            "lock_capability": dict(context.lock_capability),
            "support_session_id": context.support_session_id,
            "authorization_record_id": context.authorization_record_id,
            "prior_worker_status": prior_result.get("worker_status"),
        }
        result = self._run_worker(
            worker_kind="recovery",
            context_id=recovery_id,
            payload=payload,
            timeout_seconds=ATTEMPT_TIMEOUT_SECONDS,
            lock_capability=context.lock_capability,
        )
        if result.get("status"):
            return result
        return {
            "status": "failed",
            "reason": "worker_timeout_after_mutation",
            "mutation_phase": "stage_mutation_intent",
            "safe_recovery_complete": False,
            "terminal_evidence_digest": canonical_digest({"recovery_id": recovery_id, "status": result}),
            "receipt": {"worker_nonce": result.get("worker_nonce"), "recovery": "incomplete"},
            "stage_result_payload": None,
            "terminal_persisted": False,
            "safety_violations": 1,
        }

    def _run_worker(
        self,
        *,
        worker_kind: str,
        context_id: str,
        payload: Mapping[str, Any],
        timeout_seconds: int,
        lock_capability: Mapping[str, Any],
    ) -> dict[str, Any]:
        phase = self._required_phase()
        paths: QualificationPaths = phase["paths"]
        if not context_id:
            raise ProductionRuntimeBlocked("worker_context_id_invalid")
        ledger = ProductionQualificationLedger(paths.data_dir)
        result_path = f"{WORKER_RESULT_PREFIX}{context_id}.json"
        worker_nonce = uuid4().hex
        input_payload = {
            **dict(payload),
            "context_id": context_id,
            "worker_nonce": worker_nonce,
            "qualification_paths": _paths_payload(paths),
            "result_path": result_path,
            "runtime_lock_state_root": str(self.runtime_lock_state_root) if self.runtime_lock_state_root else None,
        }
        ledger.insert_if_absent(f"{WORKER_INPUT_PREFIX}{context_id}.json", input_payload)
        environment = self._child_environment(paths, lock_capability=lock_capability, worker_nonce=worker_nonce)
        read_fd, write_fd = os.pipe()
        os.set_inheritable(read_fd, True)
        os.set_inheritable(write_fd, False)
        command = [
            sys.executable,
            "-m",
            "dating_boost.apps.tashuo.standalone_production_worker",
            worker_kind,
            "--data-dir",
            str(paths.data_dir),
            "--context-id",
            context_id,
            "--barrier-fd",
            str(read_fd),
        ]
        process: subprocess.Popen[bytes] | None = None
        io_dir = paths.work_dir / "worker-io"
        io_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stdout_file = tempfile.TemporaryFile(dir=io_dir)
        stderr_file = tempfile.TemporaryFile(dir=io_dir)
        try:
            process = self.worker_launcher(
                command,
                cwd=self.source_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                close_fds=True,
                pass_fds=(read_fd,),
            )
            os.close(read_fd)
            read_fd = -1
            identity = _wait_for_process_identity(process.pid)
            if identity is None:
                raise WorkerIdentityConflict("worker_identity_unavailable")
            pgid = os.getpgid(process.pid)
            WorkerProcessRegistry(ledger).register(
                context_id=context_id,
                worker_kind=worker_kind,
                pid=process.pid,
                pgid=pgid,
                worker_nonce=worker_nonce,
                identity=identity,
            )
            os.write(write_fd, b"1")
            os.close(write_fd)
            write_fd = -1
            outcome = self._wait_for_worker(
                process=process,
                ledger=ledger,
                context_id=context_id,
                worker_nonce=worker_nonce,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, WorkerIdentityConflict, subprocess.SubprocessError):
            if process is not None:
                self._terminate_worker(ledger, context_id=context_id, process=process)
            stdout_file.close()
            stderr_file.close()
            return {"worker_status": "launch_failed", "worker_nonce": worker_nonce}
        finally:
            if read_fd >= 0:
                os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)
        stdout_bytes = _read_bounded_worker_output(stdout_file)
        stderr_bytes = _read_bounded_worker_output(stderr_file)
        stdout_file.close()
        stderr_file.close()
        if _sensitive_worker_output_detected(
            stdout_bytes + stderr_bytes,
            environment=environment,
        ):
            return {
                "worker_status": "sensitive_output_detected",
                "worker_nonce": worker_nonce,
                "output_digest": hashlib.sha256(stdout_bytes + stderr_bytes).hexdigest(),
            }
        if outcome.get("worker_status") == "timeout":
            return {**outcome, "worker_nonce": worker_nonce}
        try:
            result = ledger.read_record(result_path)
        except FileNotFoundError:
            return {"worker_status": "result_missing", "worker_nonce": worker_nonce}
        return {**result, "worker_status": "completed", "worker_nonce": worker_nonce}

    def _wait_for_worker(
        self,
        *,
        process: subprocess.Popen[bytes],
        ledger: ProductionQualificationLedger,
        context_id: str,
        worker_nonce: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        deadline = self.monotonic() + timeout_seconds
        next_heartbeat = self.monotonic() + HEARTBEAT_SECONDS
        while process.poll() is None:
            now = self.monotonic()
            if now >= deadline:
                self._terminate_worker(ledger, context_id=context_id, process=process)
                return {"worker_status": "timeout"}
            if now >= next_heartbeat:
                renewer = self._required_phase()["lock_renewer"]
                renewed = renewer()
                if renewed.get("qualification_id") != self._required_phase()["paths"].qualification_id:
                    self._terminate_worker(ledger, context_id=context_id, process=process)
                    return {"worker_status": "heartbeat_failed"}
                next_heartbeat = now + HEARTBEAT_SECONDS
            self.sleep(min(WORKER_HEARTBEAT_POLL_SECONDS, max(0.0, deadline - now)))
        process.communicate()
        try:
            WorkerProcessRegistry(ledger).mark_terminal(
                context_id=context_id,
                worker_nonce=worker_nonce,
                exit_code=int(process.returncode or 0),
            )
        except (FileNotFoundError, WorkerIdentityConflict):
            return {"worker_status": "registry_terminal_failed", "exit_code": process.returncode}
        return {"worker_status": "exited", "exit_code": process.returncode}

    def _terminate_worker(
        self,
        ledger: ProductionQualificationLedger,
        *,
        context_id: str,
        process: subprocess.Popen[bytes],
    ) -> None:
        registry = WorkerProcessRegistry(ledger)
        verification = registry.verify_live_identity(context_id)
        if verification.get("status") == "blocked":
            GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(reason="worker_identity_mismatch")
            return
        if verification.get("status") == "ok":
            registry.signal_verified_group(context_id, sig=signal.SIGTERM)
        try:
            process.wait(timeout=WORKER_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            verification = registry.verify_live_identity(context_id)
            if verification.get("status") != "ok":
                GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(reason="worker_identity_mismatch")
                return
            registry.signal_verified_group(context_id, sig=signal.SIGKILL)
            try:
                process.wait(timeout=WORKER_TERMINATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(reason="worker_termination_unverified")
        if process.poll() is not None:
            try:
                record = registry.read(context_id)
                registry.mark_terminal(
                    context_id=context_id,
                    worker_nonce=str(record.get("worker_nonce") or ""),
                    exit_code=int(process.returncode or 0),
                )
            except (FileNotFoundError, WorkerIdentityConflict):
                GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(
                    reason="worker_identity_mismatch"
                )

    def _child_environment(
        self,
        paths: QualificationPaths,
        *,
        lock_capability: Mapping[str, Any],
        worker_nonce: str,
    ) -> dict[str, str]:
        qualification = ProductionQualificationLedger(paths.data_dir).read_record(
            f"standalone_production/qualifications/{paths.qualification_id}.json"
        )
        environment_fingerprint = qualification.get("environment_fingerprint")
        model = environment_fingerprint.get("model") if isinstance(environment_fingerprint, Mapping) else {}
        credential_name = str((model or {}).get("api_key_env") or "MINIMAX_API_KEY")
        environment = build_child_environment(paths, credential_env_names=[credential_name])
        if os.environ.get("DATING_BOOST_TEST_KEY"):
            environment["DATING_BOOST_TEST_KEY"] = os.environ["DATING_BOOST_TEST_KEY"]
        runtime_capability = lock_capability.get("runtime_capability")
        environment["DATING_BOOST_GUI_RUNTIME_CAPABILITY"] = json.dumps(
            runtime_capability if isinstance(runtime_capability, Mapping) else {},
            sort_keys=True,
            separators=(",", ":"),
        )
        environment["DATING_BOOST_DUAL_LOCK_CAPABILITY"] = json.dumps(
            dict(lock_capability),
            sort_keys=True,
            separators=(",", ":"),
        )
        environment["DATING_BOOST_WORKER_NONCE"] = worker_nonce
        if self.runtime_lock_state_root is not None:
            environment["DATING_BOOST_RUNTIME_LOCK_ROOT"] = str(self.runtime_lock_state_root)
        return environment

    def _required_phase(self) -> dict[str, Any]:
        if self._phase is None:
            raise ProductionRuntimeBlocked("qualification_phase_not_started")
        return self._phase


class ProductionGuiPort(Protocol):
    def bind_target(self, target: Mapping[str, Any], *, slot: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def capture_state(self, target: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def guarded_set_if_empty(self, text: str) -> Mapping[str, Any]: ...

    def read_composer(self) -> Mapping[str, Any]: ...

    def guarded_clear_if_exact(self, text: str) -> Mapping[str, Any]: ...

    def input_sentinel_snapshot(self) -> Mapping[str, Any]: ...

    def input_sentinel_status(self, baseline: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def pause_runtime(self, reason: str) -> Mapping[str, Any]: ...


class ProductionWorkItemPort(Protocol):
    def prepare(
        self,
        *,
        binding: QualificationBinding,
        target: Mapping[str, Any],
        slot: Mapping[str, Any],
        authorization_record_id: str,
    ) -> Mapping[str, Any]: ...

    def record_stage(
        self,
        work_item: Mapping[str, Any],
        *,
        result_status: str,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


class ProductionAttemptEngine:
    def __init__(
        self,
        *,
        paths: QualificationPaths,
        binding: QualificationBinding,
        capability: Mapping[str, Any],
        gui: ProductionGuiPort,
        work_items: ProductionWorkItemPort,
        worker_nonce: str,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        mutation_guard: Callable[[], Mapping[str, Any]] | None = None,
        recovery: bool = False,
    ):
        self.paths = paths
        self.binding = binding
        self.capability = dict(capability)
        self.gui = gui
        self.work_items = work_items
        self.worker_nonce = worker_nonce
        self.monotonic_ns = monotonic_ns
        self._mutation_guard = mutation_guard
        self.recovery_mode = recovery
        self.ledger = ProductionQualificationLedger(paths.data_dir)
        self.protocol = ProductionAttemptProtocol(
            self.ledger,
            binding,
            mutation_guard=self._guard,
            monotonic_ns=monotonic_ns,
            guard_fencing_tokens=(
                (
                    int(capability.get("local_fencing_token") or 0),
                    int(capability.get("runtime_fencing_token") or 0),
                )
                if recovery
                else None
            ),
        )

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        target = dict(payload.get("target") or {})
        slot = dict(payload.get("slot") or {})
        work_item: dict[str, Any] | None = None
        baseline: dict[str, Any] | None = None
        observed: dict[str, Any] | None = None
        plan: dict[str, Any] | None = None
        commands: list[dict[str, Any]] = []
        try:
            self._advance("surface_navigation_started", {"slot": slot.get("planned_slot_id")})
            bound = self._require_ok(self.gui.bind_target(target, slot=slot), "target_mismatch")
            baseline = dict(self._require_ok(self.gui.capture_state(target), "capture_transient"))
            if baseline.get("target_hash") != target.get("target_hash"):
                raise ProductionRuntimeBlocked("target_mismatch")
            self._advance(
                "target_bound",
                {
                    "target_hash": baseline.get("target_hash"),
                    "target_binding_digest": baseline.get("target_binding_digest"),
                    "tail_digest": baseline.get("tail_digest"),
                },
                updates={
                    "target_binding": target.get("probe_target_binding"),
                    "baseline_tail": baseline.get("tail"),
                    "baseline_state_digest": canonical_digest(_state_certificate(baseline)),
                },
            )
            if baseline.get("composer_text") != "":
                raise ProductionRuntimeBlocked("candidate_composer_occupied")
            self._advance("composer_empty_verified", {"composer_empty": True})
            prepared = self.work_items.prepare(
                binding=self.binding,
                target=target,
                slot=slot,
                authorization_record_id=str(payload.get("authorization_record_id") or ""),
            )
            work_item = dict(self._require_ok(prepared, "worker_exception")["work_item"])
            if work_item.get("qualification_binding") != self.binding.to_dict():
                raise ProductionRuntimeBlocked("qualification_binding_mismatch")
            if _stable_target_digest(work_item.get("target_binding")) != _stable_target_digest(
                target.get("probe_target_binding")
            ):
                raise ProductionRuntimeBlocked("target_mismatch")
            composer_text = str(work_item.get("payload_text") or "")
            payload_messages = work_item.get("payload_messages")
            if not isinstance(payload_messages, list):
                payload_messages = [{"text": composer_text}]
            plan = build_composer_plan(payload_messages=payload_messages, composer_text=composer_text)
            refreshed = dict(self._require_ok(self.gui.capture_state(target), "capture_transient"))
            revalidation = validate_pre_stage_revalidation(
                baseline,
                refreshed,
                now_monotonic_ns=self.monotonic_ns(),
            )
            if revalidation.get("status") != "ok":
                raise ProductionRuntimeBlocked(str(revalidation.get("reason") or "precondition_mismatch"))
            self._advance(
                "pre_stage_revalidated",
                revalidation,
                updates={
                    "composer_plan": plan,
                    "action_request_id": work_item.get("action_request_id"),
                    "pre_stage_state_digest": canonical_digest(_state_certificate(refreshed)),
                },
            )
            self._guard()
            sentinel_baseline = self._require_ok(
                self.gui.input_sentinel_snapshot(),
                "user_or_external_interference_detected",
            )
            sentinel_counts = sentinel_baseline.get("counts")
            if not isinstance(sentinel_counts, Mapping):
                raise ProductionRuntimeBlocked("user_or_external_interference_detected")
            self._advance(
                "stage_mutation_intent",
                {"planned_composer_text_hash": plan["planned_composer_text_hash"]},
                updates={
                    "input_sentinel_baseline": dict(sentinel_counts),
                    "input_sentinel_coverage_started": True,
                },
            )
            commands.append({"intent": "guarded_ax_set_if_empty"})
            self._guard()
            self._require_ok(
                self.gui.guarded_set_if_empty(plan["planned_composer_text"]),
                "composer_state_unknown",
            )
            sentinel_after_mutation = self._require_zero_input_events(sentinel_counts)
            self._advance(
                "stage_mutation_completed",
                {"input_backend": "guarded_macos_accessibility"},
                updates={
                    "input_sentinel_coverage_complete": True,
                    "input_sentinel_after_mutation": sentinel_after_mutation,
                },
            )
            composer = self._require_ok(self.gui.read_composer(), "composer_state_unknown")
            observed = record_observed_composer(plan, str(composer.get("value") or ""))
            self._advance(
                "staged_verified",
                observed,
                updates={"observed_composer": observed},
            )
            self._advance("cleanup_started", {"target_hash": target["target_hash"]})
            cleanup_revalidation = dict(
                self._require_ok(self.gui.capture_state(target), "cleanup_state_unknown")
            )
            if (
                cleanup_revalidation.get("target_hash") != target.get("target_hash")
                or cleanup_revalidation.get("target_binding_digest")
                != target.get("target_binding_digest")
                or cleanup_revalidation.get("composer_text")
                != observed["exact_observed_composer_text"]
                or int(cleanup_revalidation.get("user_event_count") or 0) != 0
            ):
                raise ProductionRuntimeBlocked("user_or_external_interference_detected")
            self._require_zero_input_events(sentinel_counts)
            commands.append({"intent": "guarded_ax_clear_if_exact"})
            self._guard()
            self._require_ok(
                self.gui.guarded_clear_if_exact(observed["exact_observed_composer_text"]),
                "cleanup_state_unknown",
            )
            cleared = self._require_ok(self.gui.read_composer(), "cleanup_state_unknown")
            if cleared.get("value") != "":
                raise ProductionRuntimeBlocked("cleanup_state_unknown")
            cleanup = {
                "status": "verified",
                "composer_empty": True,
                "target_hash": target["target_hash"],
            }
            self._advance(
                "cleanup_verified",
                cleanup,
                updates={
                    "cleanup_verification": cleanup,
                    "cleanup_revalidation_digest": canonical_digest(
                        _state_certificate(cleanup_revalidation)
                    ),
                },
            )
            post = dict(self._require_ok(self.gui.capture_state(target), "negative_send_unverified"))
            negative = evaluate_negative_send(
                pre_tail=baseline["tail"],
                post_tail=post["tail"],
                observed_composer_text_hash=observed["normalized_observed_composer_text_hash"],
                command_audit=commands,
                send_mode="stage",
                managed_gui_send=False,
                live_send_executed=False,
            )
            if negative.get("status") != "verified":
                raise ProductionRuntimeBlocked("negative_send_unverified")
            self._advance(
                "negative_send_verified",
                negative,
                updates={"negative_send_verification": negative},
            )
            stage_evidence = _stage_evidence(
                target_hash=str(target["target_hash"]),
                observed=observed,
                result_status="succeeded",
            )
            stage_record = self.work_items.record_stage(
                work_item,
                result_status="succeeded",
                evidence=stage_evidence,
            )
            if stage_record.get("status") not in {"ok", "stage_recorded"}:
                raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
            predecessor = {
                "target_hash": target["target_hash"],
                "target_binding_digest": target["target_binding_digest"],
                "candidate_key": target.get("candidate_key"),
                "target_binding": target.get("probe_target_binding"),
            }
            stage_consumed_after_verified_cleanup(
                self.paths.data_dir,
                binding=self.binding,
                action_request_id=str(work_item["action_request_id"]),
                cleanup_verification=cleanup,
                negative_send_verification=negative,
                predecessor_binding=predecessor,
            )
            self._advance(
                "stage_consumed",
                {"action_request_id": work_item["action_request_id"]},
                updates={"predecessor_binding": predecessor},
            )
            terminal_digest = canonical_digest(
                {
                    "cleanup": cleanup,
                    "negative_send": negative,
                    "stage_record": stage_record,
                }
            )
            self._advance(
                "attempt_terminal_committed",
                {"terminal_evidence_digest": terminal_digest},
                updates={"terminal_evidence_digest": terminal_digest},
            )
            receipt = _attempt_receipt(
                worker_nonce=self.worker_nonce,
                status="succeeded",
                cleanup=cleanup,
                negative=negative,
                provider_identity=prepared.get("provider_identity"),
            )
            self.protocol.record_terminal(
                status="succeeded",
                reason_code=None,
                terminal_evidence_digest=terminal_digest,
                receipt=receipt,
            )
            evidence_certificate = {
                "attempt_id": self.binding.attempt_id,
                "target_hash": target["target_hash"],
                "baseline_tail_digest": baseline["tail"]["certificate_digest"],
                "post_tail_digest": post["tail"]["certificate_digest"],
                "negative_send_digest": canonical_digest(negative),
                "cleanup_digest": canonical_digest(cleanup),
                "command_audit_digest": canonical_digest(commands),
            }
            return {
                "schema_version": 1,
                "status": "succeeded",
                "reason": None,
                "mutation_phase": "attempt_terminal_committed",
                "safe_recovery_complete": True,
                "terminal_evidence_digest": terminal_digest,
                "receipt": receipt,
                "stage_result_payload": None,
                "negative_send_verification": negative,
                "cleanup_verification": cleanup,
                "predecessor_binding": predecessor,
                "evidence_certificate": evidence_certificate,
                "terminal_persisted": True,
                "safety_violations": 0,
            }
        except ProductionRuntimeBlocked as exc:
            return self._record_failure(
                reason=exc.reason,
                target=target,
                work_item=work_item,
                baseline=baseline,
                observed=observed,
                commands=commands,
            )
        except Exception:
            return self._record_failure(
                reason="worker_exception",
                target=target,
                work_item=work_item,
                baseline=baseline,
                observed=observed,
                commands=commands,
            )
        finally:
            self.work_items.close()

    def recover(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        target = dict(payload.get("target") or {})
        attempt = self.ledger.read_record(f"standalone_production/attempts/{self.binding.attempt_id}.json")
        mutation_phase = str(attempt.get("mutation_phase") or "not_started")
        try:
            self._require_ok(self.gui.bind_target(target, slot={"mode": "recovery"}), "target_mismatch")
            state = dict(self._require_ok(self.gui.capture_state(target), "composer_state_unknown"))
            exact = ((attempt.get("observed_composer") or {}).get("exact_observed_composer_text"))
            composer = state.get("composer_text")
            composer_state = "empty" if composer == "" else "exact" if isinstance(exact, str) and composer == exact else "other"
            sentinel_baseline = attempt.get("input_sentinel_baseline")
            sentinel_status = (
                dict(self.gui.input_sentinel_status(sentinel_baseline))
                if isinstance(sentinel_baseline, Mapping)
                else _blocked("input_sentinel_coverage_incomplete")
            )
            sentinel_coverage_complete = (
                attempt.get("input_sentinel_coverage_complete") is True
                and sentinel_status.get("status") == "ok"
                and int(sentinel_status.get("user_event_count") or 0) == 0
            )
            target_matches = (
                state.get("target_hash") == target.get("target_hash")
                and state.get("target_binding_digest") == target.get("target_binding_digest")
            )
            decision = decide_attempt_recovery(
                mutation_phase=mutation_phase,
                composer_state=composer_state,
                target_matches=target_matches,
                stage_mutation_completed=MUTATION_PHASE_INDEX.get(mutation_phase, -1)
                >= MUTATION_PHASE_INDEX["stage_mutation_completed"],
                input_sentinel_coverage_complete=sentinel_coverage_complete,
                user_event_count=int(state.get("user_event_count") or 0),
            )
            if decision["action"] == "block_and_pause":
                self.gui.pause_runtime("composer_state_unknown")
                return self._recovery_terminal(
                    reason="composer_state_unknown",
                    mutation_phase=mutation_phase,
                    safe=False,
                )
            if decision["action"] == "abandon_before_mutation":
                if self._attempt_stage_results(attempt):
                    raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
                work_item = self._recovery_work_item(attempt)
                if work_item is not None:
                    abandon_action_request_before_mutation(
                        self.paths.data_dir,
                        binding=self.binding,
                        action_request_id=str(work_item["action_request_id"]),
                    )
                return self._recovery_terminal(
                    reason="worker_timeout_before_mutation",
                    mutation_phase=mutation_phase,
                    safe=True,
                )
            commands: list[dict[str, Any]] = []
            current_phase = mutation_phase
            if current_phase == "staged_verified":
                self._advance("cleanup_started", {"recovery": True, "target_hash": target["target_hash"]})
                current_phase = "cleanup_started"
            if decision["action"] == "clear_exact_then_observe_negative_send":
                if not sentinel_coverage_complete or int(state.get("user_event_count") or 0) != 0:
                    raise ProductionRuntimeBlocked("user_or_external_interference_detected")
                commands.append({"intent": "guarded_ax_clear_if_exact"})
                self._guard()
                self._require_ok(self.gui.guarded_clear_if_exact(str(exact)), "cleanup_state_unknown")
                state = dict(self._require_ok(self.gui.capture_state(target), "negative_send_unverified"))
            target_matches = (
                state.get("target_hash") == target.get("target_hash")
                and state.get("target_binding_digest") == target.get("target_binding_digest")
            )
            if state.get("composer_text") != "" or not target_matches:
                raise ProductionRuntimeBlocked("cleanup_state_unknown")
            baseline_tail = attempt.get("baseline_tail")
            observed_hash = ((attempt.get("observed_composer") or {}).get("normalized_observed_composer_text_hash"))
            if not isinstance(baseline_tail, Mapping) or not isinstance(observed_hash, str):
                raise ProductionRuntimeBlocked("negative_send_unverified")
            negative = evaluate_negative_send(
                pre_tail=baseline_tail,
                post_tail=state["tail"],
                observed_composer_text_hash=observed_hash,
                command_audit=commands,
                send_mode="stage",
                managed_gui_send=False,
                live_send_executed=False,
            )
            if negative.get("status") != "verified":
                raise ProductionRuntimeBlocked("negative_send_unverified")
            cleanup = {
                "status": "verified",
                "composer_empty": True,
                "target_hash": target["target_hash"],
            }
            if current_phase == "cleanup_started":
                self._advance(
                    "cleanup_verified",
                    cleanup,
                    updates={"cleanup_verification": cleanup},
                )
                current_phase = "cleanup_verified"
            if current_phase == "cleanup_verified":
                self._advance(
                    "negative_send_verified",
                    negative,
                    updates={"negative_send_verification": negative},
                )
                current_phase = "negative_send_verified"
            if MUTATION_PHASE_INDEX[current_phase] < MUTATION_PHASE_INDEX["negative_send_verified"]:
                raise ProductionRuntimeBlocked("negative_send_unverified")

            stage_results = self._attempt_stage_results(attempt)
            work_item = self._recovery_work_item(attempt)
            if not stage_results:
                if work_item is None:
                    raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
                self.work_items.record_stage(
                    work_item,
                    result_status="failed",
                    evidence=_stage_evidence(
                        target_hash=str(target["target_hash"]),
                        observed=attempt.get("observed_composer"),
                        result_status="failed",
                    ),
                )
                stage_results = self._attempt_stage_results(attempt)
            if len(stage_results) != 1:
                raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
            stage_result = stage_results[0]
            if stage_result.get("result_status") == "succeeded":
                predecessor = dict(attempt.get("predecessor_binding") or _predecessor_from_target(target))
                if current_phase == "negative_send_verified":
                    if work_item is None:
                        raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
                    stage_consumed_after_verified_cleanup(
                        self.paths.data_dir,
                        binding=self.binding,
                        action_request_id=str(work_item["action_request_id"]),
                        cleanup_verification=cleanup,
                        negative_send_verification=negative,
                        predecessor_binding=predecessor,
                    )
                    self._advance(
                        "stage_consumed",
                        {"recovery": True, "action_request_id": work_item["action_request_id"]},
                        updates={"predecessor_binding": predecessor},
                    )
                    current_phase = "stage_consumed"
                if current_phase == "stage_consumed":
                    terminal_digest = canonical_digest(
                        {"cleanup": cleanup, "negative_send": negative, "stage_result": stage_result}
                    )
                    self._advance(
                        "attempt_terminal_committed",
                        {"terminal_evidence_digest": terminal_digest, "recovery": True},
                        updates={"terminal_evidence_digest": terminal_digest},
                    )
                    current_phase = "attempt_terminal_committed"
                if current_phase != "attempt_terminal_committed":
                    raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
                evidence_certificate = _attempt_evidence_certificate(
                    attempt_id=self.binding.attempt_id,
                    target=target,
                    baseline_tail=baseline_tail,
                    post_tail=state["tail"],
                    negative=negative,
                    cleanup=cleanup,
                    commands=commands,
                )
                return self._recovery_terminal(
                    reason=None,
                    mutation_phase=current_phase,
                    safe=True,
                    status="succeeded",
                    cleanup=cleanup,
                    negative=negative,
                    predecessor=predecessor,
                    evidence_certificate=evidence_certificate,
                )
            if stage_result.get("result_status") != "failed":
                raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
            return self._recovery_terminal(
                reason="worker_timeout_after_mutation",
                mutation_phase=current_phase,
                safe=True,
                cleanup=cleanup,
                negative=negative,
            )
        except ProductionRuntimeBlocked as exc:
            self.gui.pause_runtime(exc.reason)
            return self._recovery_terminal(
                reason=exc.reason,
                mutation_phase=mutation_phase,
                safe=False,
            )
        except Exception:
            self.gui.pause_runtime("composer_state_unknown")
            return self._recovery_terminal(
                reason="composer_state_unknown",
                mutation_phase=mutation_phase,
                safe=False,
            )
        finally:
            self.work_items.close()

    def _attempt_stage_results(self, attempt: Mapping[str, Any]) -> list[dict[str, Any]]:
        action_request_id = str(attempt.get("action_request_id") or "")
        expected_binding = self.binding.to_dict()
        related: list[dict[str, Any]] = []
        for event in JsonStorage(self.paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl")):
            raw_binding = event.get("qualification_binding")
            bound_attempt_id = raw_binding.get("attempt_id") if isinstance(raw_binding, Mapping) else None
            if (
                (action_request_id and event.get("action_request_id") == action_request_id)
                or bound_attempt_id == self.binding.attempt_id
            ):
                if raw_binding != expected_binding:
                    raise ProductionRuntimeBlocked("qualification_binding_mismatch")
                related.append(dict(event))
        if len(related) > 1:
            raise ProductionRuntimeBlocked("stage_result_cardinality_invalid")
        return related

    def _recovery_work_item(self, attempt: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            work_item = JsonStorage(self.paths.data_dir).read_json(
                Path("operator/current_work_item.json"),
                expected_schema_version=1,
            )
        except FileNotFoundError:
            return None
        if (
            work_item.get("work_item_type") != "send_message"
            or work_item.get("action_request_id") != attempt.get("action_request_id")
            or work_item.get("qualification_binding") != self.binding.to_dict()
        ):
            raise ProductionRuntimeBlocked("qualification_binding_mismatch")
        return dict(work_item)

    def _record_failure(
        self,
        *,
        reason: str,
        target: Mapping[str, Any],
        work_item: Mapping[str, Any] | None,
        baseline: Mapping[str, Any] | None,
        observed: Mapping[str, Any] | None,
        commands: list[dict[str, Any]],
    ) -> dict[str, Any]:
        attempt = self.ledger.read_record(f"standalone_production/attempts/{self.binding.attempt_id}.json")
        mutation_phase = str(attempt.get("mutation_phase") or "not_started")
        mutation_started = MUTATION_PHASE_INDEX.get(mutation_phase, 999) >= MUTATION_PHASE_INDEX["stage_mutation_intent"]
        safe_recovery = not mutation_started
        cleanup: dict[str, Any] | None = None
        negative: dict[str, Any] | None = None
        if mutation_started and observed is not None and baseline is not None:
            try:
                sentinel_baseline = attempt.get("input_sentinel_baseline")
                if not isinstance(sentinel_baseline, Mapping):
                    raise ProductionRuntimeBlocked("user_or_external_interference_detected")
                self._require_zero_input_events(sentinel_baseline)
                cleanup_state = self._require_ok(
                    self.gui.capture_state(target),
                    "cleanup_state_unknown",
                )
                if (
                    cleanup_state.get("target_hash") != target.get("target_hash")
                    or cleanup_state.get("target_binding_digest")
                    != target.get("target_binding_digest")
                    or cleanup_state.get("composer_text")
                    != observed["exact_observed_composer_text"]
                    or int(cleanup_state.get("user_event_count") or 0) != 0
                ):
                    raise ProductionRuntimeBlocked("user_or_external_interference_detected")
                commands.append({"intent": "guarded_ax_clear_if_exact"})
                self._guard()
                self._require_ok(
                    self.gui.guarded_clear_if_exact(str(observed["exact_observed_composer_text"])),
                    "cleanup_state_unknown",
                )
                cleared = self._require_ok(self.gui.read_composer(), "cleanup_state_unknown")
                if cleared.get("value") != "":
                    raise ProductionRuntimeBlocked("cleanup_state_unknown")
                cleanup = {
                    "status": "verified",
                    "composer_empty": True,
                    "target_hash": target.get("target_hash"),
                }
                post = self._require_ok(self.gui.capture_state(target), "negative_send_unverified")
                negative = evaluate_negative_send(
                    pre_tail=baseline["tail"],
                    post_tail=post["tail"],
                    observed_composer_text_hash=str(observed["normalized_observed_composer_text_hash"]),
                    command_audit=commands,
                    send_mode="stage",
                    managed_gui_send=False,
                    live_send_executed=False,
                )
                safe_recovery = negative.get("status") == "verified"
            except Exception:
                safe_recovery = False
        if mutation_started and work_item is not None:
            try:
                stage_results = self._attempt_stage_results(attempt)
                if not stage_results:
                    self.work_items.record_stage(
                        work_item,
                        result_status="failed",
                        evidence=_stage_evidence(
                            target_hash=str(target.get("target_hash") or ""),
                            observed=observed,
                            result_status="failed",
                        ),
                    )
                    stage_results = self._attempt_stage_results(attempt)
                if len(stage_results) != 1 or stage_results[0].get("result_status") != "failed":
                    safe_recovery = False
            except Exception:
                safe_recovery = False
        elif mutation_started:
            try:
                stage_results = self._attempt_stage_results(attempt)
                if len(stage_results) != 1 or stage_results[0].get("result_status") != "failed":
                    safe_recovery = False
            except Exception:
                safe_recovery = False
        elif not mutation_started and work_item is not None:
            try:
                abandon_action_request_before_mutation(
                    self.paths.data_dir,
                    binding=self.binding,
                    action_request_id=str(work_item.get("action_request_id") or ""),
                )
            except Exception:
                safe_recovery = False
        if mutation_started and not safe_recovery:
            self.gui.pause_runtime("composer_state_unknown")
        normalized_reason = reason if reason in REGISTERED_REASONS else "worker_exception"
        terminal_digest = canonical_digest(
            {
                "attempt_id": self.binding.attempt_id,
                "reason": normalized_reason,
                "mutation_phase": mutation_phase,
                "safe_recovery_complete": safe_recovery,
                "cleanup": cleanup,
                "negative": negative,
            }
        )
        receipt = _attempt_receipt(
            worker_nonce=self.worker_nonce,
            status="failed",
            cleanup=cleanup,
            negative=negative,
            provider_identity=None,
        )
        terminal_persisted = False
        if safe_recovery:
            record_terminal = (
                self.protocol.record_recovery_terminal if self.recovery_mode else self.protocol.record_terminal
            )
            record_terminal(
                status="failed",
                reason_code=normalized_reason,
                terminal_evidence_digest=terminal_digest,
                receipt=receipt,
            )
            terminal_persisted = True
        return {
            "schema_version": 1,
            "status": "failed",
            "reason": normalized_reason,
            "mutation_phase": mutation_phase,
            "safe_recovery_complete": safe_recovery,
            "terminal_evidence_digest": terminal_digest,
            "receipt": receipt,
            "stage_result_payload": None,
            "cleanup_verification": cleanup,
            "negative_send_verification": negative,
            "predecessor_binding": None,
            "evidence_certificate": None,
            "terminal_persisted": terminal_persisted,
            "safety_violations": 0 if safe_recovery else 1,
        }

    def _recovery_terminal(
        self,
        *,
        reason: str | None,
        mutation_phase: str,
        safe: bool,
        status: str = "failed",
        cleanup: Mapping[str, Any] | None = None,
        negative: Mapping[str, Any] | None = None,
        predecessor: Mapping[str, Any] | None = None,
        evidence_certificate: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_reason = None if status == "succeeded" else reason if reason in REGISTERED_REASONS else "worker_exception"
        digest = canonical_digest(
            {
                "attempt_id": self.binding.attempt_id,
                "recovery": True,
                "reason": normalized_reason,
                "mutation_phase": mutation_phase,
                "safe": safe,
                "status": status,
                "cleanup": dict(cleanup) if cleanup is not None else None,
                "negative": dict(negative) if negative is not None else None,
            }
        )
        receipt = _attempt_receipt(
            worker_nonce=self.worker_nonce,
            status=status,
            cleanup=cleanup,
            negative=negative,
            provider_identity=None,
        )
        if not safe:
            return {
                "schema_version": 1,
                "status": "failed",
                "reason": normalized_reason,
                "mutation_phase": mutation_phase,
                "safe_recovery_complete": False,
                "terminal_evidence_digest": digest,
                "receipt": receipt,
                "stage_result_payload": None,
                "cleanup_verification": cleanup,
                "negative_send_verification": negative,
                "predecessor_binding": None,
                "evidence_certificate": None,
                "terminal_persisted": False,
                "safety_violations": 1,
            }
        record_terminal = (
            self.protocol.record_recovery_terminal if self.recovery_mode else self.protocol.record_terminal
        )
        record_terminal(
            status=status,
            reason_code=normalized_reason,
            terminal_evidence_digest=digest,
            receipt={**receipt, "recovery_receipt": True},
        )
        return {
            "schema_version": 1,
            "status": status,
            "reason": normalized_reason,
            "mutation_phase": mutation_phase,
            "safe_recovery_complete": safe,
            "terminal_evidence_digest": digest,
            "receipt": receipt,
            "stage_result_payload": None,
            "cleanup_verification": cleanup,
            "negative_send_verification": negative,
            "predecessor_binding": dict(predecessor) if predecessor is not None else None,
            "evidence_certificate": (
                dict(evidence_certificate) if evidence_certificate is not None else None
            ),
            "terminal_persisted": True,
            "safety_violations": 0,
        }

    def _advance(
        self,
        phase: str,
        evidence: Mapping[str, Any],
        *,
        updates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.protocol.advance(
            phase,
            evidence_digest=canonical_digest(dict(evidence)),
            updates=updates,
        )

    def _require_zero_input_events(self, baseline: Mapping[str, Any]) -> dict[str, Any]:
        status = dict(
            self._require_ok(
                self.gui.input_sentinel_status(baseline),
                "user_or_external_interference_detected",
            )
        )
        if int(status.get("user_event_count") or 0) != 0:
            raise ProductionRuntimeBlocked("user_or_external_interference_detected")
        return status

    def _guard(self) -> Mapping[str, Any]:
        result = (
            self._mutation_guard()
            if self._mutation_guard is not None
            else delegated_mutation_guard(self.paths, self.capability)
        )
        if result.get("status") != "ok":
            raise ProductionRuntimeBlocked(str(result.get("reason") or "fencing_mismatch"))
        return result

    @staticmethod
    def _require_ok(result: Mapping[str, Any], reason: str) -> Mapping[str, Any]:
        if result.get("status") != "ok":
            actual = str(result.get("reason") or reason)
            raise ProductionRuntimeBlocked(actual if actual in REGISTERED_REASONS else reason)
        return result


class TaShuoProductionGui:
    def __init__(
        self,
        *,
        paths: QualificationPaths,
        capability: Mapping[str, Any],
    ):
        from dating_boost.apps.registry import create_adapter
        from dating_boost.apps.tashuo.standalone import TaShuoMacIosStandaloneObservationProvider
        from dating_boost.intelligence.vision_backend_factory import create_vision_backend

        self.paths = paths
        self.capability = dict(capability)
        qualification = ProductionQualificationLedger(paths.data_dir).read_record(
            f"standalone_production/qualifications/{paths.qualification_id}.json"
        )
        self.qualification_salt = str(qualification["qualification_salt"])
        environment = qualification.get("environment_fingerprint") or {}
        model = environment.get("model") if isinstance(environment, Mapping) else {}
        self.expected_model_identity = dict(model or {})
        vision_config = {
            "type": str((model or {}).get("vision_backend") or "minimax"),
            "model": str((model or {}).get("vision_model_identifier") or "MiniMax-M3"),
            "base_url": str((model or {}).get("base_url") or "https://api.minimaxi.com/v1"),
            "api_key_env": str((model or {}).get("api_key_env") or "MINIMAX_API_KEY"),
        }
        self.vision_backend = create_vision_backend(vision_config)
        self.output_dir = paths.work_dir / "gui"
        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.adapter = create_adapter("tashuo", runtime="mac-ios-app")
        self.provider = TaShuoMacIosStandaloneObservationProvider(
            root=paths.data_dir,
            output_dir=self.output_dir,
            vision_backend=self.vision_backend,
            adapter_factory=lambda: self.adapter,
        )
        self._sentinel = MacUserInputSentinel()
        self._sentinel_baseline: dict[int, int] | None = None

    def select_target(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from dating_boost.apps.tashuo.standalone_production_evidence import qualification_target_hash

        slot = payload.get("slot") if isinstance(payload.get("slot"), Mapping) else {}
        mode = str(slot.get("mode") or "")
        excluded = set(str(item) for item in payload.get("excluded_target_hashes") or [])
        if mode == "current-thread":
            predecessor = payload.get("predecessor_binding")
            if not isinstance(predecessor, Mapping):
                return _blocked("current_thread_predecessor_missing")
            target_binding = predecessor.get("target_binding")
            candidate_key = str(predecessor.get("candidate_key") or "")
            if not isinstance(target_binding, Mapping) or not candidate_key:
                return _blocked("current_thread_predecessor_missing")
            self.provider.precheck_payload(app_id="tashuo")
            thread = self.provider.observe_thread(app_id="tashuo", candidate_key=candidate_key)
            if thread.get("status") != "ok":
                return _blocked("exact_target_relocation_transient")
            if not self._provider_identity_valid():
                return _blocked("provider_identity_drift")
            if _stable_target_digest(thread.get("target_binding")) != _stable_target_digest(target_binding):
                return _blocked("target_mismatch")
            target_binding = dict(thread["target_binding"])
            return self._eligible_target(candidate_key, target_binding)
        if mode != "message-list":
            return _blocked("qualification_slot_mode_invalid")
        listing = self.provider.observe_message_list(app_id="tashuo", scan_cursor={})
        if listing.get("status") != "ok":
            return _blocked(str(listing.get("reason") or "prepare_message_page_transient"))
        if not self._provider_identity_valid():
            return _blocked("provider_identity_drift")
        candidates = [item for item in listing.get("candidates") or [] if isinstance(item, Mapping)]
        last_occupied_hash = None
        for index, candidate in enumerate(candidates):
            if index > 0:
                prepared = self.provider.precheck_payload(app_id="tashuo")
                if prepared.get("status") != "ok":
                    break
            candidate_key = str(candidate.get("candidate_key") or "")
            if not candidate_key:
                continue
            thread = self.provider.observe_thread(app_id="tashuo", candidate_key=candidate_key)
            if thread.get("status") != "ok" or not isinstance(thread.get("target_binding"), Mapping):
                continue
            if not self._provider_identity_valid():
                return _blocked("provider_identity_drift")
            target_binding = dict(thread["target_binding"])
            target_hash = qualification_target_hash(self.qualification_salt, _stable_target_binding(target_binding))
            if target_hash in excluded:
                continue
            composer = self.read_composer()
            if composer.get("status") != "ok":
                continue
            if composer.get("value") != "":
                last_occupied_hash = target_hash
                continue
            return self._eligible_target(candidate_key, target_binding)
        result = {"status": "inconclusive", "reason": "no_eligible_empty_composer"}
        if last_occupied_hash is not None:
            result["excluded_target_hash"] = last_occupied_hash
        return result

    def _eligible_target(self, candidate_key: str, target_binding: Mapping[str, Any]) -> dict[str, Any]:
        from dating_boost.apps.tashuo.standalone_production_evidence import qualification_target_hash

        target_hash = qualification_target_hash(self.qualification_salt, _stable_target_binding(target_binding))
        target = {
            "candidate_key": candidate_key,
            "probe_target_binding": dict(target_binding),
            "target_hash": target_hash,
            "target_binding_digest": canonical_digest(_stable_target_binding(target_binding)),
        }
        self._sentinel_baseline = self._sentinel.snapshot()
        state = self.capture_state(target)
        if state.get("status") != "ok":
            return _blocked(str(state.get("reason") or "capture_transient"))
        if state.get("composer_text") != "":
            return {
                "status": "inconclusive",
                "reason": "no_eligible_empty_composer",
                "excluded_target_hash": target_hash,
            }
        precondition_digest = canonical_digest(
            {
                "target_hash": target_hash,
                "target_binding_digest": target["target_binding_digest"],
                "tail_digest": state["tail_digest"],
                "composer_empty": True,
            }
        )
        return {
            "schema_version": 1,
            "status": "eligible",
            **target,
            "precondition_digest": precondition_digest,
            "baseline_tail_digest": state["tail_digest"],
        }

    def bind_target(self, target: Mapping[str, Any], *, slot: Mapping[str, Any]) -> Mapping[str, Any]:
        candidate_key = str(target.get("candidate_key") or "")
        expected = target.get("probe_target_binding")
        if not candidate_key or not isinstance(expected, Mapping):
            return _blocked("target_mismatch")
        cached = self.provider.targets.get(candidate_key)
        current = self.provider.observe_current_thread(
            app_id="tashuo",
            candidate_key=candidate_key,
            cached_target=cached,
        )
        if current.get("status") != "ok" or _stable_target_digest(current.get("target_binding")) != _stable_target_digest(
            expected
        ):
            prepared = self.provider.precheck_payload(app_id="tashuo")
            if prepared.get("status") != "ok":
                return _blocked("exact_target_relocation_transient")
            current = self.provider.observe_thread(app_id="tashuo", candidate_key=candidate_key)
        if current.get("status") != "ok":
            return _blocked("exact_target_relocation_transient")
        if _stable_target_digest(current.get("target_binding")) != _stable_target_digest(expected):
            return _blocked("target_mismatch")
        self._sentinel_baseline = self._sentinel.snapshot()
        return {"schema_version": 1, "status": "ok", "target_hash": target.get("target_hash")}

    def capture_state(self, target: Mapping[str, Any]) -> Mapping[str, Any]:
        from dating_boost.apps.tashuo.perception import analyze_tashuo_conversation_evidence_v2

        observed = self.adapter.observe(output_dir=self.output_dir)
        if observed.get("status") != "ok" or observed.get("screen_state") != "tashuo_conversation":
            return _blocked(str(observed.get("reason") or "target_mismatch"))
        screen = observed.get("screen") if isinstance(observed.get("screen"), Mapping) else {}
        preflight = observed.get("preflight") if isinstance(observed.get("preflight"), Mapping) else {}
        window = preflight.get("window") if isinstance(preflight.get("window"), Mapping) else {}
        captured_ns = time.monotonic_ns()
        capture_id = f"capture_{uuid4().hex}"
        observation_id = f"observation_{uuid4().hex}"
        viewport_identity = canonical_digest(
            {
                "window": dict(window),
                "screen_state": observed.get("screen_state"),
                "screen_path_suffix": Path(str(screen.get("path") or "unknown")).suffix,
            }
        )
        tail = analyze_tashuo_conversation_evidence_v2(
            dict(observed),
            backend=self.vision_backend,
            qualification_salt=self.qualification_salt,
            target_binding=_stable_target_binding(target.get("probe_target_binding")),
            viewport_identity=viewport_identity,
            capture_id=capture_id,
            observation_id=observation_id,
            captured_monotonic_ns=captured_ns,
        )
        if tail.get("status") != "ok":
            return _blocked(str(tail.get("reason") or "capture_transient"))
        if not self._provider_identity_valid():
            return _blocked("provider_identity_drift")
        composer = self.read_composer()
        if composer.get("status") != "ok":
            return composer
        event_count = self._sentinel.delta(self._sentinel_baseline) if self._sentinel_baseline is not None else 0
        return {
            "schema_version": 1,
            "status": "ok",
            "frontmost_app": "tashuo",
            "window_identity": canonical_digest(dict(window)),
            "target_hash": target.get("target_hash"),
            "target_binding_digest": target.get("target_binding_digest"),
            "tail_digest": _tail_content_digest(tail),
            "tail": {key: value for key, value in tail.items() if key != "status"},
            "composer_text": str(composer.get("value") or ""),
            "captured_monotonic_ns": captured_ns,
            "user_event_count": event_count,
        }

    def guarded_set_if_empty(self, text: str) -> Mapping[str, Any]:
        from dating_boost.apps.tashuo.send_input_ax import _guarded_set_tashuo_ax_text_area_if_empty

        return _guarded_set_tashuo_ax_text_area_if_empty(self.adapter.session, text)

    def read_composer(self) -> Mapping[str, Any]:
        from dating_boost.apps.tashuo.send_input_ax import _tashuo_ax_text_area_value

        return _tashuo_ax_text_area_value(self.adapter.session)

    def guarded_clear_if_exact(self, text: str) -> Mapping[str, Any]:
        from dating_boost.apps.tashuo.send_input_ax import _guarded_clear_tashuo_ax_text_area_if_exact

        return _guarded_clear_tashuo_ax_text_area_if_exact(self.adapter.session, text)

    def input_sentinel_snapshot(self) -> Mapping[str, Any]:
        try:
            counts = self._sentinel.snapshot()
        except ProductionRuntimeBlocked as exc:
            return _blocked(exc.reason)
        return {
            "schema_version": 1,
            "status": "ok",
            "counts": {str(event_type): count for event_type, count in counts.items()},
        }

    def input_sentinel_status(self, baseline: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return self._sentinel.status(baseline)
        except ProductionRuntimeBlocked as exc:
            return _blocked(exc.reason)

    def pause_runtime(self, reason: str) -> Mapping[str, Any]:
        state_root = os.environ.get("DATING_BOOST_RUNTIME_LOCK_ROOT")
        return GuiRuntimeLock(state_root=Path(state_root) if state_root else None).pause(reason=reason)

    def harness_factory(self, app_id: str, runtime: str | None = None) -> Any:
        from dating_boost.apps.tashuo.standalone import TaShuoStandalonePrecheckHarness

        return TaShuoStandalonePrecheckHarness(self.provider, app_id=app_id, runtime=runtime)

    def _provider_identity_valid(self) -> bool:
        actual = getattr(self.vision_backend, "last_response_identity", None)
        return _provider_identity_matches(self.expected_model_identity, actual)


class BoundProductionObservationProvider:
    def __init__(self, gui: TaShuoProductionGui, target: Mapping[str, Any]):
        self.gui = gui
        self.target = dict(target)

    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        return _blocked("qualification_bound_provider_requires_current_thread")

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        if candidate_key != self.target.get("candidate_key"):
            return _blocked("target_mismatch")
        return self.observe_current_thread(app_id=app_id)

    def observe_current_thread(self, *, app_id: str) -> dict[str, Any]:
        candidate_key = str(self.target.get("candidate_key") or "")
        cached = self.gui.provider.targets.get(candidate_key)
        result = self.gui.provider.observe_current_thread(
            app_id=app_id,
            candidate_key=candidate_key,
            cached_target=cached,
        )
        if result.get("status") == "ok" and _stable_target_digest(result.get("target_binding")) != _stable_target_digest(
            self.target.get("probe_target_binding")
        ):
            return _blocked("target_mismatch")
        return result


class ExistingStandaloneWorkItems:
    def __init__(self, *, paths: QualificationPaths, gui: TaShuoProductionGui):
        self.paths = paths
        self.gui = gui
        self._active = False

    def prepare(
        self,
        *,
        binding: QualificationBinding,
        target: Mapping[str, Any],
        slot: Mapping[str, Any],
        authorization_record_id: str,
    ) -> Mapping[str, Any]:
        from dating_boost.core.managed_session import ManagedSessionRepository
        from dating_boost.core.standalone_runtime import StandaloneAgentRuntime, StandaloneDraftPlanner
        from dating_boost.core.standalone_session import StandaloneSessionRepository

        ledger = ProductionQualificationLedger(self.paths.data_dir)
        authorization_record = ledger.read_record(
            f"standalone_production/config/{authorization_record_id}.json"
        )
        authorization = authorization_record.get("authorization")
        if not isinstance(authorization, dict):
            return _blocked("authorization_invalid")
        qualification = ledger.read_record(
            f"standalone_production/qualifications/{self.paths.qualification_id}.json"
        )
        environment = qualification.get("environment_fingerprint") or {}
        model = environment.get("model") if isinstance(environment, Mapping) else {}
        backend = {
            "type": str((model or {}).get("backend") or "minimax"),
            "model": str((model or {}).get("model_identifier") or "MiniMax-M3"),
            "base_url": str((model or {}).get("base_url") or "https://api.minimaxi.com/v1"),
            "api_key_env": str((model or {}).get("api_key_env") or "MINIMAX_API_KEY"),
        }
        vision_backend = {
            "type": str((model or {}).get("vision_backend") or "minimax"),
            "model": str((model or {}).get("vision_model_identifier") or "MiniMax-M3"),
            "base_url": backend["base_url"],
            "api_key_env": backend["api_key_env"],
        }
        provider = BoundProductionObservationProvider(self.gui, target)

        def harness_factory(app_id: str, runtime: str | None = None) -> Any:
            from dating_boost.apps.tashuo.standalone import TaShuoStandalonePrecheckHarness

            return TaShuoStandalonePrecheckHarness(self.gui.provider, app_id=app_id, runtime=runtime)

        managed = ManagedSessionRepository(self.paths.data_dir, harness_factory=harness_factory)
        if managed.status().get("status") in {"active", "paused"}:
            managed.stop(reason="qualification_attempt_restart")
        started = managed.start(
            app_id="tashuo",
            authorization=authorization,
            goal=None,
            availability=None,
            send_mode="stage",
            managed_gui_send=False,
            scan_interval_seconds=120,
            harness_runtime="mac-ios-app",
            initial_surface="current-thread",
            qualification_binding=binding.to_dict(),
        )
        if started.get("status") != "active":
            return _blocked(str(started.get("reason") or "worker_exception"))
        standalone = StandaloneSessionRepository(self.paths.data_dir)
        if standalone.status().get("status") == "active":
            standalone.stop(reason="qualification_attempt_restart")
        standalone_started = standalone.start(
            app_id="tashuo",
            runtime="mac-ios-app",
            send_mode="stage",
            observation_source={
                "type": "live_gui",
                "app_id": "tashuo",
                "runtime": "mac-ios-app",
                "output_dir": str(self.paths.work_dir / "gui"),
            },
            backend=backend,
            scan_interval_seconds=120,
            managed_gui_send=False,
            vision_backend=vision_backend,
            initial_surface="current-thread",
            qualification_binding=binding.to_dict(),
        )
        if standalone_started.get("status") != "active":
            return _blocked(str(standalone_started.get("reason") or "worker_exception"))
        self._active = True
        runtime = StandaloneAgentRuntime(
            self.paths.data_dir,
            observation_provider=provider,
            harness_factory=harness_factory,
            action_executor=None,
            draft_planner=StandaloneDraftPlanner(
                self.paths.data_dir,
                backend_config=backend,
                allow_stage_soft_accept=True,
            ),
        )
        for _ in range(12):
            tick = runtime.tick()
            standalone.record_tick(tick)
            if tick.get("status") == "needs_action_executor" and isinstance(tick.get("work_item"), dict):
                provider_identity = tick["work_item"].get("provider_response_identity")
                if not _provider_identity_matches(model or {}, provider_identity):
                    return _blocked("provider_identity_drift")
                return {
                    "schema_version": 1,
                    "status": "ok",
                    "work_item": tick["work_item"],
                    "provider_identity": provider_identity,
                }
            if tick.get("status") in {"blocked", "error", "no_work"}:
                return _blocked(str(tick.get("reason") or "worker_exception"))
        return _blocked("worker_exception")

    def record_stage(
        self,
        work_item: Mapping[str, Any],
        *,
        result_status: str,
        evidence: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        from dating_boost.core.operator import OperatorRepository

        payload = {
            "schema_version": 1,
            "action": "send_message",
            "app_id": "tashuo",
            "action_request_id": work_item.get("action_request_id"),
            "target_match_id": work_item.get("target_match_id") or work_item.get("match_id"),
            "payload_hash": work_item.get("payload_hash"),
            "pre_action_observation_id": work_item.get("pre_action_observation_id"),
            "precondition_hash": work_item.get("precondition_hash"),
            "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
            "qualification_binding": work_item.get("qualification_binding"),
            "result_status": result_status,
            "evidence": {"stage_mode": True, "live_send_executed": False},
            "stage_attempt_status": evidence.get("stage_attempt_status"),
            "staged_text_verified": evidence.get("staged_text_verified"),
            "staged_text_verification": evidence.get("staged_text_verification"),
            "target_verification": evidence.get("target_verification"),
        }
        return OperatorRepository(self.paths.data_dir).record_stage_result(payload)

    def close(self) -> None:
        if not self._active:
            return
        from dating_boost.core.managed_session import ManagedSessionRepository
        from dating_boost.core.standalone_session import StandaloneSessionRepository

        try:
            StandaloneSessionRepository(self.paths.data_dir).stop(reason="qualification_attempt_complete")
        finally:
            ManagedSessionRepository(self.paths.data_dir).stop(reason="qualification_attempt_complete")
            self._active = False


class MacUserInputSentinel:
    EVENT_TYPES = (1, 2, 3, 4, 5, 6, 10, 11, 12, 22)

    def snapshot(self) -> dict[int, int]:
        if sys.platform != "darwin":
            return {event_type: 0 for event_type in self.EVENT_TYPES}
        try:
            import ctypes

            framework = ctypes.CDLL(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            )
            counter = framework.CGEventSourceCounterForEventType
            counter.argtypes = [ctypes.c_int32, ctypes.c_uint32]
            counter.restype = ctypes.c_uint32
            return {event_type: int(counter(0, event_type)) for event_type in self.EVENT_TYPES}
        except (AttributeError, OSError):
            raise ProductionRuntimeBlocked("user_or_external_interference_detected") from None

    def delta(self, baseline: Mapping[int, int] | None) -> int:
        if baseline is None:
            return 0
        current = self.snapshot()
        return sum(
            max(
                0,
                current[event_type]
                - int(baseline.get(event_type, baseline.get(str(event_type), 0))),
            )
            for event_type in self.EVENT_TYPES
        )

    def status(self, baseline: Mapping[str, Any]) -> dict[str, Any]:
        current = self.snapshot()
        delta = sum(
            max(
                0,
                current[event_type]
                - int(baseline.get(str(event_type), baseline.get(event_type, 0))),
            )
            for event_type in self.EVENT_TYPES
        )
        return {
            "schema_version": 1,
            "status": "ok",
            "user_event_count": delta,
            "current_counts": {
                str(event_type): count for event_type, count in current.items()
            },
        }


def run_selection_worker(payload: Mapping[str, Any]) -> dict[str, Any]:
    paths = paths_from_worker_input(payload)
    gui = TaShuoProductionGui(paths=paths, capability=dict(payload.get("lock_capability") or {}))
    return gui.select_target(payload)


def run_attempt_worker(payload: Mapping[str, Any], *, recovery: bool = False) -> dict[str, Any]:
    paths = paths_from_worker_input(payload)
    binding = QualificationBinding.from_dict(payload.get("qualification_binding") or {})
    capability = dict(payload.get("lock_capability") or {})
    gui = TaShuoProductionGui(paths=paths, capability=capability)
    work_items = ExistingStandaloneWorkItems(paths=paths, gui=gui)
    engine = ProductionAttemptEngine(
        paths=paths,
        binding=binding,
        capability=capability,
        gui=gui,
        work_items=work_items,
        worker_nonce=str(payload.get("worker_nonce") or ""),
        recovery=recovery,
    )
    return engine.recover(payload) if recovery else engine.execute(payload)


def delegated_mutation_guard(paths: QualificationPaths, capability: Mapping[str, Any]) -> Mapping[str, Any]:
    state_root = os.environ.get("DATING_BOOST_RUNTIME_LOCK_ROOT")
    runtime_lock = GuiRuntimeLock(state_root=Path(state_root) if state_root else None)
    lock_set = ProductionLockSet(paths, runtime_lock=runtime_lock)
    return lock_set.validate_delegated_capability(capability)


def worker_input(ledger: ProductionQualificationLedger, context_id: str) -> dict[str, Any]:
    return ledger.read_record(f"{WORKER_INPUT_PREFIX}{context_id}.json")


def write_worker_result(
    ledger: ProductionQualificationLedger,
    *,
    context_id: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return ledger.insert_if_absent(f"{WORKER_RESULT_PREFIX}{context_id}.json", dict(result))


def paths_from_worker_input(payload: Mapping[str, Any]) -> QualificationPaths:
    raw = payload.get("qualification_paths")
    if not isinstance(raw, Mapping):
        raise ProductionRuntimeBlocked("qualification_paths_invalid")
    qualification_dir = Path(str(raw.get("qualification_dir") or "")).resolve()
    paths = QualificationPaths(
        qualification_id=str(raw.get("qualification_id") or ""),
        qualification_dir=qualification_dir,
        data_dir=Path(str(raw.get("data_dir") or "")).resolve(),
        work_dir=Path(str(raw.get("work_dir") or "")).resolve(),
        vault_dir=Path(str(raw.get("vault_dir") or "")).resolve(),
        output_dir=Path(str(raw.get("output_dir") or "")).resolve(),
        runner_lock=Path(str(raw.get("runner_lock") or "")).resolve(),
        ownership_digest=str(raw.get("ownership_digest") or ""),
    )
    for child in (paths.data_dir, paths.work_dir, paths.vault_dir, paths.output_dir, paths.runner_lock):
        if not child.is_relative_to(qualification_dir):
            raise ProductionRuntimeBlocked("qualification_paths_escape")
    return paths


def _paths_payload(paths: QualificationPaths) -> dict[str, str]:
    return {
        "qualification_id": paths.qualification_id,
        "qualification_dir": str(paths.qualification_dir),
        "data_dir": str(paths.data_dir),
        "work_dir": str(paths.work_dir),
        "vault_dir": str(paths.vault_dir),
        "output_dir": str(paths.output_dir),
        "runner_lock": str(paths.runner_lock),
        "ownership_digest": paths.ownership_digest,
    }


def _state_certificate(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "frontmost_app": state.get("frontmost_app"),
        "window_identity": state.get("window_identity"),
        "target_hash": state.get("target_hash"),
        "target_binding_digest": state.get("target_binding_digest"),
        "tail_digest": state.get("tail_digest"),
        "composer_text_hash": hashlib.sha256(str(state.get("composer_text") or "").encode("utf-8")).hexdigest(),
        "captured_monotonic_ns": state.get("captured_monotonic_ns"),
        "user_event_count": state.get("user_event_count"),
    }


def _stable_target_digest(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    thread = value.get("thread_evidence") if isinstance(value.get("thread_evidence"), Mapping) else {}
    message_list = value.get("message_list_evidence") if isinstance(value.get("message_list_evidence"), Mapping) else {}
    return canonical_digest(
        {
            "binding_type": value.get("binding_type"),
            "candidate_key": value.get("candidate_key"),
            "thread_visual_anchor_hash": thread.get("visual_anchor_hash"),
            "message_list_visual_anchor_hash": message_list.get("visual_anchor_hash"),
        }
    )


def _stable_target_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionRuntimeBlocked("target_mismatch")
    thread = value.get("thread_evidence") if isinstance(value.get("thread_evidence"), Mapping) else {}
    message_list = value.get("message_list_evidence") if isinstance(value.get("message_list_evidence"), Mapping) else {}
    return {
        "schema_version": 1,
        "binding_type": value.get("binding_type"),
        "candidate_key": value.get("candidate_key"),
        "thread_visual_anchor_hash": thread.get("visual_anchor_hash"),
        "message_list_visual_anchor_hash": message_list.get("visual_anchor_hash"),
    }


def _tail_content_digest(tail: Mapping[str, Any]) -> str:
    bubbles = []
    for bubble in tail.get("bubbles") or []:
        if not isinstance(bubble, Mapping):
            continue
        bubbles.append(
            {
                "direction": bubble.get("direction"),
                "text_hash": bubble.get("text_hash"),
                "bounds": bubble.get("bounds"),
                "anchor": bubble.get("anchor"),
                "order": bubble.get("order"),
                "confidence": bubble.get("confidence"),
            }
        )
    return canonical_digest(
        {
            "target_hash": tail.get("target_hash"),
            "target_binding_digest": tail.get("target_binding_digest"),
            "viewport_identity": tail.get("viewport_identity"),
            "bubbles": bubbles,
        }
    )


def _provider_identity_matches(expected_model: Mapping[str, Any], actual: Any) -> bool:
    if not isinstance(actual, Mapping):
        return False
    if actual.get("response_model_identifier") != expected_model.get("response_model_identifier"):
        return False
    expected_stable = expected_model.get("provider_identifier")
    actual_stable = actual.get("stable_provider_identifier")
    if expected_stable == "revision_unavailable":
        return actual_stable in {None, ""}
    return actual_stable == expected_stable


def _stage_evidence(
    *,
    target_hash: str,
    observed: Mapping[str, Any] | None,
    result_status: str,
) -> dict[str, Any]:
    verified = result_status == "succeeded" and observed is not None
    return {
        "stage_attempt_status": "completed" if verified else "failed",
        "staged_text_verified": verified,
        "staged_text_verification": {
            "status": "verified" if verified else "failed",
            "normalized_observed_composer_text_hash": (
                observed.get("normalized_observed_composer_text_hash") if observed is not None else None
            ),
        },
        "target_verification": {"status": "ok", "target_hash": target_hash},
        "evidence": {"stage_mode": True, "live_send_executed": False},
    }


def _predecessor_from_target(target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "target_hash": target.get("target_hash"),
        "target_binding_digest": target.get("target_binding_digest"),
        "candidate_key": target.get("candidate_key"),
        "target_binding": target.get("probe_target_binding"),
    }


def _attempt_evidence_certificate(
    *,
    attempt_id: str,
    target: Mapping[str, Any],
    baseline_tail: Mapping[str, Any],
    post_tail: Mapping[str, Any],
    negative: Mapping[str, Any],
    cleanup: Mapping[str, Any],
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "target_hash": target.get("target_hash"),
        "baseline_tail_digest": baseline_tail.get("certificate_digest"),
        "post_tail_digest": post_tail.get("certificate_digest"),
        "negative_send_digest": canonical_digest(dict(negative)),
        "cleanup_digest": canonical_digest(dict(cleanup)),
        "command_audit_digest": canonical_digest(commands),
    }


def _attempt_receipt(
    *,
    worker_nonce: str,
    status: str,
    cleanup: Mapping[str, Any] | None,
    negative: Mapping[str, Any] | None,
    provider_identity: Any,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "worker_nonce": worker_nonce,
        "status": status,
        "cleanup_digest": canonical_digest(dict(cleanup)) if cleanup is not None else None,
        "negative_send_digest": canonical_digest(dict(negative)) if negative is not None else None,
        "provider_identity": dict(provider_identity) if isinstance(provider_identity, Mapping) else None,
        "live_send_executed": False,
        "send_mode": "stage",
    }


def _launch_worker(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
    return subprocess.Popen(command, **kwargs)


def _wait_for_process_identity(pid: int) -> dict[str, Any] | None:
    for _ in range(40):
        identity = process_identity(pid)
        if identity is not None:
            return identity
        time.sleep(0.025)
    return None


def _read_bounded_worker_output(handle: Any) -> bytes:
    try:
        handle.flush()
        handle.seek(0)
        content = handle.read(MAX_WORKER_OUTPUT_BYTES + 1)
    except (OSError, ValueError):
        return WORKER_OUTPUT_LIMIT_MARKER
    if len(content) > MAX_WORKER_OUTPUT_BYTES:
        return WORKER_OUTPUT_LIMIT_MARKER
    return bytes(content)


def _sensitive_worker_output_detected(
    output: bytes,
    *,
    environment: Mapping[str, str],
) -> bool:
    if WORKER_OUTPUT_LIMIT_MARKER in output:
        return True
    sensitive_names = {
        name
        for name in environment
        if name == "DATING_BOOST_TEST_KEY"
        or name.endswith("_API_KEY")
        or name.endswith("_TOKEN")
        or name.endswith("_SECRET")
    }
    for name in sensitive_names:
        value = environment.get(name, "")
        if len(value) >= 8 and value.encode("utf-8") in output:
            return True
    return False


def _clear_directory_contents(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}
