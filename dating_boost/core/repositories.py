from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost.core.models import MemoryItem, ReplyMode, UserProfile
from dating_boost.core.storage import JsonStorage, StorageCorruptionError


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
        relative_path = self._feedback_events_path(match_id)
        path = self._storage._resolve_path(relative_path)
        if not path.exists():
            return []

        events: list[dict[str, object]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise StorageCorruptionError(f"expected JSON object in JSONL: {relative_path}")
                events.append(event)
        except json.JSONDecodeError as exc:
            raise StorageCorruptionError(f"corrupt JSONL: {relative_path}") from exc
        return events

    def _feedback_events_path(self, match_id: str) -> Path:
        self._validate_match_id(match_id)
        return Path("matches") / match_id / "feedback_events.jsonl"

    def _validate_match_id(self, match_id: str) -> None:
        if match_id in {"", ".", ".."} or "/" in match_id or "\\" in match_id:
            raise ValueError(f"invalid match_id: {match_id!r}")

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
