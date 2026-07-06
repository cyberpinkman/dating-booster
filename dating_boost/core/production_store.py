from __future__ import annotations

from pathlib import Path

from dating_boost.core.encryption import PayloadCipher
from dating_boost.core.production_store_backup import ProductionStoreBackupMixin
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
from dating_boost.core.production_store_confirmation import ProductionStoreConfirmationMixin
from dating_boost.core.production_store_delete import ProductionStoreDeleteMixin
from dating_boost.core.production_store_locks import ProductionStoreLocksMixin
from dating_boost.core.production_store_records import ProductionStoreRecordsMixin
from dating_boost.core.production_store_schema import ProductionStoreSchemaMixin


class ProductionDataStore(
    ProductionStoreSchemaMixin,
    ProductionStoreRecordsMixin,
    ProductionStoreBackupMixin,
    ProductionStoreLocksMixin,
    ProductionStoreConfirmationMixin,
    ProductionStoreDeleteMixin,
):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.db_path = self.root / PRODUCTION_DB_NAME
        self._cipher = PayloadCipher(self.root)
