from __future__ import annotations

import struct
import zlib
from dataclasses import replace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo.managed_rendered_verification import (
    ManagedRenderedVerifier,
    RENDERED_VERIFICATION_SCHEMA,
    accepted_rendered_verification,
    rendered_verification_applicable,
)
from dating_boost.apps.tashuo.managed_visual_evidence import VisualBubble, VisualFrame, VisualTransition


pytestmark = pytest.mark.managed_critical


def _transition(observed="同文😀", **changes):
    return VisualTransition(**{
        "same_conversation": True, "baseline_messages_preserved": True,
        "added_bubbles": (VisualBubble("outbound", observed, "text"),),
        "other_conversation_change": False, "composer_state": "empty",
        "composer_text": "", "confidence": "high", **changes,
    })


def _result(**changes):
    return {
        "comparison": "identical", "confidence": "high",
        "before_composer_readable": True, "after_new_outbound_readable": True, **changes,
    }


def _png(value=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + bytes([value] * 6)) * 2))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def frames(tmp_path):
    result = []
    for name, second in (("before", 1), ("after", 2)):
        path = tmp_path / f"{name}.png"
        path.write_bytes(_png())
        result.append(VisualFrame.from_payload({
            "status": "ok", "path": path, "frame_id": name,
            "captured_at": f"2026-09-20T10:00:0{second}+00:00", "state": "tashuo_conversation",
        }))
    return tuple(result)


@pytest.mark.parametrize("expected,observed,applicable", [
    ("同文😄", "同文😀", True),
    ("😄😅😁", "😀😂😃", True),
    ("🙏", "😀", True),  # Both endpoints of the explicitly bounded range.
    ("😄😅😁😇", "😀😂😃😊", False),
    ("同文😄", "同文😄", False),
    ("同文😄", "同文", False),
    ("同文😄", "同文😀😀", False),
    ("甲😄", "乙😀", False),
    ("甲，😄", "甲。😀", False),
    ("同文 😄", "同文　😀", False),
    ("同文😄", "同文🫠", False),
    ("同文😄", "同文☀", False),
    ("同文😄", "同文\U0001f650", False),
    ("👩\u200d💻😄", "👩\u200d💻😀", False),
    ("❤️😄", "❤️😀", False),
    ("☀\ufe0e😄", "☀\ufe0e😀", False),
    ("字\U000e0100😄", "字\U000e0100😀", False),
    ("👍🏻😄", "👍🏻😀", False),
    ("👍🏿😄", "👍🏿😀", False),
    ("é😄", "e\u0301😀", False),
    ("a\r\n😄", "a\n😀", False),
    ("😄a", "a😀", False),
    ("", "", False),
])
def test_eligibility_is_only_one_to_three_simple_face_substitutions(expected, observed, applicable):
    assert rendered_verification_applicable(expected, _transition(observed)) is applicable


@pytest.mark.parametrize("changes", [
    {"same_conversation": False},
    {"baseline_messages_preserved": False},
    {"other_conversation_change": True},
    {"confidence": "medium"},
    {"confidence": "low"},
    {"added_bubbles": ()},
    {"added_bubbles": (VisualBubble("inbound", "同文😀", "text"),)},
    {"added_bubbles": (VisualBubble("outbound", "同文😀", "media"),)},
    {"added_bubbles": (VisualBubble("outbound", "同文😀", "unknown"),)},
    {"added_bubbles": (VisualBubble("outbound", "同文😀", "text"), VisualBubble("outbound", "other", "text"))},
])
def test_eligibility_requires_certain_continuity_and_exactly_one_new_text_outbound(changes):
    assert not rendered_verification_applicable("同文😄", _transition(**changes))


def test_inbound_alongside_the_single_outbound_does_not_remove_eligibility():
    transition = _transition(added_bubbles=(
        VisualBubble("outbound", "同文😀", "text"), VisualBubble("inbound", "new reply", "text"),
    ))
    assert rendered_verification_applicable("同文😄", transition)
    assert not transition.continuation_allowed("同文😄")


@pytest.mark.parametrize("changes", [
    {"comparison": "different"}, {"comparison": "uncertain"},
    {"confidence": "medium"}, {"confidence": "low"},
    {"before_composer_readable": False}, {"after_new_outbound_readable": False},
])
def test_valid_negative_or_uncertain_results_are_returned_for_durable_recording(frames, changes):
    backend = Mock()
    backend.analyze_images_structured.return_value = _result(**changes)
    verifier = ManagedRenderedVerifier(backend)
    result = verifier.compare(*frames)
    assert result == _result(**changes)
    assert not accepted_rendered_verification(result)
    with pytest.raises(ValueError, match="^managed_rendered_pair_already_attempted$"):
        verifier.compare(*frames)
    backend.analyze_images_structured.assert_called_once()


@pytest.mark.parametrize("payload", [
    None, [], "identical", {},
    _result(comparison=True), _result(comparison="equal"), _result(confidence=1),
    _result(confidence="certain"), _result(before_composer_readable=1),
    _result(after_new_outbound_readable="true"), _result(reason="private model content"),
    {key: value for key, value in _result().items() if key != "comparison"},
])
def test_schema_is_strict_and_malformed_results_cannot_be_accepted_or_retried(frames, payload):
    backend = Mock()
    backend.analyze_images_structured.return_value = payload
    verifier = ManagedRenderedVerifier(backend)
    assert not accepted_rendered_verification(payload)
    with pytest.raises(ValueError, match="^managed_rendered_result_invalid$"):
        verifier.compare(*frames)
    with pytest.raises(ValueError, match="^managed_rendered_pair_already_attempted$"):
        verifier.compare(*frames)
    backend.analyze_images_structured.assert_called_once()


def test_one_ordered_full_image_request_has_no_expected_text_or_codepoints(frames):
    backend = Mock()
    backend.analyze_images_structured.return_value = _result()
    verifier = ManagedRenderedVerifier(backend)
    assert rendered_verification_applicable("PRIVATE_EXPECTED😄", _transition("PRIVATE_EXPECTED😀"))
    result = verifier.compare(*frames)
    assert accepted_rendered_verification(result)
    system, user, paths, schema = backend.analyze_images_structured.call_args.args
    assert paths == [frames[0].path, frames[1].path]
    assert schema == RENDERED_VERIFICATION_SCHEMA
    assert set(schema["required"]) == set(_result())
    assert "Image 1 is BEFORE; image 2 is AFTER" in system
    assert "already-filled message composer" in user
    assert "newly added outbound" in user
    for forbidden in ("PRIVATE_EXPECTED", "😄", "😀", "1F604", "1F600"):
        assert forbidden not in system + user + str(schema)
    with pytest.raises(ValueError, match="^managed_rendered_pair_already_attempted$"):
        verifier.compare(*frames)
    backend.analyze_images_structured.assert_called_once()


def test_backend_failure_is_redacted_and_has_no_retry(frames):
    backend = Mock()
    backend.analyze_images_structured.side_effect = RuntimeError("private model content")
    verifier = ManagedRenderedVerifier(backend)
    with pytest.raises(ValueError, match="^managed_rendered_comparison_failed$"):
        verifier.compare(*frames)
    with pytest.raises(ValueError, match="^managed_rendered_pair_already_attempted$"):
        verifier.compare(*frames)
    backend.analyze_images_structured.assert_called_once()


@pytest.mark.parametrize("when", ["before", "during"])
def test_frame_overwrite_is_rejected_before_and_after_comparison(frames, when):
    backend = Mock()
    if when == "before":
        frames[0].path.write_bytes(_png(1))
    else:
        def overwrite(*_args):
            frames[1].path.write_bytes(_png(1))
            return _result()

        backend.analyze_images_structured.side_effect = overwrite
    with pytest.raises(ValueError, match="^managed_visual_frame_changed$"):
        ManagedRenderedVerifier(backend).compare(*frames)
    assert backend.analyze_images_structured.call_count == int(when == "during")


@pytest.mark.parametrize("kind,code", [
    ("stale", "managed_visual_frame_not_fresh"),
    ("reused", "managed_visual_frame_reused"),
])
def test_nonfresh_or_reused_frame_rejects_without_model(frames, kind, code):
    before, after = frames
    if kind == "stale":
        after = replace(after, captured_at=before.captured_at)
    else:
        after = replace(after, frame_id=before.frame_id)
    backend = Mock()
    with pytest.raises(ValueError, match=f"^{code}$"):
        ManagedRenderedVerifier(backend).compare(before, after)
    backend.analyze_images_structured.assert_not_called()
