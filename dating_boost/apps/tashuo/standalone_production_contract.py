from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
PROTOCOL_VERSION = "tashuo-standalone-stage-production-v1"
REASON_SCHEMA_VERSION = 1
SCHEDULER_VERSION = "planned-slots-v1"
SHARED_RUNTIME_LOCK_PROTOCOL_VERSION = 1

CANARY_CYCLE_COUNT = 10
SOAK_CYCLE_COUNT = 100
SOAK_MESSAGE_LIST_CYCLES = 80
SOAK_CURRENT_THREAD_CYCLES = 20
SOAK_MIN_DURATION_NS = 8 * 60 * 60 * 1_000_000_000
SOAK_INTERVAL_NS = math.ceil(SOAK_MIN_DURATION_NS / (SOAK_CYCLE_COUNT - 1))
CANARY_VALIDITY_SECONDS = 24 * 60 * 60
SELECTION_PROBE_TIMEOUT_SECONDS = 120
ATTEMPT_TIMEOUT_SECONDS = 300
LEASE_SECONDS = 5 * 60
HEARTBEAT_SECONDS = 30
MAX_HEARTBEAT_AGE_SECONDS = 90
SOAK_MAX_ATTEMPTS_PER_CYCLE = 3
SOAK_RETRY_DELAYS_SECONDS = (30, 120)
MAX_SELECTION_PROBES_PER_SLOT = 3

OUTCOME_STATES = frozenset(
    {
        "created",
        "preflight_passed",
        "canary_running",
        "canary_passed",
        "soak_running",
        "soak_criteria_met",
        "qualification_blocked",
        "qualification_expired",
    }
)
OUTCOME_TERMINAL_STATES = frozenset({"qualification_blocked", "qualification_expired"})
OUTCOME_TRANSITIONS = {
    "created": frozenset({"preflight_passed", "qualification_blocked"}),
    "preflight_passed": frozenset({"canary_running", "qualification_blocked"}),
    "canary_running": frozenset({"canary_passed", "qualification_blocked"}),
    "canary_passed": frozenset({"soak_running", "qualification_blocked", "qualification_expired"}),
    "soak_running": frozenset({"soak_criteria_met", "qualification_blocked"}),
    "soak_criteria_met": frozenset({"qualification_blocked"}),
    "qualification_blocked": frozenset(),
    "qualification_expired": frozenset(),
}

FINALIZATION_STATES = (
    "open",
    "evidence_written",
    "provisional_validated",
    "purge_pending",
    "purged",
    "bundle_sealed",
    "bundle_validated",
    "manifest_published",
    "validated",
)
FINALIZATION_TERMINAL_STATES = frozenset({"validated"})
USER_TERMINAL_STATES = frozenset({"protocol_passed", "blocked_finalized", "expired_finalized"})

MUTATION_PHASES = (
    "not_started",
    "surface_navigation_started",
    "target_bound",
    "composer_empty_verified",
    "pre_stage_revalidated",
    "stage_mutation_intent",
    "stage_mutation_completed",
    "staged_verified",
    "cleanup_started",
    "cleanup_verified",
    "negative_send_verified",
    "stage_consumed",
    "attempt_terminal_committed",
)
MUTATION_PHASE_INDEX = {name: index for index, name in enumerate(MUTATION_PHASES)}

RETRYABLE_REASONS = frozenset(
    {
        "model_timeout",
        "vision_timeout",
        "app_launch_transient",
        "capture_transient",
        "prepare_message_page_transient",
        "exact_target_relocation_transient",
        "worker_timeout_before_mutation",
    }
)

REGISTERED_REASONS = frozenset(
    RETRYABLE_REASONS
    | {
        "candidate_composer_occupied",
        "no_eligible_empty_composer",
        "insufficient_eligible_targets",
        "authorization_invalid",
        "authorization_drift",
        "environment_drift",
        "runtime_scope_mismatch",
        "runtime_lock_conflict",
        "runtime_safety_paused",
        "support_ownership_conflict",
        "target_mismatch",
        "thread_mismatch",
        "payload_mismatch",
        "precondition_mismatch",
        "qualification_binding_mismatch",
        "fencing_mismatch",
        "composer_state_unknown",
        "cleanup_state_unknown",
        "negative_send_unverified",
        "live_send_evidence_detected",
        "user_or_external_interference_detected",
        "receipt_conflict",
        "terminal_audit_missing",
        "stage_result_cardinality_invalid",
        "hash_chain_invalid",
        "worker_identity_mismatch",
        "worker_exception",
        "worker_result_missing",
        "worker_timeout_after_mutation",
        "provider_identity_drift",
        "boot_session_changed",
        "wall_clock_rollback",
        "canary_expired",
        "finalization_failed",
        "preflight_blocked",
    }
)


class ContractViolation(ValueError):
    def __init__(self, reason: str, **details: Any):
        super().__init__(reason)
        self.reason = reason
        self.details = details


@dataclass(frozen=True, slots=True)
class QualificationBinding:
    qualification_id: str
    phase: str
    cycle_index: int
    attempt_id: str
    local_fencing_token: int
    runtime_fencing_token: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.schema_version != SCHEMA_VERSION
            or not _identifier(self.qualification_id)
            or self.phase not in {"canary", "soak"}
            or not isinstance(self.cycle_index, int)
            or isinstance(self.cycle_index, bool)
            or self.cycle_index < 1
            or not _identifier(self.attempt_id)
            or not _positive_integer(self.local_fencing_token)
            or not _positive_integer(self.runtime_fencing_token)
        ):
            raise ContractViolation("qualification_binding_invalid")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {"schema_version": payload.pop("schema_version"), **payload}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> QualificationBinding:
        try:
            return cls(
                schema_version=payload.get("schema_version"),
                qualification_id=payload.get("qualification_id"),
                phase=payload.get("phase"),
                cycle_index=payload.get("cycle_index"),
                attempt_id=payload.get("attempt_id"),
                local_fencing_token=payload.get("local_fencing_token"),
                runtime_fencing_token=payload.get("runtime_fencing_token"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ContractViolation):
                raise
            raise ContractViolation("qualification_binding_invalid") from exc


@dataclass(frozen=True, slots=True)
class SelectionProbeBinding:
    qualification_id: str
    phase: str
    planned_slot_id: str
    probe_id: str
    local_fencing_token: int
    runtime_fencing_token: int
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.schema_version != SCHEMA_VERSION
            or not _identifier(self.qualification_id)
            or self.phase not in {"canary", "soak"}
            or not _identifier(self.planned_slot_id)
            or not _identifier(self.probe_id)
            or not _positive_integer(self.local_fencing_token)
            or not _positive_integer(self.runtime_fencing_token)
        ):
            raise ContractViolation("selection_probe_binding_invalid")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {"schema_version": payload.pop("schema_version"), **payload}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> SelectionProbeBinding:
        try:
            return cls(
                schema_version=payload.get("schema_version"),
                qualification_id=payload.get("qualification_id"),
                phase=payload.get("phase"),
                planned_slot_id=payload.get("planned_slot_id"),
                probe_id=payload.get("probe_id"),
                local_fencing_token=payload.get("local_fencing_token"),
                runtime_fencing_token=payload.get("runtime_fencing_token"),
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ContractViolation):
                raise
            raise ContractViolation("selection_probe_binding_invalid") from exc


def protocol_config() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "reason_schema_version": REASON_SCHEMA_VERSION,
        "scheduler_version": SCHEDULER_VERSION,
        "shared_runtime_lock_protocol_version": SHARED_RUNTIME_LOCK_PROTOCOL_VERSION,
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "send_mode": "stage",
        "managed_gui_send": False,
        "staging_input_backend": "guarded_macos_accessibility",
        "canary_cycle_count": CANARY_CYCLE_COUNT,
        "soak_cycle_count": SOAK_CYCLE_COUNT,
        "soak_min_duration_ns": SOAK_MIN_DURATION_NS,
        "soak_interval_ns": SOAK_INTERVAL_NS,
        "selection_probe_timeout_seconds": SELECTION_PROBE_TIMEOUT_SECONDS,
        "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS,
        "soak_retry_delays_seconds": list(SOAK_RETRY_DELAYS_SECONDS),
    }


def transition_outcome(current: str, target: str) -> str:
    if current not in OUTCOME_STATES or target not in OUTCOME_STATES:
        raise ContractViolation("outcome_state_unknown", current=current, target=target)
    if current in OUTCOME_TERMINAL_STATES:
        raise ContractViolation("outcome_terminal", current=current, target=target)
    if target not in OUTCOME_TRANSITIONS[current]:
        raise ContractViolation("outcome_transition_invalid", current=current, target=target)
    return target


def transition_finalization(current: str, target: str) -> str:
    if target == "finalization_failed":
        if current not in {*FINALIZATION_STATES, "finalization_failed"}:
            raise ContractViolation("finalization_state_unknown", current=current)
        return target
    if current == "finalization_failed":
        if target not in FINALIZATION_STATES:
            raise ContractViolation("finalization_transition_invalid", current=current, target=target)
        return target
    try:
        current_index = FINALIZATION_STATES.index(current)
        target_index = FINALIZATION_STATES.index(target)
    except ValueError as exc:
        raise ContractViolation("finalization_state_unknown", current=current, target=target) from exc
    if current in FINALIZATION_TERMINAL_STATES:
        raise ContractViolation("finalization_terminal", current=current, target=target)
    if target_index != current_index + 1:
        raise ContractViolation("finalization_transition_invalid", current=current, target=target)
    return target


def derive_terminal_state(outcome_state: str, finalization_state: str) -> str | None:
    if finalization_state != "validated":
        return None
    return {
        "soak_criteria_met": "protocol_passed",
        "qualification_blocked": "blocked_finalized",
        "qualification_expired": "expired_finalized",
    }.get(outcome_state)


def mutation_started(mutation_phase: str) -> bool:
    try:
        return MUTATION_PHASE_INDEX[mutation_phase] >= MUTATION_PHASE_INDEX["stage_mutation_intent"]
    except KeyError as exc:
        raise ContractViolation("mutation_phase_unknown", mutation_phase=mutation_phase) from exc


def can_retry_reason(reason: str, *, mutation_phase: str, safe_recovery_complete: bool) -> bool:
    if reason not in RETRYABLE_REASONS:
        return False
    if not mutation_started(mutation_phase):
        return True
    return safe_recovery_complete is True


def build_canary_schedule(qualification_id: str) -> list[dict[str, Any]]:
    if not _identifier(qualification_id):
        raise ContractViolation("qualification_id_invalid")
    modes = ["message-list"] * CANARY_CYCLE_COUNT
    modes[2] = "current-thread"
    modes[7] = "current-thread"
    return _build_schedule(qualification_id, "canary", modes)


def build_soak_schedule(qualification_id: str) -> list[dict[str, Any]]:
    if not _identifier(qualification_id):
        raise ContractViolation("qualification_id_invalid")
    modes: list[str] = []
    for _ in range(SOAK_CURRENT_THREAD_CYCLES):
        modes.extend(["message-list"] * 4)
        modes.append("current-thread")
    return _build_schedule(qualification_id, "soak", modes)


def _build_schedule(qualification_id: str, phase: str, modes: Sequence[str]) -> list[dict[str, Any]]:
    schedule: list[dict[str, Any]] = []
    for index, mode in enumerate(modes, start=1):
        slot_id = _stable_slot_id(qualification_id, phase, index, mode)
        predecessor = schedule[-1]["planned_slot_id"] if mode == "current-thread" else None
        schedule.append(
            {
                "schema_version": SCHEMA_VERSION,
                "phase": phase,
                "planned_index": index,
                "planned_slot_id": slot_id,
                "mode": mode,
                "predecessor_planned_slot_id": predecessor,
            }
        )
    return schedule


def canonicalize_authorization(payload: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ContractViolation("authorization_invalid", field="now")
    canonical = json.loads(canonical_json(dict(payload)))
    required = {
        "schema_version": SCHEMA_VERSION,
        "app_id": "tashuo",
        "scope": "send_chat_messages",
        "autonomous_send": True,
        "live_send": False,
        "requires_post_action_verification": True,
    }
    for key, expected in required.items():
        if canonical.get(key) != expected:
            raise ContractViolation("authorization_invalid", field=key)
    if not _identifier(canonical.get("authorization_id")):
        raise ContractViolation("authorization_invalid", field="authorization_id")
    allowed_actions = canonical.get("allowed_actions")
    if not isinstance(allowed_actions, list) or "send_message" not in allowed_actions:
        raise ContractViolation("authorization_invalid", field="allowed_actions")
    if canonical.get("revoked_at") not in (None, ""):
        raise ContractViolation("authorization_invalid", field="revoked_at")
    try:
        created_at = _parse_datetime(canonical.get("created_at"))
        expires_at = _parse_datetime(canonical.get("expires_at"))
    except (TypeError, ValueError) as exc:
        raise ContractViolation("authorization_invalid", field="timestamp") from exc
    current = now.astimezone(UTC)
    if created_at > current or expires_at <= current or expires_at <= created_at:
        raise ContractViolation("authorization_invalid", field="validity")
    if _is_in_quiet_hours(canonical.get("quiet_hours"), current):
        raise ContractViolation("authorization_invalid", field="quiet_hours")
    canonical["allowed_actions"] = sorted(set(str(item) for item in allowed_actions))
    for list_field in ("allowed_match_ids", "goal_ids", "quiet_hours"):
        if not isinstance(canonical.get(list_field), list):
            raise ContractViolation("authorization_invalid", field=list_field)
    return {"payload": canonical, "digest": canonical_digest(canonical)}


def compute_config_hash(environment_fingerprint: Mapping[str, Any], protocol: Mapping[str, Any] | None = None) -> str:
    return canonical_digest(
        {
            "environment_fingerprint": dict(environment_fingerprint),
            "protocol_config": dict(protocol if protocol is not None else protocol_config()),
        }
    )


def build_environment_fingerprint(
    components: Mapping[str, Any],
    *,
    qualification_salt: str,
    credential: str,
) -> dict[str, Any]:
    required = {
        "tool_version",
        "execution",
        "loaded_package_digest",
        "dependency_snapshot_digest",
        "python",
        "system",
        "display",
        "permissions",
        "tashuo",
        "runtime",
        "user_model_snapshot_digest",
        "model",
        "authorization_digest",
    }
    if not required.issubset(components):
        raise ContractViolation("environment_component_missing", missing=sorted(required - set(components)))
    execution = components.get("execution")
    if not isinstance(execution, Mapping):
        raise ContractViolation("environment_execution_invalid")
    mode = execution.get("mode")
    if mode == "source_checkout" and execution.get("clean") is not True:
        raise ContractViolation("environment_dirty_source_checkout")
    if mode == "source_checkout" and not all(_identifier(execution.get(key)) for key in ("git_commit", "tree_digest")):
        raise ContractViolation("environment_execution_invalid")
    if mode == "built_artifact" and not _identifier(execution.get("artifact_digest")):
        raise ContractViolation("environment_execution_invalid")
    if mode not in {"source_checkout", "built_artifact"}:
        raise ContractViolation("environment_execution_invalid")
    permissions = components.get("permissions")
    if not isinstance(permissions, Mapping) or permissions.get("accessibility") is not True or permissions.get(
        "screen_recording"
    ) is not True:
        raise ContractViolation("environment_permission_missing")
    runtime = components.get("runtime")
    expected_runtime = {
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "send_mode": "stage",
        "managed_gui_send": False,
        "staging_input_backend": "guarded_macos_accessibility",
        "runtime_lock_protocol_version": SHARED_RUNTIME_LOCK_PROTOCOL_VERSION,
    }
    if not isinstance(runtime, Mapping) or any(runtime.get(key) != value for key, value in expected_runtime.items()):
        raise ContractViolation("environment_runtime_invalid")
    model = components.get("model")
    if not isinstance(model, Mapping):
        raise ContractViolation("environment_model_invalid")
    model_payload = dict(model)
    provider_identifier = model_payload.get("provider_identifier")
    if not _identifier(provider_identifier) or provider_identifier == "revision_unavailable":
        model_payload["provider_identifier"] = "revision_unavailable"
        model_pin_level = "endpoint_identifier_only"
    else:
        model_pin_level = "deployment_identifier"
    if not qualification_salt or not credential:
        raise ContractViolation("environment_credential_invalid")
    fingerprint = {
        "schema_version": SCHEMA_VERSION,
        **{key: json.loads(canonical_json(components[key])) for key in sorted(required - {"model"})},
        "model": json.loads(canonical_json(model_payload)),
        "credential_fingerprint": hmac.new(
            qualification_salt.encode("utf-8"),
            credential.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
        "model_pin_level": model_pin_level,
        "protocol": protocol_config(),
    }
    return fingerprint


def environment_fingerprints_match(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, Any]:
    drift: list[str] = []
    _collect_drift(expected, actual, path="", result=drift)
    return {"matches": not drift, "drift_fields": sorted(drift)}


def compute_canary_accept_token(
    *,
    qualification_id: str,
    config_hash: str,
    canary_chain_root: str,
    canary_certificate_digest: str,
) -> str:
    parts = (
        "tashuo-standalone-soak",
        qualification_id,
        config_hash,
        canary_chain_root,
        canary_certificate_digest,
    )
    if not all(_identifier(part) for part in parts[1:]):
        raise ContractViolation("canary_accept_token_binding_invalid")
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_canary_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    predicates = {
        "committed_cycles": metrics.get("committed_cycles") == CANARY_CYCLE_COUNT,
        "successful_cycles": metrics.get("successful_cycles") == CANARY_CYCLE_COUNT,
        "first_attempt_successes": metrics.get("first_attempt_successes") == CANARY_CYCLE_COUNT,
        "no_retries": metrics.get("retried_cycles") == 0 and metrics.get("total_attempts") == CANARY_CYCLE_COUNT,
        "surface_quota": metrics.get("message_list_cycles") == 8 and metrics.get("current_thread_cycles") == 2,
        "no_safety_violations": metrics.get("safety_violations") == 0,
        "terminal_audits": metrics.get("terminal_audits") == CANARY_CYCLE_COUNT,
        "stage_results": metrics.get("completed_stage_results") == CANARY_CYCLE_COUNT,
        "attempt_outcomes": metrics.get("attempt_outcomes") == CANARY_CYCLE_COUNT,
        "receipts": metrics.get("receipts") == CANARY_CYCLE_COUNT,
        "phase_cleanup": metrics.get("phase_cleanup_ok") is True,
        "support_bundle": metrics.get("support_bundle_ok") is True,
        "hash_chain": metrics.get("hash_chain_ok") is True,
        "sqlite_integrity": metrics.get("sqlite_quick_check") == "ok",
    }
    return _predicate_result(predicates)


def validate_soak_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    starts = metrics.get("actual_start_ns")
    intervals_ok = _valid_soak_intervals(starts)
    predicates = {
        "committed_cycles": metrics.get("committed_cycles") == SOAK_CYCLE_COUNT,
        "terminal_cycle_successes": _integer_at_least(metrics.get("terminal_cycle_successes"), 99),
        "first_attempt_successes": _integer_at_least(metrics.get("first_attempt_successes"), 99),
        "retried_cycles": _integer_at_most(metrics.get("retried_cycles"), 1),
        "total_attempts": _integer_at_most(metrics.get("total_attempts"), 102),
        "surface_quota": (
            metrics.get("message_list_cycles") == SOAK_MESSAGE_LIST_CYCLES
            and metrics.get("current_thread_cycles") == SOAK_CURRENT_THREAD_CYCLES
        ),
        "monotonic_intervals": intervals_ok,
        "boot_session": metrics.get("boot_session_unchanged") is True,
        "environment": metrics.get("environment_matches_canary") is True,
        "no_safety_violations": metrics.get("safety_violations") == 0,
        "phase_cleanup": metrics.get("phase_cleanup_ok") is True,
        "support_bundles": metrics.get("support_bundles_ok") is True,
        "artifacts": metrics.get("artifacts_ok") is True,
        "hash_chain": metrics.get("hash_chain_ok") is True,
        "sqlite_integrity": metrics.get("sqlite_quick_check") == "ok",
    }
    return _predicate_result(predicates)


def derive_claim(
    state: str,
    *,
    qualification_id: str,
    config_hash: str,
    manifest_digest: str,
) -> dict[str, str]:
    if state == "canary_passed":
        code = "CANARY_PASSED_SOAK_NOT_RUN"
        text = "canary passed for the pinned environment; soak not run; qualification not passed"
    elif state == "protocol_passed":
        code = "PROTOCOL_PASSED_PINNED_ENVIRONMENT"
        text = "tashuo standalone stage-only qualification protocol passed for the pinned environment"
    elif state in {"qualification_blocked", "blocked_finalized"}:
        code = "QUALIFICATION_BLOCKED"
        text = "tashuo standalone stage-only qualification blocked"
    elif state in {"qualification_expired", "expired_finalized"}:
        code = "QUALIFICATION_EXPIRED"
        text = "tashuo standalone stage-only qualification expired"
    else:
        raise ContractViolation("claim_state_invalid", state=state)
    suffix = f"; qualification_id={qualification_id}; config_hash={config_hash}; manifest_digest={manifest_digest}"
    return {"claim_code": code, "text": text + suffix}


def _predicate_result(predicates: Mapping[str, bool]) -> dict[str, Any]:
    failed = [name for name, passed in predicates.items() if not passed]
    return {"passed": not failed, "predicates": dict(predicates), "failed_predicates": failed}


def _valid_soak_intervals(starts: Any) -> bool:
    if not isinstance(starts, list) or len(starts) != SOAK_CYCLE_COUNT:
        return False
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in starts):
        return False
    if any(current - previous < SOAK_INTERVAL_NS for previous, current in zip(starts, starts[1:])):
        return False
    return starts[-1] - starts[0] >= SOAK_MIN_DURATION_NS


def _stable_slot_id(qualification_id: str, phase: str, index: int, mode: str) -> str:
    digest = canonical_digest(
        {"qualification_id": qualification_id, "phase": phase, "planned_index": index, "mode": mode}
    )[:16]
    return f"slot_{phase}_{index:03d}_{digest}"


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _integer_at_least(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _integer_at_most(value: Any, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= maximum


def _parse_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC)


def _is_in_quiet_hours(value: Any, now: datetime) -> bool:
    if value in (None, []):
        return False
    if not isinstance(value, list):
        return True
    current = now.timetz().replace(tzinfo=None)
    for item in value:
        if not isinstance(item, dict):
            return True
        try:
            start = time.fromisoformat(str(item["start"]))
            end = time.fromisoformat(str(item["end"]))
        except (KeyError, ValueError):
            return True
        if start <= end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False


def _collect_drift(expected: Any, actual: Any, *, path: str, result: list[str]) -> None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        keys = set(expected) | set(actual)
        for key in sorted(keys, key=str):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in expected or key not in actual:
                result.append(child_path)
                continue
            _collect_drift(expected[key], actual[key], path=child_path, result=result)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            result.append(path)
            return
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            _collect_drift(expected_item, actual_item, path=f"{path}[{index}]", result=result)
        return
    if expected != actual:
        result.append(path)
