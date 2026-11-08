"""Model latency must not own the lifecycle lock or extend send authorization."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Event
from unittest.mock import Mock

import pytest

from dating_boost.core.managed_run import JsonManagedRunStore, ManagedRun
from dating_boost.core.managed_visual_action import TaShuoVisualManagedActionPort
from tests.test_managed_run import Clock, FixtureDecision, FixtureObservation, _config
from tests.test_managed_visual_action import _FakeIO, _outbound, _transition
from tests.test_managed_visual_restart import bind_thread

pytestmark = pytest.mark.managed_critical


def _runtime(tmp_path, phase):
    clock = Clock()
    io = _FakeIO(tmp_path / "frames")
    io.clock = clock.value
    verifier = Mock()
    port = TaShuoVisualManagedActionPort(tmp_path / "data", io=io, verifier=verifier)
    binding = {
        "binding_type": "current_thread_visual_identity", "candidate_key": "row-a",
        "thread_evidence": {"visual_anchor_hash": "anchor-a", "observation_id": "observation-a"},
    }
    candidate = bind_thread(port, io, binding)
    config = _config()
    config = replace(config, authorization=replace(config.authorization, allowed_target_ids=(candidate.target_id,)))
    preparations = 0

    def prepare():
        nonlocal preparations
        preparations += 1
        io.clock = max(io.clock, clock.value)
        if preparations == (1 if phase == "stage" else 2):
            io.body += 1  # A layout change requires model interpretation.

    io.on_prepare = prepare
    store = JsonManagedRunStore(tmp_path / "data")
    runtime = ManagedRun(store, FixtureObservation(clock, [candidate], thread_revision="inbound-a"),
                         FixtureDecision("reply"), port, now=clock)
    return runtime, store, io, verifier, clock, config


@pytest.mark.parametrize("phase", ["stage", "click"])
@pytest.mark.parametrize("change", ["pause", "stop", "pause_resume"])
@pytest.mark.parametrize("fails", [False, True])
def test_action_analysis_releases_lifecycle_lock_and_discards_old_work(tmp_path, monkeypatch, phase, change, fails):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, store, io, verifier, _, config = _runtime(tmp_path, phase)
    entered, release = Event(), Event()

    def compare(*args):
        entered.set()
        assert release.wait(5)
        if fails:
            raise TimeoutError("late synthetic response")
        return _transition()

    verifier.compare.side_effect = compare
    runtime.start(config, run_id="boundary")
    with ThreadPoolExecutor(max_workers=2) as pool:
        tick = pool.submit(runtime.tick)
        assert entered.wait(5)

        def control():
            if change == "stop":
                return runtime.stop()
            result = runtime.pause()
            if change == "pause_resume":
                result = runtime.resume()
            return result

        mutation = pool.submit(control)
        try:
            result = mutation.result(timeout=0.5)
            assert result["status"] == {"pause": "paused", "stop": "stopped", "pause_resume": "active"}[change]
        finally:
            release.set()
        outcome = tick.result(timeout=5)
    assert outcome["status"] in {"paused", "stopped", "blocked"}
    assert io.sent_texts == []
    assert io.calls.count("stage_text") == (0 if phase == "stage" else 1)
    assert store.load("boundary").attempted_send_count == 0
    assert store.load("boundary").thread_states == {}
    assert not runtime.action.safety.is_paused()


@pytest.mark.parametrize("deadline", ["authorization", "duration"])
def test_remote_click_verification_cannot_extend_authorized_window(tmp_path, monkeypatch, deadline):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, store, io, verifier, clock, config = _runtime(tmp_path, "click")
    if deadline == "authorization":
        config = replace(config, authorization=replace(config.authorization,
                         expires_at=(clock.value + timedelta(seconds=20)).isoformat()))
    else:
        config = replace(config, duration_minutes=1)

    def compare(*args):
        clock.value += timedelta(seconds=65)
        io.clock = clock.value
        return _transition()

    verifier.compare.side_effect = compare
    runtime.start(config, run_id="deadline")
    outcome = runtime.tick()
    assert outcome["reason"] == {"authorization": "authorization_expired", "duration": "managed_run_duration_elapsed"}[deadline]
    assert io.sent_texts == []
    assert store.load("deadline").attempted_send_count == 0


def test_split_action_keeps_the_local_pixel_path_without_extra_captures(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, _, io, verifier, clock, config = _runtime(tmp_path, "unused")
    io.on_prepare = lambda: setattr(io, "clock", max(io.clock, clock.value))
    verifier.compare.return_value = _transition(_outbound("reply"))
    runtime.start(config, run_id="pixels")
    assert runtime.tick()["status"] == "confirmed"
    assert io.calls.count("capture") == 3
    assert verifier.compare.call_count == 1
    assert io.sent_texts == ["reply"]


@pytest.mark.parametrize("phase", ["stage", "click"])
def test_remote_preparation_requires_unchanged_fresh_pixels_before_mutation(tmp_path, monkeypatch, phase):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    runtime, store, io, verifier, _, config = _runtime(tmp_path, phase)

    def compare(*args):
        io.body += 1  # UI changed while the model interpreted the captured pixels.
        return _transition()

    verifier.compare.side_effect = compare
    runtime.start(config, run_id="changed")
    assert runtime.tick()["status"] == "failed_before_click"
    assert io.sent_texts == []
    assert io.calls.count("stage_text") == (0 if phase == "stage" else 1)
    assert store.load("changed").attempted_send_count == 0
