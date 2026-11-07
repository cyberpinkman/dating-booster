"""Restart the real visual action port around a durable pre-click checkpoint."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock

import pytest

from dating_boost.core.managed_run import JsonManagedRunStore, ManagedRun, ThreadCandidate
from dating_boost.core.managed_visual_action import TaShuoVisualManagedActionPort
from tests.test_managed_run import Clock, FixtureDecision, FixtureObservation, _config
from tests.test_managed_visual_action import _FakeIO, _outbound, _transition


pytestmark = pytest.mark.managed_critical


class ProcessExit(BaseException):
    pass


class CrashAfterPrepared(JsonManagedRunStore):
    def save(self, record):
        super().save(record)
        if any(attempt["status"] == "prepared_to_click" for attempt in record.send_attempts.values()):
            raise ProcessExit


def bind_thread(port, io, binding):
    result = port.bind_thread(binding, {
        "candidate_key": "row-a", "managed_visual_frame": io.frame(),
    })
    binding["thread_evidence"]["managed_inbound_revision"] = result["inbound_revision"]
    return ThreadCandidate(
        candidate_key="row-a", target_id="match-a", target_binding="binding-a",
        discovery_revision="discovery-a", inbound_revision="inbound-a",
        metadata={"verified_target_binding": binding, "verified_inbound_revision": "inbound-a"},
    )


@pytest.mark.parametrize("composer", ["original reply", "", "user edited reply"])
def test_new_visual_port_resumes_only_the_exact_durable_single_message(tmp_path, composer):
    before_io = _FakeIO(tmp_path / "before")
    verifier = Mock()
    verifier.compare.return_value = _transition(_outbound("original reply"))
    before_port = TaShuoVisualManagedActionPort(tmp_path / "data", io=before_io, verifier=verifier)
    binding = {
        "binding_type": "current_thread_visual_identity", "candidate_key": "row-a",
        "thread_evidence": {"visual_anchor_hash": "anchor-a", "observation_id": "observation-a"},
    }
    candidate = bind_thread(before_port, before_io, binding)
    clock = Clock()
    config = _config()
    config = replace(config, authorization=replace(config.authorization, allowed_target_ids=(candidate.target_id,)))
    original_store = CrashAfterPrepared(tmp_path / "data")
    original = ManagedRun(
        original_store, FixtureObservation(clock, [candidate], thread_revision="inbound-a"),
        FixtureDecision("original reply"), before_port, now=clock,
    )
    original.start(config, run_id="restart-run")
    with pytest.raises(ProcessExit):
        original.tick()
    assert before_io.calls.count("stage_text") == 1
    assert before_io.calls.count("click_return") == 0

    # Only the external app state and encrypted database survive the restart.
    resumed_io = _FakeIO(tmp_path / "after")
    resumed_io.composer = composer
    resumed_io.body = before_io.body
    resumed_io.clock = before_io.clock
    resumed_port = TaShuoVisualManagedActionPort(tmp_path / "data", io=resumed_io, verifier=verifier)
    fresh_candidate = bind_thread(resumed_port, resumed_io, deepcopy(binding))
    planner = FixtureDecision("replacement must never be used")
    store = JsonManagedRunStore(tmp_path / "data")
    runtime = ManagedRun(
        store, FixtureObservation(clock, [fresh_candidate], thread_revision="inbound-a"), planner, resumed_port, now=clock,
    )

    result = runtime.tick()

    assert planner.calls == ["prioritize"]
    assert resumed_io.calls.count("stage_text") == 0
    if composer == "original reply":
        assert result["status"] == "confirmed"
        assert resumed_io.sent_texts == ["original reply"]
        assert store.load("restart-run").confirmed_send_count == 1
        runtime.tick()
        assert resumed_io.calls.count("click_return") == 1
    else:
        assert result["status"] == "failed_before_click"
        assert resumed_io.calls.count("click_return") == 0
        assert store.load("restart-run").attempted_send_count == 0
