from __future__ import annotations

import math
import os
import re
import shutil
import struct
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from dating_boost.core.live_send_contract import pre_send_time_block
from dating_boost.apps.tashuo.managed_composer_ax import guarded_stage, snapshot
from dating_boost.apps.tashuo.runtime_common import (
    _is_mac_ios_app_session,
    _tashuo_message_input_tap_ratio,
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.core.safety import SafetyRepository
from dating_boost.harness.base import WindowInfo


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reason(payload: Any, fallback: str) -> str:
    value = payload.get("reason") if isinstance(payload, dict) else None
    if isinstance(value, str) and len(value) <= 96 and re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value):
        return value
    return fallback


def _blocked(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "blocked", "reason": reason, **extra}


def _composer_top_ratio(before: Any, after: Any, window: WindowInfo, frame: Path) -> float | None:
    """Use only stable AX geometry corroborated by the actual captured window."""
    keys = ("composer_position", "composer_size", "window_position", "window_size")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    if before.get("status") != "ok" or after.get("status") != "ok":
        return None
    if before.get("frontmost") is not True or after.get("frontmost") is not True:
        return None
    process_pid = before.get("process_pid")
    if (
        type(process_pid) is not int or process_pid <= 0
        or after.get("process_pid") != process_pid or window.process_pid != process_pid
    ):
        return None
    try:
        for key in keys:
            pair = before.get(key)
            next_pair = after.get(key)
            if (
                not isinstance(pair, list) or len(pair) != 2
                or not isinstance(next_pair, list) or len(next_pair) != 2 or pair != next_pair
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in [*pair, *next_pair])
            ):
                return None
        cx, cy = before["composer_position"]
        cw, ch = before["composer_size"]
        wx, wy = before["window_position"]
        ww, wh = before["window_size"]
        if min(cw, ch, ww, wh) <= 0 or not (0 <= cx - wx <= ww - cw and 0 <= cy - wy <= wh - ch):
            return None
        if (window.x, window.y, window.width, window.height) != (wx, wy, ww, wh):
            return None
        with frame.open("rb") as source:
            header = source.read(24)
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[8:16] != b"\x00\x00\x00\rIHDR":
            return None
        width, height = struct.unpack(">II", header[16:24])
        # Native screencapture is either logical 1x or Retina 2x. Reject a
        # shadow border, resize, anisotropic scale, or guessed crop transform.
        if not any(
            abs(width - ww * scale) <= 0.5 and abs(height - wh * scale) <= 0.5
            for scale in (1, 2)
        ):
            return None
        ratio = (cy - wy) / wh
        return ratio if 0.5 < ratio < 0.98 else None
    except (AttributeError, OSError, OverflowError, TypeError, ValueError, struct.error):
        return None


def _window_from_snapshot(observed: dict[str, Any]) -> WindowInfo | None:
    process_pid = observed.get("process_pid")
    if type(process_pid) is not int or process_pid <= 0:
        return None
    position, size = observed.get("window_position"), observed.get("window_size")
    if not isinstance(position, list) or len(position) != 2 or not isinstance(size, list) or len(size) != 2:
        return None
    values = [*position, *size]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        return None
    # The shared capture seam binds this PID and geometry to a unique CG
    # window. Fractional geometry must not silently select another rectangle.
    if any(value != int(value) for value in values):
        return None
    x, y, width, height = (int(value) for value in values)
    if width <= 0 or height <= 0:
        return None
    return WindowInfo(
        frontmost=observed.get("frontmost") is True, x=x, y=y, width=width, height=height,
        name="她说", process_pid=process_pid,
    )


class TaShuoManagedVisualIO:
    """Small GUI seams; the caller owns visual identity and durable send gates.

    This class never plans messages, interprets screenshots, clears a composer,
    or retries Return. Capture timestamps precede all caller-side model work.
    """

    def __init__(self, root: Path, output_dir: Path, adapter_factory: Callable[[], Any]):
        self.root = root
        self.output_dir = output_dir.expanduser().resolve()
        self.adapter_factory = adapter_factory
        self.safety = SafetyRepository(root)
        self.runtime_scope = RuntimeScopeRepository(root)
        self._adapter: Any | None = None

    @property
    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = self.adapter_factory()
        return self._adapter

    def _runtime_block(self) -> dict[str, Any] | None:
        scope = self.runtime_scope.validate(app_id="tashuo", runtime="mac-ios-app")
        if scope is not None:
            return _blocked(_reason(scope, "runtime_scope_mismatch"))
        if not _is_mac_ios_app_session(self.adapter.session):
            return _blocked("managed_tashuo_requires_mac_ios_app")
        if getattr(self.adapter.session, "app_id", "tashuo") != "tashuo":
            return _blocked("runtime_scope_mismatch")
        return None

    def _mutation_block(self) -> dict[str, Any] | None:
        if self.safety.is_paused():
            return _blocked("global_safety_paused")
        return None

    def _guarded(self, operation: Callable[[], dict[str, Any]], fallback: str) -> dict[str, Any]:
        try:
            blocked = self._runtime_block()
            if blocked is not None:
                return blocked
            result = self.adapter._with_runtime_guard(operation)
            if not isinstance(result, dict):
                return _blocked(fallback)
            return result
        except Exception:  # noqa: BLE001 - no raw GUI/AX exception text leaves this seam.
            return _blocked(fallback)

    def _snapshot(self) -> dict[str, Any]:
        payload = snapshot(self.adapter.session)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return _blocked(_reason(payload, "managed_composer_snapshot_unavailable"))
        if (
            type(payload.get("frontmost")) is not bool or type(payload.get("focused")) is not bool
            or (payload.get("value") is not None and not isinstance(payload["value"], str))
        ):
            return _blocked("managed_composer_snapshot_unavailable")
        return payload

    def _foreground_snapshot(self, observed: dict[str, Any]) -> dict[str, Any]:
        if observed.get("status") != "ok" or observed.get("frontmost") is True:
            return observed
        blocked = self._mutation_block()
        if blocked is not None:
            return blocked
        activation = self.adapter.session._activate_window()
        if not isinstance(activation, dict) or activation.get("status") != "ok":
            return _blocked(_reason(activation, "managed_tashuo_activation_failed"))
        refreshed = self._snapshot()
        if refreshed.get("status") != "ok":
            return refreshed
        if refreshed.get("frontmost") is not True:
            return _blocked("managed_tashuo_not_frontmost")
        return refreshed

    def capture_initial_thread(self) -> dict[str, Any]:
        """Establish the focused viewport before the first visual interpretation.

        Opening the composer can dismiss a banner or move visible messages.
        Perform that layout change before the frame used for draft and binding,
        while ordinary capture remains a read-only, focus-free observation.
        """
        prepared = self.prepare_composer()
        if prepared.get("status") != "ok":
            return prepared
        if prepared.get("focus_performed") is True:
            time.sleep(0.2)
        return self.capture()

    def capture(self) -> dict[str, Any]:

        def operation() -> dict[str, Any]:
            blocked = self._mutation_block()
            if blocked is not None:
                return blocked
            self.output_dir.mkdir(parents=True, exist_ok=True)
            unique_id = uuid4().hex
            frame_id = "managed_visual_" + unique_id
            frame_path = self.output_dir / f"managed_visual.{unique_id}.png"
            # Capture the supplied fresh AX window directly. Running the full
            # observer here repeats doctor, activation and window discovery.
            with tempfile.TemporaryDirectory(prefix=".managed_visual_capture.", dir=self.output_dir) as temporary:
                before = self._foreground_snapshot(self._snapshot())
                if before.get("status") != "ok":
                    return before
                window = _window_from_snapshot(before)
                if window is None:
                    return _blocked("managed_tashuo_window_geometry_unavailable")
                blocked = self._mutation_block()
                if blocked is not None:
                    return blocked
                screen = self.adapter.session.capture_window(output=Path(temporary) / "capture.png", window=window, ocr=False)
                captured_at = _now_iso()
                if not isinstance(screen, dict) or screen.get("status") != "ok":
                    return _blocked(_reason(screen, "managed_visual_capture_failed"))
                source = screen.get("path")
                if not isinstance(source, str) or not source:
                    return _blocked("managed_visual_capture_path_missing")
                with Path(source).open("rb") as captured, open(
                    frame_path, "xb", opener=lambda path, flags: os.open(path, flags, 0o600),
                ) as immutable:
                    shutil.copyfileobj(captured, immutable)
                evidence = {"path": str(frame_path), "captured_at": captured_at, "frame_id": frame_id}
                state = screen.get("state")
                if state != "tashuo_conversation":
                    return _blocked(
                        "managed_visual_conversation_not_verified", **evidence,
                        observed_state=_reason({"reason": state}, "unknown"),
                    )
                try:
                    after = self._snapshot()
                except Exception:  # noqa: BLE001 - optional mask proof never loses the captured frame.
                    after = _blocked("managed_composer_snapshot_unavailable")
                composer_top_ratio = _composer_top_ratio(before, after, window, frame_path)
            return {
                "status": "ok", **evidence, "state": "tashuo_conversation",
                "composer_top_ratio": composer_top_ratio,
            }

        return self._guarded(operation, "managed_visual_capture_failed")

    @staticmethod
    def _composer_reading(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("status") != "ok":
            return _blocked(_reason(payload, "managed_composer_exact_text_unavailable"))
        if payload.get("value") is None:
            return _blocked("tashuo_ax_text_area_not_found")
        if not isinstance(payload.get("value"), str):
            return _blocked("managed_composer_exact_text_unavailable")
        return {"status": "ok", "value": payload["value"]}

    def read_composer(self) -> dict[str, Any]:
        return self._guarded(lambda: self._composer_reading(self._snapshot()), "managed_composer_exact_text_unavailable")

    @staticmethod
    def _composer_mismatch(payload: dict[str, Any], expected_text: str | None) -> dict[str, Any] | None:
        if payload.get("status") != "ok":
            return payload
        if expected_text is None and payload["value"] != "":
            return _blocked("candidate_composer_occupied")
        if expected_text is not None and payload["value"] != expected_text:
            return _blocked("managed_pre_click_composer_exact_mismatch")
        return None

    def prepare_composer(self, expected_text: str | None = None) -> dict[str, Any]:
        focus_performed = False

        def operation() -> dict[str, Any]:
            nonlocal focus_performed
            if expected_text is not None and not isinstance(expected_text, str):
                return _blocked("managed_expected_composer_text_invalid", focus_performed=False)
            blocked = self._mutation_block()
            if blocked is not None:
                return {**blocked, "focus_performed": False}
            before = self._snapshot()
            reading = self._composer_reading(before)
            missing = reading.get("reason") == "tashuo_ax_text_area_not_found"
            if not (missing and expected_text is None):
                mismatch = self._composer_mismatch(reading, expected_text)
                if mismatch is not None:
                    return {**mismatch, "focus_performed": False}
            if before.get("status") != "ok":
                return {**before, "focus_performed": False}
            if before["frontmost"] and before["focused"] and not missing:
                return {**reading, "focus_performed": False}
            before = self._foreground_snapshot(before)
            reading = self._composer_reading(before)
            missing = reading.get("reason") == "tashuo_ax_text_area_not_found"
            if not (missing and expected_text is None):
                mismatch = self._composer_mismatch(reading, expected_text)
                if mismatch is not None:
                    return {**mismatch, "focus_performed": False}
            if before.get("status") != "ok":
                return {**before, "focus_performed": False}
            if before["focused"] and not missing:
                return {**reading, "focus_performed": False}
            session = self.adapter.session
            window = _window_from_snapshot(before)
            if window is None:
                return _blocked("managed_tashuo_window_geometry_unavailable", focus_performed=False)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".managed_visual_focus.", dir=self.output_dir) as temporary:
                screen = session.capture_window(output=Path(temporary) / "focus.png", window=window, ocr=False)
            if not isinstance(screen, dict) or screen.get("status") != "ok" or screen.get("state") != "tashuo_conversation":
                return _blocked("managed_visual_conversation_not_verified", focus_performed=False)
            blocked = self._mutation_block()
            if blocked is not None:
                return {**blocked, "focus_performed": False}
            # A read-only missing field may be the collapsed native input bar.
            # Existing AX fields use the focused input geometry instead.
            focus_performed = True
            focus = session._click_ratio(window, _tashuo_message_input_tap_ratio(session, focused=not missing))
            if not isinstance(focus, dict) or focus.get("status") != "ok":
                return _blocked(_reason(focus, "managed_composer_focus_failed"), focus_performed=True)
            deadline = time.monotonic() + 0.6
            while True:
                after = self._snapshot()
                reading = self._composer_reading(after)
                remaining = deadline - time.monotonic()
                if reading.get("reason") != "tashuo_ax_text_area_not_found" or remaining <= 0:
                    mismatch = self._composer_mismatch(reading, expected_text)
                    if mismatch is not None:
                        return {**mismatch, "focus_performed": True}
                    if after.get("frontmost") is not True or after.get("focused") is not True:
                        return _blocked("managed_composer_focus_not_verified", focus_performed=True)
                    return {**reading, "focus_performed": True}
                time.sleep(min(0.1, remaining))

        result = self._guarded(operation, "managed_composer_prepare_failed")
        result.setdefault("focus_performed", focus_performed)
        return result

    def stage_text(self, text: str) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            if not isinstance(text, str) or not text:
                return _blocked("managed_stage_text_empty")
            blocked = self._mutation_block()
            if blocked is not None:
                return blocked
            staged = guarded_stage(self.adapter.session, text)
            captured_at = _now_iso()
            if not isinstance(staged, dict) or staged.get("status") != "ok":
                return _blocked(_reason(staged, "managed_stage_failed"))
            if staged.get("staged_exact_text_ax_verified") is not True:
                return _blocked("managed_stage_exact_text_not_verified")
            return {"status": "ok", "staged_exact_text_verified": True, "captured_at": captured_at}

        return self._guarded(operation, "managed_stage_failed")

    def click_return(self, expected_text: str, *, deadline_at: str | None = None) -> dict[str, Any]:
        invoked = False
        receipt_id = "tashuo_visual_click_" + uuid4().hex

        def operation() -> dict[str, Any]:
            nonlocal invoked
            if not isinstance(expected_text, str) or not expected_text:
                return _blocked("managed_click_expected_text_empty")
            observed = self._snapshot()
            mismatch = self._composer_mismatch(self._composer_reading(observed), expected_text)
            if mismatch is not None:
                return mismatch
            if observed.get("frontmost") is not True:
                return _blocked("managed_tashuo_not_frontmost")
            if observed.get("focused") is not True:
                return _blocked("managed_composer_focus_not_verified")
            blocked = self._mutation_block()
            if blocked is not None:
                return blocked
            if deadline_at is not None:
                try:
                    deadline = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
                    if deadline.tzinfo is None:
                        raise ValueError("timezone required")
                    expired = datetime.fromisoformat(_now_iso().replace("Z", "+00:00")) >= deadline
                except (AttributeError, TypeError, ValueError):
                    return _blocked("managed_burst_continuation_deadline_invalid")
                if expired:
                    return _blocked("managed_burst_continuation_expired")
            if time_block := pre_send_time_block():
                return time_block
            invoked = True
            result = self.adapter.session._press_return_key()
            clicked_at = _now_iso()
            if not isinstance(result, dict) or result.get("status") != "ok":
                return {"status": "unknown", "reason": "managed_return_result_unknown", "receipt_id": receipt_id, "clicked_at": clicked_at}
            return {"status": "ok", "receipt_id": receipt_id, "clicked_at": clicked_at}

        try:
            blocked = self._runtime_block()
            if blocked is not None:
                return blocked
            result = self.adapter._with_runtime_guard(operation)
            if not isinstance(result, dict):
                raise ValueError("invalid guarded action result")
            return result
        except Exception:  # noqa: BLE001 - never retry an attempted irreversible action.
            if invoked:
                return {"status": "unknown", "reason": "managed_return_result_unknown", "receipt_id": receipt_id}
            return _blocked("managed_click_precondition_failed")
