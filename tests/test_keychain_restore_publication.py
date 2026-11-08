from pathlib import Path

import pytest

from dating_boost.core.encryption import DataKeyProvider, EncryptionError, LOCAL_KEY_NAME
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import JsonStorage


@pytest.fixture
def keychain(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "keychain")
    monkeypatch.delenv("DATING_BOOST_TEST_KEY", raising=False)
    keys = {}
    monkeypatch.setattr(DataKeyProvider, "_load_keychain_key", lambda self: keys.get(self.account))
    monkeypatch.setattr(DataKeyProvider, "_store_keychain_key", lambda self, key: keys.__setitem__(self.account, key))
    # The implementation must remove a newly bound key when publication rolls back.
    monkeypatch.setattr(DataKeyProvider, "_delete_keychain_key", lambda self: keys.pop(self.account, None), raising=False)
    return keys


def _prepare(tmp_path, existing):
    source, target, archive = tmp_path / "source", tmp_path / "target", tmp_path / "backup.zip"
    JsonStorage(source).write_json(Path("sample.json"), {"schema_version": 1, "value": "restored"})
    assert ProductionDataStore(source).backup(archive, recovery_passphrase="synthetic-passphrase")["status"] == "ok"
    store = ProductionDataStore(target)
    if existing:
        JsonStorage(target).write_json(Path("sample.json"), {"schema_version": 1, "value": "original"})
        assert store.get_document("sample.json")["value"] == "original"  # Prime the old provider cache.
    return target, archive, store


@pytest.mark.parametrize("existing", [False, True])
def test_keychain_restore_binds_final_account_without_temporary_items(tmp_path, keychain, existing):
    target, archive, store = _prepare(tmp_path, existing)
    before_accounts = set(keychain)
    target_account = DataKeyProvider(target).account
    result = store.restore(archive, confirm="restore", recovery_passphrase="synthetic-passphrase")
    assert result["status"] == "ok"
    assert ProductionDataStore(target).get_document("sample.json")["value"] == "restored"
    assert store.get_document("sample.json")["value"] == "restored"
    assert set(keychain) == before_accounts | {target_account}
    assert not (target / LOCAL_KEY_NAME).exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["final_verification", "key_publication"])
def test_keychain_publication_failure_restores_directory_and_account(tmp_path, monkeypatch, keychain, existing, failure):
    target, archive, store = _prepare(tmp_path, existing)
    before_keys = dict(keychain)
    target_account = DataKeyProvider(target).account
    original_doctor = ProductionDataStore.doctor
    failed = False

    def fail_final_doctor(self):
        if self.root == target:
            raise EncryptionError("synthetic final verification failure")
        return original_doctor(self)

    def fail_after_key_write(self, key):
        nonlocal failed
        keychain[self.account] = key
        if self.account == target_account and not failed:
            failed = True
            raise EncryptionError("synthetic key publication failure")

    if failure == "final_verification":
        monkeypatch.setattr(ProductionDataStore, "doctor", fail_final_doctor)
    else:
        monkeypatch.setattr(DataKeyProvider, "_store_keychain_key", fail_after_key_write)
    result = store.restore(archive, confirm="restore", recovery_passphrase="synthetic-passphrase")
    assert result["status"] == "blocked"
    assert result["reason"] == "restore_publication_failed"
    assert keychain == before_keys
    if existing:
        assert ProductionDataStore(target).get_document("sample.json")["value"] == "original"
        assert store.get_document("sample.json")["value"] == "original"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".target.restore-backup-*"))
