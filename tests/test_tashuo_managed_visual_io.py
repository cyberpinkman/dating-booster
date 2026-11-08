from __future__ import annotations

import os
import stat
import struct
import zlib
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo import managed_visual_io as module
from dating_boost.apps.tashuo.managed_visual_io import TaShuoManagedVisualIO
from dating_boost.core.managed_run import ManagedClickBlocked
from tests.test_managed_run import _config, _runtime


pytestmark = pytest.mark.managed_critical


def _snapshot(value="", *, focused=True, frontmost=True):
    return {
        "status": "ok", "value": value, "focused": focused, "frontmost": frontmost,
        "composer_position": [-90.0, 520.0] if value is not None else None,
        "composer_size": [160.0, 50.0] if value is not None else None,
        "window_position": [-100.0, 200.0], "window_size": [200.0, 400.0],
        "process_pid": 1234,
    }


def _png(path, width=200, height=400):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = (b"\x00" + b"\x00\x00\x00" * width) * height
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


class Adapter:
    def __init__(self):
        self.guarded = False
        self.guard_calls = 0
        self.frame_count = 0
        self.session = SimpleNamespace(
            app_id="tashuo", harness_backend="mac_ios_app",
            doctor=Mock(), _window_info=Mock(),
            _activate_window=Mock(return_value={"status": "ok"}),
            _click_ratio=Mock(return_value={"status": "ok"}),
            _press_return_key=Mock(return_value={"status": "ok"}),
            capture_window=Mock(side_effect=self.capture_window),
        )

    def _with_runtime_guard(self, operation):
        assert not self.guarded, "The real runtime guard is not reentrant."
        self.guard_calls += 1
        self.guarded = True
        try:
            return operation()
        finally:
            self.guarded = False

    def capture_window(self, *, output, window, ocr):
        assert self.guarded
        assert ocr is False
        assert (window.x, window.y, window.width, window.height) == (-100, 200, 200, 400)
        self.frame_count += 1
        output.write_bytes(f"frame {self.frame_count}".encode())
        return {"status": "ok", "state": "tashuo_conversation", "path": str(output)}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    adapter = Adapter()
    io = TaShuoManagedVisualIO(tmp_path / "data", tmp_path / "frames", lambda: adapter)
    io.runtime_scope.validate = Mock(return_value=None)
    io.safety.is_paused = Mock(return_value=False)
    read = Mock(return_value=_snapshot())
    stage = Mock(return_value={"status": "ok", "staged_exact_text_ax_verified": True})
    monkeypatch.setattr(module, "snapshot", read)
    monkeypatch.setattr(module, "guarded_stage", stage)
    return io, adapter, read, stage, adapter.session.capture_window


def test_persistent_conversation_frame_is_owner_only_with_a_permissive_umask(setup):
    io, *_ = setup
    original = os.umask(0)
    try:
        result = io.capture()
    finally:
        os.umask(original)
    assert result["status"] == "ok"
    assert stat.S_IMODE(Path(result["path"]).stat().st_mode) == 0o600


def test_capture_preserves_history_and_avoids_doctor_activation_and_window_rediscovery(setup, monkeypatch):
    io, adapter, read, _, capture = setup
    timestamps = iter(["2026-09-20T00:00:01Z", "2026-09-20T00:00:02Z"])
    monkeypatch.setattr(module, "_now_iso", lambda: next(timestamps))
    first, second = io.capture(), io.capture()
    assert first["status"] == second["status"] == "ok"
    assert first["path"] != second["path"]
    assert first["frame_id"] != second["frame_id"]
    assert first["captured_at"] == "2026-09-20T00:00:01Z"
    assert second["captured_at"] == "2026-09-20T00:00:02Z"
    assert Path(first["path"]).is_absolute()
    assert Path(first["path"]).name.startswith("managed_visual.")
    assert Path(first["path"]).read_bytes() == b"frame 1"
    assert Path(second["path"]).read_bytes() == b"frame 2"
    assert first["composer_top_ratio"] is None
    assert adapter.guard_calls == 2
    assert read.call_count == 4
    assert capture.call_count == 2
    assert capture.call_args.kwargs["window"].process_pid == 1234
    adapter.session.doctor.assert_not_called()
    adapter.session._activate_window.assert_not_called()
    adapter.session._window_info.assert_not_called()


@pytest.mark.parametrize("pid", [None, True, 0, -1, "1234", 1234.0])
def test_capture_requires_observed_process_identity_before_capturing(setup, pid):
    io, _, read, _, capture = setup
    read.return_value = {**_snapshot(), "process_pid": pid}
    assert io.capture()["reason"] == "managed_tashuo_window_geometry_unavailable"
    capture.assert_not_called()


def test_capture_activates_only_background_app_and_uses_refreshed_snapshot(setup):
    io, adapter, read, _, capture = setup
    read.side_effect = [_snapshot(frontmost=False), _snapshot(), _snapshot()]
    assert io.capture()["status"] == "ok"
    adapter.session._activate_window.assert_called_once_with()
    assert read.call_count == 3
    assert capture.call_args.kwargs["window"].frontmost is True
    adapter.session.doctor.assert_not_called()
    adapter.session._window_info.assert_not_called()


@pytest.mark.parametrize("state", ["tashuo_message_list", "unknown", "PRIVATE name and text"])
def test_capture_preserves_rejected_page_frame_without_treating_it_as_verified(setup, state):
    io, adapter, _, _, capture = setup

    def wrong_page(**kwargs):
        return {**adapter.capture_window(**kwargs), "state": state}

    capture.side_effect = wrong_page
    result = io.capture()
    assert result["status"] == "blocked"
    assert result["reason"] == "managed_visual_conversation_not_verified"
    assert result["observed_state"] == (state if state != "PRIVATE name and text" else "unknown")
    assert "state" not in result
    assert result["frame_id"] and result["captured_at"]
    assert Path(result["path"]).read_bytes() == b"frame 1"
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize("screen", [None, {"status": "blocked"}, {"status": "ok", "state": "tashuo_conversation"}])
def test_capture_rejects_missing_image_evidence(setup, screen):
    io, _, _, _, capture = setup
    capture.side_effect = None
    capture.return_value = screen
    assert io.capture()["status"] == "blocked"


def _geometry_capture(setup, monkeypatch, *, before=None, after=None, dimensions=(200, 400)):
    io, adapter, read, _, capture = setup
    events = []
    readings = iter([before if before is not None else _snapshot(), after if after is not None else _snapshot()])

    def observed(session):
        assert adapter.guarded
        events.append("snapshot")
        value = next(readings)
        if isinstance(value, Exception):
            raise value
        return value

    def frame(*, output, window, ocr):
        assert adapter.guarded and ocr is False
        events.append("capture")
        _png(output, *dimensions)
        return {"status": "ok", "state": "tashuo_conversation", "path": str(output)}

    def clock():
        assert adapter.guarded
        events.append("timestamp")
        return "2026-09-20T00:00:01Z"

    read.side_effect = observed
    capture.side_effect = frame
    monkeypatch.setattr(module, "_now_iso", clock)
    result = io.capture()
    assert events == ["snapshot", "capture", "timestamp", "snapshot"]
    assert adapter.guard_calls == 1
    assert result["status"] == "ok"
    return result


@pytest.mark.parametrize("scale", [1, 2])
def test_capture_mask_requires_stable_geometry_and_matching_png(setup, monkeypatch, scale):
    result = _geometry_capture(setup, monkeypatch, dimensions=(200 * scale, 400 * scale))
    assert result["composer_top_ratio"] == 0.8
    assert result["captured_at"] == "2026-09-20T00:00:01Z"


@pytest.mark.parametrize("field", ["composer_position", "composer_size", "window_position", "window_size"])
def test_capture_never_masks_when_geometry_changes(setup, monkeypatch, field):
    after = _snapshot()
    after[field][0] += 1.0
    assert _geometry_capture(setup, monkeypatch, after=after)["composer_top_ratio"] is None


@pytest.mark.parametrize("dimensions", [(400, 400), (200, 800), (300, 600), (201, 400), (400, 799), (440, 840)])
def test_capture_never_guesses_retina_scale_shadow_border_or_resized_image(setup, monkeypatch, dimensions):
    assert _geometry_capture(setup, monkeypatch, dimensions=dimensions)["composer_top_ratio"] is None


@pytest.mark.parametrize("after", [{"status": "blocked", "reason": "managed_ax_unavailable"}, RuntimeError("PRIVATE"), {"status": "ok"}, _snapshot(frontmost=False)])
def test_uncertain_post_capture_snapshot_keeps_full_frame_without_mask(setup, monkeypatch, after):
    result = _geometry_capture(setup, monkeypatch, after=after)
    assert result["composer_top_ratio"] is None
    assert "PRIVATE" not in str(result)


def test_capture_missing_composer_still_has_window_and_never_guesses_mask(setup, monkeypatch):
    result = _geometry_capture(setup, monkeypatch, before=_snapshot(None, focused=False), after=_snapshot(None, focused=False))
    assert result["composer_top_ratio"] is None


@pytest.mark.parametrize("ratio", [0.0, 0.5, 0.98, 1.0])
def test_composer_boundary_outside_supported_region_never_masks_chat(setup, monkeypatch, ratio):
    geometry = _snapshot()
    geometry["composer_position"][1] = 200.0 + 400.0 * ratio
    geometry["composer_size"][1] = 1.0
    assert _geometry_capture(setup, monkeypatch, before=geometry, after=deepcopy(geometry))["composer_top_ratio"] is None


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), True, "200", 0, -1])
def test_invalid_window_geometry_blocks_before_screenshot(setup, invalid):
    io, _, read, _, capture = setup
    observed = _snapshot()
    observed["window_size"][0] = invalid
    read.return_value = observed
    assert io.capture()["reason"] == "managed_tashuo_window_geometry_unavailable"
    capture.assert_not_called()


def test_runtime_guard_rejection_prevents_snapshot_and_capture(setup):
    io, adapter, read, _, capture = setup
    adapter._with_runtime_guard = lambda operation: {"status": "blocked", "reason": "runtime_busy"}
    assert io.capture() == {"status": "blocked", "reason": "runtime_busy"}
    read.assert_not_called()
    capture.assert_not_called()


def test_read_composer_preserves_exact_value_and_uses_one_guarded_snapshot(setup):
    io, adapter, read, *_ = setup
    text = "原文  \n"

    def observed(session):
        assert adapter.guarded
        return _snapshot(text)

    read.side_effect = observed
    assert io.read_composer() == {"status": "ok", "value": text}
    read.assert_called_once()


@pytest.mark.parametrize("expected", [None, "expected"])
def test_prepare_already_focused_needs_only_one_fresh_snapshot(setup, expected):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot(expected or "")
    assert io.prepare_composer(expected) == {"status": "ok", "value": expected or "", "focus_performed": False}
    read.assert_called_once()
    capture.assert_not_called()
    adapter.session._activate_window.assert_not_called()
    adapter.session._window_info.assert_not_called()
    adapter.session._click_ratio.assert_not_called()
    stage.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
def test_prepare_expands_or_focuses_without_writing_or_return(setup, missing):
    io, adapter, read, stage, capture = setup
    read.side_effect = [_snapshot(None if missing else "", focused=False), _snapshot()]
    result = io.prepare_composer()
    assert result == {"status": "ok", "value": "", "focus_performed": True}
    assert adapter.session._click_ratio.call_args.args[1] == {"x": 0.32, "y": 0.91 if missing else 0.90}
    assert capture.call_args.kwargs["ocr"] is False
    assert read.call_count == 2
    adapter.session._window_info.assert_not_called()
    adapter.session._activate_window.assert_not_called()
    stage.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


@pytest.mark.parametrize("value", ["draft", " ", "\n"])
def test_prepare_never_touches_existing_user_draft(setup, value):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot(value, focused=False, frontmost=False)
    assert io.prepare_composer() == {"status": "blocked", "reason": "candidate_composer_occupied", "focus_performed": False}
    adapter.session._click_ratio.assert_not_called()
    adapter.session._activate_window.assert_not_called()
    capture.assert_not_called()
    stage.assert_not_called()


@pytest.mark.parametrize("value", ["wrong", None])
def test_prepare_expected_text_never_repairs_missing_or_wrong_input(setup, value):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot(value, focused=False)
    assert io.prepare_composer("expected")["status"] == "blocked"
    adapter.session._click_ratio.assert_not_called()
    capture.assert_not_called()
    stage.assert_not_called()


@pytest.mark.parametrize("expected", [None, "expected"])
def test_prepare_refocus_checks_exact_value_without_overwriting_racing_draft(setup, expected):
    io, adapter, read, stage, _ = setup
    read.side_effect = [_snapshot(expected or "", focused=False), _snapshot("user changed it")]
    result = io.prepare_composer(expected)
    assert result["status"] == "blocked"
    assert result["focus_performed"] is True
    stage.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


def test_prepare_rechecks_value_after_activation_without_clearing_new_draft(setup):
    io, adapter, read, stage, capture = setup
    read.side_effect = [_snapshot(frontmost=False, focused=False), _snapshot("new user draft")]
    assert io.prepare_composer()["reason"] == "candidate_composer_occupied"
    adapter.session._activate_window.assert_called_once()
    adapter.session._click_ratio.assert_not_called()
    stage.assert_not_called()
    capture.assert_not_called()


def test_prepare_waits_at_most_six_tenths_for_ax_and_never_retries_focus(setup, monkeypatch):
    io, adapter, read, *_ = setup
    read.return_value = _snapshot(None, focused=False)
    now = [0.0]
    sleeps = []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(module.time, "sleep", sleep)
    assert io.prepare_composer()["reason"] == "tashuo_ax_text_area_not_found"
    assert sum(sleeps) <= 0.6
    assert adapter.session._click_ratio.call_count == 1


def test_prepare_requires_conversation_evidence_before_focus(setup):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot(focused=False)
    capture.side_effect = None
    capture.return_value = {"status": "ok", "state": "tashuo_question_gate"}
    assert io.prepare_composer()["reason"] == "managed_visual_conversation_not_verified"
    adapter.session._click_ratio.assert_not_called()
    stage.assert_not_called()


def test_prepare_focus_exception_reports_attempt_without_private_error(setup):
    io, adapter, read, stage, _ = setup
    read.return_value = _snapshot(focused=False)
    adapter.session._click_ratio.side_effect = RuntimeError("PRIVATE")
    assert io.prepare_composer() == {"status": "blocked", "reason": "managed_composer_prepare_failed", "focus_performed": True}
    stage.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


def test_stage_one_atomic_ax_set_returns_actual_completion_timestamp(setup, monkeypatch):
    io, adapter, read, stage, capture = setup
    events = []

    def setter(session, text):
        assert adapter.guarded and text == "expected"
        events.append("atomic_stage")
        return {"status": "ok", "staged_exact_text_ax_verified": True, "value": "expected"}

    def now():
        events.append("timestamp")
        return "2026-09-20T00:00:01Z"

    stage.side_effect = setter
    monkeypatch.setattr(module, "_now_iso", now)
    assert io.stage_text("expected") == {"status": "ok", "staged_exact_text_verified": True, "captured_at": "2026-09-20T00:00:01Z"}
    assert events == ["atomic_stage", "timestamp"]
    stage.assert_called_once()
    read.assert_not_called()
    capture.assert_not_called()
    adapter.session._click_ratio.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


@pytest.mark.parametrize("payload,reason", [({"status": "blocked", "reason": "candidate_composer_occupied"}, "candidate_composer_occupied"), ({"status": "ok"}, "managed_stage_exact_text_not_verified")])
def test_stage_requires_atomic_exact_proof_and_never_retries(setup, payload, reason):
    io, _, _, stage, _ = setup
    stage.return_value = payload
    assert io.stage_text("expected")["reason"] == reason
    assert stage.call_count == 1


@pytest.mark.parametrize("operation", ["prepare", "stage", "click", "capture"])
def test_global_pause_blocks_mutations(setup, operation):
    io, adapter, read, stage, _ = setup
    io.safety.is_paused.return_value = True
    read.return_value = _snapshot("expected")
    result = {"prepare": lambda: io.prepare_composer("expected"), "stage": lambda: io.stage_text("expected"), "click": lambda: io.click_return("expected"), "capture": io.capture}[operation]()
    assert result["reason"] == "global_safety_paused"
    adapter.session._click_ratio.assert_not_called()
    adapter.session._activate_window.assert_not_called()
    adapter.session._press_return_key.assert_not_called()
    stage.assert_not_called()


def test_pause_arriving_during_prepare_capture_blocks_focus(setup):
    io, adapter, read, *_ = setup
    read.return_value = _snapshot(focused=False)
    io.safety.is_paused.side_effect = [False, True]
    assert io.prepare_composer()["reason"] == "global_safety_paused"
    adapter.session._click_ratio.assert_not_called()


@pytest.mark.parametrize("value", ["", "wrong", "expected\n"])
def test_return_requires_fresh_exact_readback(setup, value):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot(value)
    assert io.click_return("expected")["reason"] == "managed_pre_click_composer_exact_mismatch"
    adapter.session._press_return_key.assert_not_called()
    adapter.session._click_ratio.assert_not_called()
    stage.assert_not_called()
    capture.assert_not_called()


@pytest.mark.parametrize("field,reason", [("frontmost", "managed_tashuo_not_frontmost"), ("focused", "managed_composer_focus_not_verified")])
def test_return_never_activates_or_refocuses_when_fresh_focus_proof_is_missing(setup, field, reason):
    io, adapter, read, *_ = setup
    read.return_value = {**_snapshot("expected"), field: False}
    assert io.click_return("expected") == {"status": "blocked", "reason": reason}
    adapter.session._press_return_key.assert_not_called()
    adapter.session._click_ratio.assert_not_called()
    adapter.session._activate_window.assert_not_called()


@pytest.mark.parametrize("deadline,reason", [("2026-09-20T00:00:01Z", "managed_burst_continuation_expired"), ("bad", "managed_burst_continuation_deadline_invalid"), ("2026-09-20T00:00:05", "managed_burst_continuation_deadline_invalid"), (123, "managed_burst_continuation_deadline_invalid")])
def test_return_checks_deadline_before_irreversible_action(setup, monkeypatch, deadline, reason):
    io, adapter, read, *_ = setup
    read.return_value = _snapshot("expected")
    monkeypatch.setattr(module, "_now_iso", lambda: "2026-09-20T00:00:01Z")
    assert io.click_return("expected", deadline_at=deadline) == {"status": "blocked", "reason": reason}
    adapter.session._press_return_key.assert_not_called()


def test_run_rechecks_quiet_hours_after_slow_gui_preflight_before_return(setup, monkeypatch):
    io, adapter, read, *_ = setup
    runtime, store, _, _, action, clock = _runtime()
    quiet_start = clock.value + timedelta(minutes=1)
    window = f"{quiet_start.astimezone():%H:%M}-{(quiet_start + timedelta(hours=1)).astimezone():%H:%M}"
    runtime.start(_config(quiet_hours=(window,)), run_id="timing")

    def slow_snapshot(*args, **kwargs):
        clock.value = quiet_start
        return _snapshot(action.composer_text)

    original_click = action.click_send

    def click(candidate):
        result = io.click_return(action.composer_text)
        if result["status"] == "blocked":
            raise ManagedClickBlocked(result["reason"])
        return original_click(candidate)

    read.side_effect = slow_snapshot
    monkeypatch.setattr(action, "click_send", click)
    result = runtime.tick("timing")
    adapter.session._press_return_key.assert_not_called()
    assert result["action_reason"] == "authorization_quiet_hours"
    assert store.load("timing").attempted_send_count == 0


@pytest.mark.parametrize("boundary", ["authorization", "duration"])
def test_return_rechecks_the_full_send_window_after_ax_latency(setup, monkeypatch, boundary):
    io, adapter, read, *_ = setup
    runtime, store, _, _, action, clock = _runtime()
    expiry = clock.value + timedelta(minutes=1)
    config = _config(duration_minutes=1 if boundary == "duration" else 120)
    if boundary == "authorization":
        config = replace(config, authorization=replace(config.authorization, expires_at=expiry.isoformat()))
    runtime.start(config, run_id="timing")

    def slow_snapshot(*args, **kwargs):
        clock.value = expiry
        return _snapshot(action.composer_text)

    def click(candidate):
        result = io.click_return(action.composer_text)
        if result["status"] == "blocked":
            raise ManagedClickBlocked(result["reason"])
        raise AssertionError("Return crossed an expired window")

    read.side_effect = slow_snapshot
    monkeypatch.setattr(action, "click_send", click)
    result = runtime.tick("timing")
    adapter.session._press_return_key.assert_not_called()
    assert result["action_reason"] == {"authorization": "authorization_expired", "duration": "managed_run_duration_elapsed"}[boundary]
    assert store.load("timing").attempted_send_count == 0


def test_return_is_once_without_focus_capture_stage_or_retry(setup, monkeypatch):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot("expected")
    monkeypatch.setattr(module, "_now_iso", lambda: "2026-09-20T00:00:01Z")
    result = io.click_return("expected", deadline_at="2026-09-20T00:00:02Z")
    assert result["status"] == "ok"
    assert result["receipt_id"]
    assert result["clicked_at"] == "2026-09-20T00:00:01Z"
    read.assert_called_once()
    assert adapter.session._press_return_key.call_count == 1
    adapter.session._click_ratio.assert_not_called()
    stage.assert_not_called()
    capture.assert_not_called()


@pytest.mark.parametrize("failure", ["return_exception", "return_non_ok", "guard_release_exception"])
def test_every_uncertainty_after_return_is_unknown_and_never_retried(setup, failure):
    io, adapter, read, *_ = setup
    read.return_value = _snapshot("expected")
    if failure == "return_exception":
        adapter.session._press_return_key.side_effect = RuntimeError("PRIVATE")
    elif failure == "return_non_ok":
        adapter.session._press_return_key.return_value = {"status": "blocked", "reason": "PRIVATE"}
    else:
        original = adapter._with_runtime_guard

        def released(operation):
            original(operation)
            raise RuntimeError("PRIVATE")

        adapter._with_runtime_guard = released
    result = io.click_return("expected")
    assert result["status"] == "unknown"
    assert result["reason"] == "managed_return_result_unknown"
    assert "PRIVATE" not in str(result)
    assert adapter.session._press_return_key.call_count == 1


def test_exception_before_return_is_blocked_and_redacted(setup):
    io, adapter, read, *_ = setup
    read.side_effect = RuntimeError("PRIVATE")
    assert io.click_return("expected") == {"status": "blocked", "reason": "managed_click_precondition_failed"}
    adapter.session._press_return_key.assert_not_called()


@pytest.mark.parametrize("operation", ["capture", "read", "prepare", "stage", "click"])
def test_wrong_runtime_blocks_all_gui_operations(setup, operation):
    io, adapter, read, stage, capture = setup
    adapter.session.harness_backend = "iphone_mirroring_macos"
    result = {"capture": io.capture, "read": io.read_composer, "prepare": io.prepare_composer, "stage": lambda: io.stage_text("expected"), "click": lambda: io.click_return("expected")}[operation]()
    assert result["reason"] == "managed_tashuo_requires_mac_ios_app"
    assert adapter.guard_calls == 0
    read.assert_not_called()
    stage.assert_not_called()
    capture.assert_not_called()


def test_selected_scope_mismatch_is_not_silently_switched(setup):
    io, adapter, *_ = setup
    io.runtime_scope.validate.return_value = {"status": "blocked", "reason": "runtime_scope_mismatch"}
    assert io.read_composer()["reason"] == "runtime_scope_mismatch"
    assert adapter.guard_calls == 0


def test_initial_thread_prepare_failure_never_produces_baseline_or_writes(setup, monkeypatch):
    io, adapter, _, stage, capture = setup
    failure = {"status": "blocked", "reason": "candidate_composer_occupied", "focus_performed": False}
    io.prepare_composer = Mock(return_value=failure)
    io.capture = Mock(side_effect=AssertionError("no baseline after failed preparation"))
    sleep = Mock()
    monkeypatch.setattr(module.time, "sleep", sleep)
    assert io.capture_initial_thread() is failure
    io.capture.assert_not_called()
    stage.assert_not_called()
    capture.assert_not_called()
    sleep.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


@pytest.mark.parametrize("focus_performed", [False, True])
def test_initial_thread_returns_the_exact_post_preparation_frame(setup, monkeypatch, focus_performed):
    io, _, _, _, _ = setup
    events = []
    frame = {"status": "ok", "path": "/fixture/focused.png", "frame_id": "focused-frame", "captured_at": "2026-09-20T00:00:01Z", "state": "tashuo_conversation"}
    def prepare():
        events.append("prepare")
        return {"status": "ok", "value": "", "focus_performed": focus_performed}
    def capture():
        events.append("capture")
        return frame
    def sleep(seconds):
        events.append(("settle", seconds))
    io.prepare_composer = prepare
    io.capture = capture
    monkeypatch.setattr(module.time, "sleep", sleep)
    assert io.capture_initial_thread() is frame
    assert events == (["prepare", ("settle", 0.2), "capture"] if focus_performed else ["prepare", "capture"])


def test_initial_thread_expands_composer_before_capturing_interpreted_frame(setup, monkeypatch):
    io, adapter, read, stage, capture = setup
    read.side_effect = [_snapshot(None, focused=False), _snapshot(), _snapshot(), _snapshot()]
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    result = io.capture_initial_thread()
    assert result["status"] == "ok"
    assert Path(result["path"]).read_bytes() == b"frame 2"
    assert capture.call_count == 2  # Existing pre-focus page proof, then focused baseline.
    adapter.session._click_ratio.assert_called_once()
    stage.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


def test_initial_thread_preserves_existing_draft_without_capture_or_focus(setup):
    io, adapter, read, stage, capture = setup
    read.return_value = _snapshot("user draft", focused=False)
    assert io.capture_initial_thread()["reason"] == "candidate_composer_occupied"
    capture.assert_not_called()
    stage.assert_not_called()
    adapter.session._click_ratio.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


def test_initial_thread_pause_during_settle_blocks_baseline_capture(setup, monkeypatch):
    io, adapter, _, stage, capture = setup
    io.prepare_composer = Mock(return_value={"status": "ok", "value": "", "focus_performed": True})
    def pause(seconds):
        io.safety.is_paused.return_value = True
    monkeypatch.setattr(module.time, "sleep", pause)
    assert io.capture_initial_thread()["reason"] == "global_safety_paused"
    capture.assert_not_called()
    stage.assert_not_called()
    adapter.session._press_return_key.assert_not_called()


def test_ordinary_capture_never_repeats_initial_composer_preparation(setup, monkeypatch):
    io, adapter, read, stage, _ = setup
    read.return_value = _snapshot(focused=False)
    io.prepare_composer = Mock(side_effect=AssertionError("ordinary capture must not focus"))
    sleep = Mock()
    monkeypatch.setattr(module.time, "sleep", sleep)
    assert io.capture()["status"] == "ok"
    io.prepare_composer.assert_not_called()
    adapter.session._click_ratio.assert_not_called()
    stage.assert_not_called()
    sleep.assert_not_called()
