from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from dating_boost.apps.tashuo.standalone_production_contract import (
    MUTATION_PHASE_INDEX,
    PROTOCOL_VERSION,
    REASON_SCHEMA_VERSION,
    REGISTERED_REASONS,
    SCHEMA_VERSION,
    QualificationBinding,
    SelectionProbeBinding,
    canonical_digest,
)
from dating_boost.core.production_store import ProductionDataStore


PRODUCTION_PREFIX = "standalone_production/"
EVENT_STREAM = "standalone_production/events.jsonl"


class LedgerError(RuntimeError):
    pass


class LedgerConflict(LedgerError):
    pass


class LedgerCorruption(LedgerError):
    pass


class ProductionQualificationLedger:
    """Encrypted qualification ledger with immutable inserts and explicit CAS.

    This deliberately bypasses the general document upsert and audit-event
    replacement methods. Qualification commits need conflict detection, not
    last-writer-wins behavior.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _chmod(self.data_dir, 0o700)
        self._store = ProductionDataStore(self.data_dir)
        if not self._store.db_path.exists():
            self._store.initialize_empty()
        else:
            self._store.ensure_schema()
        _chmod(self._store.db_path, 0o600)

    def insert_if_absent(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized_path = _record_path(path)
        record = _mapping(payload, reason="immutable_record_invalid")
        digest = canonical_digest(record)
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload_json FROM documents WHERE path = ?", (normalized_path,)).fetchone()
            if row is not None:
                existing = self._decode_document(normalized_path, row["payload_json"])
                if canonical_digest(existing) != digest:
                    raise LedgerConflict("immutable_record_conflict")
                return {"status": "replayed", "path": normalized_path, "digest": digest}
            conn.execute(
                """
                INSERT INTO documents (path, schema_version, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    normalized_path,
                    record.get("schema_version"),
                    self._store._encode_document(normalized_path, record),
                    _now_iso(),
                ),
            )
        return {"status": "inserted", "path": normalized_path, "digest": digest}

    def create_versioned(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if "ledger_version" in payload:
            raise LedgerConflict("ledger_version_reserved")
        record = {**_mapping(payload, reason="versioned_record_invalid"), "ledger_version": 1}
        result = self.insert_if_absent(path, record)
        if result["status"] == "replayed":
            raise LedgerConflict("versioned_record_already_exists")
        return record

    def compare_and_swap(
        self,
        path: str,
        *,
        expected_version: int,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_path = _record_path(path)
        if not _positive_int(expected_version):
            raise LedgerConflict("ledger_version_invalid")
        updates = _mapping(changes, reason="versioned_changes_invalid")
        if "ledger_version" in updates:
            raise LedgerConflict("ledger_version_reserved")
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload_json FROM documents WHERE path = ?", (normalized_path,)).fetchone()
            if row is None:
                raise LedgerConflict("versioned_record_missing")
            current = self._decode_document(normalized_path, row["payload_json"])
            if current.get("ledger_version") != expected_version:
                raise LedgerConflict("ledger_version_conflict")
            updated = {**current, **updates, "ledger_version": expected_version + 1}
            conn.execute(
                """
                UPDATE documents
                SET schema_version = ?, payload_json = ?, updated_at = ?
                WHERE path = ?
                """,
                (
                    updated.get("schema_version"),
                    self._store._encode_document(normalized_path, updated),
                    _now_iso(),
                    normalized_path,
                ),
            )
        return updated

    def read_record(self, path: str) -> dict[str, Any]:
        normalized_path = _record_path(path)
        payload = self._store.get_document(normalized_path)
        if payload is None:
            raise FileNotFoundError(normalized_path)
        return _mapping(payload, reason="ledger_record_corrupt")

    def list_records(self, prefix: str) -> list[dict[str, Any]]:
        normalized_prefix = _record_prefix(prefix)
        return [
            {"path": item["path"], "payload": _mapping(item["payload"], reason="ledger_record_corrupt")}
            for item in self._store.list_documents(prefix=normalized_prefix)
        ]

    def append_event(
        self,
        *,
        event_id: str,
        event_type: str,
        binding: QualificationBinding | SelectionProbeBinding | Mapping[str, Any],
        reason_code: str | None,
        mutation_phase: str,
        evidence_digest: str,
        extras: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not _identifier(event_id) or not _identifier(event_type) or not _identifier(evidence_digest):
            raise LedgerCorruption("event_fields_invalid")
        if mutation_phase not in MUTATION_PHASE_INDEX:
            raise LedgerCorruption("mutation_phase_unknown")
        if reason_code is not None and reason_code not in REGISTERED_REASONS:
            raise LedgerCorruption("reason_code_unknown")
        normalized_binding = _event_binding(binding)
        binding_field = (
            "qualification_binding" if isinstance(normalized_binding, QualificationBinding) else "selection_probe_binding"
        )
        event_request = {
            "event_id": event_id,
            "event_type": event_type,
            binding_field: normalized_binding.to_dict(),
            "reason_code": reason_code,
            "mutation_phase": mutation_phase,
            "evidence_digest": evidence_digest,
            "extras": _mapping(extras or {}, reason="event_extras_invalid"),
        }
        request_digest = canonical_digest(event_request)
        with self._store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing_row = conn.execute(
                "SELECT payload_json FROM audit_events WHERE stream = ? AND event_id = ?",
                (EVENT_STREAM, event_id),
            ).fetchone()
            if existing_row is not None:
                existing = self._decode_event(event_id, existing_row["payload_json"])
                if existing.get("event_request_digest") != request_digest:
                    raise LedgerConflict("event_conflict")
                return existing
            last_row = conn.execute(
                """
                SELECT event_id, payload_json
                FROM audit_events
                WHERE stream = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (EVENT_STREAM,),
            ).fetchone()
            previous = self._decode_event(last_row["event_id"], last_row["payload_json"]) if last_row else None
            sequence = int(previous.get("sequence")) + 1 if previous is not None else 1
            previous_hash = previous.get("event_hash") if previous is not None else None
            body = {
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "reason_schema_version": REASON_SCHEMA_VERSION,
                "sequence": sequence,
                **event_request,
                "event_request_digest": request_digest,
                "created_at": _now_iso(),
            }
            event_hash = canonical_digest({"previous_hash": previous_hash, "event_without_hash": body})
            event = {**body, "previous_hash": previous_hash, "event_hash": event_hash}
            conn.execute(
                """
                INSERT INTO audit_events (stream, event_id, target_match_id, payload_json, created_at)
                VALUES (?, ?, NULL, ?, ?)
                """,
                (
                    EVENT_STREAM,
                    event_id,
                    self._store._encode_audit_event(EVENT_STREAM, event_id, event),
                    event["created_at"],
                ),
            )
        return event

    def list_events(self) -> list[dict[str, Any]]:
        return [
            _mapping(item["payload"], reason="event_corrupt")
            for item in self._store.list_audit_events(stream=EVENT_STREAM)
        ]

    def validate_event_chain(self) -> dict[str, Any]:
        try:
            events = self.list_events()
        except Exception:
            return {"valid": False, "reason": "event_stream_unreadable", "chain_root": None, "event_count": 0}
        previous_hash: str | None = None
        for expected_sequence, event in enumerate(events, start=1):
            if event.get("sequence") != expected_sequence:
                return _chain_error("event_sequence_invalid", previous_hash, expected_sequence - 1)
            if event.get("previous_hash") != previous_hash:
                return _chain_error("event_previous_hash_mismatch", previous_hash, expected_sequence - 1)
            stored_hash = event.get("event_hash")
            body = {key: value for key, value in event.items() if key not in {"previous_hash", "event_hash"}}
            expected_hash = canonical_digest({"previous_hash": previous_hash, "event_without_hash": body})
            if stored_hash != expected_hash:
                return _chain_error("event_hash_mismatch", previous_hash, expected_sequence - 1)
            try:
                if "qualification_binding" in event:
                    binding = QualificationBinding.from_dict(event.get("qualification_binding") or {})
                else:
                    binding = SelectionProbeBinding.from_dict(event.get("selection_probe_binding") or {})
            except ValueError:
                return _chain_error("event_binding_invalid", previous_hash, expected_sequence - 1)
            if (
                event.get("mutation_phase") not in MUTATION_PHASE_INDEX
                or event.get("reason_schema_version") != REASON_SCHEMA_VERSION
                or binding.local_fencing_token < 1
                or binding.runtime_fencing_token < 1
            ):
                return _chain_error("event_contract_invalid", previous_hash, expected_sequence - 1)
            previous_hash = stored_hash
        return {"valid": True, "reason": None, "chain_root": previous_hash, "event_count": len(events)}

    def create_qualification(self, qualification_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not _identifier(qualification_id):
            raise LedgerCorruption("qualification_id_invalid")
        return self.create_versioned(
            f"standalone_production/qualifications/{qualification_id}.json",
            {"schema_version": SCHEMA_VERSION, "qualification_id": qualification_id, **dict(payload)},
        )

    def create_cycle(
        self,
        *,
        qualification_id: str,
        phase: str,
        cycle_index: int,
        planned_slot_id: str,
        mode: str,
        actual_start_ns: int | None = None,
    ) -> dict[str, Any]:
        if phase not in {"canary", "soak"} or not _positive_int(cycle_index):
            raise LedgerCorruption("cycle_binding_invalid")
        if actual_start_ns is not None and not _positive_int(actual_start_ns):
            raise LedgerCorruption("cycle_timing_invalid")
        return self.create_versioned(
            _cycle_path(phase, cycle_index),
            {
                "schema_version": SCHEMA_VERSION,
                "qualification_id": qualification_id,
                "phase": phase,
                "cycle_index": cycle_index,
                "planned_slot_id": planned_slot_id,
                "mode": mode,
                "state": "planned",
                "attempt_ids": [],
                "final_attempt_id": None,
                **({"actual_start_ns": actual_start_ns} if actual_start_ns is not None else {}),
            },
        )

    def add_cycle_attempt(self, phase: str, cycle_index: int, attempt_id: str, *, expected_version: int) -> dict[str, Any]:
        path = _cycle_path(phase, cycle_index)
        cycle = self.read_record(path)
        attempts = list(cycle.get("attempt_ids") or [])
        if attempt_id in attempts:
            raise LedgerConflict("cycle_attempt_duplicate")
        attempts.append(attempt_id)
        return self.compare_and_swap(
            path,
            expected_version=expected_version,
            changes={"attempt_ids": attempts, "state": "running"},
        )

    def claim_final_attempt(
        self,
        phase: str,
        cycle_index: int,
        attempt_id: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        path = _cycle_path(phase, cycle_index)
        cycle = self.read_record(path)
        existing = cycle.get("final_attempt_id")
        if existing is not None:
            if existing == attempt_id:
                return cycle
            raise LedgerConflict("cycle_final_attempt_conflict")
        if attempt_id not in (cycle.get("attempt_ids") or []):
            raise LedgerConflict("cycle_final_attempt_not_registered")
        return self.compare_and_swap(
            path,
            expected_version=expected_version,
            changes={"final_attempt_id": attempt_id},
        )

    def mark_attempt_terminal_committed(
        self,
        phase: str,
        cycle_index: int,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        path = _cycle_path(phase, cycle_index)
        cycle = self.read_record(path)
        if cycle.get("state") == "attempt_terminal_committed":
            return cycle
        if cycle.get("state") != "running" or not cycle.get("final_attempt_id"):
            raise LedgerConflict("cycle_attempt_terminal_commit_invalid")
        return self.compare_and_swap(
            path,
            expected_version=expected_version,
            changes={"state": "attempt_terminal_committed"},
        )

    def mark_cycle_commit_intent(
        self,
        phase: str,
        cycle_index: int,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        path = _cycle_path(phase, cycle_index)
        cycle = self.read_record(path)
        if cycle.get("state") == "cycle_commit_intent":
            return cycle
        if cycle.get("state") != "attempt_terminal_committed":
            raise LedgerConflict("cycle_commit_intent_invalid")
        return self.compare_and_swap(
            path,
            expected_version=expected_version,
            changes={"state": "cycle_commit_intent"},
        )

    def commit_cycle(
        self,
        phase: str,
        cycle_index: int,
        *,
        expected_version: int,
        success: bool,
        actual_start_ns: int,
        commit_index: int,
        predecessor_binding: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = _cycle_path(phase, cycle_index)
        cycle = self.read_record(path)
        target = "cycle_committed_success" if success else "cycle_committed_failure"
        if cycle.get("state") == target:
            expected_predecessor = dict(predecessor_binding) if predecessor_binding is not None else None
            if (
                cycle.get("actual_start_ns") != actual_start_ns
                or cycle.get("commit_index") != commit_index
                or cycle.get("predecessor_binding") != expected_predecessor
            ):
                raise LedgerConflict("cycle_final_commit_conflict")
            return cycle
        if cycle.get("state") != "cycle_commit_intent":
            raise LedgerConflict("cycle_final_commit_invalid")
        if not _positive_int(actual_start_ns) or not _positive_int(commit_index):
            raise LedgerConflict("cycle_commit_timing_invalid")
        return self.compare_and_swap(
            path,
            expected_version=expected_version,
            changes={
                "state": target,
                "actual_start_ns": actual_start_ns,
                "commit_index": commit_index,
                **(
                    {"predecessor_binding": dict(predecessor_binding)}
                    if predecessor_binding is not None
                    else {}
                ),
            },
        )

    def create_attempt(self, binding: QualificationBinding, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = {
            "schema_version": SCHEMA_VERSION,
            "qualification_binding": binding.to_dict(),
            "attempt_id": binding.attempt_id,
            **dict(payload),
        }
        return self.create_versioned(_attempt_path(binding.attempt_id), record)

    def update_attempt(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        changes: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.compare_and_swap(
            _attempt_path(attempt_id),
            expected_version=expected_version,
            changes=changes,
        )

    def record_attempt_outcome(self, binding: QualificationBinding, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = _bound_record(binding, payload)
        return self.insert_if_absent(_outcome_path(binding.attempt_id), record)

    def record_receipt(self, binding: QualificationBinding, payload: Mapping[str, Any]) -> dict[str, Any]:
        _validate_receipt_export_safety(payload)
        record = _bound_record(binding, payload)
        return self.insert_if_absent(_receipt_path(binding.attempt_id), record)

    def read_receipt(self, attempt_id: str) -> dict[str, Any]:
        return self.read_record(_receipt_path(attempt_id))

    def read_attempt_outcome(self, attempt_id: str) -> dict[str, Any]:
        return self.read_record(_outcome_path(attempt_id))

    def validate_attempt_graph(
        self,
        attempt_ids: Sequence[str],
        *,
        stage_results: Sequence[Mapping[str, Any]],
        require_exact_attempt_set: bool = True,
    ) -> dict[str, Any]:
        reasons: set[str] = set()
        expected_ids = list(attempt_ids)
        if len(expected_ids) != len(set(expected_ids)):
            reasons.add("attempt_id_duplicate")
        attempt_records = self.list_records("standalone_production/attempts/")
        actual_ids = {str(item["payload"].get("attempt_id") or "") for item in attempt_records}
        if (
            require_exact_attempt_set
            and actual_ids != set(expected_ids)
            or not require_exact_attempt_set
            and not set(expected_ids).issubset(actual_ids)
        ):
            reasons.add("attempt_orphan_or_missing")
        stage_by_attempt: dict[str, list[Mapping[str, Any]]] = {}
        for stage_result in stage_results:
            raw_binding = stage_result.get("qualification_binding")
            try:
                stage_binding = QualificationBinding.from_dict(raw_binding if isinstance(raw_binding, Mapping) else {})
            except ValueError:
                reasons.add("qualification_binding_mismatch")
                continue
            if stage_binding.attempt_id not in expected_ids:
                if require_exact_attempt_set:
                    reasons.add("stage_result_orphan")
                continue
            stage_by_attempt.setdefault(stage_binding.attempt_id, []).append(stage_result)
        for attempt_id in expected_ids:
            try:
                attempt = self.read_record(_attempt_path(attempt_id))
                outcome = self.read_attempt_outcome(attempt_id)
                receipt = self.read_receipt(attempt_id)
            except FileNotFoundError:
                reasons.add("outcome_or_receipt_missing")
                continue
            try:
                attempt_binding = QualificationBinding.from_dict(attempt.get("qualification_binding") or {})
                outcome_binding = QualificationBinding.from_dict(outcome.get("qualification_binding") or {})
                receipt_binding = QualificationBinding.from_dict(receipt.get("qualification_binding") or {})
            except ValueError:
                reasons.add("qualification_binding_mismatch")
                continue
            if not (attempt_binding == outcome_binding == receipt_binding) or attempt_binding.attempt_id != attempt_id:
                reasons.add("qualification_binding_mismatch")
            mutation_phase = outcome.get("mutation_phase") or attempt.get("mutation_phase")
            if mutation_phase not in MUTATION_PHASE_INDEX:
                reasons.add("mutation_phase_unknown")
                continue
            expected_stage_count = 1 if MUTATION_PHASE_INDEX[mutation_phase] >= MUTATION_PHASE_INDEX["stage_mutation_intent"] else 0
            bound_stages = stage_by_attempt.get(attempt_id, [])
            if len(bound_stages) != expected_stage_count:
                reasons.add("stage_result_cardinality_invalid")
            for stage in bound_stages:
                try:
                    stage_binding = QualificationBinding.from_dict(stage.get("qualification_binding") or {})
                except ValueError:
                    reasons.add("qualification_binding_mismatch")
                    continue
                if stage_binding != attempt_binding:
                    reasons.add("qualification_binding_mismatch")
        return {"valid": not reasons, "reasons": sorted(reasons), "attempt_count": len(expected_ids)}

    def quick_check(self) -> dict[str, str]:
        try:
            with self._store._connect() as conn:
                rows = conn.execute("PRAGMA quick_check").fetchall()
            values = [str(row[0]) for row in rows]
        except Exception:
            return {"status": "blocked", "sqlite_quick_check": "unavailable"}
        if values == ["ok"]:
            return {"status": "ok", "sqlite_quick_check": "ok"}
        return {"status": "blocked", "sqlite_quick_check": "failed"}

    def _decode_document(self, path: str, stored: str) -> dict[str, Any]:
        return _mapping(self._store._decode_document(path, stored), reason="ledger_record_corrupt")

    def _decode_event(self, event_id: str, stored: str) -> dict[str, Any]:
        return _mapping(self._store._decode_audit_event(EVENT_STREAM, event_id, stored), reason="event_corrupt")


def _bound_record(binding: QualificationBinding, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "qualification_binding": binding.to_dict(),
        "attempt_id": binding.attempt_id,
        **dict(payload),
    }


def _validate_receipt_export_safety(payload: Mapping[str, Any]) -> None:
    forbidden_fragments = (
        "text",
        "message",
        "chat",
        "name",
        "screenshot",
        "screen_path",
        "clipboard",
        "api_key",
        "prompt",
        "response_body",
        "exact_observed",
    )

    def visit(value: Any, *, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).lower()
                if any(fragment in normalized for fragment in forbidden_fragments):
                    raise LedgerCorruption("receipt_sensitive_field_forbidden")
                visit(item, path=f"{path}.{normalized}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                visit(item, path=f"{path}[{index}]")
        elif isinstance(value, str) and len(value) > 512:
            raise LedgerCorruption("receipt_value_too_large")

    visit(payload, path="receipt")


def _record_path(path: str) -> str:
    if not isinstance(path, str):
        raise LedgerCorruption("ledger_path_invalid")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or not path.startswith(PRODUCTION_PREFIX) or ".." in parsed.parts or parsed.suffix != ".json":
        raise LedgerCorruption("ledger_path_invalid")
    return parsed.as_posix()


def _record_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not prefix.startswith(PRODUCTION_PREFIX) or ".." in PurePosixPath(prefix).parts:
        raise LedgerCorruption("ledger_prefix_invalid")
    return PurePosixPath(prefix).as_posix().rstrip("/") + "/"


def _mapping(value: Any, *, reason: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LedgerCorruption(reason)
    return dict(value)


def _event_binding(
    value: QualificationBinding | SelectionProbeBinding | Mapping[str, Any],
) -> QualificationBinding | SelectionProbeBinding:
    if isinstance(value, QualificationBinding):
        return value
    if isinstance(value, SelectionProbeBinding):
        return value
    try:
        if "attempt_id" in value:
            return QualificationBinding.from_dict(value)
        return SelectionProbeBinding.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise LedgerCorruption("qualification_binding_invalid") from exc


def _cycle_path(phase: str, cycle_index: int) -> str:
    if phase not in {"canary", "soak"} or not _positive_int(cycle_index):
        raise LedgerCorruption("cycle_binding_invalid")
    return f"standalone_production/cycles/{phase}/{cycle_index}.json"


def _attempt_path(attempt_id: str) -> str:
    if not _identifier(attempt_id):
        raise LedgerCorruption("attempt_id_invalid")
    return f"standalone_production/attempts/{attempt_id}.json"


def _outcome_path(attempt_id: str) -> str:
    if not _identifier(attempt_id):
        raise LedgerCorruption("attempt_id_invalid")
    return f"standalone_production/attempt_outcomes/{attempt_id}.json"


def _receipt_path(attempt_id: str) -> str:
    if not _identifier(attempt_id):
        raise LedgerCorruption("attempt_id_invalid")
    return f"standalone_production/receipts/{attempt_id}.json"


def _chain_error(reason: str, root: str | None, count: int) -> dict[str, Any]:
    return {"valid": False, "reason": reason, "chain_root": root, "event_count": count}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value and "/" not in value


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
