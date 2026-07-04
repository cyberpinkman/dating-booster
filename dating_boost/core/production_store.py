from __future__ import annotations

from pathlib import Path

from dating_boost.core.encryption import PayloadCipher
from dating_boost.core.production_store_backup import ProductionStoreBackupMixin
from dating_boost.core.production_store_common import *
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
