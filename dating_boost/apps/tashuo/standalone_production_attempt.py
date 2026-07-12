from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dating_boost.apps.tashuo.standalone_production_contract import (
    MUTATION_PHASE_INDEX,
    MUTATION_PHASES,
    QualificationBinding,
    canonical_digest,
)
from dating_boost.apps.tashuo.standalone_production_evidence import normalize_evidence_text, normalized_text_hash
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.core.production_store import ProductionDataStore


class AttemptProtocolViolation(RuntimeError):
    pass


def build_composer_plan(
    *,
    payload_messages: Sequence[Mapping[str, Any]],
    composer_text: str,
) -> dict[str, Any]:
    if not isinstance(payload_messages, Sequence) or isinstance(payload_messages, (str, bytes)) or not payload_messages:
        raise AttemptProtocolViolation("payload_messages_invalid")
    normalized = normalize_evidence_text(composer_text)
    if not normalized:
        raise AttemptProtocolViolation("composer_text_empty")
    canonical_messages = [dict(item) for item in payload_messages]
    return {
        "schema_version": 1,
        "payload_hash": canonical_digest({"schema_version": 1, "messages": canonical_messages}),
        "planned_composer_text": normalized,
        "planned_composer_text_hash": normalized_text_hash(normalized),
        "planned_composer_character_count": len(normalized),
    }


def record_observed_composer(plan: Mapping[str, Any], observed_ax_text: str) -> dict[str, Any]:
    if not isinstance(observed_ax_text, str):
        raise AttemptProtocolViolation("observed_composer_invalid")
    normalized_hash = normalized_text_hash(observed_ax_text)
    if normalized_hash != plan.get("planned_composer_text_hash"):
        raise AttemptProtocolViolation("staged_text_mismatch")
    return {
        "schema_version": 1,
        "status": "verified",
        "exact_observed_composer_text": observed_ax_text,
        "exact_observed_composer_text_hash": hashlib.sha256(observed_ax_text.encode("utf-8")).hexdigest(),
        "normalized_observed_composer_text_hash": normalized_hash,
        "observed_composer_character_count": len(observed_ax_text),
    }


def validate_pre_stage_revalidation(
    baseline: Mapping[str, Any],
    refreshed: Mapping[str, Any],
    *,
    now_monotonic_ns: int,
    maximum_age_ns: int = 2_000_000_000,
) -> dict[str, Any]:
    comparisons = (
        ("frontmost_app", "pre_stage_frontmost_app_changed"),
        ("window_identity", "pre_stage_window_changed"),
        ("target_binding_digest", "pre_stage_target_changed"),
        ("tail_digest", "pre_stage_tail_changed"),
    )
    for field, reason in comparisons:
        if baseline.get(field) != refreshed.get(field):
            return _blocked(reason)
    if refreshed.get("composer_text") != "":
        return _blocked("candidate_composer_occupied")
    if refreshed.get("user_event_count") != 0:
        return _blocked("user_or_external_interference_detected")
    captured = refreshed.get("captured_monotonic_ns")
    if not isinstance(captured, int) or isinstance(captured, bool):
        return _blocked("pre_stage_evidence_time_invalid")
    age = now_monotonic_ns - captured
    if age < 0 or age > maximum_age_ns:
        return _blocked("pre_stage_evidence_stale")
    return {
        "schema_version": 1,
        "status": "ok",
        "reason": "pre_stage_revalidated",
        "evidence_age_ns": age,
        "target_binding_digest": refreshed.get("target_binding_digest"),
        "tail_digest": refreshed.get("tail_digest"),
    }


class ProductionAttemptProtocol:
    def __init__(
        self,
        ledger: ProductionQualificationLedger,
        binding: QualificationBinding,
        *,
        mutation_guard: Callable[[], Mapping[str, Any]],
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        guard_fencing_tokens: tuple[int, int] | None = None,
    ):
        self.ledger = ledger
        self.binding = binding
        self._mutation_guard = mutation_guard
        self._monotonic_ns = monotonic_ns
        self._guard_fencing_tokens = guard_fencing_tokens

    def start(
        self,
        *,
        precondition_digest: str,
        target_hash: str,
        target: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_guard()
        timestamp = self._monotonic_ns()
        checkpoint = {
            "phase": "not_started",
            "evidence_digest": precondition_digest,
            "recorded_monotonic_ns": timestamp,
        }
        attempt = self.ledger.create_attempt(
            self.binding,
            {
                "mutation_phase": "not_started",
                "precondition_digest": precondition_digest,
                "target_hash": target_hash,
                **({"target": dict(target)} if target is not None else {}),
                "checkpoints": [checkpoint],
                "started_monotonic_ns": timestamp,
            },
        )
        self._require_guard()
        self.ledger.append_event(
            event_id=f"checkpoint_{self.binding.attempt_id}_not_started",
            event_type="attempt_started",
            binding=self.binding,
            reason_code=None,
            mutation_phase="not_started",
            evidence_digest=precondition_digest,
            extras={"target_hash": target_hash},
        )
        return attempt

    def advance(
        self,
        mutation_phase: str,
        *,
        evidence_digest: str,
        updates: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempt_path = f"standalone_production/attempts/{self.binding.attempt_id}.json"
        attempt = self.ledger.read_record(attempt_path)
        current = attempt.get("mutation_phase")
        if current not in MUTATION_PHASE_INDEX or mutation_phase not in MUTATION_PHASE_INDEX:
            raise AttemptProtocolViolation("mutation_phase_unknown")
        if MUTATION_PHASE_INDEX[mutation_phase] != MUTATION_PHASE_INDEX[current] + 1:
            raise AttemptProtocolViolation("mutation_phase_transition_invalid")
        self._require_guard()
        checkpoint = {
            "phase": mutation_phase,
            "evidence_digest": evidence_digest,
            "recorded_monotonic_ns": self._monotonic_ns(),
        }
        checkpoints = list(attempt.get("checkpoints") or []) + [checkpoint]
        updated = self.ledger.update_attempt(
            self.binding.attempt_id,
            expected_version=attempt["ledger_version"],
            changes={
                **dict(updates or {}),
                "mutation_phase": mutation_phase,
                "checkpoints": checkpoints,
            },
        )
        guard = self._require_guard()
        extras = None
        if self._guard_fencing_tokens is not None:
            extras = {
                "recovery_fencing": {
                    "local_fencing_token": guard["local_fencing_token"],
                    "runtime_fencing_token": guard["runtime_fencing_token"],
                }
            }
        self.ledger.append_event(
            event_id=f"checkpoint_{self.binding.attempt_id}_{mutation_phase}",
            event_type=mutation_phase,
            binding=self.binding,
            reason_code=None,
            mutation_phase=mutation_phase,
            evidence_digest=evidence_digest,
            extras=extras,
        )
        return updated

    def record_terminal(
        self,
        *,
        status: str,
        reason_code: str | None,
        terminal_evidence_digest: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        attempt = self.ledger.read_record(f"standalone_production/attempts/{self.binding.attempt_id}.json")
        mutation_phase = str(attempt.get("mutation_phase") or "")
        if mutation_phase not in MUTATION_PHASE_INDEX:
            raise AttemptProtocolViolation("mutation_phase_unknown")
        self._require_guard()
        outcome_payload = {
            "status": status,
            "reason_code": reason_code,
            "mutation_phase": mutation_phase,
            "terminal_evidence_digest": terminal_evidence_digest,
        }
        outcome = self.ledger.record_attempt_outcome(self.binding, outcome_payload)
        self._require_guard()
        receipt_result = self.ledger.record_receipt(
            self.binding,
            {**dict(receipt), "status": status, "mutation_phase": mutation_phase},
        )
        self._require_guard()
        self.ledger.append_event(
            event_id=f"terminal_{self.binding.attempt_id}",
            event_type="attempt_terminal" if status == "succeeded" else "attempt_terminal_failure",
            binding=self.binding,
            reason_code=reason_code,
            mutation_phase=mutation_phase,
            evidence_digest=terminal_evidence_digest,
        )
        return {"status": "recorded", "outcome": outcome, "receipt": receipt_result}

    def record_recovery_terminal(
        self,
        *,
        status: str,
        reason_code: str | None,
        terminal_evidence_digest: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        attempt = self.ledger.read_record(f"standalone_production/attempts/{self.binding.attempt_id}.json")
        mutation_phase = str(attempt.get("mutation_phase") or "")
        if mutation_phase not in MUTATION_PHASE_INDEX or self._guard_fencing_tokens is None:
            raise AttemptProtocolViolation("recovery_binding_invalid")
        guard = self._require_guard()
        recovery_fencing = {
            "local_fencing_token": guard["local_fencing_token"],
            "runtime_fencing_token": guard["runtime_fencing_token"],
        }
        outcome = self.ledger.record_attempt_outcome(
            self.binding,
            {
                "status": status,
                "reason_code": reason_code,
                "mutation_phase": mutation_phase,
                "terminal_evidence_digest": terminal_evidence_digest,
                "recovery_terminal": True,
                "recovery_fencing": recovery_fencing,
            },
        )
        self._require_guard()
        receipt_result = self.ledger.record_receipt(
            self.binding,
            {
                **dict(receipt),
                "status": status,
                "mutation_phase": mutation_phase,
                "recovery_receipt": True,
                "recovery_fencing": recovery_fencing,
            },
        )
        self._require_guard()
        self.ledger.append_event(
            event_id=f"recovery_terminal_{self.binding.attempt_id}",
            event_type="attempt_recovery_terminal",
            binding=self.binding,
            reason_code=reason_code,
            mutation_phase=mutation_phase,
            evidence_digest=terminal_evidence_digest,
            extras={"recovery_fencing": recovery_fencing},
        )
        return {"status": "recorded", "outcome": outcome, "receipt": receipt_result}

    def _require_guard(self) -> Mapping[str, Any]:
        result = self._mutation_guard()
        if result.get("status") != "ok":
            raise AttemptProtocolViolation(str(result.get("reason") or "mutation_guard_blocked"))
        expected_local, expected_runtime = self._guard_fencing_tokens or (
            self.binding.local_fencing_token,
            self.binding.runtime_fencing_token,
        )
        if result.get("local_fencing_token") != expected_local:
            raise AttemptProtocolViolation("local_fencing_token_mismatch")
        if result.get("runtime_fencing_token") != expected_runtime:
            raise AttemptProtocolViolation("runtime_fencing_token_mismatch")
        return result


def decide_attempt_recovery(
    *,
    mutation_phase: str,
    composer_state: str,
    target_matches: bool,
    stage_mutation_completed: bool,
    input_sentinel_coverage_complete: bool,
    user_event_count: int,
) -> dict[str, Any]:
    if mutation_phase not in MUTATION_PHASE_INDEX:
        raise AttemptProtocolViolation("mutation_phase_unknown")
    if composer_state not in {"empty", "exact", "other", "unknown"}:
        raise AttemptProtocolViolation("composer_state_invalid")
    mutation_started = MUTATION_PHASE_INDEX[mutation_phase] >= MUTATION_PHASE_INDEX["stage_mutation_intent"]
    if not mutation_started and target_matches and composer_state == "empty":
        return _recovery("abandon_before_mutation", pause=False)
    if not target_matches:
        return _recovery("block_and_pause", pause=True)
    if not mutation_started:
        return _recovery("block_and_pause", pause=True)
    if composer_state == "empty":
        return _recovery("observe_negative_send", pause=False)
    if (
        composer_state == "exact"
        and stage_mutation_completed
        and input_sentinel_coverage_complete
        and user_event_count == 0
    ):
        return _recovery("clear_exact_then_observe_negative_send", pause=False)
    return _recovery("block_and_pause", pause=True)


def stage_consumed_after_verified_cleanup(
    data_dir: Path,
    *,
    binding: QualificationBinding,
    action_request_id: str,
    cleanup_verification: Mapping[str, Any],
    negative_send_verification: Mapping[str, Any],
    predecessor_binding: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        cleanup_verification.get("status") != "verified"
        or cleanup_verification.get("composer_empty") is not True
    ):
        raise AttemptProtocolViolation("cleanup_not_verified")
    if negative_send_verification.get("status") != "verified":
        raise AttemptProtocolViolation("negative_send_not_verified")
    target_hash = cleanup_verification.get("target_hash")
    if (
        not isinstance(target_hash, str)
        or negative_send_verification.get("target_hash") != target_hash
        or predecessor_binding.get("target_hash") != target_hash
    ):
        raise AttemptProtocolViolation("cleanup_target_mismatch")
    transition = {
        "schema_version": 1,
        "transition": "stage_consumed_after_verified_cleanup",
        "qualification_binding": binding.to_dict(),
        "action_request_id": action_request_id,
        "cleanup_digest": canonical_digest(dict(cleanup_verification)),
        "negative_send_digest": canonical_digest(dict(negative_send_verification)),
        "predecessor_binding": dict(predecessor_binding),
    }
    transition_path = f"standalone_production/stage_consumptions/{binding.attempt_id}.json"
    store = ProductionDataStore(data_dir.resolve())
    store.ensure_schema()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = _read_document(conn, store, transition_path)
        if existing is not None:
            if canonical_digest(existing) != canonical_digest(transition):
                raise AttemptProtocolViolation("stage_consumption_conflict")
            return {"schema_version": 1, "status": "replayed", "attempt_id": binding.attempt_id}
        session = _required_document(conn, store, "operator/session.json", "operator_session_missing")
        work_item = session.get("current_work_item")
        current_document = _required_document(
            conn,
            store,
            "operator/current_work_item.json",
            "operator_current_work_item_missing",
        )
        if not isinstance(work_item, dict) or work_item != current_document:
            raise AttemptProtocolViolation("operator_current_work_item_mismatch")
        if work_item.get("work_item_type") != "send_message" or work_item.get("action_request_id") != action_request_id:
            raise AttemptProtocolViolation("action_request_binding_mismatch")
        _require_binding(session.get("qualification_binding"), binding)
        _require_binding(work_item.get("qualification_binding"), binding)
        states_document = _required_document(conn, store, "automation/states.json", "automation_states_missing")
        states = states_document.get("states")
        if not isinstance(states, list):
            raise AttemptProtocolViolation("automation_states_invalid")
        matching = [state for state in states if isinstance(state, dict) and state.get("last_action_request_id") == action_request_id]
        if len(matching) != 1:
            raise AttemptProtocolViolation("automation_active_request_mismatch")
        state = matching[0]
        _require_binding(state.get("qualification_binding"), binding)
        if state.get("state") != "staged_pending_user":
            raise AttemptProtocolViolation("automation_stage_not_pending")
        updated_state = dict(state)
        updated_state["state"] = "draft_ready"
        updated_state["last_qualification_stage_consumed"] = {
            "qualification_id": binding.qualification_id,
            "attempt_id": binding.attempt_id,
            "action_request_id": action_request_id,
            "predecessor_binding_digest": canonical_digest(dict(predecessor_binding)),
        }
        for key in (
            "last_action_request_id",
            "last_outbound_payload_hash",
            "last_precondition_hash",
            "last_autonomous_audit_binding",
            "last_pre_action_observation_id",
            "qualification_binding",
        ):
            updated_state.pop(key, None)
        updated_states = [updated_state if item is state else item for item in states]
        updated_session = {**session, "current_work_item": None}
        _write_document(conn, store, "operator/session.json", updated_session)
        _write_document(conn, store, "automation/states.json", {**states_document, "states": updated_states})
        conn.execute("DELETE FROM documents WHERE path = ?", ("operator/current_work_item.json",))
        _insert_document(conn, store, transition_path, transition)
    return {"schema_version": 1, "status": "stage_consumed", "attempt_id": binding.attempt_id}


def abandon_action_request_before_mutation(
    data_dir: Path,
    *,
    binding: QualificationBinding,
    action_request_id: str,
) -> dict[str, Any]:
    ledger = ProductionQualificationLedger(data_dir)
    attempt = ledger.read_record(f"standalone_production/attempts/{binding.attempt_id}.json")
    mutation_phase = str(attempt.get("mutation_phase") or "")
    if (
        mutation_phase not in MUTATION_PHASE_INDEX
        or MUTATION_PHASE_INDEX[mutation_phase] >= MUTATION_PHASE_INDEX["stage_mutation_intent"]
    ):
        raise AttemptProtocolViolation("action_request_abandon_after_mutation_forbidden")
    transition = {
        "schema_version": 1,
        "transition": "qualification_action_request_abandoned_before_mutation",
        "qualification_binding": binding.to_dict(),
        "action_request_id": action_request_id,
        "mutation_phase": mutation_phase,
    }
    transition_path = f"standalone_production/action_request_abandons/{binding.attempt_id}.json"
    store = ProductionDataStore(data_dir.resolve())
    store.ensure_schema()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = _read_document(conn, store, transition_path)
        if existing is not None:
            if canonical_digest(existing) != canonical_digest(transition):
                raise AttemptProtocolViolation("action_request_abandon_conflict")
            return {"schema_version": 1, "status": "replayed", "attempt_id": binding.attempt_id}
        session = _required_document(conn, store, "operator/session.json", "operator_session_missing")
        work_item = session.get("current_work_item")
        current_document = _required_document(
            conn,
            store,
            "operator/current_work_item.json",
            "operator_current_work_item_missing",
        )
        if not isinstance(work_item, dict) or work_item != current_document:
            raise AttemptProtocolViolation("operator_current_work_item_mismatch")
        if work_item.get("work_item_type") != "send_message" or work_item.get("action_request_id") != action_request_id:
            raise AttemptProtocolViolation("action_request_binding_mismatch")
        _require_binding(session.get("qualification_binding"), binding)
        _require_binding(work_item.get("qualification_binding"), binding)
        states_document = _required_document(conn, store, "automation/states.json", "automation_states_missing")
        states = states_document.get("states")
        if not isinstance(states, list):
            raise AttemptProtocolViolation("automation_states_invalid")
        matching = [state for state in states if isinstance(state, dict) and state.get("last_action_request_id") == action_request_id]
        if len(matching) != 1:
            raise AttemptProtocolViolation("automation_active_request_mismatch")
        state = matching[0]
        _require_binding(state.get("qualification_binding"), binding)
        updated_state = dict(state)
        updated_state["state"] = "draft_ready"
        updated_state["last_qualification_action_request_abandoned"] = {
            "qualification_id": binding.qualification_id,
            "attempt_id": binding.attempt_id,
            "action_request_id": action_request_id,
            "mutation_phase": mutation_phase,
        }
        for key in (
            "last_action_request_id",
            "last_outbound_payload_hash",
            "last_precondition_hash",
            "last_autonomous_audit_binding",
            "last_pre_action_observation_id",
            "qualification_binding",
        ):
            updated_state.pop(key, None)
        updated_states = [updated_state if item is state else item for item in states]
        _write_document(conn, store, "operator/session.json", {**session, "current_work_item": None})
        _write_document(conn, store, "automation/states.json", {**states_document, "states": updated_states})
        conn.execute("DELETE FROM documents WHERE path = ?", ("operator/current_work_item.json",))
        _insert_document(conn, store, transition_path, transition)
    return {"schema_version": 1, "status": "abandoned", "attempt_id": binding.attempt_id}


def _require_binding(value: Any, expected: QualificationBinding) -> None:
    if not isinstance(value, dict):
        raise AttemptProtocolViolation("qualification_binding_mismatch")
    try:
        actual = QualificationBinding.from_dict(value)
    except ValueError as exc:
        raise AttemptProtocolViolation("qualification_binding_mismatch") from exc
    if actual != expected:
        raise AttemptProtocolViolation("qualification_binding_mismatch")


def _read_document(conn, store: ProductionDataStore, path: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT payload_json FROM documents WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    payload = store._decode_document(path, row["payload_json"])
    if not isinstance(payload, dict):
        raise AttemptProtocolViolation("stored_document_invalid")
    return payload


def _required_document(conn, store: ProductionDataStore, path: str, reason: str) -> dict[str, Any]:
    payload = _read_document(conn, store, path)
    if payload is None:
        raise AttemptProtocolViolation(reason)
    return payload


def _write_document(conn, store: ProductionDataStore, path: str, payload: Mapping[str, Any]) -> None:
    conn.execute(
        """
        UPDATE documents
        SET schema_version = ?, payload_json = ?, updated_at = ?
        WHERE path = ?
        """,
        (payload.get("schema_version"), store._encode_document(path, dict(payload)), _now_iso(), path),
    )


def _insert_document(conn, store: ProductionDataStore, path: str, payload: Mapping[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO documents (path, schema_version, payload_json, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (path, payload.get("schema_version"), store._encode_document(path, dict(payload)), _now_iso()),
    )


def _recovery(action: str, *, pause: bool) -> dict[str, Any]:
    return {"action": action, "runtime_safety_pause_required": pause}


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
