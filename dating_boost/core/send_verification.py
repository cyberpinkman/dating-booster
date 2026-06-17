from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from dating_boost.core.support import classify_text_topics


RedactScreen = Callable[[dict[str, Any]], dict[str, Any]]


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def text_fingerprint_fields(prefix: str, text: str) -> dict[str, Any]:
    return {
        f"{prefix}_fingerprint": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        f"{prefix}_character_count": len(text),
        f"{prefix}_topic_labels": classify_text_topics(text),
    }


def expected_text_observation_stats(text: str, expected_text: str) -> dict[str, Any]:
    normalized_text = normalize_text(text)
    comparable_text = message_text_comparable(text)
    comparable_expected = message_text_comparable(expected_text)
    return {
        "text_hash": hash_text(text) if text else None,
        "normalized_text_hash": hash_text(normalized_text) if normalized_text else None,
        "text_character_count": len(text) if text else None,
        "expected_text_occurrences": comparable_text.count(comparable_expected) if comparable_expected else 0,
    }


def message_text_matches(observed_text: str, expected_text: str) -> bool:
    if not expected_text:
        return False
    if expected_text in observed_text or normalize_text(expected_text) in normalize_text(observed_text):
        return True
    comparable_expected = message_text_comparable(expected_text)
    return bool(comparable_expected and comparable_expected in message_text_comparable(observed_text))


def message_text_comparable(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def staged_text_ocr_evidence(
    *,
    verification_method: str,
    observed_text: str,
    expected_text: str,
    baseline_text: str = "",
    screen: dict[str, Any] | None = None,
    redact_screen: RedactScreen | None = None,
    exact_text_ocr_verified: bool | None = None,
    visual_only_exact_verification_allowed: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_stats = expected_text_observation_stats(observed_text, expected_text)
    baseline_stats = expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    result: dict[str, Any] = {
        "verification_method": verification_method,
        "expected_payload_hash": hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": observed_stats["text_hash"],
        "observed_character_count": observed_stats["text_character_count"],
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "baseline_expected_text_occurrences": baseline_stats["expected_text_occurrences"] if baseline_stats else None,
        "baseline_text_hash": baseline_stats["text_hash"] if baseline_stats else None,
        "exact_text_ocr_verified": (
            message_text_matches(observed_text, expected_text)
            if exact_text_ocr_verified is None
            else bool(exact_text_ocr_verified)
        ),
        "visual_only_exact_verification_allowed": visual_only_exact_verification_allowed,
    }
    if screen is not None and redact_screen is not None:
        result["screen"] = redact_screen(screen)
    if extra:
        result.update(extra)
    return result


def outbound_text_ocr_evidence(
    *,
    verification_method: str,
    observed_text: str,
    expected_text: str,
    exact_text_ocr_verified: bool | None = None,
    visual_only_exact_verification_allowed: bool | None = None,
) -> dict[str, Any]:
    result = {
        "verification_method": verification_method,
        "expected_payload_hash": hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": hash_text(observed_text) if observed_text else None,
        "observed_character_count": len(observed_text) if observed_text else None,
        "exact_text_ocr_verified": (
            message_text_matches(observed_text, expected_text)
            if exact_text_ocr_verified is None
            else bool(exact_text_ocr_verified)
        ),
    }
    if visual_only_exact_verification_allowed is not None:
        result["visual_only_exact_verification_allowed"] = visual_only_exact_verification_allowed
    return result


def staged_text_visual_verification_request(
    *,
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
    instructions: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "schema_version": 1,
        "verification_type": "staged_text_visual",
        "status": "needs_host_visual_verification",
        "expected_payload_hash": hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "screen_path": screen.get("path"),
        "screen_state": screen.get("state"),
        "ocr_text_hash": staged_verification.get("observed_text_hash"),
        "ocr_text_character_count": staged_verification.get("observed_character_count"),
        "observed_expected_text_occurrences": staged_verification.get("observed_expected_text_occurrences"),
        "baseline_expected_text_occurrences": staged_verification.get("baseline_expected_text_occurrences"),
        "next_host_action": "visually_verify_staged_text_before_live_send",
        "instructions": instructions,
    }
    if extra:
        request.update(extra)
    return request
