from __future__ import annotations

from datetime import timedelta
from typing import Any

from dating_boost.core.production_store_common import *

__all__ = ["ProductionStoreLocksMixin"]

class ProductionStoreLocksMixin:
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
            if lock.get("run_id") != run_id:
                lock["schema_version"] = AUTOMATION_LOCK_SCHEMA_VERSION
                lock["lock_name"] = lock_name
                lock["status"] = "mismatch"
                lock["released_at"] = None
                return lock
        lock["schema_version"] = AUTOMATION_LOCK_SCHEMA_VERSION
        lock["lock_name"] = lock_name
        lock["status"] = "released"
        lock["released_at"] = now_text
        return lock

    def get_lock(self, lock_name: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM locks WHERE lock_name = ?", (lock_name,)).fetchone()
        if row is None:
            return None
        lock = dict(row)
        lock["schema_version"] = AUTOMATION_LOCK_SCHEMA_VERSION
        lock["lock_name"] = lock_name
        return lock

    def force_release_lock(self, lock_name: str, *, now: str | None = None) -> dict[str, Any]:
        self.ensure_schema()
        now_text = now or _now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM locks WHERE lock_name = ?", (lock_name,)).fetchone()
            if row is None:
                return {
                    "schema_version": AUTOMATION_LOCK_SCHEMA_VERSION,
                    "lock_name": lock_name,
                    "status": "missing",
                    "released_at": now_text,
                }
            lock = dict(row)
            conn.execute(
                "UPDATE locks SET status = 'released', expires_at = ? WHERE lock_name = ?",
                (now_text, lock_name),
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
