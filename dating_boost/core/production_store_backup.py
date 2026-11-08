from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from dating_boost.core.encryption import DataKeyProvider, EncryptionError, LOCAL_KEY_NAME, PayloadCipher
from dating_boost.core.storage import storage_write_lock
from dating_boost.core.storage_lifecycle import storage_lifecycle_lease
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


class _RestorePublicationError(RuntimeError):
    pass


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
        output = output.resolve()
        # The snapshot lives outside the replaceable root. Only capture holds the
        # root write/lifecycle lease; compression can proceed during maintenance.
        with tempfile.TemporaryDirectory(prefix="dating-boost-backup-") as temp_dir:
            snapshot_path = Path(temp_dir) / PRODUCTION_DB_NAME
            with storage_write_lock(self.root):
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
                # A caller's provider may have cached a key before waiting for a
                # concurrent rekey. Bind anew inside the same epoch as the DB copy.
                cipher = PayloadCipher(self.root, key_provider=self._cipher.provider.provider_name)
                with self._connect() as conn, closing(sqlite3.connect(snapshot_path)) as snapshot:
                    conn.backup(snapshot)
                    metadata = dict(snapshot.execute("SELECT key, value FROM metadata").fetchall())
                manifest = {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "backup_format": "dating_boost_sqlite_zip",
                    "created_at": _now_iso(),
                    "encrypted": True,
                    "db_file": PRODUCTION_DB_NAME,
                    "metadata": metadata,
                    "key_recovery": "passphrase",
                    "recovery_key": cipher.encrypt_recovery_key(recovery_passphrase),
                }
            # An archive placed inside the store must not be unlinked by root
            # replacement while open. This shared lease still permits rekey.
            output_lease = storage_lifecycle_lease(self.root) if output.is_relative_to(self.root) else nullcontext()
            with output_lease:
                output.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
                    archive.write(snapshot_path, PRODUCTION_DB_NAME)
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
        with storage_lifecycle_lease(self.root, exclusive=True, blocking=False) as acquired:
            if not acquired:
                return {"schema_version": DATA_STORE_SCHEMA_VERSION, "status": "blocked", "reason": "data_store_busy"}
            return self._restore_locked(input_path, recovery_passphrase=recovery_passphrase)

    def _restore_locked(self, input_path: Path, *, recovery_passphrase: str | None) -> dict[str, Any]:
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
            # Validation must not create Keychain entries bound to disposable paths.
            temp_store = type(self)(temp_root, key_provider="local")
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
            try:
                self._replace_root_with(temp_root)
            except _RestorePublicationError as exc:
                return {
                    "schema_version": DATA_STORE_SCHEMA_VERSION,
                    "status": "blocked",
                    "reason": "restore_publication_failed",
                    "error_type": str(exc),
                }
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "input": str(input_path),
            "db_path": str(self.db_path),
            "encrypted": bool(manifest.get("encrypted")),
            "key_recovery": manifest.get("key_recovery") or "legacy_local_key",
        }

    def rekey(self) -> dict[str, Any]:
        # Key rotation must exclude repository operations that still hold the old
        # provider/key, across both payload rewrites and the final WAL checkpoint.
        with storage_write_lock(self.root):
            return self._rekey_locked()

    def _rekey_locked(self) -> dict[str, Any]:
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
        with self._connect() as conn:
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is not None and int(checkpoint[0]) != 0:
            raise RuntimeError("rekey_wal_checkpoint_busy")
        return {
            "schema_version": DATA_STORE_SCHEMA_VERSION,
            "status": "ok",
            "encryption": self._encryption_payload(),
            "rekeyed_documents": len(documents),
            "rekeyed_events": len(audit_events),
        }

    def _replace_root_with(self, source_root: Path) -> None:
        self.root.parent.mkdir(parents=True, exist_ok=True)
        restored_key = DataKeyProvider(source_root, provider_name="local").load_existing_key()
        provider_name = self._cipher.provider.provider_name
        destination_provider = DataKeyProvider(self.root, provider_name=provider_name)
        keychain_destination = provider_name == "keychain" and not os.environ.get("DATING_BOOST_TEST_KEY")
        previous_key = destination_provider.load_existing_key() if keychain_destination else None
        backup_root = self.root.parent / f".{self.root.name}.restore-backup-{_digest({'root': str(self.root), 'at': _now_iso()})[:12]}"
        had_existing = self.root.exists()
        if had_existing:
            self.root.rename(backup_root)
        published = False
        key_may_have_changed = False
        try:
            source_root.rename(self.root)
            published = True
            if keychain_destination:
                if restored_key is None:
                    raise EncryptionError("restored data key is unavailable")
                key_may_have_changed = True
                destination_provider.store_key(restored_key)
                (self.root / LOCAL_KEY_NAME).unlink(missing_ok=True)
            # Verify through the final path and a fresh provider, not the temporary
            # validator or an instance that may have cached the destination's old key.
            final_store = type(self)(self.root, key_provider=provider_name)
            with final_store._connect() as conn:
                final_store._set_metadata(conn, "encryption_provider", provider_name)
            if final_store.doctor().get("status") != "ok":
                raise EncryptionError("restored store validation failed")
        except Exception as exc:
            try:
                if published:
                    self.root.rename(source_root)
                if had_existing and backup_root.exists():
                    backup_root.rename(self.root)
                if key_may_have_changed:
                    if previous_key is None:
                        destination_provider.delete_key()
                    else:
                        destination_provider.store_key(previous_key)
            except Exception as rollback_exc:
                raise RuntimeError("restore_rollback_failed") from rollback_exc
            raise _RestorePublicationError(type(exc).__name__) from exc
        self._cipher = final_store._cipher
        if had_existing and backup_root.exists():
            _remove_path_if_exists(backup_root)
