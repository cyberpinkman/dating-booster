from __future__ import annotations

from datetime import datetime, timezone
import multiprocessing
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from dating_boost.core.managed_run import (
    InMemoryManagedRunStore,
    JsonManagedRunStore,
    ManagedAuthorization,
    ManagedRun,
    ManagedRunConfig,
    MessageListSnapshot,
)
from dating_boost.core.storage_lifecycle import storage_lifecycle_lease


pytestmark = pytest.mark.managed_critical


class IdleObservation:
    def __init__(self):
        self.scans = 0

    def scan_message_list(self, **kwargs):
        self.scans += 1
        return MessageListSnapshot((), datetime.now(timezone.utc).isoformat())


def _config():
    return ManagedRunConfig(
        app_id="tashuo", runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="synthetic_wait_owner", app_id="tashuo", runtime="mac-ios-app",
            allow_all_targets=True, live_send=True,
        ),
    )


def _runtime(store, sleeper):
    observation = IdleObservation()
    runtime = ManagedRun(
        store, observation,
        SimpleNamespace(prioritize=lambda candidates, **kwargs: None), object(),
        sleeper=sleeper,
    )
    return runtime, observation


def _unexpected_sleep(seconds):
    # Bound the regression failure: an incorrectly accepted second runner must
    # return immediately instead of leaving the test stuck in its own wait loop.
    raise RuntimeError("second wait runner reached polling sleep")


def _child_wait(root, entered, release, outcome):
    def sleep(seconds):
        entered.set()
        assert release.poll(10), "parent did not release the synthetic sleeper"
        release.recv()

    runtime, _ = _runtime(JsonManagedRunStore(Path(root)), sleep)
    outcome.put(runtime.run("owned_run", wait=True, poll_interval_seconds=30))


@pytest.mark.parametrize("store_kind", ["memory", "json"])
@pytest.mark.parametrize("transition", ["pause", "pause_resume"])
def test_wait_ownership_covers_idle_sleep_without_blocking_pause(tmp_path, monkeypatch, store_kind, transition):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    first_store = InMemoryManagedRunStore() if store_kind == "memory" else JsonManagedRunStore(tmp_path)
    second_store = first_store if store_kind == "memory" else JsonManagedRunStore(tmp_path)
    entered, release = threading.Event(), threading.Event()
    results = []
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) > 1:
            raise RuntimeError("old runner adopted the resumed lifecycle")
        entered.set()
        assert release.wait(10), "test did not release the synthetic sleeper"

    first, first_observation = _runtime(first_store, sleep)
    second, competing_observation = _runtime(second_store, _unexpected_sleep)
    assert first.start(_config(), run_id="owned_run")["status"] == "active"
    worker = threading.Thread(target=lambda: results.append(first.run(wait=True)), daemon=True)
    worker.start()
    control_done = threading.Event()
    controller = None
    try:
        assert entered.wait(3)
        before = first_store.load("owned_run").to_dict()
        competing = second.run(wait=True)
        assert competing.get("reason") == "managed_run_busy", competing
        assert competing["status"] == "blocked"
        assert competing_observation.scans == 0
        assert first_store.load("owned_run").to_dict() == before

        def pause():
            second.pause(reason="synthetic_user_pause")
            if transition == "pause_resume":
                second.resume()
            control_done.set()

        controller = threading.Thread(target=pause, daemon=True)
        controller.start()
        assert control_done.wait(1), "runner ownership blocked lifecycle control"
        if transition == "pause_resume":
            assert second.run(wait=True).get("reason") == "managed_run_busy"
    finally:
        release.set()
        worker.join(3)
        if controller is not None:
            controller.join(3)
    assert not worker.is_alive()
    expected_status = "paused" if transition == "pause" else "blocked"
    assert results[0]["status"] == expected_status
    assert first_observation.scans == 1, "old runner scanned after pause/resume"
    if transition == "pause_resume":
        assert results[0]["reason"] == "managed_run_lifecycle_changed"
        assert second.status()["status"] == "active", "old runner changed the resumed lifecycle"

    # The same durable run can acquire ownership again after its owner exits.
    second.resume()
    second._sleep = lambda seconds: second.stop(reason="synthetic_finished")
    restarted = second.run(wait=True)
    assert restarted["status"] == "stopped"
    assert competing_observation.scans == 1


def test_wait_owner_revision_is_checked_inside_tick_before_observation(monkeypatch):
    store = InMemoryManagedRunStore()
    runtime, observation = _runtime(store, _unexpected_sleep)
    controller, _ = _runtime(store, _unexpected_sleep)
    assert runtime.start(_config(), run_id="owned_run")["status"] == "active"
    tick = runtime.tick

    def resumed_before_tick(*args, **kwargs):
        controller.pause()
        controller.resume()
        return tick(*args, **kwargs)

    monkeypatch.setattr(runtime, "tick", resumed_before_tick)
    result = runtime.run(wait=True)

    assert result.get("reason") == "managed_run_lifecycle_changed"
    assert observation.scans == 0
    assert controller.status()["status"] == "active"


@pytest.mark.parametrize("failure", [RuntimeError("synthetic sleeper failure"), KeyboardInterrupt()])
def test_old_wait_owner_sleep_failure_preserves_resumed_lifecycle(failure):
    store = InMemoryManagedRunStore()
    controller, _ = _runtime(store, _unexpected_sleep)

    def sleep(seconds):
        controller.pause()
        controller.resume()
        raise failure

    runtime, observation = _runtime(store, sleep)
    runtime.start(_config(), run_id="owned_run")
    result = runtime.run(wait=True)

    assert result.get("reason") == "managed_run_lifecycle_changed"
    assert observation.scans == 1
    latest = controller.status()
    assert latest["status"] == "active"
    assert latest["run"]["lifecycle_revision"] == 2


def test_wait_without_current_run_cannot_follow_a_concurrent_start(monkeypatch):
    store = InMemoryManagedRunStore()
    runtime, observation = _runtime(store, _unexpected_sleep)
    controller, _ = _runtime(store, _unexpected_sleep)
    current_run_id = store.current_run_id
    observed_empty = False

    def started_after_empty_read():
        nonlocal observed_empty
        if not observed_empty:
            observed_empty = True
            controller.start(_config(), run_id="concurrently_started")
            return None
        return current_run_id()

    monkeypatch.setattr(store, "current_run_id", started_after_empty_read)
    result = runtime.run(wait=True)

    assert result.get("reason") == "managed_run_not_started"
    assert observation.scans == 0
    assert controller.status()["status"] == "active"


@pytest.mark.parametrize("shutdown", ["pause", "terminate"])
def test_wait_ownership_is_shared_between_processes_and_released_on_exit(tmp_path, monkeypatch, shutdown):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    controller, observation = _runtime(JsonManagedRunStore(tmp_path), _unexpected_sleep)
    assert controller.start(_config(), run_id="owned_run")["status"] == "active"
    context = multiprocessing.get_context("spawn")
    entered, outcome = context.Event(), context.Queue()
    release, child_release = context.Pipe()
    child = context.Process(target=_child_wait, args=(str(tmp_path), entered, child_release, outcome))
    child.start()
    child_release.close()
    try:
        assert entered.wait(5), "child runner did not reach idle polling"
        competing = controller.run(wait=True)
        assert competing.get("reason") == "managed_run_busy", competing
        assert observation.scans == 0
        assert controller.status()["status"] == "active"
        with storage_lifecycle_lease(tmp_path, exclusive=True, blocking=False) as maintenance_allowed:
            assert not maintenance_allowed, "idle wait runner allowed its data directory to be replaced"
        if shutdown == "pause":
            assert controller.pause()["status"] == "paused"
            release.send("continue")
            assert outcome.get(timeout=5)["status"] == "paused"
        else:
            child.terminate()
        child.join(5)
        assert not child.is_alive()
        with storage_lifecycle_lease(tmp_path, exclusive=True, blocking=False) as maintenance_allowed:
            assert maintenance_allowed

        controller.resume()
        controller._sleep = lambda seconds: controller.stop(reason="synthetic_finished")
        assert controller.run(wait=True)["status"] == "stopped"
        assert observation.scans == 1
    finally:
        if child.is_alive():
            child.terminate()
        child.join(5)
        release.close()
        outcome.close()
