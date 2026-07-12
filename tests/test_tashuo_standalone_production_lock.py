from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest

from dating_boost.apps.tashuo.standalone_production_artifacts import create_qualification_paths
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.apps.tashuo.standalone_production_lock import (
    ProductionLockConflict,
    ProductionLockSet,
    QualificationLocalLock,
    WorkerIdentityConflict,
    WorkerProcessRegistry,
)
from dating_boost.core.gui_runtime_lock import GuiRuntimeLock, process_identity


class FakeProcessPort:
    def __init__(self, alive=True):
        self.alive = alive

    def identity_is_alive(self, identity):
        return self.alive


@pytest.fixture(autouse=True)
def _local_test_key(monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    monkeypatch.setenv("DATING_BOOST_TEST_KEY", "production-local-lock-test-key")


def _paths(tmp_path, qualification_id="qual_1"):
    source = tmp_path / f"source-{qualification_id}"
    source.mkdir()
    return create_qualification_paths(
        tmp_path / "root",
        source_data_dir=source,
        qualification_id=qualification_id,
    )


def _wait_identity(pid):
    for _ in range(100):
        identity = process_identity(pid)
        if identity is not None:
            return identity
        time.sleep(0.01)
    raise AssertionError("process identity unavailable")


def test_local_lock_is_non_inheritable_and_competing_runner_is_blocked(tmp_path):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    first = QualificationLocalLock(paths, ledger).acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        assert os.get_inheritable(first.file_descriptor) is False
        assert first.local_fencing_token == 1
        with pytest.raises(ProductionLockConflict, match="qualification_os_lock_held"):
            QualificationLocalLock(paths, ledger).acquire(owner_id="owner_2", owner_nonce="nonce_2")
    finally:
        first.release()


def test_local_fencing_and_cas_renew_are_monotonic(tmp_path):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    lock = QualificationLocalLock(paths, ledger)
    first = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    token = first.local_fencing_token
    renewed = first.renew(
        expected_lease_version=first.lease_version,
        expected_fencing_token=first.local_fencing_token,
    )
    assert renewed["lease_version"] == 2
    with pytest.raises(ProductionLockConflict, match="qualification_lease_version_conflict"):
        first.renew(expected_lease_version=1, expected_fencing_token=token)
    first.release()

    second = lock.acquire(owner_id="owner_2", owner_nonce="nonce_2")
    try:
        assert second.local_fencing_token > token
    finally:
        second.release()


def test_local_delegated_capability_rejects_stale_owner_and_heartbeat(tmp_path):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    clock = {"value": 1_000_000_000}
    lock = QualificationLocalLock(paths, ledger, monotonic_ns=lambda: clock["value"])
    handle = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        capability = handle.delegated_capability()
        assert lock.validate_delegated_capability(capability)["status"] == "ok"
        assert lock.validate_delegated_capability({**capability, "owner_nonce": "wrong"})[
            "reason"
        ] == "qualification_owner_mismatch"
        clock["value"] += 91 * 1_000_000_000
        assert lock.validate_delegated_capability(capability)["reason"] == "qualification_heartbeat_stale"
    finally:
        handle.release()


def test_local_takeover_requires_dead_recorded_parent_and_advances_fencing(tmp_path):
    paths = _paths(tmp_path)
    ledger = ProductionQualificationLedger(paths.data_dir)
    process_port = FakeProcessPort(alive=True)
    lock = QualificationLocalLock(paths, ledger, process_port=process_port)
    old = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    token = old.local_fencing_token
    old._close_os_lock_without_releasing_lease()

    with pytest.raises(ProductionLockConflict, match="qualification_previous_parent_alive"):
        lock.acquire(owner_id="owner_2", owner_nonce="nonce_2", takeover=True)
    process_port.alive = False
    replacement = lock.acquire(owner_id="owner_2", owner_nonce="nonce_2", takeover=True)
    try:
        assert replacement.local_fencing_token > token
    finally:
        replacement.release()


def test_dual_lock_set_exposes_and_validates_both_fencing_tokens(tmp_path):
    paths = _paths(tmp_path)
    runtime = GuiRuntimeLock(state_root=tmp_path / "runtime")
    lock_set = ProductionLockSet(paths, runtime_lock=runtime)
    handle = lock_set.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        capability = handle.delegated_capability()
        assert capability["local_fencing_token"] >= 1
        assert capability["runtime_fencing_token"] >= 1
        assert lock_set.validate_delegated_capability(capability)["status"] == "ok"
        stale = {**capability, "local_fencing_token": capability["local_fencing_token"] + 1}
        assert lock_set.validate_delegated_capability(stale)["reason"] == "qualification_fencing_mismatch"
    finally:
        handle.release()


def test_runtime_lock_blocks_other_qualification_root(tmp_path):
    one = _paths(tmp_path, "qual_1")
    two = _paths(tmp_path, "qual_2")
    runtime = GuiRuntimeLock(state_root=tmp_path / "runtime")
    first_set = ProductionLockSet(one, runtime_lock=runtime)
    second_set = ProductionLockSet(two, runtime_lock=GuiRuntimeLock(state_root=tmp_path / "runtime"))
    first = first_set.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        with pytest.raises(Exception, match="runtime_os_lock_held"):
            second_set.acquire(owner_id="owner_2", owner_nonce="nonce_2")
    finally:
        first.release()


def test_runtime_acquire_failure_releases_local_lock(tmp_path):
    one = _paths(tmp_path, "qual_1")
    two = _paths(tmp_path, "qual_2")
    runtime = GuiRuntimeLock(state_root=tmp_path / "runtime")
    external = runtime.acquire(owner_id="external", owner_nonce="external_nonce")
    try:
        with pytest.raises(Exception, match="runtime_os_lock_held"):
            ProductionLockSet(one, runtime_lock=GuiRuntimeLock(state_root=tmp_path / "runtime")).acquire(
                owner_id="owner_1", owner_nonce="nonce_1"
            )
        local = QualificationLocalLock(two, ProductionQualificationLedger(two.data_dir)).acquire(
            owner_id="owner_2", owner_nonce="nonce_2"
        )
        local.release()
        local_one = QualificationLocalLock(one, ProductionQualificationLedger(one.data_dir)).acquire(
            owner_id="owner_3", owner_nonce="nonce_3"
        )
        local_one.release()
    finally:
        external.release()


def test_lock_fd_is_not_inherited_and_parent_death_releases_flock(tmp_path):
    paths = _paths(tmp_path)
    helper = """
import subprocess
import sys
from pathlib import Path
from dating_boost.apps.tashuo.standalone_production_artifacts import QualificationPaths
from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.apps.tashuo.standalone_production_lock import QualificationLocalLock

base = Path(sys.argv[1])
paths = QualificationPaths(
    qualification_id=sys.argv[2],
    qualification_dir=base,
    data_dir=base / 'data',
    work_dir=base / 'work',
    vault_dir=base / 'vault',
    output_dir=base / 'output',
    runner_lock=base / 'runner.lock',
    ownership_digest=sys.argv[3],
)
handle = QualificationLocalLock(paths, ProductionQualificationLedger(paths.data_dir)).acquire(
    owner_id='old_parent', owner_nonce='old_nonce'
)
child = subprocess.Popen(
    [sys.executable, '-c', 'import time; time.sleep(30)'],
    close_fds=False,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(child.pid, flush=True)
"""
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            helper,
            str(paths.qualification_dir),
            paths.qualification_id,
            paths.ownership_digest,
        ],
        cwd=paths.qualification_dir,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert parent.stdout is not None
    orphan_pid = int(parent.stdout.readline().strip())
    _, stderr = parent.communicate(timeout=10)
    assert parent.returncode == 0, stderr
    replacement = QualificationLocalLock(
        paths,
        ProductionQualificationLedger(paths.data_dir),
    ).acquire(owner_id="new_parent", owner_nonce="new_nonce", takeover=True)
    replacement.release()
    try:
        os.kill(orphan_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def test_worker_registry_reconciles_orphan_process_group_without_waitpid(tmp_path):
    paths = _paths(tmp_path)
    launcher = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                "start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL); print(p.pid,flush=True)"
            ),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert launcher.stdout is not None
    worker_pid = int(launcher.stdout.readline().strip())
    _, stderr = launcher.communicate(timeout=10)
    assert launcher.returncode == 0, stderr
    identity = _wait_identity(worker_pid)
    ledger = ProductionQualificationLedger(paths.data_dir)
    registry = WorkerProcessRegistry(ledger)
    registry.register(
        context_id="attempt_orphan_1",
        worker_kind="attempt",
        pid=worker_pid,
        pgid=os.getpgid(worker_pid),
        worker_nonce="nonce_orphan_1",
        identity=identity,
    )
    registry.mark_child_ready(
        context_id="attempt_orphan_1",
        worker_nonce="nonce_orphan_1",
        pid=worker_pid,
    )

    result = registry.reconcile_orphan("attempt_orphan_1", grace_seconds=2)

    assert result["status"] == "terminated"
    assert registry.read("attempt_orphan_1")["status"] == "disappeared"
    assert process_identity(worker_pid) is None


def test_worker_identity_or_pgid_mismatch_never_signals_process_group(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        identity = _wait_identity(process.pid)
        ledger = ProductionQualificationLedger(paths.data_dir)
        registry = WorkerProcessRegistry(ledger)
        registered = registry.register(
            context_id="attempt_identity_1",
            worker_kind="attempt",
            pid=process.pid,
            pgid=os.getpgid(process.pid),
            worker_nonce="nonce_identity_1",
            identity=identity,
        )
        registry.mark_child_ready(
            context_id="attempt_identity_1",
            worker_nonce="nonce_identity_1",
            pid=process.pid,
        )
        current = registry.read("attempt_identity_1")
        ledger.compare_and_swap(
            "standalone_production/workers/attempt_identity_1.json",
            expected_version=current["ledger_version"],
            changes={"process_start_time": "reused-pid-start-time"},
        )
        calls = []
        monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))

        result = registry.signal_verified_group("attempt_identity_1", sig=signal.SIGTERM)

        assert result["status"] == "blocked"
        assert result["reason"] == "worker_identity_mismatch"
        assert calls == []
        with pytest.raises(WorkerIdentityConflict, match="worker_registration_binding_mismatch"):
            WorkerProcessRegistry(ledger).mark_child_ready(
                context_id="attempt_identity_1",
                worker_nonce="different_nonce",
                pid=process.pid,
            )
        assert registered["worker_nonce"] == "nonce_identity_1"
    finally:
        process.terminate()
        process.wait(timeout=10)
