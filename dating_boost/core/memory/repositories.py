from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from dating_boost.core.memory.extractors import events_from_observation
from dating_boost.core.memory.models import MemoryEvent, MemoryEventType, MatchMemoryProjection
from dating_boost.core.memory.reducers import reduce_match_memory
from dating_boost.core.storage import JsonStorage
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
        ordered = sorted(deduped.values(), key=lambda event: (event.created_at, event.event_id))
        self._storage.write_jsonl(self._events_path(match_id), [event.to_dict() for event in ordered])

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
        return MatchMemoryProjection.from_dict(data)

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
        match_record = self._load_match_record(match_id)
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
        match_dir = self._storage.root / "matches" / match_id
        if not match_dir.exists():
            return 0
        deleted_files = sum(1 for path in match_dir.rglob("*") if path.is_file())
        shutil.rmtree(match_dir)
        return deleted_files

    def match_ids_with_observations(self) -> list[str]:
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
        projection = reduce_match_memory(match_id, events)
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
        preserved_events = [
            event
            for event in existing_events
            if event.evidence is None or event.evidence.source_type != "observation"
        ]
        self.replace_events(match_id, [*preserved_events, *generated_events])
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

    def _load_match_record(self, match_id: str) -> dict[str, Any] | None:
        try:
            index = self._storage.read_json(Path("matches") / "index.json", expected_schema_version=1)
        except FileNotFoundError:
            return None
        matches = index.get("matches", [])
        if not isinstance(matches, list):
            return None
        for record in matches:
            if isinstance(record, dict) and record.get("match_id") == match_id:
                return dict(record)
        return None


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
