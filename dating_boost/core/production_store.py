from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATA_STORE_SCHEMA_VERSION = 1
MIGRATION_SCHEMA_VERSION = 1
AUTOMATION_LOCK_SCHEMA_VERSION = 1
CONFIRMATION_SCHEMA_VERSION = 1
PRODUCTION_DB_NAME = "dating_boost.sqlite3"
KNOWN_SCHEMA_VERSIONS = {1, 2}
BLOCKED_DRAFT_TEXT_KEYS = {
    "blocked_draft_text",
    "best_reply",
    "safer_reply",
    "bolder_reply",
    "payload_text",
    "staged_text",
}


@dataclass(frozen=True)
class LockAcquireResult:
    acquired: bool
    lock: dict[str, Any]


class ProductionDataStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.db_path = self.root / PRODUCTION_DB_NAME

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

    def doctor(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "needs_migration",
                "storage_backend": "json",
                "db_path": str(self.db_path),
                "schema_versions": _schema_versions(),
                "checks": {
                    "sqlite_db_exists": False,
                    "schema_ok": False,
                    "migration_ok": False,
                },
            }
        self.ensure_schema()
        with self._connect() as conn:
            metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
            document_count = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            audit_event_count = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
        migration_ok = metadata.get("migration_schema_version") == str(MIGRATION_SCHEMA_VERSION)
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok" if migration_ok else "needs_migration",
            "storage_backend": "sqlite",
            "db_path": str(self.db_path),
            "schema_versions": _schema_versions(),
            "document_count": document_count,
            "audit_event_count": audit_event_count,
            "checks": {
                "sqlite_db_exists": True,
                "schema_ok": metadata.get("data_store_schema_version") == str(DATA_STORE_SCHEMA_VERSION),
                "migration_ok": migration_ok,
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
                "schema_version": MIGRATION_SCHEMA_VERSION,
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
                        json.dumps(item["payload"], ensure_ascii=False, sort_keys=True),
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
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        str(payload.get("created_at") or migrated_at),
                    ),
                )
            self._set_metadata(conn, "storage_backend", "sqlite")
            self._set_metadata(conn, "migration_schema_version", str(MIGRATION_SCHEMA_VERSION))
            self._set_metadata(conn, "migrated_at", migrated_at)
            self._set_metadata(conn, "backup_dir", str(backup_dir))
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "status": "ok",
            "storage_backend": "sqlite",
            "db_path": str(self.db_path),
            "backup_dir": str(backup_dir),
            "migrated_documents": len(documents),
            "migrated_events": len(audit_events),
        }

    def export(self, output: Path) -> dict[str, Any]:
        migration_status = self._migration_status()
        if migration_status.get("status") != "ok":
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "needs_migration",
                "storage_backend": migration_status.get("storage_backend", "json"),
                "db_path": str(self.db_path),
            }
        output = output.resolve()
        with self._connect() as conn:
            documents = [
                {
                    "path": row["path"],
                    "schema_version": row["schema_version"],
                    "payload": _redact_if_blocked(json.loads(row["payload_json"])),
                }
                for row in conn.execute("SELECT path, schema_version, payload_json FROM documents ORDER BY path")
            ]
            audit_stream = [
                _redact_if_blocked(json.loads(row["payload_json"]))
                for row in conn.execute(
                    "SELECT payload_json FROM audit_events ORDER BY created_at, stream, event_id"
                )
            ]
            metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
        export_payload = {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "storage_backend": "sqlite",
            "exported_at": _now_iso(),
            "metadata": metadata,
            "documents": documents,
            "audit_stream": audit_stream,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(export_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "storage_backend": "sqlite",
            "output": str(output),
            "document_count": len(documents),
            "audit_event_count": len(audit_stream),
        }

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
                    json.dumps(_redact_if_blocked(payload), ensure_ascii=False, sort_keys=True),
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
                    json.dumps(_redact_if_blocked(payload), ensure_ascii=False, sort_keys=True),
                    str(payload.get("created_at") or _now_iso()),
                ),
            )

    def delete(self, *, scope: str, match_id: str | None, confirm: str) -> dict[str, Any]:
        required = delete_confirm_token(scope, match_id)
        if confirm != required:
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "confirm_token_mismatch",
                "required_confirm_token": required,
            }
        if scope == "all":
            deleted_documents = 0
            deleted_events = 0
            if self.db_path.exists():
                self.ensure_schema()
                with self._connect() as conn:
                    deleted_documents = int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
                    deleted_events = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
            if self.root.exists():
                for child in list(self.root.iterdir()):
                    _remove_path_if_exists(child)
            self.root.mkdir(parents=True, exist_ok=True)
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "ok",
                "scope": scope,
                "match_id": match_id,
                "deleted_documents": max(deleted_documents, 0),
                "deleted_events": max(deleted_events, 0),
            }

        self.ensure_schema()
        deleted_documents = 0
        deleted_events = 0
        with self._connect() as conn:
            if scope == "match":
                if not match_id:
                    return {
                        "schema_version": DATA_STORE_SCHEMA_VERSION,
                        "status": "blocked",
                        "reason": "match_id_required",
                        "required_confirm_token": required,
                    }
                pattern = f"%{match_id}%"
                deleted_documents = conn.execute(
                    "DELETE FROM documents WHERE path LIKE ? OR payload_json LIKE ?",
                    (pattern, pattern),
                ).rowcount
                deleted_events = conn.execute(
                    "DELETE FROM audit_events WHERE target_match_id = ? OR payload_json LIKE ?",
                    (match_id, pattern),
                ).rowcount
                json_cleanup = self._delete_match_from_json_files(match_id)
            elif scope == "archived":
                deleted_documents = conn.execute("DELETE FROM documents WHERE path LIKE 'archived/%'").rowcount
                _remove_path_if_exists(self.root / "archived")
            else:
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "invalid_scope",
                    "required_confirm_token": required,
                }
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "scope": scope,
            "match_id": match_id,
            "deleted_documents": max(deleted_documents, 0),
            "deleted_events": max(deleted_events, 0),
            "json_cleanup": json_cleanup if scope == "match" else None,
        }

    def acquire_lock(
        self,
        lock_name: str,
        *,
        owner: str,
        run_id: str,
        ttl_seconds: int = 300,
        now: str | None = None,
    ) -> LockAcquireResult:
        self.ensure_schema()
        now_text = now or _now_iso()
        expires_at = (_parse_iso(now_text) + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing_row = conn.execute("SELECT * FROM locks WHERE lock_name = ?", (lock_name,)).fetchone()
            if existing_row is not None:
                existing = dict(existing_row)
                existing["takeover"] = False
                if existing.get("status") == "active" and _parse_iso(str(existing["expires_at"])) > _parse_iso(now_text):
                    existing["lock_name"] = lock_name
                    return LockAcquireResult(False, existing)
            takeover = bool(existing_row and existing_row["status"] == "active")
            conn.execute(
                """
                INSERT INTO locks (lock_name, owner, run_id, started_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, 'active')
                ON CONFLICT(lock_name) DO UPDATE SET
                    owner = excluded.owner,
                    run_id = excluded.run_id,
                    started_at = excluded.started_at,
                    expires_at = excluded.expires_at,
                    status = excluded.status
                """,
                (lock_name, owner, run_id, now_text, expires_at),
            )
        return LockAcquireResult(
            True,
            {
                "schema_version": AUTOMATION_LOCK_SCHEMA_VERSION,
                "lock_name": lock_name,
                "owner": owner,
                "run_id": run_id,
                "started_at": now_text,
                "expires_at": expires_at,
                "status": "active",
                "takeover": takeover,
            },
        )

    def release_lock(self, lock_name: str, *, run_id: str, now: str | None = None) -> dict[str, Any]:
        self.ensure_schema()
        now_text = now or _now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM locks WHERE lock_name = ?", (lock_name,)).fetchone()
            if row is None:
                return {
                    "schema_version": AUTOMATION_LOCK_SCHEMA_VERSION,
                    "lock_name": lock_name,
                    "run_id": run_id,
                    "status": "missing",
                    "released_at": now_text,
                }
            lock = dict(row)
            conn.execute(
                "UPDATE locks SET status = 'released', expires_at = ? WHERE lock_name = ? AND run_id = ?",
                (now_text, lock_name, run_id),
            )
        lock["schema_version"] = AUTOMATION_LOCK_SCHEMA_VERSION
        lock["lock_name"] = lock_name
        lock["status"] = "released"
        lock["released_at"] = now_text
        return lock

    def write_lock(
        self,
        lock_name: str,
        *,
        owner: str,
        run_id: str,
        started_at: str,
        expires_at: str,
        status: str,
    ) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO locks (lock_name, owner, run_id, started_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(lock_name) DO UPDATE SET
                    owner = excluded.owner,
                    run_id = excluded.run_id,
                    started_at = excluded.started_at,
                    expires_at = excluded.expires_at,
                    status = excluded.status
                """,
                (lock_name, owner, run_id, started_at, expires_at, status),
            )

    def load_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])

    def store_idempotency(self, idempotency_key: str, *, run_id: str, response: dict[str, Any]) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO idempotency (idempotency_key, run_id, response_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    idempotency_key,
                    run_id,
                    json.dumps(response, ensure_ascii=False, sort_keys=True),
                    _now_iso(),
                ),
            )

    def create_confirmation(
        self,
        *,
        action: str,
        target_match_id: str,
        payload: Any,
        precondition: Any,
        expires_at: str,
    ) -> dict[str, Any]:
        self.ensure_schema()
        now = _now_iso()
        payload_hash = payload_digest(payload)
        precondition_hash = payload_digest(precondition)
        confirmation_id = "confirmation_" + _digest(
            {
                "action": action,
                "target_match_id": target_match_id,
                "payload_hash": payload_hash,
                "precondition_hash": precondition_hash,
                "expires_at": expires_at,
                "created_at": now,
            }
        )[:16]
        payload_json = {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "confirmation_id": confirmation_id,
            "action": action,
            "target_match_id": target_match_id,
            "payload_hash": payload_hash,
            "precondition_hash": precondition_hash,
            "expires_at": expires_at,
            "created_at": now,
            "confirmed_at": None,
            "status": "pending",
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO confirmations (
                    confirmation_id, action, target_match_id, payload_hash, precondition_hash,
                    expires_at, created_at, confirmed_at, status, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'pending', ?)
                """,
                (
                    confirmation_id,
                    action,
                    target_match_id,
                    payload_hash,
                    precondition_hash,
                    expires_at,
                    now,
                    json.dumps(payload_json, ensure_ascii=False, sort_keys=True),
                ),
            )
        return payload_json

    def confirm_confirmation(self, confirmation_id: str) -> dict[str, Any]:
        self.ensure_schema()
        now = _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            ).fetchone()
            if row is None:
                return {
                    "schema_version": CONFIRMATION_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "confirmation_not_found",
                    "confirmation_id": confirmation_id,
                }
            conn.execute(
                "UPDATE confirmations SET status = 'confirmed', confirmed_at = ? WHERE confirmation_id = ?",
                (now, confirmation_id),
            )
        payload = dict(row)
        return {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "status": "confirmed",
            "confirmation_id": confirmation_id,
            "confirmed_at": now,
            "action": payload["action"],
            "target_match_id": payload["target_match_id"],
        }

    def validate_confirmation(
        self,
        *,
        confirmation_id: str,
        action: str,
        target_match_id: str,
        payload: Any,
        precondition: Any,
        now: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        now_text = now or _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            ).fetchone()
        if row is None:
            return _confirmation_blocked(confirmation_id, "confirmation_not_found")
        record = dict(row)
        if record["action"] != action:
            return _confirmation_blocked(confirmation_id, "action_mismatch")
        if record["target_match_id"] != target_match_id:
            return _confirmation_blocked(confirmation_id, "target_match_id_mismatch")
        if record["payload_hash"] != payload_digest(payload):
            return _confirmation_blocked(confirmation_id, "payload_hash_mismatch")
        if record["precondition_hash"] != payload_digest(precondition):
            return _confirmation_blocked(confirmation_id, "precondition_hash_mismatch")
        if _parse_iso(str(record["expires_at"])) <= _parse_iso(now_text):
            return _confirmation_blocked(confirmation_id, "confirmation_expired")
        if record["status"] != "confirmed":
            return _confirmation_blocked(confirmation_id, "confirmation_not_confirmed")
        return {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "status": "ok",
            "confirmation_id": confirmation_id,
            "action": action,
            "target_match_id": target_match_id,
            "payload_hash": record["payload_hash"],
            "precondition_hash": record["precondition_hash"],
            "expires_at": record["expires_at"],
            "confirmed_at": record["confirmed_at"],
        }

    def validate_confirmation_hashes(
        self,
        *,
        confirmation_id: str,
        action: str,
        target_match_id: str,
        payload_hash: str,
        precondition_hash: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        now_text = now or _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM confirmations WHERE confirmation_id = ?",
                (confirmation_id,),
            ).fetchone()
        if row is None:
            return _confirmation_blocked(confirmation_id, "confirmation_not_found")
        record = dict(row)
        if record["action"] != action:
            return _confirmation_blocked(confirmation_id, "action_mismatch")
        if record["target_match_id"] != target_match_id:
            return _confirmation_blocked(confirmation_id, "target_match_id_mismatch")
        if record["payload_hash"] != payload_hash:
            return _confirmation_blocked(confirmation_id, "payload_hash_mismatch")
        if record["precondition_hash"] != precondition_hash:
            return _confirmation_blocked(confirmation_id, "precondition_hash_mismatch")
        if _parse_iso(str(record["expires_at"])) <= _parse_iso(now_text):
            return _confirmation_blocked(confirmation_id, "confirmation_expired")
        if record["status"] != "confirmed":
            return _confirmation_blocked(confirmation_id, "confirmation_not_confirmed")
        return {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "status": "ok",
            "confirmation_id": confirmation_id,
            "action": action,
            "target_match_id": target_match_id,
            "payload_hash": payload_hash,
            "precondition_hash": precondition_hash,
            "expires_at": record["expires_at"],
            "confirmed_at": record["confirmed_at"],
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

    def _delete_match_from_json_files(self, match_id: str) -> dict[str, int]:
        deleted_files = 0
        rewritten_files = 0
        removed_jsonl_events = 0
        for path in self._iter_json_files(include_backups=True):
            if path.name == PRODUCTION_DB_NAME or path.name.startswith(f"{PRODUCTION_DB_NAME}-"):
                continue
            relative_parts = path.relative_to(self.root).parts
            if "matches" in relative_parts:
                match_index = relative_parts.index("matches")
                if len(relative_parts) > match_index + 1 and relative_parts[match_index + 1] == match_id:
                    _remove_path_if_exists(path)
                    deleted_files += 1
                    continue
            if path.suffix == ".jsonl":
                kept_lines: list[str] = []
                changed = False
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        kept_lines.append(line)
                        continue
                    if _contains_match_reference(item, match_id):
                        changed = True
                        removed_jsonl_events += 1
                        continue
                    kept_lines.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
                if changed:
                    if kept_lines:
                        path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
                        rewritten_files += 1
                    else:
                        path.unlink()
                        deleted_files += 1
                continue
            if path.suffix != ".json":
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            cleaned, remove_node, changed = _remove_match_reference(payload, match_id)
            if remove_node:
                path.unlink()
                deleted_files += 1
            elif changed:
                path.write_text(
                    json.dumps(cleaned, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                rewritten_files += 1
        _remove_empty_dirs(self.root)
        return {
            "deleted_files": deleted_files,
            "rewritten_files": rewritten_files,
            "removed_jsonl_events": removed_jsonl_events,
        }

    def _iter_json_files(self, *, include_backups: bool) -> list[Path]:
        if not self.root.exists():
            return []
        files: list[Path] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(self.root).parts
            if not include_backups and relative_parts and relative_parts[0] == "backups":
                continue
            if path.suffix in {".json", ".jsonl"}:
                files.append(path)
        return sorted(files)


class MigrationBlocked(Exception):
    def __init__(self, reason: str, path: str):
        super().__init__(reason)
        self.reason = reason
        self.path = path


def delete_confirm_token(scope: str, match_id: str | None) -> str:
    if scope == "match":
        return f"delete:match:{match_id or '<match-id>'}"
    if scope == "archived":
        return "delete:archived"
    return "delete:all"


def payload_digest(payload: Any) -> str:
    return "sha256:" + _digest(payload)


def _confirmation_blocked(confirmation_id: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": CONFIRMATION_SCHEMA_VERSION,
        "status": "blocked",
        "reason": reason,
        "confirmation_id": confirmation_id,
    }


def _schema_versions() -> dict[str, int]:
    return {
        "data_store": DATA_STORE_SCHEMA_VERSION,
        "migration": MIGRATION_SCHEMA_VERSION,
        "automation_lock": AUTOMATION_LOCK_SCHEMA_VERSION,
        "confirmation": CONFIRMATION_SCHEMA_VERSION,
    }


def _redact_if_blocked(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if not _is_blocked_payload(payload):
        return payload
    return _redact_keys(payload)


def _is_blocked_payload(payload: dict[str, Any]) -> bool:
    if payload.get("status") == "blocked":
        return True
    policy = payload.get("policy")
    return isinstance(policy, dict) and policy.get("allowed") is False


def _redact_keys(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in BLOCKED_DRAFT_TEXT_KEYS:
                continue
            result[key] = _redact_keys(item)
        return result
    if isinstance(value, list):
        return [_redact_keys(item) for item in value]
    return value


def _remove_path_if_exists(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        if path == root:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()


def _contains_match_reference(value: Any, match_id: str) -> bool:
    if isinstance(value, str):
        return match_id in value
    if isinstance(value, dict):
        return any(_contains_match_reference(item, match_id) for item in value.values())
    if isinstance(value, list):
        return any(_contains_match_reference(item, match_id) for item in value)
    return False


def _remove_match_reference(value: Any, match_id: str) -> tuple[Any, bool, bool]:
    if isinstance(value, str):
        return (None, True, True) if match_id in value else (value, False, False)
    if isinstance(value, list):
        changed = False
        result: list[Any] = []
        for item in value:
            cleaned, remove_node, item_changed = _remove_match_reference(item, match_id)
            if remove_node:
                changed = True
                continue
            if item_changed:
                changed = True
            result.append(cleaned)
        return result, False, changed
    if isinstance(value, dict):
        for key in ("match_id", "target_match_id"):
            if value.get(key) == match_id:
                return None, True, True
        changed = False
        result: dict[str, Any] = {}
        for key, item in value.items():
            cleaned, remove_node, item_changed = _remove_match_reference(item, match_id)
            if remove_node:
                changed = True
                continue
            if item_changed:
                changed = True
            result[key] = cleaned
        return result, False, changed
    return value, False, False


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
