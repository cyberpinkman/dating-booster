from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from dating_boost.core.encryption import EncryptionError, LOCAL_KEY_NAME, payload_is_encrypted
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

__all__ = ["ProductionStoreSchemaMixin"]

class ProductionStoreSchemaMixin:
    def ensure_schema(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    path TEXT PRIMARY KEY,
                    schema_version INTEGER,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    stream TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    target_match_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (stream, event_id)
                );
                CREATE TABLE IF NOT EXISTS locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS confirmations (
                    confirmation_id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    target_match_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    precondition_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self._set_metadata(conn, "data_store_schema_version", str(DATA_STORE_SCHEMA_VERSION))
            self._set_metadata(conn, "storage_backend", "sqlite")
            self._set_metadata(conn, "encrypted_payload_schema_version", str(ENCRYPTED_PAYLOAD_SCHEMA_VERSION))
            self._set_metadata(conn, "keychain_binding_schema_version", str(KEYCHAIN_BINDING_SCHEMA_VERSION))
            self._set_metadata(conn, "encryption", "enabled")
            self._set_metadata(conn, "encryption_provider", self._cipher.provider.provider_name)

    def doctor(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "needs_migration",
                "storage_backend": "json",
                "db_path": str(self.db_path),
                "schema_versions": _schema_versions(),
                "encryption": {
                    "status": "not_initialized",
                    "encrypted_payload_schema_version": ENCRYPTED_PAYLOAD_SCHEMA_VERSION,
                    "keychain_binding_schema_version": KEYCHAIN_BINDING_SCHEMA_VERSION,
                },
                "checks": {
                    "sqlite_db_exists": False,
                    "schema_ok": False,
                    "migration_ok": False,
                    "encryption_ok": False,
                },
            }
        try:
            self.ensure_schema()
            with self._connect() as conn:
                metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
                document_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
                audit_event_count = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
                verification = self._verify_encrypted_payloads(conn)
        except EncryptionError:
            return self._blocked_doctor("payload_decryption_failed")
        except sqlite3.DatabaseError:
            return self._blocked_doctor("sqlite_unreadable")
        migration_ok = metadata.get("migration_schema_version") == str(MIGRATION_SCHEMA_VERSION)
        encryption = self._cipher.status_without_creating_key()
        encryption_ok = (
            metadata.get("encryption") == "enabled"
            and verification["encrypted_documents"] == document_count
            and verification["encrypted_audit_events"] == audit_event_count
            and verification["encrypted_idempotency"] == verification["idempotency_count"]
            and verification["encrypted_confirmations"] == verification["confirmation_count"]
        )
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok" if migration_ok else "needs_migration",
            "storage_backend": "sqlite",
            "db_path": str(self.db_path),
            "schema_versions": _schema_versions(),
            "document_count": document_count,
            "audit_event_count": audit_event_count,
            "encrypted_payload_count": verification["encrypted_documents"],
            "encryption": {
                "status": "encrypted" if encryption_ok else "unknown",
                "provider": encryption.provider,
                "key_id": encryption.key_id,
                "encrypted_payload_schema_version": ENCRYPTED_PAYLOAD_SCHEMA_VERSION,
                "keychain_binding_schema_version": KEYCHAIN_BINDING_SCHEMA_VERSION,
            },
            "checks": {
                "sqlite_db_exists": True,
                "schema_ok": metadata.get("data_store_schema_version") == str(DATA_STORE_SCHEMA_VERSION),
                "migration_ok": migration_ok,
                "encryption_ok": encryption_ok,
            },
        }

    def migrate(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        backup_dir = self._backup_json_sources()
        try:
            documents, audit_events = self._load_json_sources()
        except MigrationBlocked as exc:
            if self.db_path.exists():
                self.db_path.unlink()
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "migration_schema_version": MIGRATION_SCHEMA_VERSION,
                "status": "blocked",
                "reason": exc.reason,
                "path": exc.path,
                "storage_backend": "json",
                "backup_dir": str(backup_dir),
            }

        self.ensure_schema()
        migrated_at = _now_iso()
        with self._connect() as conn:
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM audit_events")
            for item in documents:
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
                        item["path"],
                        item["schema_version"],
                        self._encode_document(item["path"], item["payload"]),
                        migrated_at,
                    ),
                )
            for event in audit_events:
                payload = event["payload"]
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
                        event["stream"],
                        event["event_id"],
                        payload.get("target_match_id"),
                        self._encode_audit_event(event["stream"], event["event_id"], payload),
                        str(payload.get("created_at") or migrated_at),
                    ),
                )
            self._set_metadata(conn, "storage_backend", "sqlite")
            self._set_metadata(conn, "migration_schema_version", str(MIGRATION_SCHEMA_VERSION))
            self._set_metadata(conn, "migrated_at", migrated_at)
            self._set_metadata(conn, "backup_dir", str(backup_dir))
            self._set_metadata(conn, "encryption", "enabled")
            self._set_metadata(conn, "encryption_provider", self._cipher.status().provider)
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "migration_schema_version": MIGRATION_SCHEMA_VERSION,
            "status": "ok",
            "storage_backend": "sqlite",
            "encryption": self._encryption_payload(),
            "db_path": str(self.db_path),
            "backup_dir": str(backup_dir),
            "migrated_documents": len(documents),
            "migrated_events": len(audit_events),
        }

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _set_metadata(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _backup_json_sources(self) -> Path:
        timestamp = _now_iso().replace(":", "").replace("-", "")
        backup_root = self.root / "backups"
        backup_dir = backup_root / timestamp
        suffix = 1
        while backup_dir.exists():
            suffix += 1
            backup_dir = backup_root / f"{timestamp}_{suffix}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for path in self._iter_source_files():
            target = backup_dir / path.relative_to(self.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        return backup_dir

    def _load_json_sources(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        documents: list[dict[str, Any]] = []
        audit_events: list[dict[str, Any]] = []
        for path in self._iter_source_files():
            relative = path.relative_to(self.root).as_posix()
            if path.suffix == ".json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise MigrationBlocked("corrupt_json", relative) from exc
                if not isinstance(payload, dict):
                    raise MigrationBlocked("invalid_json_document", relative)
                schema_version = payload.get("schema_version")
                if schema_version is not None and schema_version not in KNOWN_SCHEMA_VERSIONS:
                    raise MigrationBlocked("unknown_schema_version", relative)
                documents.append(
                    {
                        "path": relative,
                        "schema_version": schema_version,
                        "payload": _redact_if_blocked(payload),
                    }
                )
            elif path.suffix == ".jsonl":
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except UnicodeDecodeError as exc:
                    raise MigrationBlocked("invalid_jsonl", relative) from exc
                for index, line in enumerate(lines, start=1):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise MigrationBlocked("corrupt_jsonl", f"{relative}:{index}") from exc
                    if not isinstance(payload, dict):
                        raise MigrationBlocked("invalid_jsonl_event", f"{relative}:{index}")
                    schema_version = payload.get("schema_version")
                    if schema_version is not None and schema_version not in KNOWN_SCHEMA_VERSIONS:
                        raise MigrationBlocked("unknown_schema_version", f"{relative}:{index}")
                    event_id = str(payload.get("event_id") or f"event_{_digest(payload)[:16]}")
                    audit_events.append(
                        {
                            "stream": relative,
                            "event_id": event_id,
                            "payload": _redact_if_blocked(payload),
                        }
                    )
        return documents, audit_events

    def _iter_source_files(self) -> list[Path]:
        if not self.root.exists():
            return []
        files: list[Path] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(self.root).parts
            if not relative_parts:
                continue
            if relative_parts[0] == "backups":
                continue
            if path.name == PRODUCTION_DB_NAME or path.name.startswith(f"{PRODUCTION_DB_NAME}-"):
                continue
            if path.name == LOCAL_KEY_NAME:
                continue
            if path.suffix not in {".json", ".jsonl"}:
                continue
            files.append(path)
        return sorted(files)

    def _migration_status(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {"status": "needs_migration", "storage_backend": "json"}
        self.ensure_schema()
        with self._connect() as conn:
            metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
        if metadata.get("migration_schema_version") != str(MIGRATION_SCHEMA_VERSION):
            return {"status": "needs_migration", "storage_backend": "sqlite"}
        return {"status": "ok", "storage_backend": "sqlite"}

    def _blocked_doctor(self, reason: str) -> dict[str, Any]:
        encryption = self._cipher.status_without_creating_key()
        remediation = None
        if reason == "payload_decryption_failed":
            remediation = {
                "summary": "Encrypted payloads exist but could not be decrypted with the current local key.",
                "likely_causes": [
                    "missing_keychain_key",
                    "key_id_mismatch",
                    "wrong_recovery_passphrase_or_unrestored_backup",
                    "corrupted_encrypted_payload",
                ],
                "next_steps": [
                    "Run data unlock with the correct recovery passphrase if this data came from backup.",
                    "Verify this data directory belongs to the current macOS user/keychain.",
                    "If the key was rotated, restore or rekey from a valid backup.",
                    "Do not run migration or delete commands until the key issue is resolved.",
                ],
            }
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "blocked",
            "reason": reason,
            "storage_backend": "sqlite",
            "db_path": str(self.db_path),
            "schema_versions": _schema_versions(),
            "encryption": {
                "status": "ok" if encryption.enabled else "missing_key",
                "provider": encryption.provider,
                "key_id": encryption.key_id,
                "encrypted_payload_schema_version": ENCRYPTED_PAYLOAD_SCHEMA_VERSION,
                "keychain_binding_schema_version": KEYCHAIN_BINDING_SCHEMA_VERSION,
            },
            "remediation": remediation,
            "checks": {
                "sqlite_db_exists": self.db_path.exists(),
                "schema_ok": False,
                "migration_ok": False,
                "encryption_ok": False,
            },
        }

    def _blocked_export(self, reason: str, output: Path) -> dict[str, Any]:
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "blocked",
            "reason": reason,
            "storage_backend": "sqlite",
            "db_path": str(self.db_path),
            "output": str(output.resolve()),
        }

    def _verify_encrypted_payloads(self, conn: sqlite3.Connection) -> dict[str, int]:
        counts = {
            "encrypted_documents": 0,
            "encrypted_audit_events": 0,
            "encrypted_idempotency": 0,
            "idempotency_count": 0,
            "encrypted_confirmations": 0,
            "confirmation_count": 0,
        }
        for row in conn.execute("SELECT path, payload_json FROM documents"):
            stored = row["payload_json"]
            if payload_is_encrypted(stored):
                counts["encrypted_documents"] += 1
            self._decode_document(row["path"], stored)
        for row in conn.execute("SELECT stream, event_id, payload_json FROM audit_events"):
            stored = row["payload_json"]
            if payload_is_encrypted(stored):
                counts["encrypted_audit_events"] += 1
            self._decode_audit_event(row["stream"], row["event_id"], stored)
        for row in conn.execute("SELECT idempotency_key, response_json FROM idempotency"):
            counts["idempotency_count"] += 1
            stored = row["response_json"]
            if payload_is_encrypted(stored):
                counts["encrypted_idempotency"] += 1
            self._decode_idempotency(row["idempotency_key"], stored)
        for row in conn.execute("SELECT confirmation_id, payload_json FROM confirmations"):
            counts["confirmation_count"] += 1
            stored = row["payload_json"]
            if payload_is_encrypted(stored):
                counts["encrypted_confirmations"] += 1
            self._decode_confirmation(row["confirmation_id"], stored)
        return counts

    def _encode_document(self, path: str, payload: Any) -> str:
        return self._cipher.encrypt_json(payload, associated_data=f"document:{path}")

    def _decode_document(self, path: str, stored: str) -> Any:
        return self._cipher.decrypt_json(stored, associated_data=f"document:{path}")

    def _encode_audit_event(self, stream: str, event_id: str, payload: Any) -> str:
        return self._cipher.encrypt_json(payload, associated_data=f"audit:{stream}:{event_id}")

    def _decode_audit_event(self, stream: str, event_id: str, stored: str) -> Any:
        return self._cipher.decrypt_json(stored, associated_data=f"audit:{stream}:{event_id}")

    def _encode_idempotency(self, idempotency_key: str, payload: Any) -> str:
        return self._cipher.encrypt_json(payload, associated_data=f"idempotency:{idempotency_key}")

    def _decode_idempotency(self, idempotency_key: str, stored: str) -> Any:
        return self._cipher.decrypt_json(stored, associated_data=f"idempotency:{idempotency_key}")

    def _encode_confirmation(self, confirmation_id: str, payload: Any) -> str:
        return self._cipher.encrypt_json(payload, associated_data=f"confirmation:{confirmation_id}")

    def _decode_confirmation(self, confirmation_id: str, stored: str) -> Any:
        return self._cipher.decrypt_json(stored, associated_data=f"confirmation:{confirmation_id}")

    def _encryption_payload(self) -> dict[str, Any]:
        status = self._cipher.status()
        return {
            "status": "encrypted" if status.enabled else "disabled",
            "provider": status.provider,
            "key_id": status.key_id,
            "encrypted_payload_schema_version": ENCRYPTED_PAYLOAD_SCHEMA_VERSION,
            "keychain_binding_schema_version": KEYCHAIN_BINDING_SCHEMA_VERSION,
        }
