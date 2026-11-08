"""Lifecycle generations invalidate work before a click, not its later receipt."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from dating_boost.core.managed_run import DraftDecision, JsonManagedRunStore, SendTransaction
from tests.test_managed_run import FixtureDecision, _burst_fixture, _candidate, _config, _runtime


pytestmark = pytest.mark.managed_critical


@pytest.fixture(params=["memory", "json"])
def store(request, tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    if request.param == "json":
        return JsonManagedRunStore(tmp_path)
    return None


@pytest.mark.parametrize("outcome", ["send", "wait", "handoff", "invalid"])
@pytest.mark.parametrize("operation", ["pause", "pause_resume", "stop"])
def test_late_decision_is_discarded_without_consuming_incoming(store, outcome, operation):
    entered, release = Event(), Event()

    class DelayedDecision(FixtureDecision):
        def decide(self, observation, *, config):
            entered.set()
            assert release.wait(5)
            if outcome == "send":
                return super().decide(observation, config=config)
            if outcome == "invalid":
                return DraftDecision("decision", "handoff", "wrong-target", observation.inbound_revision)
            return DraftDecision("decision", outcome, observation.target_id, observation.inbound_revision)

    runtime, store, observation, _, action, _ = _runtime(store=store, decision=DelayedDecision())
    runtime.start(_config(), run_id="generation")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(runtime.tick)
        try:
            assert entered.wait(5)
            if operation == "stop":
                runtime.stop()
            else:
                runtime.pause()
                if operation == "pause_resume":
                    runtime.resume()
            controlled = store.load("generation").to_dict()
        finally:
            release.set()
        result = pending.result(5)

    assert result["status"] == {"pause": "paused", "pause_resume": "blocked", "stop": "stopped"}[operation]
    if operation == "pause_resume":
        assert result["reason"] == "managed_run_lifecycle_changed"
    assert store.load("generation").to_dict() == controlled
    assert action.calls == []
    assert observation.calls == ["scan", "open", "observe"]
    if operation != "stop":
        if operation == "pause":
            runtime.resume()
        expected = {"send": "confirmed", "invalid": "failed_before_click"}.get(outcome, outcome)
        assert runtime.tick()["status"] == expected
        assert observation.calls == ["scan", "open", "observe"] * 2
        assert action.click_count == (1 if outcome == "send" else 0)


def test_transaction_rejects_an_old_generation_before_staging(store):
    runtime, store, observation, decision, action, clock = _runtime(store=store)
    runtime.start(_config(), run_id="generation")
    record = store.load("generation")
    candidate = replace(_candidate(), inbound_revision="inbound_7")
    thread = observation.observe_thread(candidate)
    draft = decision.decide(thread, config=record.config)
    runtime.pause()
    runtime.resume()
    controlled = store.load("generation").to_dict()

    result = SendTransaction(store=store, action=action, now=clock).execute(record, candidate, thread, draft)

    assert result["status"] == "blocked"
    assert result["reason"] == "managed_run_lifecycle_changed"
    assert action.calls == []
    assert store.load("generation").to_dict() == controlled


@pytest.mark.parametrize("boundary", ["staged", "prepared_observation", "prepared_error"])
def test_generation_change_before_click_preserves_only_the_prepared_checkpoint(store, monkeypatch, boundary):
    runtime, store, observation, _, action, _ = _runtime(store=store)
    runtime.start(_config(), run_id="generation")
    observe_composer = action.observe_composer

    def pause_resume():
        runtime.pause()
        runtime.resume()

    if boundary == "staged":
        action.after_stage = pause_resume
    else:
        # Pause after staging to create a genuine known-unsent checkpoint.
        action.after_stage = runtime.pause
        assert runtime.tick()["status"] == "paused"
        action.after_stage = None
        runtime.resume()
        def delayed_composer(candidate):
            composer = observe_composer(candidate)
            pause_resume()
            if boundary == "prepared_error":
                raise RuntimeError("late observation failure")
            return composer

        monkeypatch.setattr(action, "observe_composer", delayed_composer)

    result = runtime.tick()

    assert result["status"] == "blocked"
    assert result["reason"] == "managed_run_lifecycle_changed"
    saved = store.load("generation")
    assert saved.status == "active"
    assert saved.thread_states == {}
    assert saved.attempted_send_count == saved.confirmed_send_count == 0
    assert next(iter(saved.send_attempts.values()))["status"] == "prepared_to_click"
    assert action.stage_count == 1 and action.click_count == 0
    # A new tick may recover that checkpoint only through fresh observations.
    action.after_stage = None
    monkeypatch.setattr(action, "observe_composer", observe_composer)
    calls_before = observation.calls.count("observe")
    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("observe") == calls_before + 1
    assert action.stage_count == 1 and action.click_count == 1


@pytest.mark.parametrize("post_status", ["confirmed", "unknown_after_click"])
@pytest.mark.parametrize("operation", ["pause", "pause_resume", "stop"])
def test_clicked_result_is_still_accounted_after_a_lifecycle_change(store, monkeypatch, post_status, operation):
    runtime, store, _, _, action, _ = _runtime(store=store)
    runtime.start(_config(), run_id="generation")
    observe_post_send = action.observe_post_send

    def delayed_receipt(candidate, receipt):
        if operation == "stop":
            runtime.stop()
        else:
            runtime.pause()
            if operation == "pause_resume":
                runtime.resume()
        if post_status == "unknown_after_click":
            raise RuntimeError("receipt unavailable")
        return observe_post_send(candidate, receipt)

    monkeypatch.setattr(action, "observe_post_send", delayed_receipt)

    result = runtime.tick()

    assert result["status"] == post_status
    saved = store.load("generation")
    expected_status = "stopped" if operation == "stop" else (
        "active" if operation == "pause_resume" and post_status == "confirmed" else "paused"
    )
    assert saved.status == expected_status
    assert saved.confirmed_send_count == (1 if post_status == "confirmed" else 0)
    assert saved.attempted_send_count == action.click_count == 1
    assert runtime.tick()["status"] == ("no_work" if expected_status == "active" else expected_status)


def test_late_burst_decision_is_not_published(store, monkeypatch):
    runtime, store, observation, decision, action, _ = _burst_fixture(store=store)
    decide = decision.decide
    controlled = {}

    def delayed_decision(thread, *, config):
        result = decide(thread, config=config)
        runtime.pause()
        runtime.resume()
        controlled.update(store.load("run_burst").to_dict())
        return result

    monkeypatch.setattr(decision, "decide", delayed_decision)
    assert runtime.tick()["reason"] == "managed_run_lifecycle_changed"
    assert store.load("run_burst").to_dict() == controlled
    assert action.calls == []
    monkeypatch.setattr(decision, "decide", decide)
    assert runtime.tick()["status"] == "confirmed"
    assert observation.calls.count("observe") == 2
    assert action.click_count == 3
