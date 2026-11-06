from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from dating_boost.core.identity import has_identity_app_id
from dating_boost.core.models import MemoryItem, ReplyMode, UserProfile
from dating_boost.core.storage import JsonStorage, SchemaVersionError, StorageCorruptionError

if TYPE_CHECKING:
    from dating_boost.perception.observations import AppObservation


def _validate_match_id(match_id: str) -> None:
    if match_id in {"", ".", ".."} or "/" in match_id or "\\" in match_id:
        raise ValueError(f"invalid match_id: {match_id!r}")


def user_profile_to_dict(profile: UserProfile) -> dict[str, Any]:
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


def user_profile_from_dict(data: dict[str, Any]) -> UserProfile:
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
        return user_profile_to_dict(profile)

    def _profile_from_dict(self, data: dict[str, Any]) -> UserProfile:
        return user_profile_from_dict(data)


class ObservationRepository:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def save_observation(self, match_id: str, observation: "AppObservation") -> None:
        if not has_identity_app_id(observation.app_id):
            raise ValueError("observation requires an app_id")
        MatchRepository(self._storage.root).validate_observation_app(match_id, observation.app_id)
        document = self._load_document(match_id)
        if any(item.get("app_id") != observation.app_id for item in document["observations"]):
            raise ValueError("observation does not match the stored app scope")
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

    def load_observations(self, match_id: str) -> list["AppObservation"]:
        from dating_boost.perception.observations import AppObservation

        document = self._load_document(match_id)
        return [AppObservation.from_dict(item) for item in document["observations"]]

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

    def list_match_candidates(self, *, visible_name: str | None = None) -> list[dict[str, Any]]:
        records = self._load_index()["matches"]
        if visible_name is not None:
            name = visible_name.strip().casefold()
            records = [record for record in records if name and str(record.get("display_name") or "").strip().casefold() == name]
        return [self._scoped_record(record) for record in records]

    def get_match_record(self, match_id: str) -> dict[str, Any] | None:
        _validate_match_id(match_id)
        for record in self._load_index()["matches"]:
            if record["match_id"] == match_id:
                return self._scoped_record(record)
        return None

    def get_match_app_id(self, match_id: str) -> str | None:
        record = self.get_match_record(match_id)
        return record["app_id"] if record else None

    def _stored_app_scope(self, match_id: str) -> tuple[str | None, str]:
        record = self.get_match_record(match_id)
        if record:
            return record["app_id"], record["app_scope_status"]
        # Historical merges removed the source index entry but kept its observations.
        # Scope those archives on direct access without restoring them as candidates.
        return self._legacy_app_scope(match_id, [])

    def app_scope_requires_review(self, match_id: str) -> bool:
        return self._stored_app_scope(match_id)[1] in {"unknown", "mixed"}

    def validate_observation_app(self, match_id: str, app_id: str) -> None:
        stored_app, status = self._stored_app_scope(match_id)
        if status != "absent" and stored_app != app_id:
            raise ValueError("observation does not match the stored app scope")

    def _scoped_record(self, record: dict[str, Any]) -> dict[str, Any]:
        app_id = record.get("app_id")
        if has_identity_app_id(app_id):
            return {**record, "app_scope_status": "verified"}
        app_id, status = self._legacy_app_scope(
            record["match_id"], record.get("observation_ids", [])
        )
        scoped = {**record, "app_id": app_id, "app_scope_status": "unknown" if status == "absent" else status}
        if app_id is None:
            scoped["requires_user_confirmation"] = True
        return scoped

    def _legacy_app_scope(self, match_id: str, indexed_ids: list[str]) -> tuple[str | None, str]:
        _validate_match_id(match_id)
        base = Path("matches") / match_id
        try:
            doc = self._storage.read_json(base / "observations.json", expected_schema_version=1)
            events = self._storage.read_jsonl(base / "memory_events.jsonl")
        except FileNotFoundError:
            return None, "absent"
        except (SchemaVersionError, StorageCorruptionError):
            return None, "unknown"
        history = doc.get("observations")
        if not isinstance(history, list) or not history or not all(isinstance(item, dict) for item in history):
            return None, "unknown"
        app_evidence = [item.get("app_id") for item in history]
        raw_ids = [item.get("observation_id") for item in history]
        if not isinstance(indexed_ids, list):
            return None, "unknown"
        referenced_ids = list(indexed_ids)
        # Older stores keyed raw observations by observation_id alone. Their native
        # events can still identify the original app after another app replaced a row.
        for event in events:
            evidence = event.get("evidence") or {}
            payload = event.get("payload")
            if not isinstance(evidence, dict) or not isinstance(payload, dict):
                return None, "unknown"
            if evidence.get("source_type") == "memory_inheritance":
                continue
            if event.get("event_type") == "observation_ingested":
                app_evidence.append(payload.get("app_id"))
                referenced_ids.append(payload.get("observation_id"))
            elif evidence.get("source_type") == "observation" and isinstance(payload.get("fact"), dict):
                qualifiers = payload["fact"].get("qualifiers") or {}
                if not isinstance(qualifiers, dict):
                    return None, "unknown"
                if "app_id" in qualifiers:
                    app_evidence.append(qualifiers["app_id"])
                    referenced_ids.append(evidence.get("source_observation_id"))

        apps = {app for app in app_evidence if has_identity_app_id(app)}
        if len(apps) > 1:
            return None, "mixed"
        if not all(has_identity_app_id(app) for app in app_evidence):
            return None, "unknown"
        if not all(isinstance(item, str) and item for item in [*raw_ids, *referenced_ids]):
            return None, "unknown"
        if not set(referenced_ids).issubset(raw_ids):
            return None, "unknown"
        return apps.pop(), "verified"

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
        if not has_identity_app_id(observation.app_id):
            raise ValueError("match observation requires an app_id")
        self.validate_observation_app(match_id, observation.app_id)
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
        current["app_id"] = observation.app_id
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

    def remove_identity_confirmations(self, match_id: str) -> int:
        _validate_match_id(match_id)
        events = self._storage.read_jsonl(self._CONFIRMATIONS_PATH)
        kept_events = [
            event
            for event in events
            if event.get("match_id") != match_id
        ]
        removed = len(events) - len(kept_events)
        if removed:
            self._storage.write_jsonl(self._CONFIRMATIONS_PATH, kept_events)
        return removed

    def validate_same_app_merge(self, *, source_match_id: str, target_match_id: str) -> None:
        if source_match_id == target_match_id:
            raise ValueError("source and target match IDs must differ")
        source_app = self.get_match_app_id(source_match_id)
        if source_app is None or source_app != self.get_match_app_id(target_match_id):
            raise ValueError("identity merge requires source and target from the same verified app")

    def merge_matches(self, *, source_match_id: str, target_match_id: str) -> None:
        self.validate_same_app_merge(source_match_id=source_match_id, target_match_id=target_match_id)
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

    def delete_match(self, match_id: str) -> int:
        _validate_match_id(match_id)
        index = self._load_index()
        before = len(index["matches"])
        index["matches"] = [
            record
            for record in index["matches"]
            if record.get("match_id") != match_id
        ]
        removed = before - len(index["matches"])
        if removed:
            self._storage.write_json(self._INDEX_PATH, index)
        return removed

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
