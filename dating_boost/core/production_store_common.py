from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.encryption import (
    BACKUP_RECOVERY_KEY_SCHEMA_VERSION as ENCRYPTION_BACKUP_RECOVERY_KEY_SCHEMA_VERSION,
)

DATA_STORE_SCHEMA_VERSION = 2
MIGRATION_SCHEMA_VERSION = 1
AUTOMATION_LOCK_SCHEMA_VERSION = 1
CONFIRMATION_SCHEMA_VERSION = 1
ENCRYPTED_PAYLOAD_SCHEMA_VERSION = 1
KEYCHAIN_BINDING_SCHEMA_VERSION = 1
DIAGNOSTIC_BUNDLE_SCHEMA_VERSION = 1
RELEASE_MANIFEST_SCHEMA_VERSION = 1
BACKUP_RECOVERY_KEY_SCHEMA_VERSION = ENCRYPTION_BACKUP_RECOVERY_KEY_SCHEMA_VERSION
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

__all__ = [
    "AUTOMATION_LOCK_SCHEMA_VERSION",
    "BACKUP_RECOVERY_KEY_SCHEMA_VERSION",
    "BLOCKED_DRAFT_TEXT_KEYS",
    "CONFIRMATION_SCHEMA_VERSION",
    "DATA_STORE_SCHEMA_VERSION",
    "DIAGNOSTIC_BUNDLE_SCHEMA_VERSION",
    "ENCRYPTED_PAYLOAD_SCHEMA_VERSION",
    "KEYCHAIN_BINDING_SCHEMA_VERSION",
    "KNOWN_SCHEMA_VERSIONS",
    "LockAcquireResult",
    "MIGRATION_SCHEMA_VERSION",
    "MigrationBlocked",
    "PRODUCTION_DB_NAME",
    "RELEASE_MANIFEST_SCHEMA_VERSION",
    "_confirmation_blocked",
    "_digest",
    "_is_blocked_payload",
    "_is_match_local_path",
    "_now_iso",
    "_parse_iso",
    "_redact_if_blocked",
    "_redact_keys",
    "_remove_empty_dirs",
    "_remove_match_reference",
    "_remove_path_if_exists",
    "_schema_versions",
    "_sqlite_integrity_ok",
    "_validate_match_local_prefix",
    "delete_confirm_token",
    "payload_digest",
]


@dataclass(frozen=True)
class LockAcquireResult:
    acquired: bool
    lock: dict[str, Any]


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


def _validate_match_local_prefix(prefix: str) -> None:
    if prefix in {"", ".", "..", "/"}:
        raise ValueError(f"invalid match-local prefix: {prefix!r}")
    if prefix.startswith("/") or "\\" in prefix or not prefix.endswith("/"):
        raise ValueError(f"invalid match-local prefix: {prefix!r}")
    parts = prefix.split("/")
    if len(parts) != 3 or parts[0] != "matches" or parts[2] != "":
        raise ValueError(f"invalid match-local prefix: {prefix!r}")
    match_id = parts[1]
    if match_id in {"", ".", ".."} or any(part in {".", ".."} for part in parts if part):
        raise ValueError(f"invalid match-local prefix: {prefix!r}")


def _is_match_local_path(path: str, match_id: str) -> bool:
    parts = path.split("/")
    for index, part in enumerate(parts):
        if part == "matches" and len(parts) > index + 1 and parts[index + 1] == match_id:
            return True
    return False


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
        "encrypted_payload": ENCRYPTED_PAYLOAD_SCHEMA_VERSION,
        "keychain_binding": KEYCHAIN_BINDING_SCHEMA_VERSION,
        "backup_recovery_key": BACKUP_RECOVERY_KEY_SCHEMA_VERSION,
        "diagnostic_bundle": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
        "release_manifest": RELEASE_MANIFEST_SCHEMA_VERSION,
    }


def _sqlite_integrity_ok(db_path: Path) -> bool:
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


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


def _remove_match_reference(value: Any, match_id: str) -> tuple[Any, bool, bool]:
    if isinstance(value, str):
        return (None, True, True) if value == match_id else (value, False, False)
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
