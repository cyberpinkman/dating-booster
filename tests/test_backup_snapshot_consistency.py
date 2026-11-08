import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from dating_boost.core.encryption import DataKeyProvider, PayloadCipher
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import JsonStorage


PASSPHRASE = "synthetic-backup-passphrase"


@pytest.fixture(autouse=True)
def local_keys(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.delenv("DATING_BOOST_TEST_KEY", raising=False)


def _store(root, value="original"):
    JsonStorage(root).write_json(Path("sample.json"), {"schema_version": 1, "value": value})
    return ProductionDataStore(root)


def _replacement(tmp_path):
    archive = tmp_path / "replacement.zip"
    assert _store(tmp_path / "replacement", "replacement").backup(
        archive, recovery_passphrase=PASSPHRASE
    )["status"] == "ok"
    return archive


def _mutate(source, mutation, replacement):
    fresh = ProductionDataStore(source.root)
    if mutation == "rekey":
        return fresh.rekey()
    return fresh.restore(replacement, confirm="restore", recovery_passphrase=PASSPHRASE)


def _restore_archive(tmp_path, archive):
    restored = ProductionDataStore(tmp_path / "restored")
    result = restored.restore(archive, confirm="restore", recovery_passphrase=PASSPHRASE)
    assert result["status"] == "ok", result
    return restored


@pytest.mark.parametrize("mutation", ["rekey", "restore"])
@pytest.mark.parametrize("inside_root", [False, True])
def test_archive_packs_immutable_snapshot_after_releasing_source_lock(tmp_path, monkeypatch, mutation, inside_root):
    source = _store(tmp_path / "source")
    replacement = _replacement(tmp_path)
    archive = (source.root if inside_root else tmp_path) / "backup.zip"
    entered, release = threading.Event(), threading.Event()
    original_write = zipfile.ZipFile.write

    def pause_pack(self, filename, *args, **kwargs):
        entered.set()
        assert release.wait(5), "backup packing was not released"
        return original_write(self, filename, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", pause_pack)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(source.backup, archive, recovery_passphrase=PASSPHRASE)
        assert entered.wait(5)
        try:
            # Compression permits key rotation. Root replacement is only excluded
            # when it would unlink the archive that is still being written.
            changed = pool.submit(_mutate, source, mutation, replacement).result(timeout=2)
            if inside_root and mutation == "restore":
                assert changed["status"] == "blocked" and changed["reason"] == "data_store_busy", changed
            else:
                assert changed["status"] == "ok", changed
        finally:
            release.set()
        assert pending.result(timeout=5)["status"] == "ok"
    assert _restore_archive(tmp_path, archive).get_document("sample.json")["value"] == "original"


@pytest.mark.parametrize("mutation", ["rekey", "restore"])
def test_snapshot_and_recovery_key_capture_excludes_maintenance(tmp_path, monkeypatch, mutation):
    source = _store(tmp_path / "source")
    replacement = _replacement(tmp_path)
    archive = tmp_path / "backup.zip"
    entered, release, mutation_started = threading.Event(), threading.Event(), threading.Event()
    original_encrypt = PayloadCipher.encrypt_recovery_key

    def pause_key_capture(self, passphrase):
        envelope = original_encrypt(self, passphrase)
        if self.root == source.root:
            entered.set()
            assert release.wait(5), "backup key capture was not released"
        return envelope

    def mutate():
        mutation_started.set()
        return _mutate(source, mutation, replacement)

    monkeypatch.setattr(PayloadCipher, "encrypt_recovery_key", pause_key_capture)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(source.backup, archive, recovery_passphrase=PASSPHRASE)
        assert entered.wait(5)
        mutation_pending = pool.submit(mutate)
        assert mutation_started.wait(5)
        try:
            if mutation == "rekey":
                with pytest.raises(TimeoutError):
                    mutation_pending.result(timeout=0.1)
            else:
                busy = mutation_pending.result(timeout=2)
                assert busy["status"] == "blocked" and busy["reason"] == "data_store_busy", busy
        finally:
            release.set()
        assert pending.result(timeout=5)["status"] == "ok"
        if mutation == "rekey":
            assert mutation_pending.result(timeout=5)["status"] == "ok"
        else:
            assert _mutate(source, mutation, replacement)["status"] == "ok"
    assert _restore_archive(tmp_path, archive).get_document("sample.json")["value"] == "original"


def test_backup_rebinds_cached_keychain_provider_after_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "keychain")
    keys = {}
    monkeypatch.setattr(DataKeyProvider, "_load_keychain_key", lambda self: keys.get(self.account))
    monkeypatch.setattr(DataKeyProvider, "_store_keychain_key", lambda self, key: keys.__setitem__(self.account, key))
    monkeypatch.setattr(DataKeyProvider, "_delete_keychain_key", lambda self: keys.pop(self.account, None))
    source = _store(tmp_path / "source")
    assert source.get_document("sample.json")["value"] == "original"  # Cache the previous key.
    assert ProductionDataStore(source.root).rekey()["status"] == "ok"
    archive = tmp_path / "backup.zip"
    assert source.backup(archive, recovery_passphrase=PASSPHRASE)["status"] == "ok"
    assert _restore_archive(tmp_path, archive).get_document("sample.json")["value"] == "original"


def test_backup_includes_committed_wal_while_old_reader_prevents_checkpoint(tmp_path, monkeypatch):
    source = _store(tmp_path / "source")
    archive = tmp_path / "backup.zip"
    original_connect = source._connect

    @contextmanager
    def impatient_connect():
        with original_connect() as conn:
            # Keep the old raw-copy implementation's failed checkpoint bounded.
            conn.execute("PRAGMA busy_timeout = 1")
            yield conn

    monkeypatch.setattr(source, "_connect", impatient_connect)
    with closing(sqlite3.connect(source.db_path)) as old_reader:
        old_reader.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        old_reader.execute("BEGIN")
        assert old_reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        source.upsert_document("latest.json", {"schema_version": 1, "value": "committed-in-wal"})
        assert Path(str(source.db_path) + "-wal").stat().st_size > 0
        assert old_reader.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert source.backup(archive, recovery_passphrase=PASSPHRASE)["status"] == "ok"
    assert _restore_archive(tmp_path, archive).get_document("latest.json") == {
        "schema_version": 1, "value": "committed-in-wal"
    }
