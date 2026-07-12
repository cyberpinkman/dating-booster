from __future__ import annotations

import hashlib
import hmac
import math
import re
import unicodedata
from typing import Any, Mapping, Sequence

from dating_boost.apps.tashuo.standalone_production_contract import canonical_digest, canonical_json


TAIL_SCHEMA_VERSION = 2
MINIMUM_BUBBLE_CONFIDENCE = 0.90
HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class EvidenceViolation(ValueError):
    pass


def normalize_evidence_text(value: str) -> str:
    if not isinstance(value, str):
        raise EvidenceViolation("evidence_text_invalid")
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def normalized_text_hash(value: str) -> str:
    return hashlib.sha256(normalize_evidence_text(value).encode("utf-8")).hexdigest()


def qualification_target_hash(qualification_salt: str, target_binding: Mapping[str, Any]) -> str:
    if not isinstance(qualification_salt, str) or not qualification_salt:
        raise EvidenceViolation("qualification_salt_invalid")
    if not isinstance(target_binding, Mapping) or not target_binding:
        raise EvidenceViolation("target_binding_invalid")
    return hmac.new(
        qualification_salt.encode("utf-8"),
        canonical_json(dict(target_binding)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_conversation_tail_v2(
    *,
    qualification_salt: str,
    target_binding: Mapping[str, Any],
    viewport_identity: str,
    capture_id: str,
    observation_id: str,
    captured_monotonic_ns: int,
    bubbles: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not all(_identifier(value) for value in (viewport_identity, capture_id, observation_id)):
        raise EvidenceViolation("tail_v2_capture_identity_invalid")
    if not isinstance(captured_monotonic_ns, int) or isinstance(captured_monotonic_ns, bool) or captured_monotonic_ns < 0:
        raise EvidenceViolation("tail_v2_capture_time_invalid")
    target_binding_digest = canonical_digest(dict(target_binding))
    certified_bubbles: list[dict[str, Any]] = []
    for expected_order, raw in enumerate(bubbles, start=1):
        certified_bubbles.append(
            _certify_bubble(
                raw,
                expected_order=expected_order,
                viewport_identity=viewport_identity,
                capture_id=capture_id,
                observation_id=observation_id,
            )
        )
    confidence = min((item["confidence"] for item in certified_bubbles), default=1.0)
    body = {
        "schema_version": TAIL_SCHEMA_VERSION,
        "evidence_type": "conversation_tail_v2",
        "target_hash": qualification_target_hash(qualification_salt, target_binding),
        "target_binding_digest": target_binding_digest,
        "viewport_identity": viewport_identity,
        "capture_id": capture_id,
        "observation_id": observation_id,
        "captured_monotonic_ns": captured_monotonic_ns,
        "confidence": confidence,
        "bubbles": certified_bubbles,
    }
    body["certificate_digest"] = canonical_digest(body)
    return body


def validate_conversation_tail_v2(certificate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(certificate, Mapping):
        return _invalid("tail_v2_not_object")
    if certificate.get("schema_version") != TAIL_SCHEMA_VERSION or certificate.get("evidence_type") != "conversation_tail_v2":
        return _invalid("tail_v2_schema_invalid")
    for field in ("target_hash", "target_binding_digest"):
        if not _digest(certificate.get(field)):
            return _invalid(f"tail_v2_{field}_invalid")
    for field in ("viewport_identity", "capture_id", "observation_id"):
        if not _identifier(certificate.get(field)):
            return _invalid("tail_v2_capture_identity_invalid")
    captured = certificate.get("captured_monotonic_ns")
    if not isinstance(captured, int) or isinstance(captured, bool) or captured < 0:
        return _invalid("tail_v2_capture_time_invalid")
    confidence = certificate.get("confidence")
    if not _confidence(confidence):
        return _invalid("tail_v2_confidence_insufficient")
    bubbles = certificate.get("bubbles")
    if not isinstance(bubbles, list):
        return _invalid("tail_v2_bubbles_invalid")
    for expected_order, bubble in enumerate(bubbles, start=1):
        validation = _validate_certified_bubble(certificate, bubble, expected_order=expected_order)
        if validation is not None:
            return _invalid(validation)
    stored_digest = certificate.get("certificate_digest")
    body = {key: value for key, value in certificate.items() if key != "certificate_digest"}
    if stored_digest != canonical_digest(body):
        return _invalid("tail_v2_certificate_digest_mismatch")
    return {
        "valid": True,
        "reason": None,
        "certificate_digest": stored_digest,
        "bubble_count": len(bubbles),
    }


def evaluate_negative_send(
    *,
    pre_tail: Mapping[str, Any],
    post_tail: Mapping[str, Any],
    observed_composer_text_hash: str,
    command_audit: Sequence[Mapping[str, Any]],
    send_mode: str,
    managed_gui_send: bool,
    live_send_executed: bool,
) -> dict[str, Any]:
    pre_validation = validate_conversation_tail_v2(pre_tail)
    if pre_validation.get("valid") is not True:
        return _negative_block("negative_send_pre_tail_invalid", detail_reason=pre_validation.get("reason"))
    post_validation = validate_conversation_tail_v2(post_tail)
    if post_validation.get("valid") is not True:
        return _negative_block("negative_send_post_tail_invalid", detail_reason=post_validation.get("reason"))
    if pre_tail.get("target_hash") != post_tail.get("target_hash") or pre_tail.get("target_binding_digest") != post_tail.get(
        "target_binding_digest"
    ):
        return _negative_block("negative_send_target_mismatch")
    if pre_tail.get("viewport_identity") != post_tail.get("viewport_identity"):
        return _negative_block("negative_send_viewport_mismatch")
    if (
        pre_tail.get("capture_id") == post_tail.get("capture_id")
        or pre_tail.get("observation_id") == post_tail.get("observation_id")
        or int(post_tail["captured_monotonic_ns"]) <= int(pre_tail["captured_monotonic_ns"])
    ):
        return _negative_block("negative_send_post_not_fresh")
    if not _digest(observed_composer_text_hash):
        return _negative_block("negative_send_composer_text_hash_invalid")
    if send_mode != "stage" or managed_gui_send is not False or live_send_executed is not False:
        return _negative_block("negative_send_stage_mode_contract_invalid")
    if any(_command_is_prohibited(item) for item in command_audit):
        return _negative_block("negative_send_prohibited_command_detected")
    pre_bubbles = list(pre_tail["bubbles"])
    post_bubbles = list(post_tail["bubbles"])
    if len(post_bubbles) < len(pre_bubbles):
        return _negative_block("negative_send_pre_tail_not_preserved")
    for pre, post in zip(pre_bubbles, post_bubbles):
        if _bubble_identity(pre) != _bubble_identity(post):
            return _negative_block("negative_send_pre_tail_not_preserved")
    suffix = post_bubbles[len(pre_bubbles) :]
    outbound = [item for item in suffix if item.get("direction") == "outbound"]
    if any(item.get("text_hash") == observed_composer_text_hash for item in outbound):
        return _negative_block("negative_send_composer_text_outbound_detected")
    if outbound:
        return _negative_block("negative_send_new_outbound_detected")
    inbound_count = sum(1 for item in suffix if item.get("direction") == "inbound")
    if inbound_count != len(suffix):
        return _negative_block("negative_send_tail_delta_ambiguous")
    return {
        "schema_version": 1,
        "status": "verified",
        "reason": "negative_send_verified",
        "target_hash": pre_tail["target_hash"],
        "pre_tail_digest": pre_tail["certificate_digest"],
        "post_tail_digest": post_tail["certificate_digest"],
        "observed_composer_text_hash": observed_composer_text_hash,
        "new_inbound_count": inbound_count,
        "new_outbound_count": 0,
        "prohibited_command_count": 0,
        "send_mode": "stage",
        "managed_gui_send": False,
        "live_send_executed": False,
    }


def _certify_bubble(
    raw: Mapping[str, Any],
    *,
    expected_order: int,
    viewport_identity: str,
    capture_id: str,
    observation_id: str,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise EvidenceViolation("tail_v2_bubble_invalid")
    direction = raw.get("direction")
    if direction not in {"inbound", "outbound"}:
        raise EvidenceViolation("tail_v2_bubble_direction_invalid")
    if raw.get("order") != expected_order:
        raise EvidenceViolation("tail_v2_bubble_order_invalid")
    bounds = _normalized_bounds(raw.get("bounds"))
    anchor = raw.get("anchor")
    if not _identifier(anchor):
        raise EvidenceViolation("tail_v2_bubble_anchor_invalid")
    confidence = raw.get("confidence")
    if not _confidence(confidence):
        raise EvidenceViolation("tail_v2_confidence_insufficient")
    text = raw.get("text")
    if not isinstance(text, str):
        raise EvidenceViolation("tail_v2_bubble_text_invalid")
    return {
        "direction": direction,
        "text_hash": normalized_text_hash(text),
        "bounds": bounds,
        "anchor": anchor,
        "order": expected_order,
        "viewport_identity": viewport_identity,
        "capture_id": capture_id,
        "observation_id": observation_id,
        "confidence": float(confidence),
    }


def _validate_certified_bubble(
    certificate: Mapping[str, Any],
    bubble: Any,
    *,
    expected_order: int,
) -> str | None:
    if not isinstance(bubble, Mapping):
        return "tail_v2_bubble_invalid"
    if bubble.get("direction") not in {"inbound", "outbound"}:
        return "tail_v2_bubble_direction_invalid"
    if not _digest(bubble.get("text_hash")):
        return "tail_v2_bubble_text_hash_invalid"
    try:
        _normalized_bounds(bubble.get("bounds"))
    except EvidenceViolation:
        return "tail_v2_bubble_bounds_invalid"
    if not _identifier(bubble.get("anchor")):
        return "tail_v2_bubble_anchor_invalid"
    if bubble.get("order") != expected_order:
        return "tail_v2_bubble_order_invalid"
    if not _confidence(bubble.get("confidence")):
        return "tail_v2_confidence_insufficient"
    for field in ("viewport_identity", "capture_id", "observation_id"):
        if bubble.get(field) != certificate.get(field):
            return "tail_v2_bubble_capture_binding_invalid"
    return None


def _normalized_bounds(value: Any) -> dict[str, float | int]:
    if not isinstance(value, Mapping) or set(value) != {"x", "y", "width", "height"}:
        raise EvidenceViolation("tail_v2_bubble_bounds_invalid")
    result: dict[str, float | int] = {}
    for key in ("x", "y", "width", "height"):
        coordinate = value.get(key)
        if not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool) or not math.isfinite(coordinate):
            raise EvidenceViolation("tail_v2_bubble_bounds_invalid")
        if key in {"width", "height"} and coordinate <= 0:
            raise EvidenceViolation("tail_v2_bubble_bounds_invalid")
        result[key] = coordinate
    return result


def _bubble_identity(value: Mapping[str, Any]) -> tuple[Any, ...]:
    bounds = value["bounds"]
    return (
        value.get("direction"),
        value.get("text_hash"),
        bounds.get("x"),
        bounds.get("y"),
        bounds.get("width"),
        bounds.get("height"),
        value.get("anchor"),
        value.get("order"),
    )


def _command_is_prohibited(value: Mapping[str, Any]) -> bool:
    serialized = canonical_json(dict(value)).lower()
    markers = (
        "send-message",
        "--managed-gui-send",
        "pbcopy",
        "paste_clipboard",
        "clipboard_api",
        "key code 9",
        "key code 36",
        "tap_send",
        "click_send",
        "press_return",
        "enter_send",
    )
    return any(marker in serialized for marker in markers)


def _negative_block(reason: str, **extras: Any) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason, **extras}


def _invalid(reason: str) -> dict[str, Any]:
    return {"valid": False, "reason": reason}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value


def _digest(value: Any) -> bool:
    return isinstance(value, str) and HEX_DIGEST.fullmatch(value) is not None


def _confidence(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and MINIMUM_BUBBLE_CONFIDENCE <= float(value) <= 1.0
    )
