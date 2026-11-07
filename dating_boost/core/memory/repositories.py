from __future__ import annotations

import heapq
from pathlib import Path
from typing import Any

from dating_boost.core.memory.extractors import events_from_observation
from dating_boost.core.memory.models import IdentityTrustStatus, MemoryEvent, MemoryEventType, MemoryFact, MatchMemoryProjection
from dating_boost.core.memory.reducers import reduce_match_memory
from dating_boost.core.memory.review_queue import ReviewQueueRepository
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.repositories import MatchRepository
from dating_boost.core.storage import JsonStorage, storage_write_lock
from dating_boost.perception.observations import AppObservation


def _validate_match_id(match_id: str) -> None:
    if match_id in {"", ".", ".."} or "/" in match_id or "\\" in match_id:
        raise ValueError(f"invalid match_id: {match_id!r}")


class MemoryRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def append_event(self, match_id: str, event: MemoryEvent) -> None:
        _validate_match_id(match_id)
        if event.match_id != match_id:
            raise ValueError("event.match_id must match repository match_id")
        events = self.load_events(match_id)
        if any(existing.event_id == event.event_id for existing in events):
            return
        self._storage.append_jsonl(self._events_path(match_id), event.to_dict())

    def replace_events(self, match_id: str, events: list[MemoryEvent]) -> None:
        _validate_match_id(match_id)
        deduped: dict[str, MemoryEvent] = {}
        for event in events:
            if event.match_id != match_id:
                raise ValueError("event.match_id must match repository match_id")
            deduped[event.event_id] = event
        # The supplied log order carries causality; wall-clock timestamps and IDs do not.
        self._storage.write_jsonl(self._events_path(match_id), [event.to_dict() for event in deduped.values()])

    def load_events(self, match_id: str) -> list[MemoryEvent]:
        _validate_match_id(match_id)
        return [
            MemoryEvent.from_dict(item)
            for item in self._storage.read_jsonl(self._events_path(match_id))
        ]

    def save_projection(self, match_id: str, projection: MatchMemoryProjection) -> None:
        _validate_match_id(match_id)
        if projection.match_id != match_id:
            raise ValueError("projection.match_id must match repository match_id")
        self._storage.write_json(self._projection_path(match_id), projection.to_dict())

    def load_projection(self, match_id: str) -> MatchMemoryProjection | None:
        _validate_match_id(match_id)
        try:
            data = self._storage.read_json(self._projection_path(match_id), expected_schema_version=1)
        except FileNotFoundError:
            return None
        return self._guard_app_scope(MatchMemoryProjection.from_dict(data))

    def _guard_app_scope(self, projection: MatchMemoryProjection) -> MatchMemoryProjection:
        if MatchRepository(self._storage.root).app_scope_requires_review(projection.match_id):
            projection.identity_status = IdentityTrustStatus.APP_SCOPE_REVIEW_REQUIRED
            projection.trusted_for_context = False
            projection.trusted_for_managed_send = False
        return projection

    def export_match(self, match_id: str) -> dict[str, Any]:
        _validate_match_id(match_id)
        projection = self.load_projection(match_id)
        events = self.load_events(match_id)
        observations = self._load_observation_export(match_id)
        feedback_events = self._storage.read_jsonl(self._feedback_events_path(match_id))
        identity_confirmations = [
            item
            for item in self._storage.read_jsonl(Path("matches") / "identity_confirmations.jsonl")
            if item.get("match_id") == match_id
        ]
        match_record = MatchRepository(self._storage.root).get_match_record(match_id)
        return {
            "schema_version": 1,
            "match_id": match_id,
            "identity_status": projection.identity_status.value if projection is not None else "not_found",
            "trusted_for_context": projection.trusted_for_context if projection is not None else False,
            "trusted_for_managed_send": projection.trusted_for_managed_send if projection is not None else False,
            "match_record": match_record,
            "observations": observations,
            "projection": projection.to_dict() if projection is not None else None,
            "events": [event.to_dict() for event in events],
            "feedback_events": feedback_events,
            "identity_confirmations": identity_confirmations,
            "conflicts": [conflict.to_dict() for conflict in projection.conflicts] if projection is not None else [],
            "raw_screenshots_included": False,
        }

    def delete_match_documents(self, match_id: str) -> int:
        _validate_match_id(match_id)
        with storage_write_lock(self._storage.root):
            store = ProductionDataStore(self._storage.root)
            if not store.db_path.exists():
                match_dir = self._storage.root / "matches" / match_id
                if not match_dir.exists():
                    return 0
                deleted_files = sum(1 for path in match_dir.rglob("*") if path.is_file())
                import shutil

                shutil.rmtree(match_dir)
            else:
                prefix = f"matches/{match_id}/"
                deleted_files = store.delete_documents_with_prefix(prefix) + store.delete_audit_events_with_stream_prefix(prefix)
            ReviewQueueRepository(self._storage.root).delete_items_for_match(match_id)
            return deleted_files

    def match_ids_with_observations(self) -> list[str]:
        store = ProductionDataStore(self._storage.root)
        if store.db_path.exists():
            match_ids = {
                parts[1]
                for document in store.list_documents(prefix="matches/")
                if (parts := Path(str(document["path"])).parts)
                and len(parts) == 3
                and parts[0] == "matches"
                and parts[2] == "observations.json"
            }
            for match_id in match_ids:
                _validate_match_id(match_id)
            return sorted(match_ids)
        matches_dir = self._storage.root / "matches"
        if not matches_dir.exists():
            return []
        match_ids: list[str] = []
        for child in sorted(matches_dir.iterdir(), key=lambda item: item.name):
            if not child.is_dir():
                continue
            if not (child / "observations.json").exists():
                continue
            _validate_match_id(child.name)
            match_ids.append(child.name)
        return match_ids

    def rebuild_projection(self, match_id: str) -> MatchMemoryProjection:
        events = self.load_events(match_id)
        projection = self._guard_app_scope(reduce_match_memory(match_id, events))
        self.save_projection(match_id, projection)
        return projection

    def rebuild_projection_from_observations(
        self,
        match_id: str,
        observations: list[AppObservation],
        *,
        identity_confidence: str | None = None,
        requires_user_confirmation: bool | None = None,
    ) -> MatchMemoryProjection:
        _validate_match_id(match_id)
        if MatchRepository(self._storage.root).app_scope_requires_review(match_id):
            raise ValueError("match_app_scope_review_required")
        existing_events = self.load_events(match_id)
        identity_by_observation_id = _identity_assessments_by_observation_id(existing_events)
        generated_events: list[MemoryEvent] = []
        for observation in sorted(observations, key=lambda item: (item.captured_at, item.observation_id)):
            identity_payload = identity_by_observation_id.get(observation.observation_id, {})
            generated_events.extend(
                events_from_observation(
                    match_id,
                    observation,
                    created_at=observation.captured_at,
                    identity_confidence=identity_payload.get("confidence", identity_confidence),
                    requires_user_confirmation=identity_payload.get(
                        "requires_user_confirmation",
                        requires_user_confirmation,
                    ),
                )
            )
        generated_by_id = {event.event_id: event for event in generated_events}
        replay_events: list[MemoryEvent] = []
        for event in existing_events:
            if event.evidence is not None and event.evidence.source_type == "observation":
                # Refresh extraction in place, omitting stale observation-derived events.
                replacement = generated_by_id.pop(event.event_id, None)
                if replacement is not None:
                    replay_events.append(replacement)
            else:
                replay_events.append(event)
        replay_events.extend(generated_by_id.values())
        self.replace_events(match_id, _order_fact_dependencies(replay_events))
        return self.rebuild_projection(match_id)

    def _events_path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "memory_events.jsonl"

    def _projection_path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "match_memory_projection.json"

    def _feedback_events_path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "feedback_events.jsonl"

    def _load_observation_export(self, match_id: str) -> list[dict[str, Any]]:
        try:
            document = self._storage.read_json(Path("matches") / match_id / "observations.json", expected_schema_version=1)
        except FileNotFoundError:
            return []
        observations = document.get("observations", [])
        if not isinstance(observations, list):
            return []
        return [
            _redact_raw_observation_refs(dict(observation))
            for observation in observations
            if isinstance(observation, dict)
        ]


def _order_fact_dependencies(events: list[MemoryEvent]) -> list[MemoryEvent]:
    """Repair explicit fact dependencies without inventing historical timestamps.

    Earlier rebuilds sorted by timestamp/ID, including backdated legacy feedback.
    Keep the stored order whenever possible, but a fact must exist before an event
    can correct or reject it. Unknown references cannot establish an ordering.
    """
    creators: dict[str, int] = {}
    creator_counts: dict[str, int] = {}
    coalesced_values: dict[tuple[str, str], set[str]] = {}
    coalesced_keys: dict[str, tuple[str, str]] = {}
    fact_events = {
        MemoryEventType.PROFILE_FACT_OBSERVED, MemoryEventType.CONVERSATION_FACT_OBSERVED,
        MemoryEventType.INFERENCE_RECORDED, MemoryEventType.FACT_CORRECTED,
    }
    for index, event in enumerate(events):
        fact = event.payload.get("fact")
        if event.event_type in fact_events and isinstance(fact, dict) and fact.get("fact_id"):
            fact_id = str(fact["fact_id"])
            creators.setdefault(fact_id, index)
            creator_counts[fact_id] = creator_counts.get(fact_id, 0) + 1
            # The reducer coalesces these observations into the first fact ID.
            # A previously reordered log can lose which ID was canonical and when
            # the same value was observed again relative to a user's rejection.
            if ((event.event_type == MemoryEventType.FACT_CORRECTED or (
                    event.event_type in {MemoryEventType.PROFILE_FACT_OBSERVED, MemoryEventType.CONVERSATION_FACT_OBSERVED}
                    and fact.get("fact_type") not in {"inference", "photo_cue"}))):
                normalized = MemoryFact.from_dict(fact)
                key = (str(normalized.normalized_key), str(normalized.normalized_value))
                coalesced_keys[fact_id] = key
                coalesced_values.setdefault(key, set()).add(fact_id)

    dependencies: list[set[int]] = [set() for _ in events]
    dependents: list[list[int]] = [[] for _ in events]
    for index, event in enumerate(events):
        references: list[str] = []
        if event.event_type in {MemoryEventType.FACT_CORRECTED, MemoryEventType.FACT_REJECTED, MemoryEventType.FACT_ARCHIVED}:
            references.append(str(event.payload.get("target_fact_id") or ""))
        elif event.event_type == MemoryEventType.FEEDBACK_RECORDED and event.payload.get("label") == "wrong_assumption":
            value = event.payload.get("referenced_memory_ids") or []
            references.extend(str(item) for item in (value if isinstance(value, list) else [value]))
        for reference in references:
            if (creators.get(reference, -1) > index and (
                    creator_counts[reference] > 1 or (reference in coalesced_keys
                    and len(coalesced_values[coalesced_keys[reference]]) > 1))):
                # Moving all repeated observations before the user action could
                # erase a legitimate later observation. Preserve evidence for review.
                raise ValueError("memory_fact_reference_order_ambiguous")
        dependencies[index] = {creators[reference] for reference in references if reference in creators}
        for dependency in dependencies[index]:
            dependents[dependency].append(index)

    ready = [index for index, required in enumerate(dependencies) if not required]
    heapq.heapify(ready)
    ordered: list[MemoryEvent] = []
    while ready:
        index = heapq.heappop(ready)
        ordered.append(events[index])
        for dependent in dependents[index]:
            dependencies[dependent].remove(index)
            if not dependencies[dependent]:
                heapq.heappush(ready, dependent)
    if len(ordered) != len(events):
        # Refuse the replacement so the original evidence remains available for review.
        raise ValueError("memory_fact_dependency_cycle")
    return ordered


def _identity_assessments_by_observation_id(events: list[MemoryEvent]) -> dict[str, dict[str, object]]:
    assessments: dict[str, dict[str, object]] = {}
    for event in events:
        if event.event_type != MemoryEventType.MATCH_IDENTITY_ASSESSED:
            continue
        observation_id = event.evidence.source_observation_id if event.evidence is not None else None
        if not observation_id:
            continue
        assessments[observation_id] = {
            "confidence": event.payload.get("confidence"),
            "requires_user_confirmation": event.payload.get("requires_user_confirmation"),
        }
    return assessments


def _redact_raw_observation_refs(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_raw_observation_refs(item)
            for key, item in value.items()
            if key != "raw_ref"
        }
    if isinstance(value, list):
        return [_redact_raw_observation_refs(item) for item in value]
    return value
