from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dating_boost.core.models import MemoryItem, ReplyMode, UserProfile
from dating_boost.core.storage import JsonStorage

if TYPE_CHECKING:
    from dating_boost.perception.observations import AppObservation


def _validate_match_id(match_id: str) -> None:
    if match_id in {"", ".", ".."} or "/" in match_id or "\\" in match_id:
        raise ValueError(f"invalid match_id: {match_id!r}")


class JsonMemoryRepository:
    _USER_PROFILE_PATH = Path("user_profile.json")

    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def save_user_profile(self, profile: UserProfile) -> None:
        self._storage.write_json(self._USER_PROFILE_PATH, self._profile_to_dict(profile))

    def load_user_profile(self) -> UserProfile:
        data = self._storage.read_json(self._USER_PROFILE_PATH, expected_schema_version=1)
        return self._profile_from_dict(data)

    def append_feedback_event(self, match_id: str, event: dict[str, object]) -> None:
        self._storage.append_jsonl(self._feedback_events_path(match_id), event)

    def load_feedback_events(self, match_id: str) -> list[dict[str, object]]:
        return self._storage.read_jsonl(self._feedback_events_path(match_id))

    def _feedback_events_path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "feedback_events.jsonl"

    def _validate_match_id(self, match_id: str) -> None:
        _validate_match_id(match_id)

    def _profile_to_dict(self, profile: UserProfile) -> dict[str, Any]:
        return {
            "schema_version": profile.schema_version,
            "user_id": profile.user_id,
            "facts": [item.to_dict() for item in profile.facts],
            "preferences": [item.to_dict() for item in profile.preferences],
            "boundaries": [item.to_dict() for item in profile.boundaries],
            "style_examples": list(profile.style_examples),
            "goals": list(profile.goals),
            "persona_baseline": profile.persona_baseline,
            "persona_range": list(profile.persona_range),
            "stance_range": list(profile.stance_range),
            "updated_at": profile.updated_at,
            "default_reply_mode": profile.default_reply_mode.value,
        }

    def _profile_from_dict(self, data: dict[str, Any]) -> UserProfile:
        return UserProfile(
            schema_version=data["schema_version"],
            user_id=data["user_id"],
            facts=[MemoryItem.from_dict(item) for item in data["facts"]],
            preferences=[MemoryItem.from_dict(item) for item in data["preferences"]],
            boundaries=[MemoryItem.from_dict(item) for item in data["boundaries"]],
            style_examples=list(data["style_examples"]),
            goals=list(data["goals"]),
            persona_baseline=data["persona_baseline"],
            persona_range=list(data["persona_range"]),
            stance_range=list(data["stance_range"]),
            updated_at=data["updated_at"],
            default_reply_mode=ReplyMode(data.get("default_reply_mode", ReplyMode.ADAPTIVE.value)),
        )


class ObservationRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def save_observation(self, match_id: str, observation: "AppObservation") -> None:
        document = self._load_document(match_id)
        observations = [
            item
            for item in document["observations"]
            if item.get("observation_id") != observation.observation_id
        ]
        observations.append(observation.to_dict())
        document["observations"] = observations
        self._storage.write_json(self._observations_path(match_id), document)

    def load_latest_observation(self, match_id: str) -> "AppObservation | None":
        from dating_boost.perception.observations import AppObservation

        document = self._load_document(match_id)
        observations = [AppObservation.from_dict(item) for item in document["observations"]]
        if not observations:
            return None
        return max(observations, key=lambda observation: (observation.captured_at, observation.observation_id))

    def _load_document(self, match_id: str) -> dict[str, Any]:
        try:
            return self._storage.read_json(self._observations_path(match_id), expected_schema_version=1)
        except FileNotFoundError:
            return {"schema_version": 1, "observations": []}

    def _observations_path(self, match_id: str) -> Path:
        _validate_match_id(match_id)
        return Path("matches") / match_id / "observations.json"


class MatchRepository:
    _INDEX_PATH = Path("matches") / "index.json"
    _CONFIRMATIONS_PATH = Path("matches") / "identity_confirmations.jsonl"

    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def list_match_candidates(self) -> list[dict[str, object]]:
        return [dict(record) for record in self._load_index()["matches"]]

    def upsert_match_from_observation(
        self,
        *,
        match_id: str,
        observation: "AppObservation",
        confidence: str,
        requires_user_confirmation: bool,
    ) -> None:
        _validate_match_id(match_id)
        index = self._load_index()
        records = {
            record["match_id"]: dict(record)
            for record in index["matches"]
        }
        current = records.get(
            match_id,
            {
                "match_id": match_id,
                "display_name": None,
                "profile_cues": [],
                "conversation_fingerprint": None,
                "observation_ids": [],
                "merged_match_ids": [],
            },
        )
        hints = observation.match_identity_hints
        if hints.visible_name:
            current["display_name"] = hints.visible_name
        current["profile_cues"] = _unique_strings([*current.get("profile_cues", []), *hints.profile_cues])
        if hints.conversation_fingerprint:
            current["conversation_fingerprint"] = hints.conversation_fingerprint
        current["observation_ids"] = _unique_strings(
            [*current.get("observation_ids", []), observation.observation_id]
        )
        current["identity_confidence"] = confidence
        current["requires_user_confirmation"] = requires_user_confirmation
        current["updated_at"] = observation.captured_at
        records[match_id] = current
        index["matches"] = sorted(records.values(), key=lambda record: str(record["match_id"]))
        self._storage.write_json(self._INDEX_PATH, index)

    def append_identity_confirmation(
        self,
        *,
        match_id: str,
        observation_id: str,
        confidence: str,
        reason: str,
    ) -> None:
        _validate_match_id(match_id)
        self._storage.append_jsonl(
            self._CONFIRMATIONS_PATH,
            {
                "match_id": match_id,
                "observation_id": observation_id,
                "confidence": confidence,
                "reason": reason,
            },
        )

    def merge_matches(self, *, source_match_id: str, target_match_id: str) -> None:
        _validate_match_id(source_match_id)
        _validate_match_id(target_match_id)
        index = self._load_index()
        records = {record["match_id"]: dict(record) for record in index["matches"]}
        if source_match_id not in records or target_match_id not in records:
            raise ValueError("source and target match records must exist before merge")
        source = records.pop(source_match_id)
        target = records[target_match_id]
        target["profile_cues"] = _unique_strings(
            [*target.get("profile_cues", []), *source.get("profile_cues", [])]
        )
        target["observation_ids"] = _unique_strings(
            [*target.get("observation_ids", []), *source.get("observation_ids", [])]
        )
        target["merged_match_ids"] = _unique_strings(
            [*target.get("merged_match_ids", []), source_match_id, *source.get("merged_match_ids", [])]
        )
        index["matches"] = sorted(records.values(), key=lambda record: str(record["match_id"]))
        self._storage.write_json(self._INDEX_PATH, index)

    def _load_index(self) -> dict[str, Any]:
        try:
            return self._storage.read_json(self._INDEX_PATH, expected_schema_version=1)
        except FileNotFoundError:
            return {"schema_version": 1, "matches": []}


def _unique_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
