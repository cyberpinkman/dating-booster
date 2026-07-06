from __future__ import annotations

import json
import sqlite3
from pathlib import Path
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

__all__ = ["ProductionStoreDeleteMixin"]

class ProductionStoreDeleteMixin:
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
                deleted_documents = self._delete_match_documents(conn, match_id)
                deleted_events = self._delete_match_audit_events(conn, match_id)
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

    def _delete_match_documents(self, conn: sqlite3.Connection, match_id: str) -> int:
        deleted = 0
        for row in conn.execute("SELECT path, payload_json FROM documents").fetchall():
            path = str(row["path"])
            if _is_match_local_path(path, match_id):
                deleted += conn.execute("DELETE FROM documents WHERE path = ?", (path,)).rowcount
                continue
            payload = self._decode_document(path, row["payload_json"])
            cleaned, remove_node, changed = _remove_match_reference(payload, match_id)
            if remove_node:
                deleted += conn.execute("DELETE FROM documents WHERE path = ?", (path,)).rowcount
            elif changed:
                deleted += conn.execute(
                    """
                    UPDATE documents
                    SET payload_json = ?, updated_at = ?
                    WHERE path = ?
                    """,
                    (
                        self._encode_document(path, _redact_if_blocked(cleaned)),
                        _now_iso(),
                        path,
                    ),
                ).rowcount
        return deleted

    def _delete_match_audit_events(self, conn: sqlite3.Connection, match_id: str) -> int:
        deleted = 0
        for row in conn.execute("SELECT stream, event_id, target_match_id, payload_json FROM audit_events").fetchall():
            stream = str(row["stream"])
            event_id = str(row["event_id"])
            if row["target_match_id"] == match_id or _is_match_local_path(stream, match_id):
                deleted += conn.execute(
                    "DELETE FROM audit_events WHERE stream = ? AND event_id = ?",
                    (stream, event_id),
                ).rowcount
                continue
            payload = self._decode_audit_event(stream, event_id, row["payload_json"])
            cleaned, remove_node, changed = _remove_match_reference(payload, match_id)
            if remove_node:
                deleted += conn.execute(
                    "DELETE FROM audit_events WHERE stream = ? AND event_id = ?",
                    (stream, event_id),
                ).rowcount
            elif changed:
                deleted += conn.execute(
                    """
                    UPDATE audit_events
                    SET payload_json = ?
                    WHERE stream = ? AND event_id = ?
                    """,
                    (
                        self._encode_audit_event(stream, event_id, _redact_if_blocked(cleaned)),
                        stream,
                        event_id,
                    ),
                ).rowcount
        return deleted

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
                    cleaned, remove_node, item_changed = _remove_match_reference(item, match_id)
                    if remove_node:
                        changed = True
                        removed_jsonl_events += 1
                        continue
                    if item_changed:
                        changed = True
                        kept_lines.append(json.dumps(cleaned, ensure_ascii=False, sort_keys=True))
                    else:
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
