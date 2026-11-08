import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from unittest.mock import patch

import pytest

from dating_boost.core.managed_run import JsonManagedRunStore
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import JsonStorage, storage_write_lock


def _hold_lease(root, kind, pipe):
    store = JsonManagedRunStore(root)
    guard = (store.execution_lease("run_demo") if kind == "execution" else
             store.state_lease("run_demo") if kind == "state" else storage_write_lock(root))
    with guard as acquired:
        assert acquired is not False
        pipe.send("held")
        assert pipe.poll(10)
        pipe.recv()


def _backup(root, archive):
    JsonStorage(root).write_json(Path("sample.json"), {"schema_version": 1, "value": "original"})
    assert ProductionDataStore(root).backup(archive, recovery_passphrase="synthetic-passphrase")["status"] == "ok"


@pytest.mark.parametrize("kind", ["execution", "state", "write"])
@pytest.mark.parametrize("maintenance", ["restore", "delete_all"])
def test_destructive_maintenance_refuses_active_root_users(tmp_path, monkeypatch, kind, maintenance):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    root, archive = tmp_path / "data", tmp_path / "backup.zip"
    _backup(root, archive)
    db_inode = ProductionDataStore(root).db_path.stat().st_ino
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    worker = ctx.Process(target=_hold_lease, args=(root, kind, child))
    worker.start()
    child.close()

    def maintain():
        store = ProductionDataStore(root)
        if maintenance == "restore":
            return store.restore(archive, confirm="restore", recovery_passphrase="synthetic-passphrase")
        return store.delete(scope="all", match_id=None, confirm="delete:all")

    try:
        assert parent.poll(10) and parent.recv() == "held"
        result = maintain()
        assert result["status"] == "blocked"
        assert result["reason"] == "data_store_busy"
        assert ProductionDataStore(root).db_path.stat().st_ino == db_inode
        assert ProductionDataStore(root).get_document("sample.json")["value"] == "original"
    finally:
        parent.send("release")
        worker.join(10)
        if worker.is_alive():
            worker.terminate()
            worker.join(2)
        parent.close()
    assert worker.exitcode == 0
    assert maintain()["status"] == "ok"


def test_restore_publication_blocks_new_executor_start_and_storage_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    root, archive = tmp_path / "data", tmp_path / "backup.zip"
    _backup(root, archive)
    run_store, maintenance = JsonManagedRunStore(root), ProductionDataStore(root)
    entered, release, writer_started = threading.Event(), threading.Event(), threading.Event()
    replace_root = maintenance._replace_root_with

    def pause_publication(source):
        entered.set()
        assert release.wait(10)
        replace_root(source)

    def write_after_publication():
        writer_started.set()
        JsonStorage(root).write_json(Path("after.json"), {"schema_version": 1})

    with ThreadPoolExecutor(max_workers=2) as pool, patch.object(maintenance, "_replace_root_with", pause_publication):
        restoring = pool.submit(maintenance.restore, archive, confirm="restore", recovery_passphrase="synthetic-passphrase")
        assert entered.wait(10)
        try:
            with run_store.execution_lease("__managed_run_start__") as acquired:
                assert not acquired
            writing = pool.submit(write_after_publication)
            assert writer_started.wait(10)
            with pytest.raises(TimeoutError):
                writing.result(timeout=0.2)
        finally:
            release.set()
        assert restoring.result(timeout=10)["status"] == "ok"
        writing.result(timeout=10)
    assert ProductionDataStore(root).get_document("after.json") == {"schema_version": 1}
    with run_store.execution_lease("run_demo") as acquired:
        assert acquired


def test_lifecycle_reentrancy_and_lock_identity_survive_restore(tmp_path, monkeypatch):
    from dating_boost.core.storage_lifecycle import storage_lifecycle_lease, storage_lifecycle_path

    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    root, archive = tmp_path / "data", tmp_path / "backup.zip"
    _backup(root, archive)
    store = JsonManagedRunStore(root)
    with store.execution_lease("run_demo") as acquired:
        assert acquired
        with store.state_lease("run_demo"), storage_write_lock(root), store.state_lease("run_demo"):
            JsonStorage(root).write_json(Path("nested.json"), {"schema_version": 1})
            with storage_lifecycle_lease(root, exclusive=True, blocking=False) as upgraded:
                assert not upgraded
    lease_path = storage_lifecycle_path(root)
    assert not lease_path.is_relative_to(root)
    lease_inode = lease_path.stat().st_ino
    assert ProductionDataStore(root).restore(archive, confirm="restore", recovery_passphrase="synthetic-passphrase")["status"] == "ok"
    assert lease_path.stat().st_ino == lease_inode
    with storage_lifecycle_lease(root, exclusive=True, blocking=False) as exclusive:
        assert exclusive
        with storage_write_lock(root):
            JsonStorage(root).write_json(Path("nested.json"), {"schema_version": 1})
