from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from tests.test_managed_run import _config, _runtime


pytestmark = pytest.mark.managed_critical


def test_start_leaves_checkpoint_owned_by_running_tick_untouched(monkeypatch):
    running, store, _, _, action, _ = _runtime()
    competing, *_ = _runtime(store=store)
    running.start(_config(), run_id="current")
    verifying = Event()
    release = Event()
    observe_post_send = action.observe_post_send

    def wait_for_other_start(candidate, receipt):
        verifying.set()
        assert release.wait(timeout=5)
        return observe_post_send(candidate, receipt)

    monkeypatch.setattr(action, "observe_post_send", wait_for_other_start)
    with ThreadPoolExecutor(max_workers=1) as pool:
        tick = pool.submit(running.tick)
        try:
            assert verifying.wait(timeout=5)
            before = store.load("current")
            assert [attempt["status"] for attempt in before.send_attempts.values()] == ["click_committed"]
            result = competing.start(_config(), run_id="replacement")
            assert store.load("current") == before
            assert result["reason"] == "managed_run_busy"
        finally:
            release.set()
        assert tick.result(timeout=5)["status"] == "confirmed"

    current = store.load("current")
    assert current.status == "active"
    assert current.confirmed_send_count == action.click_count == 1
    assert store.load("replacement") is None


@pytest.mark.parametrize("run_id", ["current", "__managed_run_start__"])
def test_start_recovers_abandoned_checkpoint_after_tick_releases_lease(monkeypatch, run_id):
    running, store, _, _, action, _ = _runtime()
    running.start(_config(), run_id=run_id)

    class SimulatedCrash(BaseException):
        pass

    def crash_before_verification(candidate, receipt):
        raise SimulatedCrash

    monkeypatch.setattr(action, "observe_post_send", crash_before_verification)
    with pytest.raises(SimulatedCrash):
        running.tick()

    restarted, *_ = _runtime(store=store)
    assert restarted.start(_config(), run_id="replacement")["status"] == "blocked"
    current = store.load(run_id)
    assert current.status == "paused"
    assert [attempt["status"] for attempt in current.send_attempts.values()] == ["unknown_after_click"]
    assert store.load("replacement") is None
    assert action.click_count == 1
