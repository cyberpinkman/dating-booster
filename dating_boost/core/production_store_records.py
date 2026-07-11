from __future__ import annotations

from typing import Any

from dating_boost.core.production_store_common import (
    AUTOMATION_LOCK_SCHEMA_VERSION, BACKUP_RECOVERY_KEY_SCHEMA_VERSION, BLOCKED_DRAFT_TEXT_KEYS, CONFIRMATION_SCHEMA_VERSION,
    DATA_STORE_SCHEMA_VERSION, DIAGNOSTIC_BUNDLE_SCHEMA_VERSION, ENCRYPTED_PAYLOAD_SCHEMA_VERSION, KEYCHAIN_BINDING_SCHEMA_VERSION,
    KNOWN_SCHEMA_VERSIONS, LockAcquireResult, MIGRATION_SCHEMA_VERSION, MigrationBlocked,
    PRODUCTION_DB_NAME, RELEASE_MANIFEST_SCHEMA_VERSION, _confirmation_blocked, _digest,
    _is_blocked_payload, _is_match_local_path, _now_iso, _parse_iso,
    _redact_if_blocked, _redact_keys, _remove_empty_dirs, _remove_match_reference,
    _remove_path_if_exists, _schema_versions, _sqlite_integrity_ok, _validate_match_local_prefix,
    delete_confirm_token, payload_digest,
)

__all__ = ["ProductionStoreRecordsMixin"]

class ProductionStoreRecordsMixin:
    def upsert_document(self, relative_path: str, payload: dict[str, Any]) -> None:
        self.ensure_schema()
        schema_version = payload.get("schema_version")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (path, schema_version, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    relative_path,
                    schema_version,
                    self._encode_document(relative_path, _redact_if_blocked(payload)),
                    _now_iso(),
                ),
            )

    def append_audit_event(self, relative_path: str, payload: dict[str, Any]) -> None:
        self.ensure_schema()
        event_id = str(payload.get("event_id") or f"event_{_digest(payload)[:16]}")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (stream, event_id, target_match_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(stream, event_id) DO UPDATE SET
                    target_match_id = excluded.target_match_id,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    relative_path,
                    event_id,
                    payload.get("target_match_id"),
                    self._encode_audit_event(relative_path, event_id, _redact_if_blocked(payload)),
                    str(payload.get("created_at") or _now_iso()),
                ),
            )

    def replace_audit_stream(self, relative_path: str, payloads: list[dict[str, Any]]) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute("DELETE FROM audit_events WHERE stream = ?", (relative_path,))
            for payload in payloads:
                event_id = str(payload.get("event_id") or f"event_{_digest(payload)[:16]}")
                conn.execute(
                    """
                    INSERT INTO audit_events (stream, event_id, target_match_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(stream, event_id) DO UPDATE SET
                        target_match_id = excluded.target_match_id,
                        payload_json = excluded.payload_json,
                        created_at = excluded.created_at
                    """,
                    (
                        relative_path,
                        event_id,
                        payload.get("target_match_id"),
                        self._encode_audit_event(relative_path, event_id, _redact_if_blocked(payload)),
                        str(payload.get("created_at") or _now_iso()),
                    ),
                )

    def get_document(self, relative_path: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT path, payload_json FROM documents WHERE path = ?",
                (relative_path,),
            ).fetchone()
        if row is None:
            return None
        payload = self._decode_document(row["path"], row["payload_json"])
        return payload if isinstance(payload, dict) else {"payload": payload}

    def document_exists(self, relative_path: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM documents WHERE path = ?", (relative_path,)).fetchone()
        return row is not None

    def delete_document(self, relative_path: str) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            return int(conn.execute("DELETE FROM documents WHERE path = ?", (relative_path,)).rowcount)

    def list_documents(self, *, prefix: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT path, schema_version, payload_json, updated_at FROM documents WHERE path LIKE ? ORDER BY path",
                (f"{prefix}%",),
            ).fetchall()
        documents: list[dict[str, Any]] = []
        for row in rows:
            payload = self._decode_document(row["path"], row["payload_json"])
            documents.append(
                {
                    "path": row["path"],
                    "schema_version": row["schema_version"],
                    "updated_at": row["updated_at"],
                    "payload": payload,
                }
            )
        return documents

    def list_audit_events(self, *, stream: str) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stream, event_id, target_match_id, payload_json, created_at
                FROM audit_events
                WHERE stream = ?
                ORDER BY rowid
                """,
                (stream,),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            payload = self._decode_audit_event(row["stream"], row["event_id"], row["payload_json"])
            events.append(
                {
                    "stream": row["stream"],
                    "event_id": row["event_id"],
                    "target_match_id": row["target_match_id"],
                    "created_at": row["created_at"],
                    "payload": payload,
                }
            )
        return events

    def audit_stream_exists(self, relative_path: str) -> bool:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM audit_events WHERE stream = ? LIMIT 1", (relative_path,)).fetchone()
        return row is not None

    def delete_audit_stream(self, relative_path: str) -> int:
        self.ensure_schema()
        with self._connect() as conn:
            return int(conn.execute("DELETE FROM audit_events WHERE stream = ?", (relative_path,)).rowcount)

    def delete_documents_with_prefix(self, prefix: str) -> int:
        _validate_match_local_prefix(prefix)
        self.ensure_schema()
        with self._connect() as conn:
            return int(
                conn.execute(
                    "DELETE FROM documents WHERE substr(path, 1, ?) = ?",
                    (len(prefix), prefix),
                ).rowcount
            )
    def delete_audit_events_with_stream_prefix(self, prefix: str) -> int:
        _validate_match_local_prefix(prefix)
        self.ensure_schema()
        with self._connect() as conn:
            return int(
                conn.execute(
                    "DELETE FROM audit_events WHERE substr(stream, 1, ?) = ?",
                    (len(prefix), prefix),
                ).rowcount
            )
