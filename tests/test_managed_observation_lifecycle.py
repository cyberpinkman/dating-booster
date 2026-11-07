from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo import standalone
from dating_boost.core.managed_run import (
    DraftDecision, InMemoryManagedRunStore, ManagedAuthorization, ManagedRun, ManagedRunConfig,
)
from dating_boost.core.managed_run_provider import StandaloneObservationManagedRunPort


pytestmark = pytest.mark.managed_critical


class GuardedStore(InMemoryManagedRunStore):
    def __init__(self):
        super().__init__()
        self.local = threading.local()

    @contextmanager
    def state_lease(self, run_id):
        with super().state_lease(run_id):
            self.local.depth = getattr(self.local, "depth", 0) + 1
            try:
                yield
            finally:
                self.local.depth -= 1

    def held(self):
        return getattr(self.local, "depth", 0) > 0


def _runtime(tmp_path, monkeypatch, *, blocked_stage, failure=False):
    store = GuardedStore()
    entered, release = threading.Event(), threading.Event()
    calls = []
    image = tmp_path / "screen.png"
    image.write_bytes(b"synthetic image")
    row = {
        "candidate_key": "tashuo_visual_ada", "visible_name": "Ada", "latest_preview": "hello",
        "tap_ratio": {"x": 0.5, "y": 0.4}, "visual_anchor_hash": "0123456789abcdef",
        "visual_anchor_region": {"x1": 0.1, "y1": 0.3, "x2": 0.9, "y2": 0.5}, "confidence": "high",
    }

    def gui(action=None, **kwargs):
        assert store.held(), "navigation and capture must own the lifecycle lock"
        calls.append(action or "capture")
        return {"status": "ok", "screen": {"path": str(image)}}

    def analyze(stage, payload):
        if stage == blocked_stage and not release.is_set():
            entered.set()
            assert release.wait(5), "test did not release model analysis"
            if failure:
                raise RuntimeError("synthetic delayed model failure")
        return payload

    monkeypatch.setattr(standalone, "_analyze_tashuo_message_list_with_retry", lambda *a, **kw: analyze(
        "scan", {"status": "ok", "rows": [dict(row)]},
    ))
    monkeypatch.setattr(standalone, "_analyze_tashuo_conversation_with_retry", lambda *a, **kw: analyze(
        "thread", {
            "status": "ok", "identity": {"visible_name": "Ada", "visual_anchor_hash": "thread-anchor"},
            "visible_messages": [{"direction": "inbound", "text": "hello", "confidence": "high"}],
        },
    ))
    provider = standalone.TaShuoMacIosStandaloneObservationProvider(
        root=tmp_path / "data", output_dir=tmp_path / "harness", vision_backend=object(),
        adapter_factory=lambda: SimpleNamespace(run_action=gui, observe=gui),
    )
    published = []
    targets = {}

    def publish(target):
        assert store.held(), "target cache publication must own the lifecycle lock"
        targets[target["candidate_key"]] = {**target, "observed_at": datetime.now(timezone.utc).isoformat()}
        published.append(target["candidate_key"])

    provider.targets = SimpleNamespace(put=publish, get=targets.get)
    port = StandaloneObservationManagedRunPort(tmp_path / "data", provider, fixture_mode=False)
    ingested = []

    def ingest(payload):
        assert store.held(), "thread ingestion must follow lifecycle acceptance"
        ingested.append(payload)
        return "synthetic_match"

    port._ingest_for_planner = ingest
    decision = SimpleNamespace(
        prioritize=lambda candidates, **kw: next(iter(candidates), None),
        decide=lambda thread, **kw: DraftDecision("decision", "wait", thread.target_id, thread.inbound_revision),
    )
    runtime = ManagedRun(store, port, decision, object(), now=lambda: datetime.now(timezone.utc))
    config = ManagedRunConfig(
        app_id="tashuo", runtime="mac-ios-app",
        authorization=ManagedAuthorization(
            authorization_id="synthetic", app_id="tashuo", runtime="mac-ios-app", allow_all_targets=True,
            live_send=True,
        ),
    )
    assert runtime.start(config, run_id="test_run")["status"] == "active"
    return runtime, provider, entered, release, calls, published, ingested


@pytest.mark.parametrize("stage", ["scan", "thread"])
@pytest.mark.parametrize("operation", ["pause", "stop", "pause_resume"])
@pytest.mark.parametrize("failure", [False, True])
def test_lifecycle_changes_complete_during_analysis_and_discard_late_results(tmp_path, monkeypatch, stage, operation, failure):
    runtime, provider, entered, release, gui, published, ingested = _runtime(
        tmp_path, monkeypatch, blocked_stage=stage, failure=failure,
    )
    outcome, errors = [], []

    def tick():
        try:
            outcome.append(runtime.tick())
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=tick, daemon=True)
    worker.start()
    assert entered.wait(2), (outcome, errors)
    gui_before, published_before = list(gui), list(published)
    record_before = runtime.store.load("test_run")
    changed = threading.Event()

    def control():
        if operation == "stop":
            runtime.stop()
        else:
            runtime.pause()
            if operation == "pause_resume":
                runtime.resume()
        changed.set()

    controller = threading.Thread(target=control, daemon=True)
    controller.start()
    completed_while_model_blocked = changed.wait(0.5)
    record_after_control = runtime.store.load("test_run") if completed_while_model_blocked else None
    release.set()
    worker.join(3)
    controller.join(3)
    assert completed_while_model_blocked, "pause/stop waited for model analysis"
    assert not worker.is_alive() and not controller.is_alive()
    assert errors == []
    assert gui == gui_before
    assert published == published_before
    assert ingested == []
    latest = runtime.store.load("test_run")
    assert latest.to_dict() == record_after_control.to_dict(), "late analysis changed accepted lifecycle state"
    assert latest.cycle_count == record_before.cycle_count
    assert latest.scan_cursor == record_before.scan_cursor
    expected_status = "stopped" if operation == "stop" else "paused" if operation == "pause" else "blocked"
    assert outcome[0]["status"] == expected_status
    if operation == "pause_resume":
        assert outcome[0]["reason"] == "managed_run_lifecycle_changed"
        # Reusing the provider after a discarded generation must start fresh.
        next_result = runtime.tick()
        assert next_result["status"] == "wait", next_result
        assert len(ingested) == 1


@pytest.mark.parametrize("stage", ["scan", "thread"])
def test_capture_digest_rejects_replaced_pixels_before_analysis(tmp_path, monkeypatch, stage):
    image = tmp_path / "screen.png"
    image.write_bytes(b"original")
    provider = standalone.TaShuoMacIosStandaloneObservationProvider(
        root=tmp_path / "data", output_dir=tmp_path / "harness", vision_backend=Mock(),
        adapter_factory=lambda: SimpleNamespace(observe=lambda **kw: {"status": "ok", "screen": {"path": str(image)}}),
    )
    provider.precheck_payload = Mock(return_value={"status": "ok", "screen": {"path": str(image)}})
    if stage == "scan":
        capture = provider.capture_message_list(app_id="tashuo", scan_cursor={})
    else:
        capture = provider.capture_thread(app_id="tashuo", candidate_key="current_thread")
    image.write_bytes(b"replacement")
    result = provider.analyze_message_list(capture) if stage == "scan" else provider.analyze_thread(capture)
    assert result["status"] == "blocked"
    assert result["reason"] == ("tashuo_message_list_image_changed" if stage == "scan" else "tashuo_thread_image_changed")
    provider.vision_backend.analyze_image_structured.assert_not_called()
