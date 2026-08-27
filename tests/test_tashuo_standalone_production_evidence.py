from __future__ import annotations

import copy

import pytest


pytestmark = pytest.mark.nightly_lab

from dating_boost.apps.tashuo.standalone_production_evidence import (
    EvidenceViolation,
    build_conversation_tail_v2,
    evaluate_negative_send,
    normalized_text_hash,
    qualification_target_hash,
    validate_conversation_tail_v2,
)


def _bubble(direction, text, order, *, x=10, y=10, confidence=0.99):
    return {
        "direction": direction,
        "text": text,
        "bounds": {"x": x, "y": y + order * 20, "width": 120, "height": 18},
        "anchor": f"anchor_{order}",
        "order": order,
        "confidence": confidence,
    }


def _tail(*, capture_id="capture_pre", observation_id="obs_pre", monotonic_ns=100, bubbles=None, viewport="view_1"):
    return build_conversation_tail_v2(
        qualification_salt="salt_1",
        target_binding={"kind": "current_thread_visual_identity", "target_match_id": "match_secret"},
        viewport_identity=viewport,
        capture_id=capture_id,
        observation_id=observation_id,
        captured_monotonic_ns=monotonic_ns,
        bubbles=bubbles
        if bubbles is not None
        else [_bubble("inbound", "hello", 1), _bubble("outbound", "hi", 2)],
    )


def _evaluate(pre, post, *, commands=None, composer_text="draft"):
    return evaluate_negative_send(
        pre_tail=pre,
        post_tail=post,
        observed_composer_text_hash=normalized_text_hash(composer_text),
        command_audit=commands or [{"intent": "guarded_ax_set_if_empty"}, {"intent": "guarded_ax_clear_if_exact"}],
        send_mode="stage",
        managed_gui_send=False,
        live_send_executed=False,
    )


def test_target_hash_is_qualification_scoped_and_hides_identity():
    one = qualification_target_hash("salt_1", {"target_match_id": "match_secret"})
    two = qualification_target_hash("salt_2", {"target_match_id": "match_secret"})

    assert one != two
    assert "match_secret" not in one


def test_tail_v2_contains_only_hash_geometry_order_and_capture_identity():
    certificate = _tail()

    assert certificate["schema_version"] == 2
    assert certificate["evidence_type"] == "conversation_tail_v2"
    assert certificate["capture_id"] == "capture_pre"
    assert certificate["observation_id"] == "obs_pre"
    assert certificate["viewport_identity"] == "view_1"
    assert [item["order"] for item in certificate["bubbles"]] == [1, 2]
    assert all("text_hash" in item and "text" not in item for item in certificate["bubbles"])
    assert "hello" not in str(certificate)
    assert "match_secret" not in str(certificate)
    assert validate_conversation_tail_v2(certificate)["valid"] is True


def test_unchanged_fresh_same_target_tail_verifies_negative_send():
    pre = _tail()
    post = _tail(capture_id="capture_post", observation_id="obs_post", monotonic_ns=200)

    result = _evaluate(pre, post)

    assert result["status"] == "verified"
    assert result["new_inbound_count"] == 0
    assert result["new_outbound_count"] == 0
    assert result["pre_tail_digest"] == pre["certificate_digest"]
    assert result["post_tail_digest"] == post["certificate_digest"]


def test_inbound_only_suffix_is_allowed():
    pre = _tail()
    bubbles = [_bubble("inbound", "hello", 1), _bubble("outbound", "hi", 2), _bubble("inbound", "new", 3)]
    post = _tail(capture_id="capture_post", observation_id="obs_post", monotonic_ns=200, bubbles=bubbles)

    result = _evaluate(pre, post)

    assert result["status"] == "verified"
    assert result["new_inbound_count"] == 1


def test_any_new_outbound_or_composer_hash_outbound_blocks():
    pre = _tail()
    outbound = [_bubble("inbound", "hello", 1), _bubble("outbound", "hi", 2), _bubble("outbound", "other", 3)]
    result = _evaluate(
        pre,
        _tail(capture_id="capture_post", observation_id="obs_post", monotonic_ns=200, bubbles=outbound),
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "negative_send_new_outbound_detected"

    payload_outbound = [
        _bubble("inbound", "hello", 1),
        _bubble("outbound", "hi", 2),
        _bubble("outbound", "draft", 3),
    ]
    result = _evaluate(
        pre,
        _tail(capture_id="capture_post_2", observation_id="obs_post_2", monotonic_ns=300, bubbles=payload_outbound),
    )
    assert result["reason"] == "negative_send_composer_text_outbound_detected"


@pytest.mark.parametrize("kind", ["viewport", "target", "capture", "observation", "monotonic"])
def test_target_viewport_and_freshness_mismatches_block(kind):
    pre = _tail()
    kwargs = {"capture_id": "capture_post", "observation_id": "obs_post", "monotonic_ns": 200}
    if kind == "viewport":
        kwargs["viewport"] = "other"
    elif kind == "capture":
        kwargs["capture_id"] = "capture_pre"
    elif kind == "observation":
        kwargs["observation_id"] = "obs_pre"
    elif kind == "monotonic":
        kwargs["monotonic_ns"] = 100
    post = _tail(**kwargs)
    if kind == "target":
        post = build_conversation_tail_v2(
            qualification_salt="salt_1",
            target_binding={"kind": "current_thread_visual_identity", "target_match_id": "other_match"},
            viewport_identity="view_1",
            capture_id="capture_post",
            observation_id="obs_post",
            captured_monotonic_ns=200,
            bubbles=[_bubble("inbound", "hello", 1), _bubble("outbound", "hi", 2)],
        )

    result = _evaluate(pre, post)

    assert result["status"] == "blocked"
    expected = {
        "viewport": "negative_send_viewport_mismatch",
        "target": "negative_send_target_mismatch",
        "capture": "negative_send_post_not_fresh",
        "observation": "negative_send_post_not_fresh",
        "monotonic": "negative_send_post_not_fresh",
    }
    assert result["reason"] == expected[kind]


def test_missing_geometry_ambiguous_direction_or_low_confidence_is_not_v2_evidence():
    missing_geometry = _tail()
    missing_geometry["bubbles"][0].pop("bounds")
    ambiguous = _tail()
    ambiguous["bubbles"][0]["direction"] = "unknown"
    low_confidence = _tail()
    low_confidence["bubbles"][0]["confidence"] = 0.4

    assert validate_conversation_tail_v2(missing_geometry)["reason"] == "tail_v2_bubble_bounds_invalid"
    assert validate_conversation_tail_v2(ambiguous)["reason"] == "tail_v2_bubble_direction_invalid"
    assert validate_conversation_tail_v2(low_confidence)["reason"] == "tail_v2_confidence_insufficient"


def test_pre_tail_must_be_exact_prefix_of_post_tail():
    pre = _tail()
    changed = [_bubble("inbound", "different", 1), _bubble("outbound", "hi", 2)]
    post = _tail(capture_id="capture_post", observation_id="obs_post", monotonic_ns=200, bubbles=changed)

    result = _evaluate(pre, post)

    assert result["reason"] == "negative_send_pre_tail_not_preserved"


@pytest.mark.parametrize(
    "command",
    [
        {"cmd": ["harness", "tashuo", "send-message"]},
        {"cmd": ["standalone", "--managed-gui-send"]},
        {"cmd": ["pbcopy"]},
        {"intent": "paste_clipboard_into_frontmost_app"},
        {"script": "key code 9 using command down"},
        {"script": "key code 36"},
        {"intent": "tap_send_button"},
    ],
)
def test_prohibited_command_audit_blocks_negative_send(command):
    pre = _tail()
    post = _tail(capture_id="capture_post", observation_id="obs_post", monotonic_ns=200)

    result = _evaluate(pre, post, commands=[command])

    assert result["status"] == "blocked"
    assert result["reason"] == "negative_send_prohibited_command_detected"


def test_self_declaration_or_empty_composer_without_v2_tail_never_passes():
    pre = {"schema_version": 1, "messages": []}
    post = {"schema_version": 1, "messages": [], "composer_empty": True}

    result = _evaluate(pre, post)

    assert result["status"] == "blocked"
    assert result["reason"] == "negative_send_pre_tail_invalid"


def test_validator_recomputes_digest_and_rejects_tampering():
    certificate = _tail()
    tampered = copy.deepcopy(certificate)
    tampered["bubbles"][0]["text_hash"] = normalized_text_hash("tampered")

    result = validate_conversation_tail_v2(tampered)

    assert result["valid"] is False
    assert result["reason"] == "tail_v2_certificate_digest_mismatch"


def test_builder_rejects_raw_bubble_without_required_fields():
    with pytest.raises(EvidenceViolation, match="tail_v2_bubble_bounds_invalid"):
        _tail(bubbles=[{"direction": "inbound", "text": "hello", "order": 1, "confidence": 1.0}])
