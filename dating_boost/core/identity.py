from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


class IdentityConfidence(str, Enum):
    NEW = "new"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class IdentityResult:
    match_id: str
    confidence: IdentityConfidence
    requires_user_confirmation: bool
    reason: str


def resolve_match_identity(observation: Any, existing_matches: Iterable[dict[str, Any]]) -> IdentityResult:
    hints = observation.match_identity_hints
    visible_name = _normalize(hints.visible_name)
    profile_cues = {_normalize(cue) for cue in hints.profile_cues if _normalize(cue)}
    fingerprint = hints.conversation_fingerprint or ""

    candidates = list(existing_matches)
    if not candidates:
        return IdentityResult(
            match_id=_new_match_id(observation),
            confidence=IdentityConfidence.NEW,
            requires_user_confirmation=False,
            reason="No existing match candidates were available.",
        )

    name_matches = [
        candidate
        for candidate in candidates
        if visible_name and _normalize(candidate.get("display_name")) == visible_name
    ]
    fingerprint_matches = [
        candidate
        for candidate in name_matches
        if _fingerprint_matches(candidate, fingerprint)
    ]
    if len(fingerprint_matches) == 1:
        return IdentityResult(
            match_id=fingerprint_matches[0]["match_id"],
            confidence=IdentityConfidence.HIGH,
            requires_user_confirmation=False,
            reason="Visible name and conversation fingerprint matched.",
        )

    if len(fingerprint_matches) > 1:
        return IdentityResult(
            match_id=fingerprint_matches[0]["match_id"],
            confidence=IdentityConfidence.CONFLICT,
            requires_user_confirmation=True,
            reason="Multiple existing matches shared the same visible name and conversation fingerprint.",
        )

    high_matches = [
        candidate
        for candidate in name_matches
        if _fingerprint_matches(candidate, fingerprint)
        and profile_cues.intersection(_candidate_profile_cues(candidate))
    ]

    if len(high_matches) == 1:
        return IdentityResult(
            match_id=high_matches[0]["match_id"],
            confidence=IdentityConfidence.HIGH,
            requires_user_confirmation=False,
            reason="Visible name, profile cues, and conversation fingerprint matched.",
        )

    if len(high_matches) > 1:
        return IdentityResult(
            match_id=high_matches[0]["match_id"],
            confidence=IdentityConfidence.CONFLICT,
            requires_user_confirmation=True,
            reason="Multiple existing matches shared the same strong identity hints.",
        )

    medium_matches = [
        candidate
        for candidate in name_matches
        if _fingerprint_matches(candidate, fingerprint)
        or profile_cues.intersection(_candidate_profile_cues(candidate))
    ]
    if len(medium_matches) == 1:
        return IdentityResult(
            match_id=medium_matches[0]["match_id"],
            confidence=IdentityConfidence.MEDIUM,
            requires_user_confirmation=True,
            reason="Visible name matched with one supporting identity hint.",
        )

    if len(name_matches) == 1:
        return IdentityResult(
            match_id=name_matches[0]["match_id"],
            confidence=IdentityConfidence.LOW,
            requires_user_confirmation=True,
            reason="Only the visible name matched an existing match.",
        )

    if len(name_matches) > 1 or len(medium_matches) > 1:
        matches = medium_matches or name_matches
        return IdentityResult(
            match_id=matches[0]["match_id"],
            confidence=IdentityConfidence.CONFLICT,
            requires_user_confirmation=True,
            reason="Multiple existing matches shared the available identity hints.",
        )

    return IdentityResult(
        match_id=_new_match_id(observation),
        confidence=IdentityConfidence.NEW,
        requires_user_confirmation=False,
        reason="No existing match matched the observed identity hints.",
    )


def _candidate_profile_cues(candidate: dict[str, Any]) -> set[str]:
    return {_normalize(cue) for cue in candidate.get("profile_cues", []) if _normalize(cue)}


def _fingerprint_matches(candidate: dict[str, Any], fingerprint: str) -> bool:
    return bool(fingerprint and candidate.get("conversation_fingerprint") == fingerprint)


def _new_match_id(observation: Any) -> str:
    hints = observation.match_identity_hints
    stable_parts = [hints.visible_name or ""]
    if hints.conversation_fingerprint:
        stable_parts.append(hints.conversation_fingerprint)
    else:
        stable_parts.extend(hints.profile_cues)
        stable_parts.append(observation.observation_id or "")
    stable_text = "|".join(part for part in stable_parts if part) or "unknown"
    slug = re.sub(r"[^a-z0-9]+", "_", stable_text.lower()).strip("_") or "unknown"
    digest = hashlib.sha256(stable_text.encode("utf-8")).hexdigest()[:8]
    return f"match_{slug[:32]}_{digest}"


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold()
