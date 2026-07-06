from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from dating_boost.core.encryption import EncryptionError
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

__all__ = ["ProductionStoreBackupMixin"]

class ProductionStoreBackupMixin:
    def export(self, output: Path) -> dict[str, Any]:
        try:
            migration_status = self._migration_status()
        except sqlite3.DatabaseError:
            return self._blocked_export("sqlite_unreadable", output)
        if migration_status.get("status") != "ok":
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "needs_migration",
                "storage_backend": migration_status.get("storage_backend", "json"),
                "db_path": str(self.db_path),
            }
        output = output.resolve()
        try:
            with self._connect() as conn:
                documents = [
                    {
                        "path": row["path"],
                        "schema_version": row["schema_version"],
                        "payload": _redact_if_blocked(self._decode_document(row["path"], row["payload_json"])),
                    }
                    for row in conn.execute("SELECT path, schema_version, payload_json FROM documents ORDER BY path")
                ]
                audit_stream = [
                    _redact_if_blocked(self._decode_audit_event(row["stream"], row["event_id"], row["payload_json"]))
                    for row in conn.execute(
                        "SELECT stream, event_id, payload_json FROM audit_events ORDER BY created_at, stream, event_id"
                    )
                ]
                metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
        except EncryptionError:
            return self._blocked_export("payload_decryption_failed", output)
        except sqlite3.DatabaseError:
            return self._blocked_export("sqlite_unreadable", output)
        export_payload = {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "storage_backend": "sqlite",
            "encryption": self._encryption_payload(),
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

    def backup(self, output: Path, *, recovery_passphrase: str | None = None) -> dict[str, Any]:
        migration_status = self._migration_status()
        if migration_status.get("status") != "ok":
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "needs_migration",
                "db_path": str(self.db_path),
            }
        if not recovery_passphrase:
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "recovery_passphrase_required",
                "db_path": str(self.db_path),
            }
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            metadata = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
        manifest = {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "backup_format": "dating_boost_sqlite_zip",
            "created_at": _now_iso(),
            "encrypted": True,
            "db_file": PRODUCTION_DB_NAME,
            "metadata": metadata,
            "key_recovery": "passphrase",
            "recovery_key": self._cipher.encrypt_recovery_key(recovery_passphrase),
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
            archive.write(self.db_path, PRODUCTION_DB_NAME)
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "encrypted": True,
            "output": str(output),
            "key_recovery": "passphrase",
        }

    def restore(self, input_path: Path, *, confirm: str, recovery_passphrase: str | None = None) -> dict[str, Any]:
        if confirm != "restore":
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "confirm_token_mismatch",
                "required_confirm_token": "restore",
            }
        input_path = input_path.resolve()
        with zipfile.ZipFile(input_path) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("backup_format") != "dating_boost_sqlite_zip":
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "invalid_backup_format",
                }
            db_bytes = archive.read(str(manifest.get("db_file") or PRODUCTION_DB_NAME))
        recovery_key = manifest.get("recovery_key")
        restored_key: bytes | None = None
        if isinstance(recovery_key, dict):
            if not recovery_passphrase:
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "recovery_passphrase_required",
                    "input": str(input_path),
                }
            try:
                restored_key = self._cipher.decrypt_recovery_key(recovery_key, recovery_passphrase)
            except EncryptionError:
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "recovery_passphrase_invalid",
                    "input": str(input_path),
                }
        elif isinstance(manifest.get("local_key_material"), str):
            try:
                restored_key = base64.b64decode(str(manifest["local_key_material"]))
            except Exception:
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "legacy_local_key_invalid",
                    "input": str(input_path),
                }
            if len(restored_key) != 32:
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "legacy_local_key_invalid",
                    "input": str(input_path),
                }
        elif manifest.get("encrypted"):
            return {
                "schema_version": DATA_STORE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "recovery_key_missing",
                "input": str(input_path),
            }
        temp_parent = self.root.parent
        temp_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{self.root.name}.restore-", dir=temp_parent) as temp_dir:
            temp_root = Path(temp_dir) / "data"
            temp_root.mkdir(parents=True, exist_ok=True)
            temp_store = type(self)(temp_root)
            if restored_key is not None:
                temp_store._cipher.store_raw_key(restored_key)
            temp_store.db_path.write_bytes(db_bytes)
            if not _sqlite_integrity_ok(temp_store.db_path):
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "backup_sqlite_integrity_failed",
                    "input": str(input_path),
                }
            doctor = temp_store.doctor()
            if doctor.get("status") != "ok":
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": str(doctor.get("reason") or "backup_doctor_failed"),
                    "input": str(input_path),
                    "doctor": doctor,
                }
            self._replace_root_with(temp_root)
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "input": str(input_path),
            "db_path": str(self.db_path),
            "encrypted": bool(manifest.get("encrypted")),
            "key_recovery": manifest.get("key_recovery") or "legacy_local_key",
        }

    def rekey(self) -> dict[str, Any]:
        self.ensure_schema()
        old_key = self._cipher.provider.load_or_create_key()
        with self._connect() as conn:
            documents = [
                {
                    "path": row["path"],
                    "schema_version": row["schema_version"],
                    "payload": self._decode_document(row["path"], row["payload_json"]),
                }
                for row in conn.execute("SELECT path, schema_version, payload_json FROM documents ORDER BY path")
            ]
            audit_events = [
                {
                    "stream": row["stream"],
                    "event_id": row["event_id"],
                    "target_match_id": row["target_match_id"],
                    "payload": self._decode_audit_event(row["stream"], row["event_id"], row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in conn.execute(
                    "SELECT stream, event_id, target_match_id, payload_json, created_at FROM audit_events ORDER BY stream, event_id"
                )
            ]
            idempotency_rows = [
                {
                    "idempotency_key": row["idempotency_key"],
                    "run_id": row["run_id"],
                    "response": self._decode_idempotency(row["idempotency_key"], row["response_json"]),
                    "created_at": row["created_at"],
                }
                for row in conn.execute("SELECT idempotency_key, run_id, response_json, created_at FROM idempotency")
            ]
            confirmation_rows = [
                {
                    **dict(row),
                    "payload": self._decode_confirmation(row["confirmation_id"], row["payload_json"]),
                }
                for row in conn.execute("SELECT * FROM confirmations")
            ]
        try:
            self._cipher.rotate_key()
            rekeyed_at = _now_iso()
            with self._connect() as conn:
                for item in documents:
                    conn.execute(
                        "UPDATE documents SET payload_json = ?, updated_at = ? WHERE path = ?",
                        (self._encode_document(item["path"], item["payload"]), rekeyed_at, item["path"]),
                    )
                for item in audit_events:
                    conn.execute(
                        "UPDATE audit_events SET payload_json = ? WHERE stream = ? AND event_id = ?",
                        (self._encode_audit_event(item["stream"], item["event_id"], item["payload"]), item["stream"], item["event_id"]),
                    )
                for item in idempotency_rows:
                    conn.execute(
                        "UPDATE idempotency SET response_json = ? WHERE idempotency_key = ?",
                        (self._encode_idempotency(item["idempotency_key"], item["response"]), item["idempotency_key"]),
                    )
                for item in confirmation_rows:
                    conn.execute(
                        "UPDATE confirmations SET payload_json = ? WHERE confirmation_id = ?",
                        (self._encode_confirmation(item["confirmation_id"], item["payload"]), item["confirmation_id"]),
                    )
                self._set_metadata(conn, "rekeyed_at", rekeyed_at)
                self._set_metadata(conn, "encryption_provider", self._cipher.status().provider)
        except Exception:
            self._cipher.provider.store_key(old_key)
            raise
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "encryption": self._encryption_payload(),
            "rekeyed_documents": len(documents),
            "rekeyed_events": len(audit_events),
        }

    def _replace_root_with(self, source_root: Path) -> None:
        self.root.parent.mkdir(parents=True, exist_ok=True)
        backup_root = self.root.parent / f".{self.root.name}.restore-backup-{_digest({'root': str(self.root), 'at': _now_iso()})[:12]}"
        had_existing = self.root.exists()
        if had_existing:
            self.root.rename(backup_root)
        try:
            source_root.rename(self.root)
        except Exception:
            if had_existing and backup_root.exists() and not self.root.exists():
                backup_root.rename(self.root)
            raise
        if had_existing and backup_root.exists():
            _remove_path_if_exists(backup_root)
