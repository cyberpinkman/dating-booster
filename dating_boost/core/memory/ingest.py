from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.draft_evidence import ConversationThreadRepository, LatestTurnRepository
from dating_boost.core.identity import observation_match_id, resolve_match_identity
from dating_boost.core.memory.extractors import events_from_observation
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.repositories import MatchRepository, ObservationRepository
from dating_boost.core.storage import storage_write_lock
from dating_boost.perception.observations import AppObservation


def store_observation_with_memory(root: Path, observation: AppObservation) -> dict[str, Any]:
    _validate_storage_id(observation.observation_id, "observation_id")
    with storage_write_lock(root):
        return _ingest_observation(root, observation)


def _ingest_observation(root: Path, observation: AppObservation) -> dict[str, Any]:
    match_repo = MatchRepository(root)
    name = (observation.match_identity_hints.visible_name or "").strip()
    if name:
        candidates = match_repo.list_match_candidates(visible_name=name)
    else:
        legacy = match_repo.get_match_record(observation_match_id(observation, legacy_unscoped=True))
        candidates = [legacy] if legacy else []
    identity = resolve_match_identity(observation, existing_matches=candidates)
    _validate_storage_id(identity.match_id, "match_id")
    ObservationRepository(root).save_observation(identity.match_id, observation)
    match_repo.upsert_match_from_observation(
        match_id=identity.match_id,
        observation=observation,
        confidence=identity.confidence.value,
        requires_user_confirmation=identity.requires_user_confirmation,
    )
    if identity.requires_user_confirmation:
        match_repo.append_identity_confirmation(
            match_id=identity.match_id,
            observation_id=observation.observation_id,
            confidence=identity.confidence.value,
            reason=identity.reason,
        )

    memory_repo = MemoryRepository(root)
    events = events_from_observation(
        identity.match_id,
        observation,
        created_at=observation.captured_at,
        identity_confidence=identity.confidence.value,
        requires_user_confirmation=identity.requires_user_confirmation,
    )
    for event in events:
        memory_repo.append_event(identity.match_id, event)
    projection = memory_repo.rebuild_projection(identity.match_id)
    ConversationThreadRepository(root).overwrite_from_observation(identity.match_id, observation)
    LatestTurnRepository(root).overwrite_from_observation(identity.match_id, observation)

    return {
        "status": "ok",
        "match_id": identity.match_id,
        "confidence": identity.confidence.value,
        "requires_user_confirmation": identity.requires_user_confirmation,
        "observation_id": observation.observation_id,
        "memory_event_count": len(memory_repo.load_events(identity.match_id)),
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _validate_storage_id(value: str, label: str) -> None:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}: {value!r}")
