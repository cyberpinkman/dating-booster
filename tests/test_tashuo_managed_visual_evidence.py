from __future__ import annotations

import struct
import zlib
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo.managed_visual_evidence import (
    ManagedVisualVerifier,
    VisualFrame,
    same_body,
)


pytestmark = pytest.mark.managed_critical


def _png(*, width=4, height=8, changed_row=None) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = [b"\x00" + bytes([1 if y == changed_row else 0] * width * 3) for y in range(height)]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _payload(tmp_path, name="before", *, second=1, png=None, **changes):
    path = tmp_path / f"{name}.png"
    path.write_bytes(png if png is not None else _png())
    return {
        "status": "ok", "path": str(path), "frame_id": name,
        "captured_at": f"2026-09-20T10:00:{second:02d}+08:00",
        "state": "tashuo_conversation", **changes,
    }


def _frames(tmp_path):
    return (
        VisualFrame.from_payload(_payload(tmp_path)),
        VisualFrame.from_payload(_payload(tmp_path, "after", second=2)),
    )


def _transition(**changes):
    return {
        "same_conversation": True, "baseline_messages_preserved": True,
        "added_bubbles": [], "other_conversation_change": False,
        "composer_state": "empty", "composer_text": "", "confidence": "high", **changes,
    }


def _bubble(text="reply", *, direction="outbound", kind="text"):
    return {"direction": direction, "text": text, "kind": kind}


def _compare(tmp_path, payload):
    backend = Mock()
    backend.analyze_images_structured.return_value = deepcopy(payload)
    return ManagedVisualVerifier(backend).compare(*_frames(tmp_path))


def test_frame_is_frozen_and_body_comparison_includes_content_below_matching_title(tmp_path):
    before, identical = _frames(tmp_path)
    assert same_body(before, identical)
    assert before.file_digest == identical.file_digest
    with pytest.raises(FrozenInstanceError):
        before.frame_id = "replacement"

    changed = VisualFrame.from_payload(_payload(tmp_path, "changed", second=3, png=_png(changed_row=6)))
    assert not same_body(before, changed)


def test_ax_composer_boundary_excludes_only_composer_and_requires_matching_geometry(tmp_path):
    before = VisualFrame.from_payload(_payload(tmp_path, composer_top_ratio=0.75))
    changed_composer = VisualFrame.from_payload(_payload(
        tmp_path, "composer", second=2, png=_png(changed_row=6), composer_top_ratio=0.75,
    ))
    changed_last_body_row = VisualFrame.from_payload(_payload(
        tmp_path, "body", second=3, png=_png(changed_row=5), composer_top_ratio=0.75,
    ))
    changed_boundary = VisualFrame.from_payload(_payload(tmp_path, "boundary", second=4, composer_top_ratio=0.8))
    changed_size = VisualFrame.from_payload(_payload(
        tmp_path, "size", second=5, png=_png(width=5), composer_top_ratio=0.75,
    ))
    assert same_body(before, changed_composer)
    assert not same_body(before, changed_last_body_row)
    assert not same_body(before, changed_boundary)
    assert not same_body(before, changed_size)


@pytest.mark.parametrize("boundary", [None, True, "0.75", 0, 1, -0.1, float("nan"), float("inf")])
def test_unknown_or_invalid_composer_geometry_compares_entire_image(tmp_path, boundary):
    before = VisualFrame.from_payload(_payload(tmp_path, composer_top_ratio=boundary))
    after = VisualFrame.from_payload(_payload(
        tmp_path, "after", second=2, png=_png(changed_row=7), composer_top_ratio=boundary,
    ))
    assert before.composer_top_ratio is None
    assert not same_body(before, after)


@pytest.mark.parametrize("changes,reason", [
    ({"status": "blocked"}, "managed_visual_frame_unavailable"),
    ({"frame_id": ""}, "managed_visual_frame_identity_invalid"),
    ({"path": ""}, "managed_visual_frame_identity_invalid"),
    ({"captured_at": "2026-09-20T10:00:00"}, "managed_visual_frame_time_invalid"),
    ({"captured_at": "not-a-time"}, "managed_visual_frame_time_invalid"),
    ({"captured_at": 42}, "managed_visual_frame_time_invalid"),
    ({"state": "tashuo_message_list"}, "managed_visual_frame_not_conversation"),
])
def test_frame_rejects_missing_capture_evidence(tmp_path, changes, reason):
    with pytest.raises(ValueError, match=f"^{reason}$"):
        VisualFrame.from_payload(_payload(tmp_path, **changes))


def test_invalid_png_and_missing_file_have_fixed_errors(tmp_path):
    with pytest.raises(ValueError, match="^managed_visual_frame_png_invalid$"):
        VisualFrame.from_payload(_payload(tmp_path, png=b"private non-image content"))
    payload = _payload(tmp_path)
    Path(payload["path"]).unlink()
    with pytest.raises(ValueError, match="^managed_visual_frame_unreadable$"):
        VisualFrame.from_payload(payload)


@pytest.mark.parametrize("kind", ["frame_id", "path", "equal_time", "older_time"])
def test_frame_pair_rejects_reused_or_nonfresh_captures_before_model_call(tmp_path, kind):
    before_payload = _payload(tmp_path)
    after_payload = _payload(tmp_path, "after", second=2)
    if kind in {"frame_id", "path"}:
        after_payload[kind] = before_payload[kind]
    else:
        after_payload["captured_at"] = "2026-09-20T10:00:01+08:00" if kind == "equal_time" else "2026-09-20T01:59:59Z"
    frames = VisualFrame.from_payload(before_payload), VisualFrame.from_payload(after_payload)
    backend = Mock()
    reason = "managed_visual_frame_reused" if kind in {"frame_id", "path"} else "managed_visual_frame_not_fresh"
    for compare in (same_body, ManagedVisualVerifier(backend).compare):
        with pytest.raises(ValueError, match=f"^{reason}$"):
            compare(*frames)
    backend.analyze_images_structured.assert_not_called()


def test_frame_overwrite_before_or_during_model_call_is_rejected(tmp_path):
    frames = _frames(tmp_path)
    frames[0].path.write_bytes(_png(changed_row=3))
    backend = Mock()
    with pytest.raises(ValueError, match="^managed_visual_frame_changed$"):
        ManagedVisualVerifier(backend).compare(*frames)
    backend.analyze_images_structured.assert_not_called()

    frames = _frames(tmp_path)

    def mutate(*_args):
        frames[1].path.write_bytes(_png(changed_row=4))
        return _transition(added_bubbles=[_bubble()])

    backend.analyze_images_structured.side_effect = mutate
    with pytest.raises(ValueError, match="^managed_visual_frame_changed$"):
        ManagedVisualVerifier(backend).compare(*frames)


def test_comparison_is_one_ordered_request_without_expected_payload_in_prompts(tmp_path):
    before, after = _frames(tmp_path)
    expected = "UNIQUE_OUTBOUND_9b3e"
    backend = Mock()
    backend.analyze_images_structured.return_value = _transition(added_bubbles=[_bubble(expected)])
    result = ManagedVisualVerifier(backend).compare(before, after)
    backend.analyze_images_structured.assert_called_once()
    system, user, paths, schema = backend.analyze_images_structured.call_args.args
    assert paths == [before.path, after.path]
    assert expected not in system + user + str(schema)
    assert "BEFORE" in system and "AFTER" in system
    assert "unique ordered overlap" in system
    assert result.confirms_outbound(expected)
    assert result.continuation_allowed(expected)


@pytest.mark.parametrize("changes", [
    {"same_conversation": 1},
    {"baseline_messages_preserved": "true"},
    {"other_conversation_change": None},
    {"confidence": "certain"},
    {"composer_state": "unknown"},
    {"composer_text": None},
    {"composer_text": "unexpected text"},
    {"composer_state": "nonempty", "composer_text": ""},
    {"added_bubbles": ()},
    {"added_bubbles": [{"direction": "outbound", "text": "reply"}]},
    {"added_bubbles": [_bubble(direction="unknown")]},
    {"added_bubbles": [_bubble(kind="audio")]},
    {"added_bubbles": [_bubble(text=3)]},
    {"added_bubbles": [_bubble(text="")]},
    {"added_bubbles": [{**_bubble(), "extra": "private value"}]},
    {"reason": "private model explanation"},
])
def test_strict_schema_rejects_malformed_or_extra_model_fields_with_fixed_error(tmp_path, changes):
    with pytest.raises(ValueError, match="^managed_visual_transition_schema_invalid$"):
        _compare(tmp_path, _transition(**changes))


def test_backend_failure_does_not_expose_model_or_chat_text(tmp_path):
    backend = Mock()
    backend.analyze_images_structured.side_effect = RuntimeError("private model explanation")
    with pytest.raises(ValueError, match="^managed_visual_comparison_failed$"):
        ManagedVisualVerifier(backend).compare(*_frames(tmp_path))


@pytest.mark.parametrize("changes", [
    {"added_bubbles": []},  # An identical old bubble is not newly sent.
    {"added_bubbles": [_bubble(direction="inbound")]},
    {"added_bubbles": [_bubble(text="reply with extra text")]},
    {"added_bubbles": [_bubble(text=" reply")]},
    {"added_bubbles": [_bubble(), _bubble()]},
    {"added_bubbles": [_bubble(kind="media")]},
    {"added_bubbles": [_bubble()], "same_conversation": False},
    {"added_bubbles": [_bubble()], "baseline_messages_preserved": False},
    {"added_bubbles": [_bubble()], "other_conversation_change": True},
    {"added_bubbles": [_bubble()], "confidence": "medium"},
])
def test_outbound_confirmation_requires_one_new_exact_text_bubble_and_certain_continuity(tmp_path, changes):
    result = _compare(tmp_path, _transition(**changes))
    assert not result.confirms_outbound("reply")
    assert not result.continuation_allowed("reply")


@pytest.mark.parametrize("extra", [
    _bubble("new inbound", direction="inbound"),
    _bubble("", direction="inbound", kind="media"),
    _bubble("", direction="inbound", kind="unknown"),
])
def test_added_inbound_confirms_this_send_but_stops_continuation(tmp_path, extra):
    result = _compare(tmp_path, _transition(added_bubbles=[_bubble(), extra]))
    assert result.confirms_outbound("reply")
    assert not result.continuation_allowed("reply")
    assert not result.unchanged


def test_normalization_preserves_exact_text_apart_from_nfc_and_line_endings(tmp_path):
    result = _compare(tmp_path, _transition(added_bubbles=[_bubble("cafe\u0301\r\n你好")]))
    assert result.confirms_outbound("café\n你好")
    assert not result.confirms_outbound("café 你好")
    assert not result.confirms_outbound("café\n你好 ")


def test_title_only_identity_cannot_establish_unchanged_conversation(tmp_path):
    title_only = _compare(tmp_path, _transition(baseline_messages_preserved=False))
    assert not title_only.unchanged
    assert not title_only.confirms_outbound("reply")
    verified = _compare(tmp_path, _transition(composer_state="nonempty", composer_text="staged"))
    assert verified.unchanged
    assert verified.composer_text == "staged"
