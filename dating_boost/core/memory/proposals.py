from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from dating_boost.core.memory.models import (
    MemoryFact,
    MemoryFactType,
    MemoryScope,
    MatchMemoryProjection,
    normalized_fact_key,
    normalize_memory_value,
)
from dating_boost.core.memory.review_queue import ReviewItem, build_dedupe_key
from dating_boost.perception.observations import AppObservation


_IDENTITY_KEYWORDS = frozenset({
    "phone",
    "email",
    "address",
    "real_name",
    "social_media",
    "instagram",
    "snapchat",
    "facebook",
    "twitter",
    "whatsapp",
    "telegram",
    "linkedin",
    "phone_number",
    "contact_info",
})

_MEDIUM_KEYWORDS = frozenset({
    "preference",
    "commitment",
    "date_plan",
    "date_logistics",
    "schedule",
    "availability",
    "meeting_plan",
    "date_lead",
    "date_time",
    "date_location",
})


def _now_iso() -> str:
    override = os.environ.get("DATING_BOOST_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _review_item_id(match_id: str, normalized_key: str, normalized_value: str) -> str:
    raw = "|".join([match_id, normalized_key or "", normalized_value or ""])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"rev_{digest}"


def classify_risk(predicate: str, value: Any) -> str:
    pred_lower = predicate.strip().casefold()
    val_lower = str(value or "").casefold()
    for keyword in _IDENTITY_KEYWORDS:
        if keyword in pred_lower or keyword in val_lower:
            return "high"
    for keyword in _MEDIUM_KEYWORDS:
        if keyword in pred_lower or keyword in val_lower:
            return "medium"
    return "low"


_SOURCE_DETERMINISTIC = "deterministic"
_SOURCE_MODEL = "model"
_SOURCE_USER_FEEDBACK = "user_feedback"
_SOURCE_PLANNER = "planner"

_MODEL_EXTRACTOR_DEFERRED = (
    "Model extractor (source='model') is deferred. "
    "Only deterministic proposals are generated in this version. "
    "When implemented, extract_proposals(source='model') should call "
    "ModelBackend.generate_structured with a proposal prompt and "
    "route results through the same ReviewItem pipeline."
)


def extract_proposals(
    match_id: str,
    observation: AppObservation,
    projection: MatchMemoryProjection,
    *,
    session_id: str | None = None,
    observation_id: str | None = None,
    created_at: str | None = None,
    source: str = _SOURCE_DETERMINISTIC,
) -> list[ReviewItem]:
    timestamp = created_at or _now_iso()
    obs_id = observation_id or observation.observation_id
    proposals: list[ReviewItem] = []
    proposals.extend(
        _extract_profile_proposals(
            match_id,
            observation,
            projection,
            session_id=session_id,
            observation_id=obs_id,
            created_at=timestamp,
            source=source,
        )
    )
    proposals.extend(
        _extract_conversation_proposals(
            match_id,
            observation,
            projection,
            session_id=session_id,
            observation_id=obs_id,
            created_at=timestamp,
            source=source,
        )
    )
    proposals.extend(
        _extract_inference_proposals(
            match_id,
            observation,
            projection,
            session_id=session_id,
            observation_id=obs_id,
            created_at=timestamp,
            source=source,
        )
    )
    return proposals


def _extract_profile_proposals(
    match_id: str,
    observation: AppObservation,
    projection: MatchMemoryProjection,
    *,
    session_id: str | None,
    observation_id: str | None,
    created_at: str,
    source: str,
) -> list[ReviewItem]:
    proposals: list[ReviewItem] = []
    visible_name = observation.match_identity_hints.visible_name or match_id
    app_id = observation.app_id
    existing_keys = {
        fact.normalized_key
        for fact in projection.facts
        if fact.normalized_key is not None
    }
    for cue in observation.match_identity_hints.profile_cues:
        cue_text = str(cue).strip()
        if not cue_text:
            continue
        n_key = normalized_fact_key(visible_name, "profile_cue", {"app_id": app_id})
        if n_key in existing_keys:
            continue
        n_value = normalize_memory_value(cue_text)
        proposal = {
            "predicate": "profile_cue",
            "value": cue_text,
            "scope": MemoryScope.MATCH_PROFILE.value,
            "fact_type": MemoryFactType.VISIBLE_FACT.value,
            "confidence": observation.page_confidence.value,
            "evidence_text": "Visible profile cue from match identity hints.",
            "subject": visible_name,
            "qualifiers": {"app_id": app_id},
        }
        dedupe_key = build_dedupe_key(match_id, "propose", n_key, n_value, observation_id)
        proposals.append(
            ReviewItem(
                review_item_id=_review_item_id(match_id, n_key, n_value),
                session_id=session_id or "",
                match_id=match_id,
                observation_id=observation_id,
                proposal=proposal,
                status="pending",
                created_at=created_at,
                reported_at=None,
                reviewed_at=None,
                dedupe_key=dedupe_key,
                source=source,
                risk="low",
            )
        )
    return proposals


def _extract_conversation_proposals(
    match_id: str,
    observation: AppObservation,
    projection: MatchMemoryProjection,
    *,
    session_id: str | None,
    observation_id: str | None,
    created_at: str,
    source: str,
) -> list[ReviewItem]:
    proposals: list[ReviewItem] = []
    visible_name = observation.match_identity_hints.visible_name or match_id
    app_id = observation.app_id
    existing_keys = {
        fact.normalized_key
        for fact in projection.facts
        if fact.normalized_key is not None
    }
    for cue in observation.conversation_observation.thread_cues:
        cue_text = str(cue).strip()
        if not cue_text:
            continue
        predicate = "thread_cue"
        n_key = normalized_fact_key(visible_name, predicate, {"app_id": app_id})
        if n_key in existing_keys:
            continue
        n_value = normalize_memory_value(cue_text)
        risk = classify_risk(predicate, cue_text)
        proposal = {
            "predicate": predicate,
            "value": cue_text,
            "scope": MemoryScope.CONVERSATION.value,
            "fact_type": MemoryFactType.VISIBLE_FACT.value,
            "confidence": "medium",
            "evidence_text": "Conversation thread cue from observation.",
            "subject": visible_name,
            "qualifiers": {"app_id": app_id},
        }
        dedupe_key = build_dedupe_key(match_id, "propose", n_key, n_value, observation_id)
        proposals.append(
            ReviewItem(
                review_item_id=_review_item_id(match_id, n_key, n_value),
                session_id=session_id or "",
                match_id=match_id,
                observation_id=observation_id,
                proposal=proposal,
                status="pending",
                created_at=created_at,
                reported_at=None,
                reviewed_at=None,
                dedupe_key=dedupe_key,
                source=source,
                risk=risk,
            )
        )
    return proposals


def _extract_inference_proposals(
    match_id: str,
    observation: AppObservation,
    projection: MatchMemoryProjection,
    *,
    session_id: str | None,
    observation_id: str | None,
    created_at: str,
    source: str,
) -> list[ReviewItem]:
    proposals: list[ReviewItem] = []
    visible_name = observation.match_identity_hints.visible_name or match_id
    app_id = observation.app_id
    inference_keys = {
        inf.normalized_key
        for inf in projection.inferences
        if inf.normalized_key is not None
    }
    for hook in observation.profile_observation.hook_candidates:
        hook_text = str(hook).strip()
        if not hook_text:
            continue
        predicate = "hook_candidate"
        n_key = normalized_fact_key(visible_name, predicate, {"app_id": app_id})
        if n_key in inference_keys:
            continue
        n_value = normalize_memory_value(hook_text)
        proposal = {
            "predicate": predicate,
            "value": hook_text,
            "scope": MemoryScope.MATCH_PROFILE.value,
            "fact_type": MemoryFactType.INFERENCE.value,
            "confidence": "low",
            "evidence_text": "Hook candidate from profile observation.",
            "subject": visible_name,
            "qualifiers": {"app_id": app_id},
        }
        dedupe_key = build_dedupe_key(match_id, "propose", n_key, n_value, observation_id)
        proposals.append(
            ReviewItem(
                review_item_id=_review_item_id(match_id, n_key, n_value),
                session_id=session_id or "",
                match_id=match_id,
                observation_id=observation_id,
                proposal=proposal,
                status="pending",
                created_at=created_at,
                reported_at=None,
                reviewed_at=None,
                dedupe_key=dedupe_key,
                source=source,
                risk="low",
            )
        )
    for cue in observation.profile_observation.photo_cues:
        cue_text = str(cue).strip()
        if not cue_text:
            continue
        predicate = "photo_cue"
        n_key = normalized_fact_key(visible_name, predicate, {"app_id": app_id})
        if n_key in inference_keys:
            continue
        n_value = normalize_memory_value(cue_text)
        risk = classify_risk(predicate, cue_text)
        if risk == "high":
            risk = "medium"
        proposal = {
            "predicate": predicate,
            "value": cue_text,
            "scope": MemoryScope.MATCH_PROFILE.value,
            "fact_type": MemoryFactType.PHOTO_CUE.value,
            "confidence": "low",
            "evidence_text": "Photo cue from observation; hypothesis only.",
            "subject": visible_name,
            "qualifiers": {"app_id": app_id},
        }
        dedupe_key = build_dedupe_key(match_id, "propose", n_key, n_value, observation_id)
        proposals.append(
            ReviewItem(
                review_item_id=_review_item_id(match_id, n_key, n_value),
                session_id=session_id or "",
                match_id=match_id,
                observation_id=observation_id,
                proposal=proposal,
                status="pending",
                created_at=created_at,
                reported_at=None,
                reviewed_at=None,
                dedupe_key=dedupe_key,
                source=source,
                risk=risk,
            )
        )
    return proposals
