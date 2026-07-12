from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import plistlib
import shlex
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from dating_boost import __version__
from dating_boost.apps.tashuo.standalone_production_artifacts import (
    ArtifactViolation,
    QualificationPaths,
    create_qualification_paths,
    import_user_model_snapshot,
    load_canonical_authorization,
    publish_terminal_manifest,
    purge_sensitive_qualification_state,
    read_finalization_checkpoint,
    remove_finalization_checkpoint,
    seal_canary_certificate,
    seal_qualification_bundle_from_evidence,
    seal_qualification_evidence,
    scrub_sensitive_sentinels,
    snapshot_sentinel_candidates,
    validate_qualification_evidence,
    validate_production_artifact,
    verify_user_model_snapshot,
    write_finalization_checkpoint,
)
from dating_boost.apps.tashuo.standalone_production_attempt import ProductionAttemptProtocol
from dating_boost.apps.tashuo.standalone_production_contract import (
    CANARY_CYCLE_COUNT,
    CANARY_VALIDITY_SECONDS,
    FINALIZATION_STATES,
    MAX_SELECTION_PROBES_PER_SLOT,
    MUTATION_PHASE_INDEX,
    SOAK_CYCLE_COUNT,
    SOAK_INTERVAL_NS,
    SOAK_RETRY_DELAYS_SECONDS,
    ContractViolation,
    QualificationBinding,
    SelectionProbeBinding,
    build_canary_schedule,
    build_environment_fingerprint,
    build_soak_schedule,
    can_retry_reason,
    canonical_digest,
    compute_canary_accept_token,
    compute_config_hash,
    environment_fingerprints_match,
    transition_finalization,
    transition_outcome,
    validate_canary_metrics,
    validate_soak_metrics,
)
from dating_boost.apps.tashuo.standalone_production_ledger import (
    LedgerConflict,
    ProductionQualificationLedger,
)
from dating_boost.apps.tashuo.standalone_production_lock import (
    ProductionLockSet,
    WorkerIdentityConflict,
    WorkerProcessRegistry,
)
from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.agent_adapters import run_codex_adapter_doctor
from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.gui_runtime_lock import GuiRuntimeLock, boot_session_id
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.release import release_doctor
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.core.support import SupportLogRepository


QUALIFICATION_RECORD_PREFIX = "standalone_production/qualifications/"


class RunnerError(RuntimeError):
    pass


class RunnerBlocked(RunnerError):
    pass


class RunnerRecoveryRequired(RunnerBlocked):
    pass


class RunnerClock(Protocol):
    def now(self) -> datetime: ...

    def monotonic_ns(self) -> int: ...

    def sleep(self, seconds: float) -> None: ...

    def boot_session_id(self) -> str: ...


class SystemRunnerClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def boot_session_id(self) -> str:
        return boot_session_id()


class QualificationRuntime(Protocol):
    def start_phase(self, context: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def selection_probe(self, context: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def execute_attempt(self, context: AttemptExecutionContext) -> Mapping[str, Any]: ...

    def recover_attempt(self, context: AttemptExecutionContext) -> Mapping[str, Any]: ...

    def end_phase(self, context: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ProductionPreflight(Protocol):
    def run(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class AttemptExecutionContext:
    paths: QualificationPaths
    binding: QualificationBinding
    protocol: ProductionAttemptProtocol
    slot: dict[str, Any]
    target: dict[str, Any]
    precondition_digest: str
    attempt_number: int
    lock_capability: dict[str, Any]
    support_session_id: str
    authorization_record_id: str
    predecessor_binding: dict[str, Any] | None


@dataclass(slots=True)
class PhaseResult:
    metrics: dict[str, Any]
    support_bundle: Path
    support_session_id: str
    chain_range: dict[str, int | None]
    evidence_certificates: list[dict[str, Any]]
    predecessor_binding: dict[str, Any] | None


class ProductionQualificationRunner:
    def __init__(
        self,
        *,
        root_dir: Path,
        source_checkout: Path,
        runtime: QualificationRuntime | None = None,
        preflight: ProductionPreflight | None = None,
        clock: RunnerClock | None = None,
        runtime_lock_state_root: Path | None = None,
        built_artifact: Path | None = None,
    ):
        self.root_dir = root_dir.expanduser().resolve()
        self.source_checkout = source_checkout.expanduser().resolve()
        self.clock = clock or SystemRunnerClock()
        self.built_artifact = built_artifact.expanduser().resolve() if built_artifact is not None else None
        self.preflight = preflight or DefaultProductionPreflight(
            source_checkout=self.source_checkout,
            built_artifact=self.built_artifact,
        )
        self.runtime = runtime or _unconfigured_runtime()
        self.runtime_lock_state_root = runtime_lock_state_root

    def canary(
        self,
        *,
        user_model_source_data_dir: Path,
        authorization_path: Path,
    ) -> dict[str, Any]:
        paths = create_qualification_paths(
            self.root_dir,
            source_data_dir=user_model_source_data_dir,
        )
        ledger = ProductionQualificationLedger(paths.data_dir)
        qualification_salt = hashlib.sha256(os.urandom(32)).hexdigest()
        qualification = ledger.create_qualification(
            paths.qualification_id,
            {
                "outcome_state": "created",
                "finalization_state": "open",
                "qualification_salt": qualification_salt,
                "created_at": _iso(self.clock.now()),
                "created_monotonic_ns": self.clock.monotonic_ns(),
                "boot_session_id": self.clock.boot_session_id(),
                "active_phase": None,
                "phase_bundles": {},
                "evidence_certificates": [],
            },
        )
        try:
            snapshot = import_user_model_snapshot(
                user_model_source_data_dir,
                paths.data_dir,
                qualification_id=paths.qualification_id,
            )
            authorization = load_canonical_authorization(
                authorization_path,
                data_dir=paths.data_dir,
                now=self.clock.now(),
                qualification_id=paths.qualification_id,
            )
            preflight = self.preflight.run(
                paths=paths,
                snapshot_digest=snapshot["snapshot_digest"],
                authorization_digest=authorization["authorization_digest"],
                qualification_salt=qualification_salt,
                expected_environment_fingerprint=None,
            )
            if preflight.get("status") != "ok":
                raise RunnerBlocked(str(preflight.get("reason") or "preflight_blocked"))
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("created", "preflight_passed"),
                    "snapshot_digest": snapshot["snapshot_digest"],
                    "user_model_source_data_dir": str(user_model_source_data_dir.expanduser().resolve()),
                    "authorization_digest": authorization["authorization_digest"],
                    "authorization_record_id": authorization["record_id"],
                    "environment_fingerprint": dict(preflight["environment_fingerprint"]),
                    "config_hash": str(preflight["config_hash"]),
                    "preflight": _redacted_preflight(preflight),
                },
            )
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("preflight_passed", "canary_running"),
                    "active_phase": "canary",
                    "canary_schedule": build_canary_schedule(paths.qualification_id),
                },
            )
            phase = self._run_phase(
                paths=paths,
                ledger=ledger,
                qualification=qualification,
                phase="canary",
                authorization_path=authorization_path,
            )
            qualification = self._read_qualification(ledger, paths.qualification_id)
            metrics_validation = validate_canary_metrics(phase.metrics)
            if metrics_validation.get("passed") is not True:
                raise RunnerBlocked("canary_criteria_not_met")
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("canary_running", "canary_passed"),
                    "active_phase": None,
                    "canary_passed_at": _iso(self.clock.now()),
                    "canary_passed_monotonic_ns": self.clock.monotonic_ns(),
                    "canary_boot_session_id": self.clock.boot_session_id(),
                    "canary_expires_at": _iso(self.clock.now() + timedelta(seconds=CANARY_VALIDITY_SECONDS)),
                    "canary_expires_monotonic_ns": self.clock.monotonic_ns()
                    + CANARY_VALIDITY_SECONDS * 1_000_000_000,
                },
            )
            events = ledger.list_events()
            attempt_index = self._attempt_digest_index(ledger)
            certificate = seal_canary_certificate(
                output_dir=paths.output_dir,
                qualification_id=paths.qualification_id,
                config_hash=qualification["config_hash"],
                environment_fingerprint=qualification["environment_fingerprint"],
                events=events,
                attempt_digest_index=attempt_index,
                cycle_digest_index=self._cycle_digest_index(ledger),
                metrics=phase.metrics,
                support_bundle=phase.support_bundle,
                support_session_id=phase.support_session_id,
                chain_range=phase.chain_range,
            )
            token = compute_canary_accept_token(
                qualification_id=paths.qualification_id,
                config_hash=qualification["config_hash"],
                canary_chain_root=certificate["canary_chain_root"],
                canary_certificate_digest=certificate["digest"],
            )
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "canary_chain_root": certificate["canary_chain_root"],
                    "canary_certificate_digest": certificate["digest"],
                    "canary_accept_token": token,
                },
            )
            return {
                "schema_version": 1,
                "status": "canary_passed",
                "qualification_id": paths.qualification_id,
                "environment_fingerprint": qualification["environment_fingerprint"],
                "config_hash": qualification["config_hash"],
                "canary_chain_root": certificate["canary_chain_root"],
                "canary_accept_token": token,
                "canary_expires_at": qualification["canary_expires_at"],
                "claim_code": "CANARY_PASSED_SOAK_NOT_RUN",
                "claim_text": "canary passed for the pinned environment; soak not run; qualification not passed",
                "qualification_passed": False,
                "canary_certificate_path": certificate["path"],
                "canary_certificate_digest": certificate["digest"],
                "metrics": phase.metrics,
                "next_command": self._soak_command(paths.qualification_id, token),
            }
        except RunnerRecoveryRequired as exc:
            return self._retain_for_manual_recovery(paths=paths, ledger=ledger, reason=str(exc))
        except (ArtifactViolation, ContractViolation, LedgerConflict, RunnerBlocked) as exc:
            return self._block_and_finalize(
                paths=paths,
                ledger=ledger,
                reason=str(exc),
            )

    def soak(
        self,
        *,
        qualification_id: str,
        accept_canary: str,
        authorization_path: Path,
    ) -> dict[str, Any]:
        paths = self._existing_paths(qualification_id)
        ledger = ProductionQualificationLedger(paths.data_dir)
        qualification = self._read_qualification(ledger, qualification_id)
        if qualification.get("outcome_state") != "canary_passed":
            raise RunnerBlocked("qualification_not_waiting_for_soak")
        if accept_canary != qualification.get("canary_accept_token"):
            raise RunnerBlocked("canary_accept_token_mismatch")
        now = self.clock.now()
        canary_passed_at = _parse_iso(str(qualification.get("canary_passed_at") or ""))
        if (
            self.clock.boot_session_id() != qualification.get("canary_boot_session_id")
            or self.clock.monotonic_ns() > int(qualification.get("canary_expires_monotonic_ns") or 0)
            or now < canary_passed_at
            or now > canary_passed_at + timedelta(seconds=CANARY_VALIDITY_SECONDS)
        ):
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("canary_passed", "qualification_expired"),
                    "active_phase": None,
                },
            )
            return self._finalize(paths=paths, ledger=ledger, qualification=qualification, reason="canary_expired")
        try:
            source_path = Path(str(qualification.get("user_model_source_data_dir") or ""))
            snapshot = verify_user_model_snapshot(
                source_path,
                expected_digest=str(qualification["snapshot_digest"]),
            )
            if snapshot.get("status") != "ok":
                raise RunnerBlocked(str(snapshot.get("reason") or "user_model_snapshot_drift"))
            authorization = load_canonical_authorization(
                authorization_path,
                data_dir=paths.data_dir,
                now=self.clock.now(),
                qualification_id=qualification_id,
                expected_digest=qualification["authorization_digest"],
            )
            preflight = self.preflight.run(
                paths=paths,
                snapshot_digest=qualification["snapshot_digest"],
                authorization_digest=authorization["authorization_digest"],
                qualification_salt=qualification["qualification_salt"],
                expected_environment_fingerprint=qualification["environment_fingerprint"],
            )
            if preflight.get("status") != "ok":
                raise RunnerBlocked(str(preflight.get("reason") or "preflight_blocked"))
            comparison = environment_fingerprints_match(
                qualification["environment_fingerprint"],
                preflight["environment_fingerprint"],
            )
            if comparison.get("matches") is not True or preflight.get("config_hash") != qualification.get("config_hash"):
                raise RunnerBlocked("environment_drift")
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("canary_passed", "soak_running"),
                    "active_phase": "soak",
                    "soak_schedule": build_soak_schedule(qualification_id),
                    "soak_started_at": _iso(self.clock.now()),
                    "soak_started_monotonic_ns": self.clock.monotonic_ns(),
                    "soak_boot_session_id": self.clock.boot_session_id(),
                },
            )
            phase = self._run_phase(
                paths=paths,
                ledger=ledger,
                qualification=qualification,
                phase="soak",
                authorization_path=authorization_path,
            )
            qualification = self._read_qualification(ledger, qualification_id)
            validation = validate_soak_metrics(phase.metrics)
            if validation.get("passed") is not True:
                raise RunnerBlocked("soak_criteria_not_met:" + ",".join(validation.get("failed_predicates") or []))
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("soak_running", "soak_criteria_met"),
                    "active_phase": None,
                    "soak_finished_at": _iso(self.clock.now()),
                },
            )
            return self._finalize(paths=paths, ledger=ledger, qualification=qualification, reason=None)
        except RunnerRecoveryRequired as exc:
            return self._retain_for_manual_recovery(paths=paths, ledger=ledger, reason=str(exc))
        except (ArtifactViolation, ContractViolation, LedgerConflict, RunnerBlocked) as exc:
            return self._block_and_finalize(paths=paths, ledger=ledger, reason=str(exc))

    def status(self, *, qualification_id: str | None = None) -> dict[str, Any]:
        if qualification_id is None:
            if not self.root_dir.is_dir():
                return {"schema_version": 1, "status": "ok", "qualifications": []}
            summaries = []
            for directory in sorted(self.root_dir.iterdir()):
                if directory.is_dir():
                    summary = self._status_one(directory.name)
                    if summary is not None:
                        summaries.append(summary)
            return {"schema_version": 1, "status": "ok", "qualifications": summaries}
        result = self._status_one(qualification_id)
        if result is None:
            return {"schema_version": 1, "status": "not_found", "qualification_id": qualification_id}
        return result

    def janitor(self) -> dict[str, Any]:
        if not self.root_dir.is_dir():
            return {"schema_version": 1, "status": "ok", "actions": []}
        actions: list[dict[str, Any]] = []
        for directory in sorted(self.root_dir.iterdir()):
            if not directory.is_dir():
                continue
            qualification_id = directory.name
            try:
                paths = self._existing_paths(qualification_id)
            except (ArtifactViolation, RunnerBlocked):
                actions.append({"qualification_id": qualification_id, "status": "quarantined", "reason": "ownership_invalid"})
                continue
            if (paths.output_dir / "terminal_manifest.json").is_file():
                continue
            if not paths.data_dir.is_dir():
                try:
                    result = self.finalize(qualification_id=qualification_id)
                except (ArtifactViolation, RunnerBlocked):
                    result = {"status": "finalization_failed", "reason": "finalization_resume_failed"}
                actions.append({"qualification_id": qualification_id, "status": result.get("status")})
                continue
            try:
                ledger = ProductionQualificationLedger(paths.data_dir)
                qualification = self._read_qualification(ledger, qualification_id)
            except Exception:
                actions.append({"qualification_id": qualification_id, "status": "quarantined", "reason": "ledger_unreadable"})
                continue
            try:
                checkpoint = read_finalization_checkpoint(paths.output_dir)
            except ArtifactViolation:
                checkpoint = None
            if (
                isinstance(checkpoint, Mapping)
                and checkpoint.get("state") == "finalization_failed"
                and self._finalization_cleanup_due(checkpoint)
            ):
                if self._has_unknown_gui_mutation(ledger):
                    pause = GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(
                        reason="unknown_qualification_gui_mutation"
                    )
                    actions.append(
                        {
                            "qualification_id": qualification_id,
                            "status": "retained_for_manual_recovery",
                            "pause_id": pause.get("pause_id"),
                        }
                    )
                    continue
                resumed = self.finalize(qualification_id=qualification_id)
                if resumed.get("status") != "finalization_failed":
                    actions.append(
                        {"qualification_id": qualification_id, "status": resumed.get("status")}
                    )
                    continue
                purge = purge_sensitive_qualification_state(paths)
                write_finalization_checkpoint(
                    paths.output_dir,
                    {
                        "qualification_id": qualification_id,
                        "outcome_state": qualification.get("outcome_state"),
                        "state": "retention_expired",
                        "last_completed_state": checkpoint.get("last_completed_state"),
                        "reason": resumed.get("reason"),
                        "failed_at": checkpoint.get("failed_at"),
                        "cleanup_after": checkpoint.get("cleanup_after"),
                        "purge_result": purge,
                    },
                )
                actions.append(
                    {"qualification_id": qualification_id, "status": "retention_expired"}
                )
                continue
            state = str(qualification.get("outcome_state") or "")
            if state == "canary_passed" and self._canary_wait_expired(qualification):
                qualification = self._update_qualification(
                    ledger,
                    qualification,
                    {"outcome_state": "qualification_expired", "active_phase": None},
                )
                result = self._finalize(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    reason="canary_expired",
                )
                actions.append({"qualification_id": qualification_id, "status": result.get("status")})
                continue
            if state in {"canary_running", "soak_running"} and self._recovery_deadline_elapsed(qualification):
                unknown = self._has_unknown_gui_mutation(ledger)
                if unknown:
                    pause = GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(
                        reason="unknown_qualification_gui_mutation"
                    )
                    actions.append(
                        {
                            "qualification_id": qualification_id,
                            "status": "retained_for_manual_recovery",
                            "pause_id": pause.get("pause_id"),
                        }
                    )
                    continue
                qualification = self._update_qualification(
                    ledger,
                    qualification,
                    {
                        "outcome_state": "qualification_blocked",
                        "active_phase": None,
                        "blocked_reason": "recovery_deadline_elapsed",
                    },
                )
                result = self._finalize(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    reason="recovery_deadline_elapsed",
                )
                actions.append({"qualification_id": qualification_id, "status": result.get("status")})
        return {"schema_version": 1, "status": "ok", "actions": actions}

    def _finalization_cleanup_due(self, checkpoint: Mapping[str, Any]) -> bool:
        cleanup_after = checkpoint.get("cleanup_after")
        if not isinstance(cleanup_after, str):
            return True
        try:
            return self.clock.now() >= _parse_iso(cleanup_after)
        except RunnerBlocked:
            return True

    def _canary_wait_expired(self, qualification: Mapping[str, Any]) -> bool:
        try:
            expires = _parse_iso(str(qualification.get("canary_expires_at") or ""))
        except RunnerBlocked:
            return True
        return self.clock.now() > expires or self.clock.boot_session_id() != qualification.get("canary_boot_session_id")

    def _recovery_deadline_elapsed(self, qualification: Mapping[str, Any]) -> bool:
        last = qualification.get("last_action_wall_at") or qualification.get("created_at")
        if not isinstance(last, str):
            return True
        try:
            return self.clock.now() > _parse_iso(last) + timedelta(hours=1)
        except RunnerBlocked:
            return True

    @staticmethod
    def _has_unknown_gui_mutation(ledger: ProductionQualificationLedger) -> bool:
        for item in ledger.list_records("standalone_production/attempts/"):
            attempt = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            phase = str(attempt.get("mutation_phase") or "not_started")
            if MUTATION_PHASE_INDEX.get(phase, -1) < MUTATION_PHASE_INDEX["stage_mutation_intent"]:
                continue
            attempt_id = str(attempt.get("attempt_id") or "")
            try:
                ledger.read_attempt_outcome(attempt_id)
                ledger.read_receipt(attempt_id)
            except FileNotFoundError:
                return True
        return False

    def resume(self, *, qualification_id: str, authorization_path: Path) -> dict[str, Any]:
        paths = self._existing_paths(qualification_id)
        ledger = ProductionQualificationLedger(paths.data_dir)
        qualification = self._read_qualification(ledger, qualification_id)
        active_phase = qualification.get("active_phase")
        if active_phase not in {"canary", "soak"}:
            raise RunnerBlocked("qualification_has_no_active_phase")
        try:
            authorization = load_canonical_authorization(
                authorization_path,
                data_dir=paths.data_dir,
                now=self.clock.now(),
                qualification_id=qualification_id,
                expected_digest=qualification["authorization_digest"],
            )
            snapshot = verify_user_model_snapshot(
                Path(str(qualification.get("user_model_source_data_dir") or "")),
                expected_digest=str(qualification["snapshot_digest"]),
            )
            if snapshot.get("status") != "ok":
                raise RunnerBlocked(str(snapshot.get("reason") or "user_model_snapshot_drift"))
            preflight = self.preflight.run(
                paths=paths,
                snapshot_digest=qualification["snapshot_digest"],
                authorization_digest=authorization["authorization_digest"],
                qualification_salt=qualification["qualification_salt"],
                expected_environment_fingerprint=qualification["environment_fingerprint"],
            )
            if preflight.get("status") != "ok" or preflight.get("config_hash") != qualification.get("config_hash"):
                raise RunnerBlocked(str(preflight.get("reason") or "environment_drift"))
            phase = self._persisted_phase_result(
                paths=paths,
                qualification=qualification,
                phase=active_phase,
            )
            if phase is None:
                phase = self._run_phase(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    phase=active_phase,
                    authorization_path=authorization_path,
                    resume=True,
                )
            qualification = self._read_qualification(ledger, qualification_id)
            if active_phase == "canary":
                return self._complete_canary_phase(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    phase=phase,
                )
            validation = validate_soak_metrics(phase.metrics)
            if validation.get("passed") is not True:
                raise RunnerBlocked(
                    "soak_criteria_not_met:" + ",".join(validation.get("failed_predicates") or [])
                )
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    "outcome_state": transition_outcome("soak_running", "soak_criteria_met"),
                    "active_phase": None,
                    "soak_finished_at": _iso(self.clock.now()),
                },
            )
            return self._finalize(paths=paths, ledger=ledger, qualification=qualification, reason=None)
        except RunnerRecoveryRequired as exc:
            return self._retain_for_manual_recovery(paths=paths, ledger=ledger, reason=str(exc))
        except (ArtifactViolation, ContractViolation, LedgerConflict, RunnerBlocked) as exc:
            return self._block_and_finalize(paths=paths, ledger=ledger, reason=str(exc))

    def _persisted_phase_result(
        self,
        *,
        paths: QualificationPaths,
        qualification: Mapping[str, Any],
        phase: str,
    ) -> PhaseResult | None:
        metrics = qualification.get(f"{phase}_metrics")
        phase_bundles = qualification.get("phase_bundles")
        support_sessions = qualification.get("phase_support_sessions")
        chain_ranges = qualification.get("phase_chain_ranges")
        if not all(
            isinstance(value, Mapping)
            for value in (metrics, phase_bundles, support_sessions, chain_ranges)
        ):
            return None
        bundle = _relative_existing(paths.qualification_dir, phase_bundles.get(phase))
        support_session_id = support_sessions.get(phase)
        chain_range = chain_ranges.get(phase)
        if (
            bundle is None
            or not isinstance(support_session_id, str)
            or not isinstance(chain_range, Mapping)
            or not isinstance(chain_range.get("start"), int)
            or not isinstance(chain_range.get("end"), int)
        ):
            return None
        return PhaseResult(
            metrics=dict(metrics),
            support_bundle=bundle,
            support_session_id=support_session_id,
            chain_range={
                "start": int(chain_range["start"]),
                "end": int(chain_range["end"]),
            },
            evidence_certificates=[
                dict(item)
                for item in qualification.get("evidence_certificates") or []
                if isinstance(item, Mapping)
            ],
            predecessor_binding=(
                dict(qualification[f"{phase}_predecessor_binding"])
                if isinstance(qualification.get(f"{phase}_predecessor_binding"), Mapping)
                else None
            ),
        )

    def _record_evidence_certificate(
        self,
        ledger: ProductionQualificationLedger,
        certificate: Mapping[str, Any],
    ) -> dict[str, Any]:
        attempt_id = str(certificate.get("attempt_id") or "")
        if not attempt_id:
            raise RunnerBlocked("evidence_certificate_attempt_missing")
        attempt = ledger.read_record(f"standalone_production/attempts/{attempt_id}.json")
        return ledger.insert_if_absent(
            f"standalone_production/evidence_certificates/{attempt_id}.json",
            {
                "schema_version": 1,
                "attempt_id": attempt_id,
                "qualification_binding": attempt.get("qualification_binding"),
                "certificate": dict(certificate),
            },
        )

    def _phase_evidence_certificates(
        self,
        ledger: ProductionQualificationLedger,
        phase: str,
    ) -> list[dict[str, Any]]:
        certificates: list[dict[str, Any]] = []
        for item in ledger.list_records("standalone_production/evidence_certificates/"):
            payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else {}
            binding = payload.get("qualification_binding")
            certificate = payload.get("certificate")
            if (
                isinstance(binding, Mapping)
                and binding.get("phase") == phase
                and isinstance(certificate, Mapping)
            ):
                certificates.append(dict(certificate))
        return sorted(certificates, key=lambda item: str(item.get("attempt_id") or ""))

    def finalize(self, *, qualification_id: str) -> dict[str, Any]:
        paths = self._existing_paths(qualification_id)
        ledger = ProductionQualificationLedger(paths.data_dir) if paths.data_dir.is_dir() else None
        if ledger is not None:
            qualification = self._read_qualification(ledger, qualification_id)
            if qualification.get("outcome_state") not in {
                "soak_criteria_met",
                "qualification_blocked",
                "qualification_expired",
            }:
                raise RunnerBlocked("qualification_not_finalizable")
        else:
            terminal = paths.output_dir / "terminal_manifest.json"
            bundle = paths.output_dir / "qualification_bundle.zip"
            if terminal.is_file() and bundle.is_file():
                return self._terminal_result(paths=paths, reason=None)
            checkpoint = read_finalization_checkpoint(paths.output_dir)
            if checkpoint is None or checkpoint.get("state") not in {
                "purged",
                "bundle_sealed",
                "bundle_validated",
                "finalization_failed",
            }:
                raise RunnerBlocked("qualification_not_finalizable")
            qualification = {
                "qualification_id": qualification_id,
                "outcome_state": checkpoint.get("outcome_state"),
                "config_hash": None,
            }
        return self._finalize(paths=paths, ledger=ledger, qualification=qualification, reason=None)

    def _complete_canary_phase(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        qualification: dict[str, Any],
        phase: PhaseResult,
    ) -> dict[str, Any]:
        validation = validate_canary_metrics(phase.metrics)
        if validation.get("passed") is not True:
            raise RunnerBlocked("canary_criteria_not_met")
        qualification = self._update_qualification(
            ledger,
            qualification,
            {
                "outcome_state": transition_outcome("canary_running", "canary_passed"),
                "active_phase": None,
                "canary_passed_at": _iso(self.clock.now()),
                "canary_passed_monotonic_ns": self.clock.monotonic_ns(),
                "canary_boot_session_id": self.clock.boot_session_id(),
                "canary_expires_at": _iso(self.clock.now() + timedelta(seconds=CANARY_VALIDITY_SECONDS)),
                "canary_expires_monotonic_ns": self.clock.monotonic_ns()
                + CANARY_VALIDITY_SECONDS * 1_000_000_000,
            },
        )
        certificate = seal_canary_certificate(
            output_dir=paths.output_dir,
            qualification_id=paths.qualification_id,
            config_hash=qualification["config_hash"],
            environment_fingerprint=qualification["environment_fingerprint"],
            events=ledger.list_events(),
            attempt_digest_index=self._attempt_digest_index(ledger),
            cycle_digest_index=self._cycle_digest_index(ledger),
            metrics=phase.metrics,
            support_bundle=phase.support_bundle,
            support_session_id=phase.support_session_id,
            chain_range=phase.chain_range,
        )
        token = compute_canary_accept_token(
            qualification_id=paths.qualification_id,
            config_hash=qualification["config_hash"],
            canary_chain_root=certificate["canary_chain_root"],
            canary_certificate_digest=certificate["digest"],
        )
        qualification = self._update_qualification(
            ledger,
            qualification,
            {
                "canary_chain_root": certificate["canary_chain_root"],
                "canary_certificate_digest": certificate["digest"],
                "canary_accept_token": token,
            },
        )
        return {
            "schema_version": 1,
            "status": "canary_passed",
            "qualification_id": paths.qualification_id,
            "environment_fingerprint": qualification["environment_fingerprint"],
            "config_hash": qualification["config_hash"],
            "canary_chain_root": certificate["canary_chain_root"],
            "canary_accept_token": token,
            "canary_expires_at": qualification["canary_expires_at"],
            "claim_code": "CANARY_PASSED_SOAK_NOT_RUN",
            "claim_text": "canary passed for the pinned environment; soak not run; qualification not passed",
            "qualification_passed": False,
            "canary_certificate_path": certificate["path"],
            "canary_certificate_digest": certificate["digest"],
            "metrics": phase.metrics,
            "next_command": self._soak_command(paths.qualification_id, token),
        }

    def _run_phase(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger | None,
        qualification: dict[str, Any],
        phase: str,
        authorization_path: Path,
        resume: bool = False,
    ) -> PhaseResult:
        owner_id = f"{paths.qualification_id}:{phase}"
        owner_nonce = hashlib.sha256(os.urandom(32)).hexdigest()
        runtime_lock = GuiRuntimeLock(
            state_root=self.runtime_lock_state_root,
            monotonic_ns=self.clock.monotonic_ns,
        )
        lock_set = ProductionLockSet(
            paths,
            runtime_lock=runtime_lock,
            monotonic_ns=self.clock.monotonic_ns,
        )
        lock_handle = lock_set.acquire(owner_id=owner_id, owner_nonce=owner_nonce, takeover=resume)
        support = SupportLogRepository(paths.data_dir)
        support_owner = {"qualification_id": paths.qualification_id, "phase": phase}
        qualification = self._read_qualification(ledger, paths.qualification_id)
        chain_start_key = f"{phase}_active_chain_start"
        support_session_key = f"{phase}_active_support_session_id"
        stored_chain_start = qualification.get(chain_start_key)
        stored_support_session = qualification.get(support_session_key)
        support_already_stopped = False
        if isinstance(stored_support_session, str):
            stored_session = support.get_session(stored_support_session)
            if not isinstance(stored_session, Mapping):
                lock_handle.release()
                raise RunnerBlocked("support_session_resume_binding_mismatch")
            if stored_session.get("status") == "active":
                support_session = support.start_session(
                    host="codex",
                    app_id="tashuo",
                    owner=support_owner,
                )
            elif stored_session.get("status") == "stopped":
                support_session = dict(stored_session)
                support_already_stopped = True
            else:
                lock_handle.release()
                raise RunnerBlocked("support_session_resume_binding_mismatch")
        else:
            support_session = support.start_session(
                host="codex",
                app_id="tashuo",
                owner=support_owner,
            )
        if support_session.get("status") not in {"active", "stopped"}:
            lock_handle.release()
            raise RunnerBlocked(str(support_session.get("reason") or "support_session_start_failed"))
        support_session_id = str(support_session["session_id"])
        if stored_chain_start is not None or stored_support_session is not None:
            if (
                not isinstance(stored_chain_start, int)
                or stored_chain_start < 1
                or stored_support_session != support_session_id
            ):
                lock_handle.release()
                raise RunnerBlocked("support_session_resume_binding_mismatch")
            chain_start = stored_chain_start
        else:
            chain_start = len(ledger.list_events()) + 1
            qualification = self._update_qualification(
                ledger,
                qualification,
                {
                    chain_start_key: chain_start,
                    support_session_key: support_session_id,
                },
            )
        capability = self._renew_lock_capability(lock_handle)
        runtime_started = False
        runtime_ended = False
        support_stopped = support_already_stopped
        retain_support_session = False
        if support_already_stopped:
            try:
                return self._resume_stopped_phase(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    phase=phase,
                    support=support,
                    support_session_id=support_session_id,
                    chain_start=chain_start,
                )
            finally:
                lock_handle.release()
        try:
            started = self.runtime.start_phase(
                {
                    "phase": phase,
                    "paths": paths,
                    "support_session_id": support_session_id,
                    "lock_capability": capability,
                    "authorization_record_id": qualification["authorization_record_id"],
                    "resume": resume,
                    "lock_renewer": lambda: self._renew_lock_capability(lock_handle),
                }
            )
        except Exception:
            started = {"status": "blocked", "reason": "runtime_phase_start_exception"}
        if started.get("status") != "ok":
            reason = str(started.get("reason") or "runtime_phase_start_failed")
            try:
                self._seal_failed_phase(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    phase=phase,
                    support=support,
                    support_session_id=support_session_id,
                    support_owner=support_owner,
                    required_support_contexts=[],
                    metrics=_initial_metrics(phase),
                    evidence_certificates=[],
                    predecessor_binding=qualification.get(f"{phase}_predecessor_binding"),
                    chain_start=chain_start,
                    runtime_started=False,
                    runtime_ended=False,
                    support_stopped=False,
                )
            finally:
                lock_handle.release()
            raise RunnerBlocked(reason)
        runtime_started = True
        schedule = list(qualification[f"{phase}_schedule"])
        cycle_records = {
            int(item["payload"].get("cycle_index")): item["payload"]
            for item in ledger.list_records(f"standalone_production/cycles/{phase}/")
        }
        existing_cycles = {
            index: cycle
            for index, cycle in cycle_records.items()
            if cycle.get("state") in {"cycle_committed_success", "cycle_committed_failure"}
        }
        progress = self._load_phase_progress(ledger=ledger, phase=phase)
        metrics = progress["metrics"]
        evidence_certificates = self._phase_evidence_certificates(ledger, phase)
        predecessor = progress.get("predecessor") or qualification.get(f"{phase}_predecessor_binding")
        previous_actual_start = progress.get("previous_actual_start")
        required_support_contexts: list[str] = []
        try:
            slot_queue = list(schedule)
            while slot_queue:
                slot = slot_queue.pop(0)
                cycle_index = int(slot["planned_index"])
                if cycle_index in existing_cycles:
                    committed_cycle = existing_cycles[cycle_index]
                    self._commit_cycle_terminal(
                        paths=paths,
                        ledger=ledger,
                        phase=phase,
                        cycle_index=cycle_index,
                        final_attempt_id=str(committed_cycle.get("final_attempt_id") or ""),
                        success=committed_cycle.get("state") == "cycle_committed_success",
                        actual_start_ns=int(committed_cycle.get("actual_start_ns") or 0),
                        commit_index=int(committed_cycle.get("commit_index") or 0),
                        predecessor_binding=(
                            committed_cycle.get("predecessor_binding")
                            if isinstance(committed_cycle.get("predecessor_binding"), Mapping)
                            else None
                        ),
                        validate_all_attempts=False,
                    )
                    continue
                if slot["mode"] == "current-thread" and not _predecessor_matches_slot(predecessor, slot):
                    if phase == "canary":
                        raise RunnerBlocked("current_thread_predecessor_missing")
                    replacement_index = next(
                        (
                            index
                            for index, candidate in enumerate(slot_queue)
                            if candidate.get("mode") == "message-list"
                            and int(candidate.get("planned_index") or 0) not in existing_cycles
                        ),
                        None,
                    )
                    if replacement_index is None:
                        raise RunnerBlocked("current_thread_predecessor_missing")
                    replacement = slot_queue.pop(replacement_index)
                    slot = {
                        **slot,
                        "deferred_predecessor_planned_slot_id": replacement["planned_slot_id"],
                    }
                    slot_queue.insert(0, slot)
                    slot_queue.insert(0, replacement)
                    continue
                cycle = cycle_records.get(cycle_index)
                recovered_final_result: Mapping[str, Any] | None = None
                if cycle is not None:
                    actual_start = int(cycle.get("actual_start_ns") or 0)
                    if actual_start <= 0:
                        raise RunnerBlocked("cycle_timing_missing")
                    if phase == "soak" and actual_start not in metrics["actual_start_ns"]:
                        metrics["actual_start_ns"].append(actual_start)
                        previous_actual_start = actual_start
                    if cycle.get("state") in {"attempt_terminal_committed", "cycle_commit_intent"}:
                        final_attempt_id = str(cycle.get("final_attempt_id") or "")
                        if not final_attempt_id:
                            raise RunnerBlocked("terminal_audit_missing")
                        outcome = ledger.read_attempt_outcome(final_attempt_id)
                        receipt = ledger.read_receipt(final_attempt_id)
                        recovered_final_result = _persisted_attempt_result(
                            ledger,
                            final_attempt_id,
                            outcome=outcome,
                            receipt=receipt,
                        )
                    elif cycle.get("state") == "running":
                        recovered = self._recover_pending_attempt(
                            paths=paths,
                            ledger=ledger,
                            phase=phase,
                            slot=slot,
                            cycle=cycle,
                            lock_handle=lock_handle,
                            lock_set=lock_set,
                            support=support,
                            support_session_id=support_session_id,
                            authorization_record_id=qualification["authorization_record_id"],
                            predecessor=predecessor if isinstance(predecessor, Mapping) else None,
                            required_support_contexts=required_support_contexts,
                        )
                        cycle = recovered["cycle"]
                        recovered_result = recovered.get("result")
                        if isinstance(recovered_result, Mapping):
                            retryable = can_retry_reason(
                                str(recovered_result.get("reason") or ""),
                                mutation_phase=str(recovered_result.get("mutation_phase") or "not_started"),
                                safe_recovery_complete=recovered_result.get("safe_recovery_complete") is True,
                            )
                            if phase == "canary" or not retryable or len(cycle.get("attempt_ids") or []) >= 3:
                                recovered_final_result = recovered_result
                else:
                    if phase == "soak" and previous_actual_start is not None:
                        due = previous_actual_start + SOAK_INTERVAL_NS
                        self._sleep_until_monotonic(due)
                    actual_start = self.clock.monotonic_ns()
                    if phase == "soak":
                        metrics["actual_start_ns"].append(actual_start)
                        previous_actual_start = actual_start
                    cycle = ledger.create_cycle(
                        qualification_id=paths.qualification_id,
                        phase=phase,
                        cycle_index=cycle_index,
                        planned_slot_id=slot["planned_slot_id"],
                        mode=slot["mode"],
                        actual_start_ns=actual_start,
                    )
                    cycle_records[cycle_index] = cycle
                if recovered_final_result is None:
                    target = self._select_target(
                        paths=paths,
                        ledger=ledger,
                        support=support,
                        support_session_id=support_session_id,
                        lock_handle=lock_handle,
                        phase=phase,
                        slot=slot,
                        predecessor=predecessor,
                        required_support_contexts=required_support_contexts,
                        authorization_path=authorization_path,
                    )
                else:
                    final_attempt_id = str((cycle.get("attempt_ids") or [""])[-1])
                    attempt_record = ledger.read_record(
                        f"standalone_production/attempts/{final_attempt_id}.json"
                    )
                    target = dict(attempt_record.get("target") or {})
                max_attempts = 1 if phase == "canary" else 3
                final_result = recovered_final_result
                first_attempt_succeeded = (
                    final_result is not None
                    and final_result.get("status") == "succeeded"
                    and len(cycle.get("attempt_ids") or []) == 1
                )
                if recovered_final_result is not None:
                    metrics["safety_violations"] += int(recovered_final_result.get("safety_violations") or 0)
                    if recovered_final_result.get("status") == "succeeded":
                        recovered_predecessor = dict(recovered_final_result.get("predecessor_binding") or {})
                        if recovered_predecessor:
                            recovered_predecessor.update(
                                {
                                    "source_cycle_index": cycle_index,
                                    "source_planned_slot_id": slot["planned_slot_id"],
                                    "source_mode": slot["mode"],
                                }
                            )
                            predecessor = recovered_predecessor
                        recovered_evidence = recovered_final_result.get("evidence_certificate")
                        if isinstance(recovered_evidence, dict):
                            self._record_evidence_certificate(ledger, recovered_evidence)
                            evidence_certificates.append(dict(recovered_evidence))
                first_new_attempt = (
                    max_attempts + 1
                    if recovered_final_result is not None
                    else len(cycle.get("attempt_ids") or []) + 1
                )
                for attempt_number in range(first_new_attempt, max_attempts + 1):
                    if attempt_number > 1:
                        self.clock.sleep(SOAK_RETRY_DELAYS_SECONDS[attempt_number - 2])
                    capability = self._renew_lock_capability(lock_handle)
                    self._recheck_action_guards(
                        paths=paths,
                        ledger=ledger,
                        authorization_path=authorization_path,
                    )
                    attempt_id = f"attempt_{phase}_{cycle_index:03d}_{attempt_number}_{hashlib.sha256(os.urandom(16)).hexdigest()[:10]}"
                    binding = QualificationBinding(
                        qualification_id=paths.qualification_id,
                        phase=phase,
                        cycle_index=cycle_index,
                        attempt_id=attempt_id,
                        local_fencing_token=capability["local_fencing_token"],
                        runtime_fencing_token=capability["runtime_fencing_token"],
                    )
                    cycle = ledger.add_cycle_attempt(
                        phase,
                        cycle_index,
                        attempt_id,
                        expected_version=cycle["ledger_version"],
                    )
                    guard = lambda cap=capability: lock_set.validate_delegated_capability(cap)
                    protocol = ProductionAttemptProtocol(
                        ledger,
                        binding,
                        mutation_guard=guard,
                        monotonic_ns=self.clock.monotonic_ns,
                    )
                    protocol.start(
                        precondition_digest=str(target["precondition_digest"]),
                        target_hash=str(target["target_hash"]),
                        target=target,
                    )
                    context = AttemptExecutionContext(
                        paths=paths,
                        binding=binding,
                        protocol=protocol,
                        slot=dict(slot),
                        target=dict(target),
                        precondition_digest=str(target["precondition_digest"]),
                        attempt_number=attempt_number,
                        lock_capability=capability,
                        support_session_id=support_session_id,
                        authorization_record_id=qualification["authorization_record_id"],
                        predecessor_binding=dict(predecessor) if isinstance(predecessor, dict) else None,
                    )
                    required_support_contexts.append(attempt_id)
                    command = support.record_command_started(
                        ["qualification", "attempt"],
                        context={
                            "support_session_id": support_session_id,
                            "qualification_id": paths.qualification_id,
                            "phase": phase,
                            "attempt_id": attempt_id,
                        },
                    )
                    try:
                        result = self.runtime.execute_attempt(context)
                    except Exception:
                        support.record_command_interrupted(
                            command,
                            argv=["qualification", "attempt"],
                            reason="worker_exception",
                        )
                        raise RunnerBlocked("worker_exception") from None
                    support.record_command_finished(
                        command,
                        argv=["qualification", "attempt"],
                        exit_code=0 if result.get("status") == "succeeded" else 2,
                        duration_ms=0,
                    )
                    stage_payload = result.get("stage_result_payload")
                    if isinstance(stage_payload, dict):
                        ActionAuditRepository(paths.data_dir).append_stage_result(
                            stage_payload,
                            created_at=_iso(self.clock.now()),
                        )
                    if result.get("terminal_persisted") is True:
                        try:
                            persisted_outcome = ledger.read_attempt_outcome(attempt_id)
                            persisted_receipt = ledger.read_receipt(attempt_id)
                        except FileNotFoundError:
                            raise RunnerBlocked("terminal_audit_missing") from None
                        if (
                            persisted_outcome.get("status") != result.get("status")
                            or persisted_receipt.get("status") != result.get("status")
                        ):
                            raise RunnerBlocked("receipt_conflict")
                    else:
                        raise RunnerRecoveryRequired(
                            str(result.get("reason") or "manual_recovery_required")
                        )
                    metrics["total_attempts"] += 1
                    metrics["safety_violations"] += int(result.get("safety_violations") or 0)
                    final_result = result
                    if result.get("status") == "succeeded":
                        first_attempt_succeeded = attempt_number == 1
                        cycle_predecessor = dict(result.get("predecessor_binding") or {})
                        if cycle_predecessor:
                            cycle_predecessor.update(
                                {
                                    "source_cycle_index": cycle_index,
                                    "source_planned_slot_id": slot["planned_slot_id"],
                                    "source_mode": slot["mode"],
                                }
                            )
                            predecessor = cycle_predecessor
                        evidence = result.get("evidence_certificate")
                        if isinstance(evidence, dict):
                            self._record_evidence_certificate(ledger, evidence)
                            evidence_certificates.append(dict(evidence))
                        break
                    mutation_phase = str(result.get("mutation_phase") or "not_started")
                    retryable = can_retry_reason(
                        str(result.get("reason") or ""),
                        mutation_phase=mutation_phase,
                        safe_recovery_complete=result.get("safe_recovery_complete") is True,
                    )
                    if phase == "canary" or not retryable or attempt_number >= max_attempts:
                        break
                if final_result is None:
                    raise RunnerBlocked("attempt_result_missing")
                final_attempt_id = str(
                    ledger.read_record(f"standalone_production/cycles/{phase}/{cycle_index}.json")["attempt_ids"][-1]
                )
                success = final_result.get("status") == "succeeded"
                cycle = self._commit_cycle_terminal(
                    paths=paths,
                    ledger=ledger,
                    phase=phase,
                    cycle_index=cycle_index,
                    final_attempt_id=final_attempt_id,
                    success=success,
                    actual_start_ns=actual_start,
                    commit_index=metrics["committed_cycles"] + 1,
                    predecessor_binding=predecessor if success and isinstance(predecessor, dict) else None,
                )
                metrics["committed_cycles"] += 1
                metrics["message_list_cycles" if slot["mode"] == "message-list" else "current_thread_cycles"] += 1
                if success:
                    metrics["terminal_cycle_successes"] += 1
                    if first_attempt_succeeded:
                        metrics["first_attempt_successes"] += 1
                if len(cycle.get("attempt_ids") or []) > 1:
                    metrics["retried_cycles"] += 1
                if phase == "canary" and not success:
                    raise RunnerBlocked(str(final_result.get("reason") or "canary_attempt_failed"))
                if slot["mode"] == "current-thread" or not success:
                    predecessor = None
            end = self.runtime.end_phase(
                {"phase": phase, "paths": paths, "support_session_id": support_session_id}
            )
            runtime_ended = True
            if end.get("status") != "ok" or int(end.get("orphan_count") or 0) != 0:
                raise RunnerBlocked("phase_cleanup_failed")
            coverage = support.validate_command_coverage(
                session_id=support_session_id,
                required_context_ids=required_support_contexts,
            )
            if coverage.get("valid") is not True:
                raise RunnerBlocked("support_command_coverage_incomplete")
            stopped = support.stop_session(session_id=support_session_id, owner=support_owner)
            if stopped.get("status") != "stopped":
                raise RunnerBlocked("support_session_stop_failed")
            support_stopped = True
            support_bundle = paths.output_dir / f"{phase}_support_strict.zip"
            bundled = support.bundle(session_id=support_session_id, output=support_bundle, redaction="strict")
            if bundled.get("status") != "ok":
                raise RunnerBlocked("support_bundle_failed")
            metrics.update(
                {
                    "successful_cycles": metrics["terminal_cycle_successes"],
                    "terminal_audits": metrics["total_attempts"],
                    "completed_stage_results": _completed_stage_results(paths.data_dir, phase),
                    "attempt_outcomes": metrics["total_attempts"],
                    "receipts": metrics["total_attempts"],
                    "phase_cleanup_ok": True,
                    "support_bundle_ok": True,
                    "support_bundles_ok": True,
                    "hash_chain_ok": ledger.validate_event_chain().get("valid") is True,
                    "sqlite_quick_check": ledger.quick_check()["sqlite_quick_check"],
                    "boot_session_unchanged": self.clock.boot_session_id()
                    == qualification.get("soak_boot_session_id", self.clock.boot_session_id()),
                    "environment_matches_canary": True,
                    "artifacts_ok": True,
                }
            )
            current_qualification = self._read_qualification(ledger, paths.qualification_id)
            if current_qualification.get("manual_recovery_required") is True:
                self._update_qualification(
                    ledger,
                    current_qualification,
                    {
                        "manual_recovery_required": False,
                        "manual_recovery_reason": None,
                        "manual_recovery_completed_at": _iso(self.clock.now()),
                    },
                )
            result = PhaseResult(
                metrics=metrics,
                support_bundle=support_bundle,
                support_session_id=support_session_id,
                chain_range={"start": chain_start, "end": len(ledger.list_events())},
                evidence_certificates=evidence_certificates,
                predecessor_binding=predecessor if isinstance(predecessor, dict) else None,
            )
            self._persist_phase_result(paths=paths, ledger=ledger, phase=phase, result=result)
            return result
        except Exception as exc:
            if isinstance(exc, RunnerRecoveryRequired):
                retain_support_session = True
                if runtime_started and not runtime_ended:
                    try:
                        self.runtime.end_phase(
                            {
                                "phase": phase,
                                "paths": paths,
                                "support_session_id": support_session_id,
                            }
                        )
                    except Exception:
                        pass
                raise
            try:
                self._seal_failed_phase(
                    paths=paths,
                    ledger=ledger,
                    qualification=qualification,
                    phase=phase,
                    support=support,
                    support_session_id=support_session_id,
                    support_owner=support_owner,
                    required_support_contexts=required_support_contexts,
                    metrics=metrics,
                    evidence_certificates=evidence_certificates,
                    predecessor_binding=predecessor,
                    chain_start=chain_start,
                    runtime_started=runtime_started,
                    runtime_ended=runtime_ended,
                    support_stopped=support_stopped,
                )
            except Exception:
                raise RunnerBlocked("phase_failure_evidence_incomplete") from None
            if isinstance(exc, (ArtifactViolation, ContractViolation, LedgerConflict, RunnerBlocked)):
                raise
            raise RunnerBlocked("phase_execution_exception") from None
        except BaseException:
            retain_support_session = True
            raise
        finally:
            if (
                not retain_support_session
                and support.active_session()
                and support.active_session().get("session_id") == support_session_id
            ):
                support.stop_session(session_id=support_session_id, owner=support_owner)
            lock_handle.release()

    def _resume_stopped_phase(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        qualification: Mapping[str, Any],
        phase: str,
        support: SupportLogRepository,
        support_session_id: str,
        chain_start: int,
    ) -> PhaseResult:
        schedule = qualification.get(f"{phase}_schedule")
        cycles = [
            item["payload"]
            for item in ledger.list_records(f"standalone_production/cycles/{phase}/")
            if isinstance(item.get("payload"), Mapping)
        ]
        if (
            not isinstance(schedule, list)
            or len(cycles) != len(schedule)
            or any(
                cycle.get("state")
                not in {"cycle_committed_success", "cycle_committed_failure"}
                for cycle in cycles
            )
        ):
            raise RunnerBlocked("support_session_stopped_before_phase_complete")
        orphan_count = sum(
            1
            for item in ledger.list_records("standalone_production/workers/")
            if (item.get("payload") or {}).get("status")
            in {"registered_waiting_barrier", "running"}
        )
        if orphan_count:
            raise RunnerBlocked("phase_cleanup_failed")
        coverage = support.validate_command_coverage(
            session_id=support_session_id,
            required_context_ids=[],
        )
        if coverage.get("valid") is not True:
            raise RunnerBlocked("support_command_coverage_incomplete")
        support_bundle = paths.output_dir / f"{phase}_support_strict.zip"
        bundled = support.bundle(
            session_id=support_session_id,
            output=support_bundle,
            redaction="strict",
        )
        if bundled.get("status") != "ok":
            raise RunnerBlocked("support_bundle_failed")
        progress = self._load_phase_progress(ledger=ledger, phase=phase)
        metrics = progress["metrics"]
        metrics.update(
            {
                "successful_cycles": metrics["terminal_cycle_successes"],
                "terminal_audits": metrics["total_attempts"],
                "completed_stage_results": _completed_stage_results(paths.data_dir, phase),
                "attempt_outcomes": metrics["total_attempts"],
                "receipts": metrics["total_attempts"],
                "phase_cleanup_ok": True,
                "support_bundle_ok": True,
                "support_bundles_ok": True,
                "hash_chain_ok": ledger.validate_event_chain().get("valid") is True,
                "sqlite_quick_check": ledger.quick_check()["sqlite_quick_check"],
                "boot_session_unchanged": self.clock.boot_session_id()
                == qualification.get("soak_boot_session_id", self.clock.boot_session_id()),
                "environment_matches_canary": True,
                "artifacts_ok": True,
            }
        )
        result = PhaseResult(
            metrics=metrics,
            support_bundle=support_bundle,
            support_session_id=support_session_id,
            chain_range={"start": chain_start, "end": len(ledger.list_events())},
            evidence_certificates=self._phase_evidence_certificates(ledger, phase),
            predecessor_binding=(
                dict(progress["predecessor"])
                if isinstance(progress.get("predecessor"), Mapping)
                else None
            ),
        )
        self._persist_phase_result(paths=paths, ledger=ledger, phase=phase, result=result)
        return result

    def _load_phase_progress(
        self,
        *,
        ledger: ProductionQualificationLedger,
        phase: str,
    ) -> dict[str, Any]:
        metrics = _initial_metrics(phase)
        cycles = [
            item["payload"]
            for item in ledger.list_records(f"standalone_production/cycles/{phase}/")
            if isinstance(item.get("payload"), dict)
        ]
        committed = sorted(
            (
                cycle
                for cycle in cycles
                if cycle.get("state") in {"cycle_committed_success", "cycle_committed_failure"}
            ),
            key=lambda cycle: int(cycle.get("commit_index") or 0),
        )
        metrics["total_attempts"] = sum(len(cycle.get("attempt_ids") or []) for cycle in cycles)
        predecessor = None
        for cycle in committed:
            attempts = [str(item) for item in cycle.get("attempt_ids") or []]
            metrics["committed_cycles"] += 1
            mode_key = "message_list_cycles" if cycle.get("mode") == "message-list" else "current_thread_cycles"
            metrics[mode_key] += 1
            if len(attempts) > 1:
                metrics["retried_cycles"] += 1
            final_attempt_id = str(cycle.get("final_attempt_id") or "")
            try:
                final_outcome = ledger.read_attempt_outcome(final_attempt_id)
            except FileNotFoundError:
                raise RunnerBlocked("terminal_audit_missing") from None
            if final_outcome.get("status") == "succeeded":
                metrics["terminal_cycle_successes"] += 1
                predecessor = cycle.get("predecessor_binding") if cycle.get("mode") == "message-list" else None
            elif cycle.get("mode") == "message-list":
                predecessor = None
            if attempts:
                try:
                    first_outcome = ledger.read_attempt_outcome(attempts[0])
                except FileNotFoundError:
                    raise RunnerBlocked("terminal_audit_missing") from None
                if first_outcome.get("status") == "succeeded":
                    metrics["first_attempt_successes"] += 1
            if phase == "soak":
                actual_start = cycle.get("actual_start_ns")
                if not isinstance(actual_start, int):
                    raise RunnerBlocked("cycle_timing_missing")
                metrics["actual_start_ns"].append(actual_start)
        metrics["successful_cycles"] = metrics["terminal_cycle_successes"]
        return {
            "metrics": metrics,
            "predecessor": predecessor,
            "previous_actual_start": (
                metrics["actual_start_ns"][-1]
                if phase == "soak" and metrics["actual_start_ns"]
                else None
            ),
        }

    def _commit_cycle_terminal(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        phase: str,
        cycle_index: int,
        final_attempt_id: str,
        success: bool,
        actual_start_ns: int,
        commit_index: int,
        predecessor_binding: Mapping[str, Any] | None,
        validate_all_attempts: bool = True,
    ) -> dict[str, Any]:
        cycle = ledger.read_record(f"standalone_production/cycles/{phase}/{cycle_index}.json")
        if cycle.get("final_attempt_id") is None:
            cycle = ledger.claim_final_attempt(
                phase,
                cycle_index,
                final_attempt_id,
                expected_version=cycle["ledger_version"],
            )
        elif cycle.get("final_attempt_id") != final_attempt_id:
            raise RunnerBlocked("cycle_final_attempt_conflict")
        graph = ledger.validate_attempt_graph(
            (
                _all_cycle_attempt_ids(ledger)
                if validate_all_attempts
                else [str(item) for item in cycle.get("attempt_ids") or []]
            ),
            stage_results=JsonStorage(paths.data_dir).read_jsonl(Path("audit/stage_results.jsonl")),
            require_exact_attempt_set=validate_all_attempts,
        )
        if graph.get("valid") is not True:
            raise RunnerBlocked("attempt_graph_invalid")
        final_attempt = ledger.read_record(f"standalone_production/attempts/{final_attempt_id}.json")
        final_binding = QualificationBinding.from_dict(final_attempt["qualification_binding"])
        if cycle.get("state") == "running":
            cycle = ledger.mark_attempt_terminal_committed(
                phase,
                cycle_index,
                expected_version=cycle["ledger_version"],
            )
        if cycle.get("state") in {
            "attempt_terminal_committed",
            "cycle_commit_intent",
            "cycle_committed_success",
            "cycle_committed_failure",
        }:
            ledger.append_event(
                event_id=f"cycle_attempt_terminal_{phase}_{cycle_index}",
                event_type="cycle_attempt_terminal_committed",
                binding=final_binding,
                reason_code=None,
                mutation_phase="attempt_terminal_committed",
                evidence_digest=canonical_digest({"cycle_index": cycle_index, "attempt_id": final_attempt_id}),
            )
        if cycle.get("state") == "attempt_terminal_committed":
            cycle = ledger.mark_cycle_commit_intent(
                phase,
                cycle_index,
                expected_version=cycle["ledger_version"],
            )
        if cycle.get("state") in {
            "cycle_commit_intent",
            "cycle_committed_success",
            "cycle_committed_failure",
        }:
            ledger.append_event(
                event_id=f"cycle_commit_intent_{phase}_{cycle_index}",
                event_type="cycle_commit_intent",
                binding=final_binding,
                reason_code=None,
                mutation_phase="attempt_terminal_committed",
                evidence_digest=canonical_digest({"cycle_index": cycle_index, "success": success}),
            )
        if cycle.get("state") == "cycle_commit_intent":
            cycle = ledger.commit_cycle(
                phase,
                cycle_index,
                expected_version=cycle["ledger_version"],
                success=success,
                actual_start_ns=actual_start_ns,
                commit_index=commit_index,
                predecessor_binding=predecessor_binding,
            )
        expected_state = "cycle_committed_success" if success else "cycle_committed_failure"
        if cycle.get("state") != expected_state:
            raise RunnerBlocked("cycle_commit_state_mismatch")
        ledger.append_event(
            event_id=f"cycle_committed_{phase}_{cycle_index}",
            event_type=str(cycle["state"]),
            binding=final_binding,
            reason_code=None,
            mutation_phase="attempt_terminal_committed",
            evidence_digest=canonical_digest(
                {"cycle_index": cycle_index, "commit_index": cycle["commit_index"]}
            ),
        )
        return cycle

    def _recover_pending_attempt(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        phase: str,
        slot: Mapping[str, Any],
        cycle: Mapping[str, Any],
        lock_handle: Any,
        lock_set: ProductionLockSet,
        support: SupportLogRepository,
        support_session_id: str,
        authorization_record_id: str,
        predecessor: Mapping[str, Any] | None,
        required_support_contexts: list[str],
    ) -> dict[str, Any]:
        attempt_ids = [str(item) for item in cycle.get("attempt_ids") or []]
        if not attempt_ids:
            return {"action": "continue", "cycle": dict(cycle), "result": None}
        attempt_id = attempt_ids[-1]
        worker_registry = WorkerProcessRegistry(ledger)
        try:
            worker = worker_registry.read(attempt_id)
        except FileNotFoundError:
            worker = None
        if isinstance(worker, Mapping) and worker.get("status") in {
            "registered_waiting_barrier",
            "running",
        }:
            try:
                worker_registry.reconcile_orphan(attempt_id)
            except WorkerIdentityConflict:
                GuiRuntimeLock(state_root=self.runtime_lock_state_root).pause(
                    reason="worker_identity_mismatch"
                )
                raise RunnerRecoveryRequired("worker_identity_mismatch") from None
        try:
            outcome = ledger.read_attempt_outcome(attempt_id)
            receipt = ledger.read_receipt(attempt_id)
        except FileNotFoundError:
            outcome = None
            receipt = None
        if outcome is not None and receipt is not None:
            result = _persisted_attempt_result(ledger, attempt_id, outcome=outcome, receipt=receipt)
            return {"action": "terminal", "cycle": dict(cycle), "result": result}
        reconciled = support.reconcile_interrupted_context(
            session_id=support_session_id,
            context_id=attempt_id,
            reason="parent_or_worker_interrupted",
        )
        if reconciled.get("status") != "ok":
            raise RunnerBlocked("support_command_coverage_incomplete")
        attempt = ledger.read_record(f"standalone_production/attempts/{attempt_id}.json")
        binding = QualificationBinding.from_dict(attempt.get("qualification_binding") or {})
        target = attempt.get("target")
        if not isinstance(target, dict):
            raise RunnerBlocked("target_mismatch")
        capability = self._renew_lock_capability(lock_handle)
        guard = lambda cap=capability: lock_set.validate_delegated_capability(cap)
        protocol = ProductionAttemptProtocol(
            ledger,
            binding,
            mutation_guard=guard,
            monotonic_ns=self.clock.monotonic_ns,
            guard_fencing_tokens=(
                int(capability["local_fencing_token"]),
                int(capability["runtime_fencing_token"]),
            ),
        )
        context = AttemptExecutionContext(
            paths=paths,
            binding=binding,
            protocol=protocol,
            slot=dict(slot),
            target=target,
            precondition_digest=str(attempt.get("precondition_digest") or ""),
            attempt_number=len(attempt_ids),
            lock_capability=capability,
            support_session_id=support_session_id,
            authorization_record_id=authorization_record_id,
            predecessor_binding=dict(predecessor) if isinstance(predecessor, Mapping) else None,
        )
        recovery_context_id = f"recovery_{attempt_id}"
        required_support_contexts.append(recovery_context_id)
        command = support.record_command_started(
            ["qualification", "recovery"],
            context={
                "support_session_id": support_session_id,
                "qualification_id": paths.qualification_id,
                "phase": phase,
                "attempt_id": recovery_context_id,
            },
        )
        try:
            result = self.runtime.recover_attempt(context)
        except Exception:
            support.record_command_interrupted(
                command,
                argv=["qualification", "recovery"],
                reason="worker_exception",
            )
            raise RunnerBlocked("worker_exception") from None
        support.record_command_finished(
            command,
            argv=["qualification", "recovery"],
            exit_code=0 if result.get("safe_recovery_complete") is True else 2,
            duration_ms=0,
        )
        if result.get("terminal_persisted") is not True:
            raise RunnerRecoveryRequired(str(result.get("reason") or "manual_recovery_required"))
        return {"action": "terminal", "cycle": dict(cycle), "result": result}

    def _seal_failed_phase(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        qualification: Mapping[str, Any],
        phase: str,
        support: SupportLogRepository,
        support_session_id: str,
        support_owner: dict[str, str],
        required_support_contexts: list[str],
        metrics: dict[str, Any],
        evidence_certificates: list[dict[str, Any]],
        predecessor_binding: Mapping[str, Any] | None,
        chain_start: int,
        runtime_started: bool,
        runtime_ended: bool,
        support_stopped: bool,
    ) -> PhaseResult:
        cleanup_ok = not runtime_started
        if runtime_started and not runtime_ended:
            try:
                ended = self.runtime.end_phase(
                    {"phase": phase, "paths": paths, "support_session_id": support_session_id}
                )
                cleanup_ok = ended.get("status") == "ok" and int(ended.get("orphan_count") or 0) == 0
            except Exception:
                cleanup_ok = False
        coverage = support.validate_command_coverage(
            session_id=support_session_id,
            required_context_ids=required_support_contexts,
        )
        if not support_stopped:
            stopped = support.stop_session(session_id=support_session_id, owner=support_owner)
            support_stopped = stopped.get("status") == "stopped"
        support_bundle = paths.output_dir / f"{phase}_support_strict.zip"
        bundled = support.bundle(session_id=support_session_id, output=support_bundle, redaction="strict")
        bundle_ok = bundled.get("status") == "ok"
        metrics.update(
            {
                "successful_cycles": metrics["terminal_cycle_successes"],
                "terminal_audits": metrics["total_attempts"],
                "completed_stage_results": _completed_stage_results(paths.data_dir, phase),
                "attempt_outcomes": len(ledger.list_records("standalone_production/attempt_outcomes/")),
                "receipts": len(ledger.list_records("standalone_production/receipts/")),
                "phase_cleanup_ok": cleanup_ok,
                "support_bundle_ok": bundle_ok and support_stopped and coverage.get("valid") is True,
                "support_bundles_ok": bundle_ok and support_stopped and coverage.get("valid") is True,
                "hash_chain_ok": ledger.validate_event_chain().get("valid") is True,
                "sqlite_quick_check": ledger.quick_check()["sqlite_quick_check"],
                "boot_session_unchanged": self.clock.boot_session_id()
                == qualification.get("soak_boot_session_id", self.clock.boot_session_id()),
                "environment_matches_canary": True,
                "artifacts_ok": bundle_ok,
            }
        )
        result = PhaseResult(
            metrics=metrics,
            support_bundle=support_bundle,
            support_session_id=support_session_id,
            chain_range={"start": chain_start, "end": len(ledger.list_events())},
            evidence_certificates=evidence_certificates,
            predecessor_binding=dict(predecessor_binding) if isinstance(predecessor_binding, Mapping) else None,
        )
        self._persist_phase_result(paths=paths, ledger=ledger, phase=phase, result=result)
        if not bundle_ok:
            raise RunnerBlocked("support_bundle_failed")
        return result

    def _persist_phase_result(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        phase: str,
        result: PhaseResult,
    ) -> dict[str, Any]:
        qualification = self._read_qualification(ledger, paths.qualification_id)
        phase_bundles = dict(qualification.get("phase_bundles") or {})
        phase_bundles[phase] = str(result.support_bundle.relative_to(paths.qualification_dir))
        support_sessions = dict(qualification.get("phase_support_sessions") or {})
        support_sessions[phase] = result.support_session_id
        chain_ranges = dict(qualification.get("phase_chain_ranges") or {})
        chain_ranges[phase] = dict(result.chain_range)
        existing_evidence = list(qualification.get("evidence_certificates") or [])
        existing_digests = {canonical_digest(item) for item in existing_evidence if isinstance(item, dict)}
        for item in result.evidence_certificates:
            if canonical_digest(item) not in existing_digests:
                existing_evidence.append(dict(item))
                existing_digests.add(canonical_digest(item))
        changes: dict[str, Any] = {
            f"{phase}_metrics": result.metrics,
            "phase_bundles": phase_bundles,
            "phase_support_sessions": support_sessions,
            "phase_chain_ranges": chain_ranges,
            "evidence_certificates": existing_evidence,
            f"{phase}_active_chain_start": None,
            f"{phase}_active_support_session_id": None,
        }
        if result.predecessor_binding is not None:
            changes[f"{phase}_predecessor_binding"] = result.predecessor_binding
        return self._update_qualification(ledger, qualification, changes)

    def _select_target(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        support: SupportLogRepository,
        support_session_id: str,
        lock_handle: Any,
        phase: str,
        slot: Mapping[str, Any],
        predecessor: Mapping[str, Any] | None,
        required_support_contexts: list[str],
        authorization_path: Path,
    ) -> dict[str, Any]:
        for probe_number in range(1, MAX_SELECTION_PROBES_PER_SLOT + 1):
            capability = self._renew_lock_capability(lock_handle)
            self._recheck_action_guards(
                paths=paths,
                ledger=ledger,
                authorization_path=authorization_path,
            )
            probe_id = f"probe_{phase}_{slot['planned_index']:03d}_{probe_number}_{hashlib.sha256(os.urandom(8)).hexdigest()[:8]}"
            binding = SelectionProbeBinding(
                qualification_id=paths.qualification_id,
                phase=phase,
                planned_slot_id=str(slot["planned_slot_id"]),
                probe_id=probe_id,
                local_fencing_token=capability["local_fencing_token"],
                runtime_fencing_token=capability["runtime_fencing_token"],
            )
            ledger.append_event(
                event_id=f"selection_started_{probe_id}",
                event_type="selection_probe_started",
                binding=binding,
                reason_code=None,
                mutation_phase="not_started",
                evidence_digest=canonical_digest({"slot": slot["planned_slot_id"], "probe": probe_number}),
            )
            required_support_contexts.append(probe_id)
            context = {
                "support_session_id": support_session_id,
                "qualification_id": paths.qualification_id,
                "phase": phase,
                "probe_id": probe_id,
            }
            command = support.record_command_started(["qualification", "selection-probe"], context=context)
            try:
                result = self.runtime.selection_probe(
                    {
                        "phase": phase,
                        "slot": dict(slot),
                        "planned_slot_id": slot["planned_slot_id"],
                        "probe_id": probe_id,
                        "selection_probe_binding": binding.to_dict(),
                        "lock_capability": capability,
                        "predecessor_binding": dict(predecessor) if predecessor is not None else None,
                    }
                )
            except Exception:
                support.record_command_interrupted(
                    command,
                    argv=["qualification", "selection-probe"],
                    reason="worker_exception",
                )
                raise RunnerBlocked("worker_exception") from None
            support.record_command_finished(
                command,
                argv=["qualification", "selection-probe"],
                exit_code=0 if result.get("status") in {"eligible", "inconclusive"} else 2,
                duration_ms=0,
            )
            reason = str(result.get("reason") or "") or None
            ledger.append_event(
                event_id=f"selection_terminal_{probe_id}",
                event_type="selection_probe_terminal",
                binding=binding,
                reason_code=reason if reason in {"no_eligible_empty_composer"} else None,
                mutation_phase="not_started",
                evidence_digest=canonical_digest(_redacted_probe_result(result)),
            )
            if result.get("status") == "eligible":
                required = ("target_hash", "target_binding_digest", "precondition_digest")
                if not all(isinstance(result.get(key), str) and result.get(key) for key in required):
                    raise RunnerBlocked("selection_probe_binding_invalid")
                return dict(result)
            if result.get("status") != "inconclusive" or reason != "no_eligible_empty_composer":
                raise RunnerBlocked(reason or "selection_probe_failed")
        raise RunnerBlocked("insufficient_eligible_targets")

    def _renew_lock_capability(self, handle: Any) -> dict[str, Any]:
        handle.local.renew(
            expected_lease_version=handle.local.lease_version,
            expected_fencing_token=handle.local.local_fencing_token,
        )
        handle.runtime.renew(
            expected_lease_version=handle.runtime.lease_version,
            expected_fencing_token=handle.runtime.fencing_token,
        )
        return handle.delegated_capability()

    def _recheck_action_guards(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        authorization_path: Path,
    ) -> None:
        qualification = self._read_qualification(ledger, paths.qualification_id)
        load_canonical_authorization(
            authorization_path,
            data_dir=paths.data_dir,
            now=self.clock.now(),
            qualification_id=paths.qualification_id,
            expected_digest=str(qualification["authorization_digest"]),
        )
        snapshot = verify_user_model_snapshot(
            Path(str(qualification.get("user_model_source_data_dir") or "")),
            expected_digest=str(qualification["snapshot_digest"]),
        )
        if snapshot.get("status") != "ok":
            raise RunnerBlocked(str(snapshot.get("reason") or "user_model_snapshot_drift"))
        recheck = getattr(self.preflight, "recheck_action", None)
        if callable(recheck):
            environment = recheck(
                paths=paths,
                snapshot_digest=qualification["snapshot_digest"],
                authorization_digest=qualification["authorization_digest"],
                qualification_salt=qualification["qualification_salt"],
                expected_environment_fingerprint=qualification["environment_fingerprint"],
            )
            if environment.get("status") != "ok":
                raise RunnerBlocked(str(environment.get("reason") or "environment_drift"))
        if self.clock.boot_session_id() != qualification.get("boot_session_id"):
            raise RunnerBlocked("boot_session_changed")
        wall_now = self.clock.now()
        monotonic_now = self.clock.monotonic_ns()
        previous_wall = qualification.get("last_action_wall_at")
        previous_monotonic = qualification.get("last_action_monotonic_ns")
        if isinstance(previous_wall, str) and wall_now < _parse_iso(previous_wall):
            raise RunnerBlocked("wall_clock_rollback")
        if isinstance(previous_monotonic, int) and monotonic_now < previous_monotonic:
            raise RunnerBlocked("wall_clock_rollback")
        self._update_qualification(
            ledger,
            qualification,
            {
                "last_action_wall_at": _iso(wall_now),
                "last_action_monotonic_ns": monotonic_now,
            },
        )

    def _sleep_until_monotonic(self, deadline_ns: int) -> None:
        while True:
            remaining_ns = deadline_ns - self.clock.monotonic_ns()
            if remaining_ns <= 0:
                return
            self.clock.sleep(remaining_ns / 1_000_000_000)

    def _retain_for_manual_recovery(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        reason: str,
    ) -> dict[str, Any]:
        qualification = self._read_qualification(ledger, paths.qualification_id)
        qualification = self._update_qualification(
            ledger,
            qualification,
            {
                "manual_recovery_required": True,
                "manual_recovery_reason": reason,
                "manual_recovery_requested_at": _iso(self.clock.now()),
            },
        )
        pause = GuiRuntimeLock(state_root=self.runtime_lock_state_root).status().get("safety_pause") or {}
        return {
            "schema_version": 1,
            "status": "recovery_required",
            "qualification_id": paths.qualification_id,
            "active_phase": qualification.get("active_phase"),
            "reason": reason,
            "runtime_safety_pause": pause,
            "qualification_passed": False,
            "next_command": (
                "python3 scripts/tashuo_mac_ios_standalone_production_gate.py resume "
                f"--root-dir {self.root_dir} --qualification-id {paths.qualification_id} "
                "--authorization <auth.json>"
                f"{self._built_artifact_cli_argument()} --json"
            ),
        }

    def _block_and_finalize(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        reason: str,
    ) -> dict[str, Any]:
        qualification = self._read_qualification(ledger, paths.qualification_id)
        current = str(qualification.get("outcome_state") or "created")
        if current not in {"qualification_blocked", "qualification_expired"}:
            qualification = self._update_qualification(
                ledger,
                qualification,
                {"outcome_state": "qualification_blocked", "active_phase": None, "blocked_reason": reason},
            )
        return self._finalize(paths=paths, ledger=ledger, qualification=qualification, reason=reason)

    def _finalize(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        qualification: dict[str, Any],
        reason: str | None,
    ) -> dict[str, Any]:
        evidence_path = paths.output_dir / "qualification_evidence.zip"
        bundle_path = paths.output_dir / "qualification_bundle.zip"
        last_completed = "open"
        sensitive_sentinels: list[str] = []
        try:
            checkpoint = read_finalization_checkpoint(paths.output_dir)
            if checkpoint is not None:
                last_completed = str(checkpoint.get("last_completed_state") or "open")
                reason = reason or _optional_string(checkpoint.get("reason"))

            if paths.data_dir.is_dir() and ledger is not None:
                sensitive_sentinels = self._finalization_sentinels(paths)
                self._require_no_sensitive_sentinels(
                    paths=paths,
                    root=paths.qualification_dir,
                    sentinels=sensitive_sentinels,
                )
                qualification = self._read_qualification(ledger, paths.qualification_id)
                events = ledger.list_events()
                receipt_index = self._attempt_digest_index(ledger)
                phase_bundles = dict(qualification.get("phase_bundles") or {})
                canary_support = _relative_existing(paths.qualification_dir, phase_bundles.get("canary"))
                soak_support = _relative_existing(paths.qualification_dir, phase_bundles.get("soak"))
                canary_certificate = paths.output_dir / "canary_certificate.zip"
                if not canary_certificate.is_file():
                    canary_certificate = None
                support_sessions = dict(qualification.get("phase_support_sessions") or {})
                chain_ranges = dict(qualification.get("phase_chain_ranges") or {})
                phase_metadata = {
                    phase: {
                        "support_session_id": support_sessions.get(phase),
                        "chain_range": chain_ranges.get(phase),
                    }
                    for phase in ("canary", "soak")
                    if support_sessions.get(phase) is not None or chain_ranges.get(phase) is not None
                }
                evidence = seal_qualification_evidence(
                    output_dir=paths.output_dir,
                    qualification_id=paths.qualification_id,
                    outcome_state=str(qualification.get("outcome_state") or "qualification_blocked"),
                    config_hash=str(qualification.get("config_hash") or "unavailable"),
                    environment_fingerprint=dict(qualification.get("environment_fingerprint") or {}),
                    canary_certificate=canary_certificate,
                    events=events,
                    receipt_digest_index=receipt_index,
                    cycle_digest_index=self._cycle_digest_index(ledger),
                    evidence_certificates=list(qualification.get("evidence_certificates") or []),
                    canary_metrics=dict(qualification.get("canary_metrics") or _initial_metrics("canary")),
                    soak_metrics=(
                        dict(qualification["soak_metrics"])
                        if isinstance(qualification.get("soak_metrics"), dict)
                        else None
                    ),
                    canary_support_bundle=canary_support,
                    soak_support_bundle=soak_support,
                    phase_bundle_metadata=phase_metadata,
                )
                if evidence["validation"].get("artifact_valid") is not True:
                    raise RunnerBlocked("qualification_evidence_invalid")
                qualification = self._advance_finalization_ledger(
                    ledger,
                    qualification,
                    target="evidence_written",
                )
                last_completed = "evidence_written"
                self._write_finalization_checkpoint(
                    paths,
                    qualification=qualification,
                    state="evidence_written",
                    last_completed=last_completed,
                    reason=reason,
                    evidence_digest=evidence["digest"],
                )
                provisional = validate_qualification_evidence(evidence_path)
                if provisional.get("artifact_valid") is not True:
                    raise RunnerBlocked("qualification_evidence_provisional_validation_failed")
                self._require_no_sensitive_sentinels(
                    paths=paths,
                    root=paths.qualification_dir,
                    sentinels=sensitive_sentinels,
                )
                qualification = self._advance_finalization_ledger(
                    ledger,
                    qualification,
                    target="provisional_validated",
                )
                last_completed = "provisional_validated"
                self._write_finalization_checkpoint(
                    paths,
                    qualification=qualification,
                    state="provisional_validated",
                    last_completed=last_completed,
                    reason=reason,
                    evidence_digest=evidence["digest"],
                )
                qualification = self._advance_finalization_ledger(
                    ledger,
                    qualification,
                    target="purge_pending",
                )
                last_completed = "purge_pending"
                self._write_finalization_checkpoint(
                    paths,
                    qualification=qualification,
                    state="purge_pending",
                    last_completed=last_completed,
                    reason=reason,
                    evidence_digest=evidence["digest"],
                )
                purge = purge_sensitive_qualification_state(paths)
                last_completed = "purged"
                self._write_finalization_checkpoint_from_evidence(
                    paths,
                    state="purged",
                    last_completed=last_completed,
                    reason=reason,
                    purge_result=purge,
                )
            else:
                provisional = validate_qualification_evidence(evidence_path)
                if provisional.get("artifact_valid") is not True:
                    raise RunnerBlocked("qualification_evidence_missing_after_purge")
                purge = {"status": "purged", "verified": True}
                last_completed = "purged"

            bundle = seal_qualification_bundle_from_evidence(
                output_dir=paths.output_dir,
                qualification_evidence=evidence_path,
                purge_result=purge,
            )
            self._require_no_sensitive_sentinels(
                paths=paths,
                root=paths.output_dir,
                sentinels=sensitive_sentinels,
            )
            last_completed = "bundle_sealed"
            self._write_finalization_checkpoint_from_evidence(
                paths,
                state="bundle_sealed",
                last_completed=last_completed,
                reason=reason,
                purge_result=purge,
                bundle_digest=bundle["digest"],
            )
            validation = validate_production_artifact(bundle_path)
            if validation.get("artifact_valid") is not True:
                raise RunnerBlocked("qualification_bundle_validation_failed")
            last_completed = "bundle_validated"
            self._write_finalization_checkpoint_from_evidence(
                paths,
                state="bundle_validated",
                last_completed=last_completed,
                reason=reason,
                purge_result=purge,
                bundle_digest=bundle["digest"],
            )
            publish_terminal_manifest(qualification_bundle=bundle_path, output_dir=paths.output_dir)
            last_completed = "validated"
            remove_finalization_checkpoint(paths.output_dir)
            _remove_provisional_artifacts(paths.output_dir)
            manifest = _read_json_object(paths.output_dir / "terminal_manifest.json")
            terminal_state = str(manifest.get("terminal_state") or "finalization_failed")
            metrics = manifest.get("soak_metrics") if terminal_state == "protocol_passed" else manifest.get("canary_metrics")
            return {
                "schema_version": 1,
                "status": terminal_state,
                "reason": reason,
                "qualification_id": paths.qualification_id,
                "qualification_passed": validation.get("qualification_passed") is True,
                "claim_code": validation.get("claim_code") or "QUALIFICATION_BLOCKED",
                "claim_text": validation.get("claim_text"),
                "config_hash": manifest.get("config_hash"),
                "manifest_digest": validation.get("manifest_digest"),
                "qualification_bundle_path": bundle["path"],
                "qualification_bundle_digest": bundle["digest"],
                "metrics": dict(metrics) if isinstance(metrics, dict) else {},
                "artifact_validation": validation,
            }
        except (ArtifactViolation, ContractViolation, LedgerConflict, RunnerBlocked) as exc:
            self._mark_finalization_failed(
                paths=paths,
                ledger=ledger,
                last_completed=last_completed,
                reason=str(exc),
            )
            return {
                "schema_version": 1,
                "status": "finalization_failed",
                "reason": str(exc),
                "qualification_id": paths.qualification_id,
                "qualification_passed": False,
                "claim_code": "QUALIFICATION_BLOCKED",
                "claim_text": None,
                "config_hash": qualification.get("config_hash"),
                "manifest_digest": None,
                "qualification_bundle_path": str(bundle_path),
                "qualification_bundle_digest": None,
                "metrics": {},
                "artifact_validation": {
                    "schema_version": 1,
                    "artifact_valid": False,
                    "qualification_passed": False,
                    "reason": str(exc),
                },
            }

    def _finalization_sentinels(self, paths: QualificationPaths) -> list[str]:
        values = set(snapshot_sentinel_candidates(paths.data_dir))
        for name, value in os.environ.items():
            if (
                name == "DATING_BOOST_TEST_KEY"
                or name.endswith("_API_KEY")
                or name.endswith("_TOKEN")
                or name.endswith("_SECRET")
            ) and len(value) >= 8:
                values.add(value)
        return sorted(values)

    @staticmethod
    def _require_no_sensitive_sentinels(
        *,
        paths: QualificationPaths,
        root: Path,
        sentinels: list[str],
    ) -> None:
        result = scrub_sensitive_sentinels(root, sentinels=sentinels)
        if result.get("status") == "ok":
            return
        if paths.data_dir.exists() or paths.work_dir.exists() or paths.vault_dir.exists():
            purge_sensitive_qualification_state(paths)
        raise RunnerBlocked(str(result.get("reason") or "sensitive_sentinel_scan_failed"))

    def _advance_finalization_ledger(
        self,
        ledger: ProductionQualificationLedger,
        qualification: dict[str, Any],
        *,
        target: str,
    ) -> dict[str, Any]:
        current = str(qualification.get("finalization_state") or "open")
        if current == target:
            return qualification
        if current in FINALIZATION_STATES and FINALIZATION_STATES.index(current) > FINALIZATION_STATES.index(target):
            return qualification
        transition_finalization(current, target)
        return self._update_qualification(
            ledger,
            qualification,
            {"finalization_state": target, "finalization_resume_from": target},
        )

    def _write_finalization_checkpoint(
        self,
        paths: QualificationPaths,
        *,
        qualification: Mapping[str, Any],
        state: str,
        last_completed: str,
        reason: str | None,
        evidence_digest: str,
    ) -> dict[str, Any]:
        return write_finalization_checkpoint(
            paths.output_dir,
            {
                "qualification_id": paths.qualification_id,
                "outcome_state": qualification.get("outcome_state"),
                "state": state,
                "last_completed_state": last_completed,
                "reason": reason,
                "evidence_digest": evidence_digest,
            },
        )

    def _write_finalization_checkpoint_from_evidence(
        self,
        paths: QualificationPaths,
        *,
        state: str,
        last_completed: str,
        reason: str | None,
        purge_result: Mapping[str, Any],
        bundle_digest: str | None = None,
    ) -> dict[str, Any]:
        evidence = _read_qualification_evidence_index(paths.output_dir / "qualification_evidence.zip")
        payload: dict[str, Any] = {
            "qualification_id": paths.qualification_id,
            "outcome_state": evidence.get("outcome_state"),
            "state": state,
            "last_completed_state": last_completed,
            "reason": reason,
            "evidence_digest": _file_sha256(paths.output_dir / "qualification_evidence.zip"),
            "purge_result": dict(purge_result),
        }
        if bundle_digest is not None:
            payload["bundle_digest"] = bundle_digest
        return write_finalization_checkpoint(paths.output_dir, payload)

    def _mark_finalization_failed(
        self,
        *,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger | None,
        last_completed: str,
        reason: str,
    ) -> None:
        try:
            existing_checkpoint = read_finalization_checkpoint(paths.output_dir)
        except ArtifactViolation:
            existing_checkpoint = None
        failed_at = _optional_string((existing_checkpoint or {}).get("failed_at")) or _iso(
            self.clock.now()
        )
        cleanup_after = _optional_string((existing_checkpoint or {}).get("cleanup_after")) or _iso(
            self.clock.now() + timedelta(hours=24)
        )
        outcome_state = None
        if paths.data_dir.is_dir() and ledger is not None:
            try:
                qualification = self._read_qualification(ledger, paths.qualification_id)
                outcome_state = qualification.get("outcome_state")
                if qualification.get("finalization_state") != "finalization_failed":
                    self._update_qualification(
                        ledger,
                        qualification,
                        {
                            "finalization_state": "finalization_failed",
                            "finalization_resume_from": last_completed,
                            "finalization_failure_reason": reason,
                        },
                    )
            except (FileNotFoundError, LedgerConflict):
                pass
        if outcome_state is None:
            try:
                outcome_state = _read_qualification_evidence_index(
                    paths.output_dir / "qualification_evidence.zip"
                ).get("outcome_state")
            except (ArtifactViolation, FileNotFoundError):
                outcome_state = "qualification_blocked"
        write_finalization_checkpoint(
            paths.output_dir,
            {
                "qualification_id": paths.qualification_id,
                "outcome_state": outcome_state,
                "state": "finalization_failed",
                "last_completed_state": last_completed,
                "reason": reason,
                "failed_at": failed_at,
                "cleanup_after": cleanup_after,
            },
        )

    def _terminal_result(self, *, paths: QualificationPaths, reason: str | None) -> dict[str, Any]:
        bundle_path = paths.output_dir / "qualification_bundle.zip"
        validation = validate_production_artifact(bundle_path)
        if validation.get("artifact_valid") is not True:
            raise RunnerBlocked("qualification_bundle_validation_failed")
        manifest = _read_json_object(paths.output_dir / "terminal_manifest.json")
        terminal_state = str(manifest.get("terminal_state") or "finalization_failed")
        metrics = manifest.get("soak_metrics") if terminal_state == "protocol_passed" else manifest.get("canary_metrics")
        return {
            "schema_version": 1,
            "status": terminal_state,
            "reason": reason,
            "qualification_id": paths.qualification_id,
            "qualification_passed": validation.get("qualification_passed") is True,
            "claim_code": validation.get("claim_code") or "QUALIFICATION_BLOCKED",
            "claim_text": validation.get("claim_text"),
            "config_hash": manifest.get("config_hash"),
            "manifest_digest": validation.get("manifest_digest"),
            "qualification_bundle_path": str(bundle_path),
            "qualification_bundle_digest": _file_sha256(bundle_path),
            "metrics": dict(metrics) if isinstance(metrics, dict) else {},
            "artifact_validation": validation,
        }

    def _status_one(self, qualification_id: str) -> dict[str, Any] | None:
        directory = self.root_dir / qualification_id
        if not directory.is_dir():
            return None
        terminal_path = directory / "output" / "terminal_manifest.json"
        if terminal_path.is_file():
            try:
                manifest = json.loads(terminal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema_version": 1, "qualification_id": qualification_id, "status": "finalization_failed"}
            return {
                "schema_version": 1,
                "qualification_id": qualification_id,
                "status": manifest.get("terminal_state"),
                "claim_code": manifest.get("claim_code"),
                "config_hash": manifest.get("config_hash"),
                "manifest_digest": manifest.get("manifest_content_digest"),
                "next_command": None,
            }
        data_dir = directory / "data"
        if not data_dir.is_dir():
            try:
                checkpoint = read_finalization_checkpoint(directory / "output")
            except ArtifactViolation:
                checkpoint = None
            state = str((checkpoint or {}).get("state") or "finalization_failed")
            return {
                "schema_version": 1,
                "qualification_id": qualification_id,
                "status": state,
                "claim_code": None,
                "config_hash": None,
                "next_command": (
                    f"python3 scripts/tashuo_mac_ios_standalone_production_gate.py finalize --root-dir {self.root_dir} "
                    f"--qualification-id {qualification_id} --json"
                ),
            }
        try:
            qualification = self._read_qualification(ProductionQualificationLedger(data_dir), qualification_id)
        except (FileNotFoundError, LedgerConflict):
            return {"schema_version": 1, "qualification_id": qualification_id, "status": "created"}
        state = str(qualification.get("outcome_state") or "unknown")
        manual_recovery_required = qualification.get("manual_recovery_required") is True
        next_command = None
        if state == "canary_passed":
            if self._canary_wait_expired(qualification):
                state = "qualification_expired_pending_cleanup"
                next_command = (
                    f"python3 scripts/tashuo_mac_ios_standalone_production_gate.py finalize --root-dir {self.root_dir} "
                    f"--qualification-id {qualification_id} --json"
                )
            else:
                next_command = self._soak_command(qualification_id, str(qualification.get("canary_accept_token") or ""))
        elif state in {"canary_running", "soak_running"}:
            next_command = (
                f"python3 scripts/tashuo_mac_ios_standalone_production_gate.py resume --root-dir {self.root_dir} "
                f"--qualification-id {qualification_id} --authorization <authorization-path>"
                f"{self._built_artifact_cli_argument()} --json"
            )
        elif state in {"qualification_blocked", "qualification_expired", "soak_criteria_met"}:
            next_command = (
                f"python3 scripts/tashuo_mac_ios_standalone_production_gate.py finalize --root-dir {self.root_dir} "
                f"--qualification-id {qualification_id} --json"
            )
        return {
            "schema_version": 1,
            "qualification_id": qualification_id,
            "status": "recovery_required" if manual_recovery_required else state,
            "claim_code": "CANARY_PASSED_SOAK_NOT_RUN" if state == "canary_passed" else None,
            "config_hash": qualification.get("config_hash"),
            "manual_recovery_reason": (
                qualification.get("manual_recovery_reason") if manual_recovery_required else None
            ),
            "next_command": next_command,
        }

    def _existing_paths(self, qualification_id: str) -> QualificationPaths:
        directory = (self.root_dir / qualification_id).resolve()
        if directory.parent != self.root_dir or not directory.is_dir():
            raise RunnerBlocked("qualification_not_found")
        data = directory / "data"
        output = directory / "output"
        if data.is_dir():
            marker = JsonStorage(data).read_json(
                Path("standalone_production/ownership.json"),
                expected_schema_version=1,
            )
        else:
            marker = None
            for candidate in (
                output / "qualification_identity.json",
                output / "terminal_manifest.json",
                output / "finalization_checkpoint.json",
            ):
                if candidate.is_file():
                    marker = _read_json_object(candidate)
                    break
            if marker is None:
                raise RunnerBlocked("qualification_ownership_missing")
        if marker.get("qualification_id") != qualification_id:
            raise RunnerBlocked("qualification_ownership_mismatch")
        return QualificationPaths(
            qualification_id=qualification_id,
            qualification_dir=directory,
            data_dir=data,
            work_dir=directory / "work",
            vault_dir=directory / "vault",
            output_dir=output,
            runner_lock=directory / "runner.lock",
            ownership_digest=canonical_digest(marker),
        )

    def _read_qualification(self, ledger: ProductionQualificationLedger, qualification_id: str) -> dict[str, Any]:
        return ledger.read_record(f"{QUALIFICATION_RECORD_PREFIX}{qualification_id}.json")

    def _update_qualification(
        self,
        ledger: ProductionQualificationLedger,
        current: dict[str, Any],
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        return ledger.compare_and_swap(
            f"{QUALIFICATION_RECORD_PREFIX}{current['qualification_id']}.json",
            expected_version=current["ledger_version"],
            changes=changes,
        )

    def _attempt_digest_index(self, ledger: ProductionQualificationLedger) -> list[dict[str, Any]]:
        receipts = {
            str(item["payload"].get("attempt_id")): item["payload"]
            for item in ledger.list_records("standalone_production/receipts/")
        }
        outcomes = {
            str(item["payload"].get("attempt_id")): item["payload"]
            for item in ledger.list_records("standalone_production/attempt_outcomes/")
        }
        attempts = {
            str(item["payload"].get("attempt_id")): item["payload"]
            for item in ledger.list_records("standalone_production/attempts/")
        }
        stage_by_attempt: dict[str, list[dict[str, Any]]] = {}
        for stage in JsonStorage(ledger.data_dir).read_jsonl(Path("audit/stage_results.jsonl")):
            raw_binding = stage.get("qualification_binding")
            if not isinstance(raw_binding, dict):
                continue
            attempt_id = str(raw_binding.get("attempt_id") or "")
            certificate = {
                "qualification_binding": raw_binding,
                "result_status": stage.get("result_status"),
                "stage_attempt_status": stage.get("stage_attempt_status"),
                "staged_text_verified": stage.get("staged_text_verified"),
                "staged_text_verification_status": (
                    (stage.get("staged_text_verification") or {}).get("status")
                    if isinstance(stage.get("staged_text_verification"), dict)
                    else None
                ),
                "target_verification_status": (
                    (stage.get("target_verification") or {}).get("status")
                    if isinstance(stage.get("target_verification"), dict)
                    else None
                ),
                "stage_mode": (stage.get("evidence") or {}).get("stage_mode"),
                "live_send_executed": (stage.get("evidence") or {}).get("live_send_executed"),
            }
            certificate["certificate_digest"] = canonical_digest(certificate)
            stage_by_attempt.setdefault(attempt_id, []).append(certificate)
        index: list[dict[str, Any]] = []
        for attempt_id in sorted(set(attempts) | set(outcomes) | set(receipts)):
            attempt = attempts.get(attempt_id) or {}
            outcome = outcomes.get(attempt_id)
            receipt = receipts.get(attempt_id)
            entry = {
                "attempt_id": attempt_id,
                "qualification_binding": attempt.get("qualification_binding"),
                "mutation_phase": attempt.get("mutation_phase"),
                "attempt_record_digest": canonical_digest(attempt) if attempt else None,
                "outcome": outcome,
                "outcome_digest": canonical_digest(outcome) if outcome is not None else None,
                "receipt": receipt,
                "receipt_digest": canonical_digest(receipt) if receipt is not None else None,
                "stage_result_certificates": stage_by_attempt.get(attempt_id, []),
            }
            entry["entry_digest"] = canonical_digest(entry)
            index.append(entry)
        return index

    def _cycle_digest_index(self, ledger: ProductionQualificationLedger) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for item in ledger.list_records("standalone_production/cycles/"):
            cycle = item["payload"]
            predecessor = cycle.get("predecessor_binding")
            summary = {
                "qualification_id": cycle.get("qualification_id"),
                "phase": cycle.get("phase"),
                "cycle_index": cycle.get("cycle_index"),
                "planned_slot_id": cycle.get("planned_slot_id"),
                "mode": cycle.get("mode"),
                "state": cycle.get("state"),
                "attempt_ids": list(cycle.get("attempt_ids") or []),
                "final_attempt_id": cycle.get("final_attempt_id"),
                "actual_start_ns": cycle.get("actual_start_ns"),
                "commit_index": cycle.get("commit_index"),
                "predecessor": (
                    {
                        "target_hash": predecessor.get("target_hash"),
                        "target_binding_digest": predecessor.get("target_binding_digest"),
                        "source_cycle_index": predecessor.get("source_cycle_index"),
                        "source_planned_slot_id": predecessor.get("source_planned_slot_id"),
                        "source_mode": predecessor.get("source_mode"),
                    }
                    if isinstance(predecessor, dict)
                    else None
                ),
            }
            summary["cycle_digest"] = canonical_digest(summary)
            entries.append(summary)
        return sorted(entries, key=lambda item: (str(item.get("phase")), int(item.get("commit_index") or 0)))

    def _soak_command(self, qualification_id: str, token: str) -> str:
        return (
            f"python3 scripts/tashuo_mac_ios_standalone_production_gate.py soak --root-dir {self.root_dir} "
            f"--qualification-id {qualification_id} --accept-canary {token} "
            f"--authorization <authorization-path>{self._built_artifact_cli_argument()} --json"
        )

    def _built_artifact_cli_argument(self) -> str:
        if self.built_artifact is None:
            return ""
        return f" --built-artifact {shlex.quote(str(self.built_artifact))}"


class DefaultProductionPreflight:
    def __init__(
        self,
        *,
        source_checkout: Path,
        built_artifact: Path | None = None,
        provider_probe: Callable[[Mapping[str, Any], str], Mapping[str, Any]] | None = None,
        ui_environment_probe: Callable[[], Mapping[str, Any]] | None = None,
    ):
        self.source_checkout = source_checkout
        self.built_artifact = built_artifact
        self.provider_probe = provider_probe or _provider_identity_probe
        self.ui_environment_probe = ui_environment_probe or _mac_ui_environment_probe

    def run(self, **kwargs: Any) -> dict[str, Any]:
        paths = kwargs["paths"]
        try:
            release = release_doctor()
            if release.get("status") != "ok":
                return _preflight_block("release_doctor_failed")
            skill = run_codex_adapter_doctor(paths.data_dir)
            if skill.get("status") != "ok":
                return _preflight_block("skill_doctor_failed")
            store = ProductionDataStore(paths.data_dir)
            migration = store.migrate()
            if migration.get("status") != "ok":
                return _preflight_block("data_migrate_failed")
            doctor = store.doctor()
            if doctor.get("status") != "ok":
                return _preflight_block("data_doctor_failed")
            capabilities = build_capabilities(paths.data_dir)
            guidance = capabilities.get("managed_live_send_guidance") or {}
            if guidance.get("direct_harness_scope") != "executor_internal_only":
                return _preflight_block("direct_harness_scope_invalid")
            storage_capabilities = capabilities.get("storage_capabilities") or {}
            if (
                storage_capabilities.get("storage_backend") != "sqlite"
                or storage_capabilities.get("encrypted_default") is not True
            ):
                return _preflight_block("encrypted_sqlite_storage_required")
            schema_versions = capabilities.get("schema_versions") or {}
            agent_capabilities = capabilities.get("agent_native_capabilities") or {}
            if (
                schema_versions.get("standalone_production_qualification") != 1
                or agent_capabilities.get("tashuo_standalone_production_qualification") is not True
                or agent_capabilities.get("tashuo_standalone_production_qualification_runtime")
                != "mac-ios-app"
                or agent_capabilities.get("tashuo_standalone_production_qualification_send_mode")
                != "stage"
                or agent_capabilities.get(
                    "tashuo_standalone_production_qualification_live_send_qualified"
                )
                is not False
            ):
                return _preflight_block("production_qualification_capability_invalid")
            scope = RuntimeScopeRepository(paths.data_dir).select(
                app_id="tashuo",
                runtime="mac-ios-app",
                source="production_qualification_preflight",
            )
            if scope.get("status") != "selected":
                return _preflight_block(str(scope.get("reason") or "runtime_scope_mismatch"))
            selected = RuntimeScopeRepository(paths.data_dir).read() or {}
            if selected.get("selected_app_id") != "tashuo" or selected.get("selected_runtime_key") != "mac_ios_app":
                return _preflight_block("runtime_scope_mismatch")
            model_config = _production_model_config()
            credential_env = str(model_config["api_key_env"])
            credential = os.environ.get(credential_env)
            if not credential:
                return _preflight_block("provider_credential_missing")
            provider = self.provider_probe(model_config, credential)
            if provider.get("status") != "ok":
                return _preflight_block(str(provider.get("reason") or "provider_identity_probe_failed"))
            components = self._collect_components(
                snapshot_digest=kwargs["snapshot_digest"],
                authorization_digest=kwargs["authorization_digest"],
                model_config=model_config,
                provider_identity=provider,
            )
            fingerprint = build_environment_fingerprint(
                components,
                qualification_salt=kwargs["qualification_salt"],
                credential=credential,
            )
            expected = kwargs.get("expected_environment_fingerprint")
            if expected is not None and environment_fingerprints_match(expected, fingerprint).get("matches") is not True:
                return _preflight_block("environment_drift")
            return {
                "status": "ok",
                "environment_fingerprint": fingerprint,
                "config_hash": compute_config_hash(fingerprint),
                "provider_identifier": fingerprint["model"]["provider_identifier"],
                "checks": {
                    "direct_harness_scope": "executor_internal_only",
                    "encrypted_storage": "sqlite",
                    "production_qualification_capability": "stage_only",
                    "release_doctor": "ok",
                    "skill_doctor": "ok",
                    "data_migrate": "ok",
                    "data_doctor": "ok",
                    "runtime_scope": "tashuo/mac-ios-app",
                    "provider_identity_probe": "ok",
                },
            }
        except (OSError, RuntimeError, ValueError, ContractViolation) as exc:
            return _preflight_block(_safe_reason(exc))

    def recheck_action(self, **kwargs: Any) -> dict[str, Any]:
        try:
            model_config = _production_model_config()
            credential = os.environ.get(str(model_config["api_key_env"]))
            if not credential:
                return _preflight_block("provider_credential_missing")
            expected_fingerprint = kwargs["expected_environment_fingerprint"]
            expected_model = (
                expected_fingerprint.get("model")
                if isinstance(expected_fingerprint, Mapping)
                and isinstance(expected_fingerprint.get("model"), Mapping)
                else {}
            )
            provider = {
                "stable_provider_identifier": expected_model.get("provider_identifier"),
                "response_model_identifier": expected_model.get("response_model_identifier"),
                "revision_identifier": expected_model.get("provider_revision_identifier"),
            }
            components = self._collect_components(
                snapshot_digest=kwargs["snapshot_digest"],
                authorization_digest=kwargs["authorization_digest"],
                model_config=model_config,
                provider_identity=provider,
            )
            fingerprint = build_environment_fingerprint(
                components,
                qualification_salt=kwargs["qualification_salt"],
                credential=credential,
            )
            comparison = environment_fingerprints_match(expected_fingerprint, fingerprint)
            if comparison.get("matches") is not True:
                return {
                    "status": "blocked",
                    "reason": "environment_drift",
                    "drift_fields": comparison.get("drift_fields"),
                }
            return {"status": "ok", "environment_fingerprint": fingerprint}
        except (OSError, RuntimeError, ValueError, ContractViolation) as exc:
            return _preflight_block(_safe_reason(exc))

    def _collect_components(
        self,
        *,
        snapshot_digest: str,
        authorization_digest: str,
        model_config: Mapping[str, Any],
        provider_identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        package_root = Path(__file__).resolve().parents[2]
        execution = _execution_fingerprint(
            source_checkout=self.source_checkout,
            built_artifact=self.built_artifact,
            loaded_package_root=package_root,
        )
        ui_environment = self.ui_environment_probe()
        display = ui_environment.get("display")
        permissions = ui_environment.get("permissions")
        if not isinstance(display, Mapping) or not isinstance(permissions, Mapping):
            raise RunnerBlocked("display_fingerprint_unavailable")
        return {
            "tool_version": __version__,
            "execution": execution,
            "loaded_package_digest": _package_digest(package_root),
            "dependency_snapshot_digest": _dependency_digest(),
            "python": {"implementation": platform.python_implementation(), "version": sys.version},
            "system": _system_fingerprint(),
            "display": dict(display),
            "permissions": dict(permissions),
            "tashuo": _tashuo_bundle_fingerprint(),
            "runtime": {
                "app_id": "tashuo",
                "runtime": "mac-ios-app",
                "send_mode": "stage",
                "managed_gui_send": False,
                "staging_input_backend": "guarded_macos_accessibility",
                "runtime_lock_protocol_version": 1,
            },
            "user_model_snapshot_digest": snapshot_digest,
            "model": {
                **dict(model_config),
                "provider_identifier": provider_identity.get("stable_provider_identifier"),
                "response_model_identifier": provider_identity.get("response_model_identifier"),
                "provider_revision_identifier": provider_identity.get("revision_identifier"),
            },
            "authorization_digest": authorization_digest,
        }


def _initial_metrics(phase: str) -> dict[str, Any]:
    return {
        "committed_cycles": 0,
        "successful_cycles": 0,
        "terminal_cycle_successes": 0,
        "first_attempt_successes": 0,
        "retried_cycles": 0,
        "total_attempts": 0,
        "message_list_cycles": 0,
        "current_thread_cycles": 0,
        "safety_violations": 0,
        "actual_start_ns": [] if phase == "soak" else [],
    }


def _completed_stage_results(data_dir: Path, phase: str) -> int:
    count = 0
    for event in JsonStorage(data_dir).read_jsonl(Path("audit/stage_results.jsonl")):
        binding = event.get("qualification_binding") if isinstance(event.get("qualification_binding"), dict) else {}
        if binding.get("phase") == phase and event.get("result_status") == "succeeded":
            count += 1
    return count


def _all_cycle_attempt_ids(ledger: ProductionQualificationLedger) -> list[str]:
    attempt_ids: list[str] = []
    for record in ledger.list_records("standalone_production/cycles/"):
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        attempt_ids.extend(str(item) for item in payload.get("attempt_ids") or [])
    return attempt_ids


def _predecessor_matches_slot(predecessor: Any, slot: Mapping[str, Any]) -> bool:
    if not isinstance(predecessor, Mapping):
        return False
    return (
        predecessor.get("source_mode") == "message-list"
        and predecessor.get("source_planned_slot_id")
        == slot.get("deferred_predecessor_planned_slot_id", slot.get("predecessor_planned_slot_id"))
        and isinstance(predecessor.get("target_hash"), str)
        and isinstance(predecessor.get("target_binding_digest"), str)
    )


def _persisted_attempt_result(
    ledger: ProductionQualificationLedger,
    attempt_id: str,
    *,
    outcome: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        worker_result = ledger.read_record(f"standalone_production/worker_results/{attempt_id}.json")
    except FileNotFoundError:
        worker_result = {}
    mutation_phase = str(outcome.get("mutation_phase") or receipt.get("mutation_phase") or "not_started")
    mutation_started = MUTATION_PHASE_INDEX.get(mutation_phase, 999) >= MUTATION_PHASE_INDEX["stage_mutation_intent"]
    safe_recovery = (
        not mutation_started
        or (
            isinstance(receipt.get("cleanup_digest"), str)
            and isinstance(receipt.get("negative_send_digest"), str)
        )
    )
    return {
        "schema_version": 1,
        "status": outcome.get("status"),
        "reason": outcome.get("reason_code"),
        "mutation_phase": mutation_phase,
        "safe_recovery_complete": safe_recovery,
        "terminal_evidence_digest": outcome.get("terminal_evidence_digest"),
        "receipt": dict(receipt),
        "predecessor_binding": worker_result.get("predecessor_binding"),
        "evidence_certificate": worker_result.get("evidence_certificate"),
        "terminal_persisted": True,
        "safety_violations": 0 if safe_recovery else 1,
    }


def _relative_existing(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def _redacted_preflight(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"status": value.get("status"), "checks": dict(value.get("checks") or {})}


def _redacted_probe_result(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": value.get("status"),
        "reason": value.get("reason"),
        "target_hash": value.get("target_hash"),
        "target_binding_digest": value.get("target_binding_digest"),
        "precondition_digest": value.get("precondition_digest"),
    }


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactViolation("artifact_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ArtifactViolation("artifact_json_invalid")
    return payload


def _read_qualification_evidence_index(path: Path) -> dict[str, Any]:
    import zipfile

    try:
        with zipfile.ZipFile(path, "r") as archive:
            payload = json.loads(archive.read("evidence_index.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ArtifactViolation("qualification_evidence_invalid") from exc
    if not isinstance(payload, dict):
        raise ArtifactViolation("qualification_evidence_invalid")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactViolation("artifact_unreadable") from exc
    return digest.hexdigest()


def _remove_provisional_artifacts(output_dir: Path) -> None:
    for name in (
        "qualification_evidence.zip",
        "qualification_evidence.zip.sha256",
        "canary_certificate.zip",
        "canary_certificate.zip.sha256",
        "qualification_identity.json",
    ):
        try:
            (output_dir / name).unlink()
        except FileNotFoundError:
            continue


def _execution_fingerprint(
    *,
    source_checkout: Path,
    built_artifact: Path | None,
    loaded_package_root: Path,
) -> dict[str, Any]:
    if built_artifact is None:
        return _source_execution_fingerprint(source_checkout)
    artifact = built_artifact.expanduser().resolve()
    if not artifact.is_file() or artifact.suffix != ".whl":
        raise RunnerBlocked("built_artifact_invalid")
    source_package = (source_checkout.expanduser().resolve() / "dating_boost").resolve()
    loaded_root = loaded_package_root.expanduser().resolve()
    if loaded_root == source_package or loaded_root.is_relative_to(source_package):
        raise RunnerBlocked("built_artifact_not_loaded")
    artifact_package_digest = _wheel_package_digest(artifact)
    loaded_package_digest = _package_digest(loaded_root)
    if artifact_package_digest != loaded_package_digest:
        raise RunnerBlocked("built_artifact_package_digest_mismatch")
    return {
        "mode": "built_artifact",
        "artifact_digest": _file_sha256(artifact),
        "artifact_package_digest": artifact_package_digest,
    }


def _source_execution_fingerprint(root: Path) -> dict[str, Any]:
    status = _run_command(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
    commit = _run_command(["git", "rev-parse", "HEAD"], cwd=root)
    tree = _run_command(["git", "rev-parse", "HEAD^{tree}"], cwd=root)
    return {
        "mode": "source_checkout",
        "git_commit": commit.strip(),
        "tree_digest": tree.strip(),
        "clean": not bool(status.strip()),
    }


def _package_digest(root: Path) -> str:
    entries = []
    for path in sorted(root.rglob("*.py")):
        if path.is_file():
            entries.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return canonical_digest(entries)


def _wheel_package_digest(path: Path) -> str:
    entries: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.startswith("dating_boost/") or not name.endswith(".py"):
                    continue
                relative = name.removeprefix("dating_boost/")
                entries.append((relative, hashlib.sha256(archive.read(name)).hexdigest()))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise RunnerBlocked("built_artifact_invalid") from exc
    if not entries:
        raise RunnerBlocked("built_artifact_invalid")
    return canonical_digest(entries)


def _dependency_digest() -> str:
    entries = []
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name") or ""
        direct_url = distribution.read_text("direct_url.json")
        entries.append({"name": name.lower(), "version": distribution.version, "direct_url": direct_url})
    return canonical_digest(sorted(entries, key=lambda item: (item["name"], item["version"])))


def _system_fingerprint() -> dict[str, Any]:
    return {
        "product_version": _run_command(["/usr/bin/sw_vers", "-productVersion"]).strip(),
        "build_version": _run_command(["/usr/bin/sw_vers", "-buildVersion"]).strip(),
        "architecture": platform.machine(),
        "boot_session_id": boot_session_id(),
    }


def _production_model_config() -> dict[str, Any]:
    model_identifier = os.environ.get("DATING_BOOST_PRODUCTION_MODEL", "MiniMax-M3")
    return {
        "backend": "minimax",
        "vision_backend": "minimax",
        "model_identifier": model_identifier,
        "vision_model_identifier": model_identifier,
        "base_url": os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1"),
        "api_key_env": os.environ.get("DATING_BOOST_MINIMAX_API_KEY_ENV", "MINIMAX_API_KEY"),
    }


def _provider_identity_probe(model_config: Mapping[str, Any], credential: str) -> dict[str, Any]:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=credential,
            base_url=str(model_config["base_url"]),
            timeout=30.0,
        )
        response = client.chat.completions.create(
            model=str(model_config["model_identifier"]),
            messages=[
                {"role": "system", "content": "Return only OK."},
                {"role": "user", "content": "Identity probe."},
            ],
            max_tokens=1,
            extra_body={"thinking": {"type": "disabled"}},
        )
    except Exception:
        return _preflight_block("provider_identity_probe_failed")
    response_model = str(getattr(response, "model", "") or "").strip()
    revision = str(getattr(response, "system_fingerprint", "") or "").strip() or None
    deployment = str(getattr(response, "deployment_id", "") or "").strip() or None
    if not response_model:
        return _preflight_block("provider_response_model_missing")
    return {
        "status": "ok",
        "response_model_identifier": response_model,
        "revision_identifier": revision,
        "stable_provider_identifier": deployment or revision,
    }


def _mac_ui_environment_probe() -> dict[str, Any]:
    override = os.environ.get("DATING_BOOST_MAC_UI_ENVIRONMENT_JSON")
    if override:
        value = json.loads(override)
        if isinstance(value, dict):
            return value
        raise RunnerBlocked("display_fingerprint_invalid")
    if platform.system() != "Darwin":
        raise RunnerBlocked("macos_required")
    script = r'''
import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

let screens: [[String: Any]] = AppKit.NSScreen.screens.enumerated().map { index, screen in
    let logical = screen.frame
    let pixel = screen.convertRectToBacking(logical)
    return [
        "index": index,
        "logical_bounds": ["x": logical.origin.x, "y": logical.origin.y, "width": logical.size.width, "height": logical.size.height],
        "pixel_bounds": ["x": pixel.origin.x, "y": pixel.origin.y, "width": pixel.size.width, "height": pixel.size.height],
        "scale_factor": screen.backingScaleFactor,
        "name": screen.localizedName
    ]
}
let appearance = Foundation.UserDefaults.standard.string(forKey: "AppleInterfaceStyle") ?? "Light"
let payload: [String: Any] = [
    "display": ["screens": screens, "appearance": appearance, "locale": Foundation.Locale.current.identifier],
    "permissions": [
        "accessibility": ApplicationServices.AXIsProcessTrusted(),
        "screen_recording": CoreGraphics.CGPreflightScreenCaptureAccess()
    ]
]
let data = try! Foundation.JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
'''
    raw = _run_command(["/usr/bin/swift", "-e", script])
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RunnerBlocked("display_fingerprint_invalid")
    return value


def _tashuo_bundle_fingerprint() -> dict[str, Any]:
    raw = os.environ.get("DATING_BOOST_TASHUO_BUNDLE_FINGERPRINT_JSON")
    if raw:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RunnerBlocked("tashuo_bundle_fingerprint_invalid")
        return value
    candidates: list[Path] = []
    try:
        matches = _run_command(
            ["/usr/bin/mdfind", "kMDItemCFBundleIdentifier == 'com.intelcupid.tashuo'"]
        ).splitlines()
        candidates.extend(Path(item).expanduser() for item in matches if item.strip())
    except RunnerBlocked:
        pass
    for root in (Path("/Applications"), Path.home() / "Applications"):
        if root.is_dir():
            candidates.extend(root.glob("*.app"))
    for bundle in sorted({candidate.resolve() for candidate in candidates if candidate.suffix == ".app"}):
        layouts = (
            (bundle / "Contents" / "Info.plist", bundle / "Contents" / "MacOS"),
            (bundle / "WrappedBundle" / "Info.plist", bundle / "WrappedBundle"),
        )
        for info_path, executable_root in layouts:
            try:
                with info_path.open("rb") as handle:
                    info = plistlib.load(handle)
            except (OSError, plistlib.InvalidFileException):
                continue
            if info.get("CFBundleIdentifier") != "com.intelcupid.tashuo":
                continue
            executable = executable_root / str(info.get("CFBundleExecutable") or "")
            if not executable.is_file():
                raise RunnerBlocked("tashuo_bundle_executable_missing")
            return {
                "bundle_id": "com.intelcupid.tashuo",
                "short_version": str(info.get("CFBundleShortVersionString") or ""),
                "build_version": str(info.get("CFBundleVersion") or ""),
                "executable_digest": _file_sha256(executable),
                "bundle_layout": "mac_ios_wrapped" if "WrappedBundle" in info_path.parts else "macos_contents",
            }
    raise RunnerBlocked("tashuo_bundle_fingerprint_unavailable")


def _run_command(command: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise RunnerBlocked(f"command_failed:{result.returncode}")
    return result.stdout


def _preflight_block(reason: str) -> dict[str, Any]:
    return {"status": "blocked", "reason": reason}


def _safe_reason(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason:
        return reason
    text = str(exc).strip()
    return text if text and len(text) <= 120 and " " not in text else type(exc).__name__


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunnerBlocked("wall_clock_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise RunnerBlocked("wall_clock_timestamp_invalid")
    return parsed.astimezone(UTC)


def _unconfigured_runtime() -> QualificationRuntime:
    from dating_boost.apps.tashuo.standalone_production_runtime import TaShuoStandaloneProductionRuntime

    return TaShuoStandaloneProductionRuntime()
