from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from dating_boost.core.gui_runtime_lock import (
    GuiRuntimeLock,
    RuntimeLockConflict,
    RuntimeSafetyPaused,
    current_process_identity,
)


class FakeProcessPort:
    def __init__(self, alive=True):
        self.alive = alive

    def identity_is_alive(self, identity):
        return self.alive


def test_runtime_lock_uses_fixed_scope_and_strict_permissions(tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path)
    handle = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        assert lock.scope == {"app_id": "tashuo", "runtime": "mac-ios-app"}
        assert lock.scope_dir == tmp_path / "tashuo-mac-ios-app"
        assert lock.scope_dir.stat().st_mode & 0o777 == 0o700
        assert lock.lock_path.stat().st_mode & 0o777 == 0o600
        assert os.get_inheritable(handle.file_descriptor) is False
        assert handle.fencing_token == 1
        assert handle.lease_version == 1
    finally:
        handle.release()


def test_competing_runtime_lock_is_blocked_across_instances(tmp_path):
    first = GuiRuntimeLock(state_root=tmp_path).acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        with pytest.raises(RuntimeLockConflict, match="runtime_os_lock_held"):
            GuiRuntimeLock(state_root=tmp_path).acquire(owner_id="owner_2", owner_nonce="nonce_2")
    finally:
        first.release()


def test_fencing_token_never_reuses_after_release(tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path)
    first = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    first_token = first.fencing_token
    first.release()
    second = lock.acquire(owner_id="owner_2", owner_nonce="nonce_2")
    try:
        assert second.fencing_token > first_token
    finally:
        second.release()


def test_renew_is_compare_and_swap_on_version_and_fencing(tmp_path):
    handle = GuiRuntimeLock(state_root=tmp_path).acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        renewed = handle.renew(expected_lease_version=1, expected_fencing_token=handle.fencing_token)
        assert renewed["lease_version"] == 2
        assert handle.lease_version == 2
        with pytest.raises(RuntimeLockConflict, match="runtime_lease_version_conflict"):
            handle.renew(expected_lease_version=1, expected_fencing_token=handle.fencing_token)
        with pytest.raises(RuntimeLockConflict, match="runtime_fencing_mismatch"):
            handle.renew(expected_lease_version=2, expected_fencing_token=handle.fencing_token + 1)
    finally:
        handle.release()


def test_delegated_capability_validates_owner_tokens_parent_and_heartbeat(tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path)
    handle = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        capability = handle.delegated_capability()
        result = lock.validate_delegated_capability(capability)
        assert result["status"] == "ok"
        stale = {**capability, "runtime_fencing_token": capability["runtime_fencing_token"] + 1}
        assert lock.validate_delegated_capability(stale)["reason"] == "runtime_fencing_mismatch"
        wrong_nonce = {**capability, "owner_nonce": "other"}
        assert lock.validate_delegated_capability(wrong_nonce)["reason"] == "runtime_owner_mismatch"
    finally:
        handle.release()


def test_dead_parent_or_stale_heartbeat_invalidates_child_capability(tmp_path):
    dead_lock = GuiRuntimeLock(state_root=tmp_path / "dead", process_port=FakeProcessPort(alive=False))
    handle = dead_lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    try:
        assert dead_lock.validate_delegated_capability(handle.delegated_capability())["reason"] == "runtime_parent_dead"
    finally:
        handle.release()

    clock = {"monotonic_ns": 1_000_000_000}
    stale_lock = GuiRuntimeLock(
        state_root=tmp_path / "stale",
        monotonic_ns=lambda: clock["monotonic_ns"],
    )
    stale_handle = stale_lock.acquire(owner_id="owner_2", owner_nonce="nonce_2")
    try:
        clock["monotonic_ns"] += 91 * 1_000_000_000
        assert stale_lock.validate_delegated_capability(stale_handle.delegated_capability())[
            "reason"
        ] == "runtime_heartbeat_stale"
    finally:
        stale_handle.release()


def test_runtime_safety_pause_blocks_every_owner_until_exact_pause_id_resumed(tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path)
    paused = lock.pause(reason="composer_state_unknown")
    assert paused["status"] == "paused"
    assert lock.status()["safety_pause"]["pause_id"] == paused["pause_id"]
    with pytest.raises(RuntimeSafetyPaused, match="runtime_safety_paused"):
        GuiRuntimeLock(state_root=tmp_path).acquire(owner_id="owner_1", owner_nonce="nonce_1")
    with pytest.raises(RuntimeSafetyPaused, match="runtime_pause_id_mismatch"):
        lock.resume(pause_id="wrong")

    resumed = lock.resume(pause_id=paused["pause_id"])
    assert resumed["status"] == "active"
    handle = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    handle.release()


def test_expired_lease_does_not_allow_takeover_while_recorded_parent_is_alive(tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path, process_port=FakeProcessPort(alive=True))
    handle = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    handle._close_os_lock_without_releasing_lease()

    with pytest.raises(RuntimeLockConflict, match="runtime_previous_parent_alive"):
        lock.acquire(owner_id="owner_2", owner_nonce="nonce_2", takeover=True)


def test_dead_owner_takeover_immediately_advances_fencing(tmp_path):
    live_port = FakeProcessPort(alive=True)
    lock = GuiRuntimeLock(state_root=tmp_path, process_port=live_port)
    old = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    old_token = old.fencing_token
    old._close_os_lock_without_releasing_lease()
    live_port.alive = False

    replacement = lock.acquire(owner_id="owner_2", owner_nonce="nonce_2", takeover=True)
    try:
        assert replacement.fencing_token > old_token
        assert lock.validate_delegated_capability(old.delegated_capability())["reason"] in {
            "runtime_fencing_mismatch",
            "runtime_owner_mismatch",
        }
    finally:
        replacement.release()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS flock/exec inheritance contract")
def test_lock_fd_is_not_inherited_by_exec_child(tmp_path):
    lock = GuiRuntimeLock(state_root=tmp_path)
    handle = lock.acquire(owner_id="owner_1", owner_nonce="nonce_1")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"], close_fds=False)
    try:
        handle.release()
        replacement = lock.acquire(owner_id="owner_2", owner_nonce="nonce_2")
        replacement.release()
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_current_process_identity_is_stable_for_same_process():
    first = current_process_identity()
    time.sleep(0.001)
    second = current_process_identity()
    assert first == second
    assert first["pid"] == os.getpid()
    assert first["process_start_time"]
    assert first["executable_digest"]
