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

__all__ = ["ProductionStoreConfirmationMixin"]

class ProductionStoreConfirmationMixin:
    def load_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT response_json FROM idempotency WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return self._decode_idempotency(idempotency_key, row["response_json"])

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
                    self._encode_idempotency(idempotency_key, response),
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
                    self._encode_confirmation(confirmation_id, payload_json),
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
