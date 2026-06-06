from __future__ import annotations

import hashlib
import json
from typing import Any

from dating_boost.core.memory.models import (
    EvidenceRef,
    MemoryEvent,
    MemoryEventType,
    MemoryFact,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.perception.observations import AppObservation


def events_from_observation(
    match_id: str,
    observation: AppObservation,
    created_at: str,
    *,
    identity_confidence: str | None = None,
    requires_user_confirmation: bool | None = None,
) -> list[MemoryEvent]:
    events: list[MemoryEvent] = [
        MemoryEvent(
            event_id=_event_id(match_id, observation.observation_id, "observation_ingested", "root"),
            event_type=MemoryEventType.OBSERVATION_INGESTED,
            match_id=match_id,
            scope=MemoryScope.CONVERSATION,
            created_at=created_at,
            payload={
                "observation_id": observation.observation_id,
                "app_id": observation.app_id,
                "page_type": observation.page_type.value,
                "captured_at": observation.captured_at,
            },
            evidence=_observation_evidence(
                observation,
                "Imported normalized app observation.",
                confidence=observation.page_confidence.value,
            ),
        )
    ]

    identity_confidence = identity_confidence or "new"
    requires_user_confirmation = bool(requires_user_confirmation)
    events.append(
        MemoryEvent(
            event_id=_event_id(
                match_id,
                observation.observation_id,
                "match_identity_assessed",
                f"{identity_confidence}|{requires_user_confirmation}",
            ),
            event_type=MemoryEventType.MATCH_IDENTITY_ASSESSED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "confidence": identity_confidence,
                "requires_user_confirmation": requires_user_confirmation,
                "visible_name": observation.match_identity_hints.visible_name,
            },
            evidence=_observation_evidence(
                observation,
                observation.match_identity_hints.evidence or "Match identity hints from observation.",
                confidence=identity_confidence,
            ),
        )
    )
    if str(identity_confidence).lower() == "conflict":
        events.append(
            MemoryEvent(
                event_id=_event_id(
                    match_id,
                    observation.observation_id,
                    "match_identity_conflict",
                    str(requires_user_confirmation),
                ),
                event_type=MemoryEventType.MATCH_IDENTITY_CONFLICT,
                match_id=match_id,
                scope=MemoryScope.MATCH_PROFILE,
                created_at=created_at,
                payload={
                    "reason": "Identity resolver found conflicting match candidates.",
                    "visible_name": observation.match_identity_hints.visible_name,
                    "requires_user_confirmation": True,
                },
                evidence=_observation_evidence(
                    observation,
                    observation.match_identity_hints.evidence or "Conflicting match identity hints from observation.",
                    confidence=identity_confidence,
                ),
            )
        )

    profile = observation.profile_observation
    if profile.profile_text.strip():
        fact = _fact(
            match_id=match_id,
            observation=observation,
            fact_id=_fact_id(match_id, observation.observation_id, "profile_text", profile.profile_text),
            fact_type=MemoryFactType.VISIBLE_FACT,
            predicate="profile_text",
            value=profile.profile_text.strip(),
            evidence_text="Visible profile text was summarized from the app.",
            created_at=created_at,
        )
        events.append(_fact_event(match_id, observation, created_at, MemoryEventType.PROFILE_FACT_OBSERVED, fact))

    for cue in observation.match_identity_hints.profile_cues:
        if not str(cue).strip():
            continue
        fact = _fact(
            match_id=match_id,
            observation=observation,
            fact_id=_fact_id(match_id, observation.observation_id, "profile_cue", cue),
            fact_type=MemoryFactType.VISIBLE_FACT,
            predicate="profile_cue",
            value=str(cue).strip(),
            evidence_text="Visible profile cue from match identity hints.",
            created_at=created_at,
        )
        events.append(_fact_event(match_id, observation, created_at, MemoryEventType.PROFILE_FACT_OBSERVED, fact))

    latest_refs = _latest_inbound_refs(observation)
    if latest_refs:
        events.append(
            MemoryEvent(
                event_id=_event_id(
                    match_id,
                    observation.observation_id,
                    "conversation_fact_observed",
                    json.dumps(latest_refs, sort_keys=True),
                ),
                event_type=MemoryEventType.CONVERSATION_FACT_OBSERVED,
                match_id=match_id,
                scope=MemoryScope.CONVERSATION,
                created_at=created_at,
                payload={
                    "observation_id": observation.observation_id,
                    "message_refs": latest_refs,
                },
                evidence=_observation_evidence(
                    observation,
                    "Latest inbound message refs were captured without storing full text.",
                    confidence=observation.page_confidence.value,
                ),
            )
        )

    for cue in profile.photo_cues:
        events.append(
            _fact_event(
                match_id,
                observation,
                created_at,
                MemoryEventType.INFERENCE_RECORDED,
                _fact(
                    match_id=match_id,
                    observation=observation,
                    fact_id=_fact_id(match_id, observation.observation_id, "photo_cue", cue),
                    fact_type=MemoryFactType.PHOTO_CUE,
                    predicate="photo_cue",
                    value=str(cue).strip(),
                    evidence_text="Photo cue from observation; hypothesis only.",
                    created_at=created_at,
                ),
            )
        )

    for hook in profile.hook_candidates:
        events.append(
            _fact_event(
                match_id,
                observation,
                created_at,
                MemoryEventType.INFERENCE_RECORDED,
                _fact(
                    match_id=match_id,
                    observation=observation,
                    fact_id=_fact_id(match_id, observation.observation_id, "hook_candidate", hook),
                    fact_type=MemoryFactType.INFERENCE,
                    predicate="hook_candidate",
                    value=str(hook).strip(),
                    evidence_text="Hook candidate from profile observation.",
                    created_at=created_at,
                ),
            )
        )

    return events


def _fact_event(
    match_id: str,
    observation: AppObservation,
    created_at: str,
    event_type: MemoryEventType,
    fact: MemoryFact,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=_event_id(match_id, observation.observation_id, event_type.value, fact.fact_id),
        event_type=event_type,
        match_id=match_id,
        scope=fact.scope,
        created_at=created_at,
        payload={"fact": fact.to_dict()},
        evidence=fact.evidence,
    )


def _fact(
    *,
    match_id: str,
    observation: AppObservation,
    fact_id: str,
    fact_type: MemoryFactType,
    predicate: str,
    value: str,
    evidence_text: str,
    created_at: str,
) -> MemoryFact:
    return MemoryFact(
        fact_id=fact_id,
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=fact_type,
        subject=observation.match_identity_hints.visible_name or match_id,
        predicate=predicate,
        value=value,
        qualifiers={"app_id": observation.app_id},
        confidence="medium" if fact_type != MemoryFactType.VISIBLE_FACT else observation.page_confidence.value,
        evidence=_observation_evidence(observation, evidence_text, confidence="medium"),
        created_at=created_at,
        last_seen_at=observation.captured_at,
    )


def _latest_inbound_refs(observation: AppObservation) -> list[dict[str, Any]]:
    messages = observation.conversation_observation.visible_messages
    latest = observation.conversation_observation.latest_inbound_messages
    refs: list[dict[str, Any]] = []
    for message in latest:
        index = _message_index(messages, message)
        text = str(message.get("text", ""))
        refs.append(
            {
                "message_index": index,
                "sender": str(message.get("sender", "")),
                "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                "char_count": len(text),
            }
        )
    return refs


def _message_index(messages: list[dict[str, str]], target: dict[str, str]) -> int | None:
    for index, message in enumerate(messages):
        if message == target:
            return index
    return None


def _observation_evidence(
    observation: AppObservation,
    evidence_text: str,
    *,
    confidence: str | None,
) -> EvidenceRef:
    return EvidenceRef(
        source_type="observation",
        source_observation_id=observation.observation_id,
        evidence_text=evidence_text,
        confidence=confidence,
    )


def _event_id(match_id: str, observation_id: str, event_type: str, content: str) -> str:
    digest = hashlib.sha256(
        "|".join([match_id, observation_id, event_type, content]).encode("utf-8")
    ).hexdigest()[:16]
    return f"mem_evt_{digest}"


def _fact_id(match_id: str, observation_id: str, predicate: str, value: str) -> str:
    digest = hashlib.sha256(
        "|".join([match_id, observation_id, predicate, str(value).strip()]).encode("utf-8")
    ).hexdigest()[:16]
    return f"mem_fact_{digest}"
