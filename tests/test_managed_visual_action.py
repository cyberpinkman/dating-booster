from __future__ import annotations

import hashlib
import struct
import zlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo.managed_visual_evidence import VisualBubble, VisualTransition
from dating_boost.core.managed_run import (
    DraftDecision, InMemoryManagedRunStore, ManagedActionError, ManagedAuthorization,
    ManagedClickBlocked, ManagedRun, ManagedRunConfig, MessageListSnapshot,
    OpenThreadObservation, ThreadCandidate, ThreadObservation,
)
from dating_boost.core.managed_visual_action import TaShuoVisualManagedActionPort


pytestmark = pytest.mark.managed_critical


def _png(body: int, composer: bool) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = [b"\x00" + bytes([body if row < 6 else int(composer)] * 12) for row in range(8)]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _transition(*bubbles, **changes):
    return VisualTransition(
        **{
            "same_conversation": True, "baseline_messages_preserved": True,
            "added_bubbles": tuple(bubbles), "other_conversation_change": False,
            "composer_state": "empty", "composer_text": "", "confidence": "high", **changes,
        }
    )


def _outbound(text="reply"):
    return VisualBubble(direction="outbound", text=text, kind="text")


class _FakeIO:
    """Synthetic PNG captures and composer state; no conversation AX interface."""

    def __init__(self, directory):
        self.directory = directory
        directory.mkdir()
        self.calls = []
        self.frames = []
        self.clock = datetime(2026, 9, 20, 10, tzinfo=timezone.utc)
        self.body = 0
        self.composer = ""
        self.composer_top_ratio = 0.75
        self.read_result = None
        self.stage_result = {"status": "ok", "staged_exact_text_verified": True}
        self.click_result = None
        self.clear_after_click = True
        self.sent_texts = []
        self.on_prepare = None
        self.on_capture = None
        self.on_stage = None

    def _time(self):
        self.clock += timedelta(seconds=1)
        return self.clock.isoformat()

    def frame(self):
        number = len(self.frames)
        path = self.directory / f"frame-{number}.png"
        path.write_bytes(_png(self.body, bool(self.composer)))
        payload = {
            "status": "ok", "path": str(path), "frame_id": f"frame-{number}",
            "captured_at": self._time(), "state": "tashuo_conversation",
            "composer_top_ratio": self.composer_top_ratio,
        }
        self.frames.append(payload)
        return payload

    def capture(self):
        self.calls.append("capture")
        result = self.frame()
        if self.on_capture is not None:
            self.on_capture(result)
        return result

    def read_composer(self):
        self.calls.append("read_composer")
        return self.read_result if self.read_result is not None else {"status": "ok", "value": self.composer}

    def prepare_composer(self, expected_text=None):
        self.calls.append("prepare_composer")
        expected = "" if expected_text is None else expected_text
        if self.composer != expected:
            return {"status": "blocked", "reason": "candidate_composer_occupied"}
        if self.on_prepare is not None:
            self.on_prepare()
        return {"status": "ok"}

    def stage_text(self, text):
        self.calls.append("stage_text")
        if self.stage_result.get("status") == "ok":
            self.composer = text
        if self.on_stage is not None:
            self.on_stage()
        return {"captured_at": self._time(), **self.stage_result}

    def click_return(self, expected_text, *, deadline_at=None):
        self.calls.append("click_return")
        assert self.composer == expected_text
        self.last_deadline = deadline_at
        if self.click_result is not None:
            return self.click_result
        clicked_at = self._time()
        self.sent_texts.append(expected_text)
        self.body += 1
        if self.clear_after_click:
            self.composer = ""
        return {"status": "ok", "receipt_id": f"receipt-{len(self.sent_texts)}", "clicked_at": clicked_at}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("DATING_BOOST_KEY_PROVIDER", "local")
    io = _FakeIO(tmp_path / "screens")
    verifier = Mock()
    verifier.compare.return_value = _transition()
    sleeper = Mock()
    port = TaShuoVisualManagedActionPort(tmp_path / "data", io=io, verifier=verifier, sleeper=sleeper)
    binding = {
        "binding_type": "current_thread_visual_identity", "candidate_key": "synthetic-person",
        "thread_evidence": {"visual_anchor_hash": "synthetic-anchor", "observation_id": "draft-observation"},
    }
    baseline = io.frame()
    bound = port.bind_thread(binding, {"candidate_key": "synthetic-person", "managed_visual_frame": baseline})
    binding["thread_evidence"]["managed_inbound_revision"] = bound["inbound_revision"]
    candidate = ThreadCandidate(
        candidate_key="synthetic-person", target_id="synthetic-target", target_binding="logical-binding",
        discovery_revision="discovery-1", inbound_revision="inbound-1",
        metadata={"verified_target_binding": binding, "verified_inbound_revision": "inbound-1"},
    )
    return SimpleNamespace(
        port=port, io=io, verifier=verifier, sleeper=sleeper, candidate=candidate,
        binding=binding, baseline=baseline, bound=bound,
    )


def _click(rig, text="reply"):
    rig.port.stage_text(rig.candidate, text)
    return rig.port.click_send(rig.candidate)


def test_initial_bind_reuses_drafting_frame_without_ax_body_reads_capture_or_vision(rig):
    assert rig.io.calls == []
    rig.verifier.compare.assert_not_called()
    assert rig.bound["evidence_source"] == "visible_conversation_screenshot"
    assert rig.bound["inbound_revision_observation_id"] == rig.baseline["frame_id"]
    assert rig.port.drain_metrics() == {}


def test_same_body_observe_and_exact_stage_use_pixels_without_visual_requests(rig):
    observed = rig.port.observe_composer(rig.candidate)
    staged = rig.port.stage_text(rig.candidate, "两行\n合成消息")
    assert observed.text == ""
    assert staged.text == rig.io.composer == "两行\n合成消息"
    assert staged.inbound_revision == rig.candidate.inbound_revision
    assert rig.io.calls.count("stage_text") == 1
    rig.verifier.compare.assert_not_called()
    metrics = rig.port.drain_metrics()
    assert metrics["pixel_reuses"] == metrics["captures"] == 2
    assert rig.io.calls.count("read_composer") == 1  # Only the explicit initial observation.
    assert rig.port.drain_metrics() == {}


def test_focus_layout_change_uses_one_pair_then_fresh_pixels_before_stage(rig):
    def expand():
        rig.io.body = 2
        rig.io.composer_top_ratio = 0.7

    rig.io.on_prepare = expand
    staged = rig.port.stage_text(rig.candidate, "reply")
    assert staged.text == "reply"
    rig.verifier.compare.assert_called_once()
    before, after = rig.verifier.compare.call_args.args
    assert before.composer_top_ratio == 0.75
    assert after.composer_top_ratio == 0.7
    assert rig.io.calls == [
        "prepare_composer", "capture", "capture", "stage_text",
    ]
    assert rig.port.drain_metrics()["visual_requests"] == 1


def test_change_during_layout_model_latency_blocks_before_staging(rig):
    rig.io.on_prepare = lambda: setattr(rig.io, "body", 1)

    def compare(*_frames):
        rig.io.body = 2
        return _transition()

    rig.verifier.compare.side_effect = compare
    with pytest.raises(ManagedActionError, match="^managed_visual_changed_during_verification$"):
        rig.port.stage_text(rig.candidate, "reply")
    rig.verifier.compare.assert_called_once()
    assert "stage_text" not in rig.io.calls
    assert "click_return" not in rig.io.calls


@pytest.mark.parametrize("failure", ["stage_proof", "atomic_readback", "stage_exception"])
def test_stage_requires_atomic_exact_proof_and_pauses_unresolved_draft(rig, failure):
    if failure == "stage_proof":
        rig.io.stage_result["staged_exact_text_verified"] = False
    elif failure == "atomic_readback":
        rig.io.stage_result = {"status": "blocked", "reason": "managed_staged_exact_text_not_verified"}
    else:
        def interrupted():
            raise RuntimeError("synthetic interruption after write")

        rig.io.on_stage = interrupted
    error = RuntimeError if failure == "stage_exception" else ManagedActionError
    with pytest.raises(error):
        rig.port.stage_text(rig.candidate, "reply")
    assert rig.port.safety.is_paused()
    assert "click_return" not in rig.io.calls


def test_stage_uses_atomic_readback_time_without_retimestamping_the_focused_frame(rig):
    result = rig.port.stage_text(rig.candidate, "reply")
    focused = rig.io.frames[-1]
    assert result.captured_at == rig.io.clock.isoformat()
    assert result.captured_at != focused["captured_at"]
    assert rig.io.calls == ["prepare_composer", "capture", "stage_text"]
    # The retained baseline is the earlier capture, not a synthetic stage-time frame.
    assert rig.port._threads[rig.candidate.candidate_key].frame.captured_at == focused["captured_at"]


def test_stage_without_optional_io_timestamp_keeps_compatible_capture_time(rig):
    stage = rig.io.stage_text

    def legacy_stage(text):
        result = stage(text)
        result.pop("captured_at")
        return result

    rig.io.stage_text = legacy_stage
    result = rig.port.stage_text(rig.candidate, "reply")
    assert result.captured_at == rig.io.frames[-1]["captured_at"]


@pytest.mark.parametrize("captured_at", ["", "not-a-time", "2026-09-20T09:00:00+00:00", None])
def test_invalid_or_prestage_io_time_cannot_replace_composer_proof(rig, captured_at):
    rig.io.stage_result["captured_at"] = captured_at
    with pytest.raises(ManagedActionError, match="^managed_stage_observation_time_invalid$"):
        rig.port.stage_text(rig.candidate, "reply")
    assert rig.port.safety.is_paused()
    assert "click_return" not in rig.io.calls


def test_new_inbound_after_focus_blocks_before_atomic_write(rig):
    rig.io.on_prepare = lambda: setattr(rig.io, "body", 1)
    rig.verifier.compare.return_value = _transition(VisualBubble("inbound", "new message", "text"))
    with pytest.raises(ManagedActionError, match="^managed_visual_conversation_changed$"):
        rig.port.stage_text(rig.candidate, "reply")
    assert rig.io.calls == ["prepare_composer", "capture"]
    assert not rig.port.safety.is_paused()


def test_new_inbound_after_atomic_write_is_caught_before_the_only_return(rig):
    rig.io.on_stage = lambda: setattr(rig.io, "body", 1)
    rig.port.stage_text(rig.candidate, "reply")
    rig.verifier.compare.assert_not_called()
    rig.verifier.compare.return_value = _transition(VisualBubble("inbound", "new message", "text"))
    with pytest.raises(ManagedClickBlocked, match="^managed_visual_conversation_changed$"):
        rig.port.click_send(rig.candidate)
    assert "click_return" not in rig.io.calls
    assert rig.port.safety.is_paused()


def test_preclick_conversation_change_is_known_block_without_return(rig):
    rig.port.stage_text(rig.candidate, "reply")
    rig.io.body += 1
    rig.verifier.compare.return_value = _transition(VisualBubble("inbound", "new message", "text"))
    with pytest.raises(ManagedClickBlocked, match="^managed_visual_conversation_changed$"):
        rig.port.click_send(rig.candidate)
    assert "click_return" not in rig.io.calls
    assert rig.port.safety.is_paused()


def test_click_return_executes_once_and_carries_burst_deadline(rig):
    rig.candidate.metadata["managed_burst_click_deadline_at"] = "2026-09-20T10:01:00Z"
    receipt = _click(rig)
    assert receipt.receipt_id == "receipt-1"
    assert rig.io.calls.count("click_return") == 1
    assert rig.io.last_deadline == rig.candidate.metadata["managed_burst_click_deadline_at"]


@pytest.mark.parametrize("inbound", [False, True])
def test_post_send_proves_new_exact_outbound_and_keeps_inbound_separate_from_confirmation(rig, inbound):
    receipt = _click(rig)
    bubbles = [_outbound()]
    if inbound:
        bubbles.append(VisualBubble("inbound", "a new reply", "text"))
    rig.verifier.compare.return_value = _transition(*bubbles)
    result = rig.port.observe_post_send(rig.candidate, receipt)
    assert result.outbound_text == "reply"
    assert result.input_cleared
    assert result.continuation_verified is (not inbound)
    assert result.receipt_id == receipt.receipt_id
    assert result.target_binding == rig.candidate.target_binding
    rig.verifier.compare.assert_called_once()
    assert rig.io.calls.count("click_return") == 1
    rig.sleeper.assert_not_called()


@pytest.mark.parametrize("transition", [
    _transition(),  # Seeing only an old identical message adds no bubble.
    _transition(VisualBubble("inbound", "reply", "text")),
    _transition(_outbound("reply but different")),
    _transition(_outbound(), baseline_messages_preserved=False),
])
def test_old_same_text_inbound_same_text_or_uncertain_alignment_does_not_confirm(rig, transition):
    receipt = _click(rig)
    rig.verifier.compare.return_value = transition
    with pytest.raises(ManagedActionError, match="^managed_visual_outbound_not_verified$"):
        rig.port.observe_post_send(rig.candidate, receipt)
    assert rig.io.calls.count("click_return") == 1


def test_post_send_requires_input_clear_even_when_outbound_is_proven(rig):
    rig.io.clear_after_click = False
    receipt = _click(rig)
    rig.verifier.compare.return_value = _transition(_outbound())
    with pytest.raises(ManagedActionError, match="^managed_visual_outbound_not_verified$"):
        rig.port.observe_post_send(rig.candidate, receipt)
    assert rig.io.calls.count("click_return") == 1


@pytest.mark.parametrize("composer_state,verified", [("empty", True), ("unreadable", False)])
def test_collapsed_post_composer_uses_the_same_visual_transition_without_another_request(rig, composer_state, verified):
    receipt = _click(rig)
    rig.io.read_result = {"status": "blocked", "reason": "tashuo_ax_text_area_not_found"}
    rig.verifier.compare.return_value = _transition(_outbound(), composer_state=composer_state)
    if verified:
        assert rig.port.observe_post_send(rig.candidate, receipt).input_cleared
    else:
        with pytest.raises(ManagedActionError, match="^managed_visual_outbound_not_verified$"):
            rig.port.observe_post_send(rig.candidate, receipt)
    rig.verifier.compare.assert_called_once()


@pytest.mark.parametrize("failure", ["overwritten", "stale"])
def test_overwritten_or_stale_preclick_capture_blocks_without_return(rig, failure):
    rig.port.stage_text(rig.candidate, "reply")
    if failure == "overwritten":
        from pathlib import Path

        Path(rig.io.frames[-1]["path"]).write_bytes(_png(7, True))
    else:
        baseline_time = rig.io.frames[-1]["captured_at"]
        rig.io.on_capture = lambda frame: frame.update(captured_at=baseline_time)
    with pytest.raises(ManagedClickBlocked, match="^managed_visual_frame_invalid$"):
        rig.port.click_send(rig.candidate)
    assert "click_return" not in rig.io.calls
    rig.verifier.compare.assert_not_called()


def test_post_capture_must_follow_the_actual_return_receipt(rig):
    receipt = _click(rig)
    rig.io.on_capture = lambda frame: frame.update(captured_at=receipt.clicked_at)
    with pytest.raises(ManagedActionError, match="^managed_post_send_capture_not_fresh$"):
        rig.port.observe_post_send(rig.candidate, receipt)
    rig.verifier.compare.assert_not_called()
    assert rig.io.calls.count("click_return") == 1


def test_changed_target_binding_rejects_before_any_io(rig):
    rig.binding["thread_evidence"]["visual_anchor_hash"] = "another-target"
    with pytest.raises(ManagedActionError, match="^managed_visual_target_evidence_missing$"):
        rig.port.observe_composer(rig.candidate)
    assert rig.io.calls == []


@pytest.mark.parametrize("messages", [("第一条", "第二条"), ("第一条", "第二条", "第三条")])
def test_real_managed_run_uses_visual_port_for_one_decision_and_contiguous_verified_burst(rig, messages):
    store = InMemoryManagedRunStore()
    observation = Mock()
    observation.scan_message_list.side_effect = lambda **_kwargs: MessageListSnapshot(
        candidates=(rig.candidate,), captured_at=rig.io._time(),
    )
    observation.open_thread.side_effect = lambda candidate: OpenThreadObservation(
        target_id=candidate.target_id, target_binding=candidate.target_binding, captured_at=rig.io._time(),
    )
    observation.observe_thread.side_effect = lambda candidate: ThreadObservation(
        target_id=candidate.target_id, target_binding=candidate.target_binding,
        inbound_revision="inbound-1", captured_at=rig.io._time(),
    )
    decision = Mock()
    decision.prioritize.side_effect = lambda candidates, **_kwargs: candidates[0] if candidates else None

    def decide(observed, **_kwargs):
        # Planning latency must not eat the adjacent-click window.
        rig.io.clock += timedelta(seconds=180)
        return DraftDecision.send(
            decision_id="synthetic-visual-burst", target_id=observed.target_id,
            inbound_revision=observed.inbound_revision,
            text="\n".join(messages), message_sequence=messages,
        )

    decision.decide.side_effect = decide
    rig.verifier.compare.side_effect = [_transition(_outbound(message)) for message in messages]
    runtime = ManagedRun(
        store, observation, decision, rig.port,
        now=lambda: rig.io.clock, monotonic=lambda: rig.io.clock.timestamp(),
        sleeper=lambda _delay: pytest.fail("synthetic burst must not sleep"),
    )
    config = ManagedRunConfig(
        app_id="tashuo", runtime="mac-ios-app", max_sends_per_run=len(messages) + 1,
        authorization=ManagedAuthorization(
            authorization_id="synthetic-visual-auth", app_id="tashuo", runtime="mac-ios-app",
            allowed_target_ids=(rig.candidate.target_id,),
        ),
    )
    assert runtime.start(config, run_id="synthetic-visual-run")["status"] == "active"
    result = runtime.tick()

    assert result["status"] == "confirmed", result
    assert result["completed_message_count"] == len(messages)
    assert result["cancelled_message_count"] == result["unknown_message_count"] == 0
    decision.decide.assert_called_once()
    observation.open_thread.assert_called_once()
    observation.observe_thread.assert_called_once()
    assert rig.io.sent_texts == list(messages)
    assert rig.io.calls.count("stage_text") == rig.io.calls.count("click_return") == len(messages)
    assert rig.verifier.compare.call_count == len(messages)
    rig.sleeper.assert_not_called()
    record = store.load("synthetic-visual-run")
    assert record.confirmed_send_count == record.attempted_send_count == len(messages)
    assert next(iter(record.send_bursts.values()))["status"] == "completed"
    profiles = [event for event in store.events("synthetic-visual-run") if event["event_type"] == "tick_profile"]
    metrics = profiles[-1]["visual_verification"]
    assert metrics["visual_requests"] == len(messages)
    assert metrics["pixel_reuses"] == 2 * len(messages)
    assert metrics["captures"] == 3 * len(messages)
    assert runtime.tick()["status"] == "no_work"
    assert rig.io.calls.count("click_return") == len(messages)


def _attempt(rig, receipt, text="reply"):
    return {
        "status": "unknown_after_click", "receipt_id": receipt.receipt_id,
        "clicked_at": receipt.clicked_at, "target_id": rig.candidate.target_id,
        "candidate_key": rig.candidate.candidate_key, "target_binding": rig.candidate.target_binding,
        "inbound_revision": rig.candidate.inbound_revision, "exact_text": text,
        "payload_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _recovery_port(rig, verifier=None):
    # No GUI-capable object or thread binding survives the simulated restart.
    return TaShuoVisualManagedActionPort(
        rig.port.evidence_store.storage.root, io=object(), verifier=verifier or Mock(),
    )


def test_identical_conversation_pixels_cannot_confirm_live_or_recovered_outbound(rig):
    receipt = _click(rig)
    rig.io.body = 0  # The composer cleared, but no conversation pixels changed.
    rig.verifier.compare.return_value = _transition(_outbound())
    with pytest.raises(ManagedActionError, match="managed_visual_outbound_not_verified"):
        rig.port.observe_post_send(rig.candidate, receipt)
    recovered = _recovery_port(rig, verifier=rig.verifier)
    with pytest.raises(ManagedActionError, match="managed_visual_outbound_not_verified"):
        recovered.recover_send(_attempt(rig, receipt))
    rig.verifier.compare.assert_not_called()


def test_restart_recovery_uses_saved_typed_evidence_without_gui_model_or_attempt_mutation(rig):
    text = "精确🙂\n第二行"
    receipt = _click(rig, text)
    rig.verifier.compare.return_value = _transition(_outbound(text))
    rig.port.observe_post_send(rig.candidate, receipt)
    attempt = _attempt(rig, receipt, text)
    original = deepcopy(attempt)
    calls = list(rig.io.calls)
    recovered = _recovery_port(rig)
    saved = recovered.evidence_store.load_for_attempt(attempt)

    result = recovered.recover_send(attempt)

    assert result.outbound_text == text
    assert result.receipt_id == receipt.receipt_id
    assert result.input_cleared is True
    assert result.continuation_verified is False
    assert result.recovery_evidence_digest == saved.manifest_digest
    assert len(result.recovery_evidence_digest) == 64
    assert attempt == original
    assert rig.io.calls == calls
    recovered.verifier.compare.assert_not_called()
    assert recovered.evidence_store.load_for_attempt(attempt) == saved
    assert not list((recovered.evidence_store.storage.root / "managed_run").rglob("*.json"))


def test_after_frame_and_ax_proof_are_saved_before_model_and_failed_transcription_is_retained(rig):
    receipt = _click(rig)
    attempt = _attempt(rig, receipt)

    def mismatch(before, after):
        saved = rig.port.evidence_store.load_for_attempt(attempt)
        assert saved.before == before
        assert saved.after == after
        assert saved.composer == {"available": True, "input_cleared": True}
        assert saved.transition is None
        return _transition(_outbound("wrong transcription"))

    rig.verifier.compare.side_effect = mismatch
    with pytest.raises(ManagedActionError, match="^managed_visual_outbound_not_verified$"):
        rig.port.observe_post_send(rig.candidate, receipt)
    saved = rig.port.evidence_store.load_for_attempt(attempt)
    assert saved.transition.added_bubbles[0].text == "wrong transcription"
    recovered = _recovery_port(rig)
    with pytest.raises(ManagedActionError, match="^managed_visual_outbound_not_verified$"):
        recovered.recover_send(attempt)
    recovered.verifier.compare.assert_not_called()


def test_failed_model_leaves_frames_for_read_only_recomparison_after_restart(rig):
    receipt = _click(rig)
    rig.verifier.compare.side_effect = RuntimeError("synthetic model failure")
    with pytest.raises(ManagedActionError, match="^managed_visual_evidence_unavailable$"):
        rig.port.observe_post_send(rig.candidate, receipt)
    attempt = _attempt(rig, receipt)
    saved = rig.port.evidence_store.load_for_attempt(attempt)
    assert saved.transition is None
    verifier = Mock()
    verifier.compare.return_value = _transition(_outbound())
    recovered = _recovery_port(rig, verifier)

    result = recovered.recover_send(attempt)

    assert result.outbound_text == "reply"
    verifier.compare.assert_called_once_with(saved.before, saved.after)
    updated = recovered.evidence_store.load_for_attempt(attempt)
    assert updated.before == saved.before and updated.after == saved.after
    assert updated.transition == verifier.compare.return_value
    assert result.recovery_evidence_digest == updated.manifest_digest


@pytest.mark.parametrize("field", [
    "receipt_id", "clicked_at", "candidate_key", "target_id", "target_binding",
    "inbound_revision", "payload_hash", "exact_text",
])
def test_recovery_rejects_mismatched_original_attempt_before_model(rig, field):
    receipt = _click(rig)
    rig.verifier.compare.return_value = _transition(_outbound())
    rig.port.observe_post_send(rig.candidate, receipt)
    attempt = _attempt(rig, receipt)
    attempt[field] += "changed"
    recovered = _recovery_port(rig)
    with pytest.raises(ManagedActionError, match="^managed_send_evidence_"):
        recovered.recover_send(attempt)
    recovered.verifier.compare.assert_not_called()


@pytest.mark.parametrize("which", ["before", "after"])
def test_recovery_rejects_changed_saved_frame_before_model(rig, which):
    receipt = _click(rig)
    rig.verifier.compare.return_value = _transition(_outbound())
    rig.port.observe_post_send(rig.candidate, receipt)
    attempt = _attempt(rig, receipt)
    saved = rig.port.evidence_store.load_for_attempt(attempt)
    getattr(saved, which).path.write_bytes(_png(8, True))
    recovered = _recovery_port(rig)
    with pytest.raises(ManagedActionError, match="^managed_send_evidence_frame_changed$"):
        recovered.recover_send(attempt)
    recovered.verifier.compare.assert_not_called()


def test_recovery_rejects_nonfresh_saved_after_time(rig):
    receipt = _click(rig)
    rig.verifier.compare.return_value = _transition(_outbound())
    rig.port.observe_post_send(rig.candidate, receipt)
    store = rig.port.evidence_store
    path = store._receipt_path(receipt.receipt_id)
    manifest = store.storage.read_json(path, expected_schema_version=1)
    manifest["after"]["captured_at"] = receipt.clicked_at
    store.storage.write_json(path, manifest)
    recovered = _recovery_port(rig)
    with pytest.raises(ManagedActionError, match="^managed_send_evidence_times_invalid$"):
        recovered.recover_send(_attempt(rig, receipt))
    recovered.verifier.compare.assert_not_called()


def test_recovery_does_not_import_unassociated_screenshots(rig):
    from dating_boost.core.managed_run import ClickReceipt

    rig.io.frame()
    recovered = _recovery_port(rig)
    with pytest.raises(ManagedActionError, match="^managed_send_evidence_missing$"):
        recovered.recover_send(_attempt(rig, ClickReceipt("missing-receipt", rig.io._time())))
    recovered.verifier.compare.assert_not_called()
    assert rig.io.calls == []


@pytest.mark.parametrize("boundary", ["prepare", "record_click", "record_after"])
def test_persistence_failure_never_crosses_an_unrecorded_return_or_reports_success(rig, monkeypatch, boundary):
    def fail(*_args, **_kwargs):
        raise OSError("synthetic storage unavailable")

    monkeypatch.setattr(rig.port.evidence_store, boundary, fail)
    if boundary == "prepare":
        with pytest.raises(ManagedClickBlocked, match="^managed_send_evidence_persistence_failed$"):
            _click(rig)
        assert rig.io.calls.count("click_return") == 0
    elif boundary == "record_click":
        with pytest.raises(ManagedActionError, match="^managed_send_evidence_persistence_failed$"):
            _click(rig)
        assert rig.io.calls.count("click_return") == 1
    else:
        receipt = _click(rig)
        with pytest.raises(ManagedActionError, match="^managed_send_evidence_persistence_failed$"):
            rig.port.observe_post_send(rig.candidate, receipt)
        assert rig.io.calls.count("click_return") == 1
    rig.verifier.compare.assert_not_called()


def test_preflight_is_durable_before_the_only_return(rig, monkeypatch):
    prepare = rig.port.evidence_store.prepare
    click = rig.io.click_return
    evidence_ids = []

    def record_preflight(**kwargs):
        evidence_id = prepare(**kwargs)
        evidence_ids.append(evidence_id)
        return evidence_id

    def checked_click(*args, **kwargs):
        assert len(evidence_ids) == 1
        store = rig.port.evidence_store
        saved = store.storage.read_json(store._preflight_path(evidence_ids[0]), expected_schema_version=1)
        assert saved["payload_hash"] == hashlib.sha256(b"reply").hexdigest()
        assert saved["candidate_key"] == rig.candidate.candidate_key
        assert saved["before"]["frame_id"] == rig.io.frames[-1]["frame_id"]
        return click(*args, **kwargs)

    monkeypatch.setattr(rig.port.evidence_store, "prepare", record_preflight)
    rig.io.click_return = checked_click
    _click(rig)
    assert rig.io.calls.count("click_return") == 1


def test_unknown_return_with_receipt_retains_association_without_claiming_success(rig):
    rig.io.click_result = {
        "status": "unknown", "reason": "managed_return_result_unknown",
        "receipt_id": "uncertain-receipt", "clicked_at": "2026-09-20T11:00:00Z",
    }
    with pytest.raises(ManagedActionError, match="^managed_return_result_unknown$"):
        _click(rig)
    saved = rig.port.evidence_store._read_receipt("uncertain-receipt")
    assert saved["clicked_at"] == rig.io.click_result["clicked_at"]
    assert saved["target_id"] == rig.candidate.target_id
    assert "after" not in saved
    assert rig.io.calls.count("click_return") == 1


def test_legacy_provenance_cannot_impersonate_original_capture_time(rig):
    from dating_boost.apps.tashuo.managed_visual_evidence import VisualFrame

    store = rig.port.evidence_store
    provenance = {"source": "host_reviewed_legacy_capture", "reviewed_at": "2026-09-20T12:00:00Z"}
    before = VisualFrame.from_payload(rig.baseline)
    evidence_id = store.prepare(
        target_id=rig.candidate.target_id, candidate_key=rig.candidate.candidate_key,
        target_binding=rig.candidate.target_binding, inbound_revision=rig.candidate.inbound_revision,
        payload_hash=hashlib.sha256(b"reply").hexdigest(), before=before, provenance=provenance,
    )
    saved = store.storage.read_json(store._preflight_path(evidence_id), expected_schema_version=1)
    assert saved["provenance"] == provenance
    assert saved["before"]["captured_at"] == rig.baseline["captured_at"]
    assert saved["prepared_at"] != saved["before"]["captured_at"]
    assert rig.io.calls == []


@pytest.mark.parametrize("comparison", ["identical", "different", "uncertain"])
def test_emoji_rendered_proof_is_bounded_and_reused_after_restart(rig, comparison):
    text = "看到了😄"
    receipt = _click(rig, text)
    rig.verifier.compare.return_value = _transition(_outbound("看到了😀"))
    rendered = Mock()
    rendered.compare.return_value = {
        "comparison": comparison, "confidence": "high",
        "before_composer_readable": True, "after_new_outbound_readable": True,
    }
    rig.port.rendered_verifier = rendered
    if comparison == "identical":
        result = rig.port.observe_post_send(rig.candidate, receipt)
        assert result.outbound_text == text and result.continuation_verified
    else:
        with pytest.raises(ManagedActionError, match="managed_visual_outbound_not_verified"):
            rig.port.observe_post_send(rig.candidate, receipt)
    rendered.compare.assert_called_once()
    attempt = _attempt(rig, receipt, text)
    recovered = _recovery_port(rig)
    recovered.rendered_verifier = Mock()
    if comparison == "identical":
        post = recovered.recover_send(attempt)
        assert post.outbound_text == text and not post.continuation_verified
        assert post.recovery_evidence_digest == recovered.evidence_store.load_for_attempt(attempt).manifest_digest
    else:
        with pytest.raises(ManagedActionError, match="managed_visual_outbound_not_verified"):
            recovered.recover_send(attempt)
    recovered.verifier.compare.assert_not_called()
    recovered.rendered_verifier.compare.assert_not_called()
    assert rig.io.calls.count("click_return") == 1


def test_rendered_model_failure_is_durable_and_never_retried_on_recovery(rig):
    text = "看到了😄"
    receipt = _click(rig, text)
    rig.verifier.compare.return_value = _transition(_outbound("看到了😀"))
    rig.port.rendered_verifier = Mock()
    rig.port.rendered_verifier.compare.side_effect = RuntimeError("private model exception")
    with pytest.raises(ManagedActionError, match="^managed_rendered_comparison_failed$"):
        rig.port.observe_post_send(rig.candidate, receipt)
    recovered = _recovery_port(rig)
    recovered.rendered_verifier = Mock()
    with pytest.raises(ManagedActionError, match="^managed_visual_outbound_not_verified$"):
        recovered.recover_send(_attempt(rig, receipt, text))
    recovered.rendered_verifier.compare.assert_not_called()
