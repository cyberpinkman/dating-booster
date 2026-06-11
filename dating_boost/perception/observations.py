from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from dating_boost.core.models import Confidence
from dating_boost.perception.taxonomy import ExceptionState, PageType, SourceType


@dataclass(frozen=True)
class MatchIdentityHints:
    visible_name: str | None
    profile_cues: list[str]
    conversation_fingerprint: str | None
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchIdentityHints":
        return cls(
            visible_name=data.get("visible_name"),
            profile_cues=list(data.get("profile_cues", [])),
            conversation_fingerprint=data.get("conversation_fingerprint"),
            evidence=data.get("evidence", ""),
        )


@dataclass(frozen=True)
class ProfileObservation:
    profile_text: str
    photo_cues: list[str]
    hook_candidates: list[str]
    review_status: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileObservation":
        profile_text = data.get("profile_text", "")
        photo_cues = list(data.get("photo_cues", []))
        hook_candidates = list(data.get("hook_candidates", []))
        review_status = str(data.get("review_status") or "").strip()
        if not review_status:
            review_status = "observed" if _profile_observation_has_visible_content(
                profile_text,
                photo_cues,
                hook_candidates,
            ) else "missing"
        return cls(
            profile_text=profile_text,
            photo_cues=photo_cues,
            hook_candidates=hook_candidates,
            review_status=review_status,
            evidence=str(data.get("evidence") or ""),
        )


@dataclass(frozen=True)
class ConversationObservation:
    visible_messages: list[dict[str, str]]
    input_state: str
    thread_cues: list[str]
    latest_inbound_messages: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationObservation":
        visible_messages = [dict(message) for message in data.get("visible_messages", [])]
        latest_inbound_messages = data.get("latest_inbound_messages")
        if latest_inbound_messages is None:
            latest_inbound_messages = _derive_latest_inbound_messages(visible_messages)
        return cls(
            visible_messages=visible_messages,
            input_state=data.get("input_state", ""),
            thread_cues=list(data.get("thread_cues", [])),
            latest_inbound_messages=[dict(message) for message in latest_inbound_messages],
        )


@dataclass(frozen=True)
class AppObservation:
    observation_id: str
    source_type: SourceType
    app_id: str
    adapter_id: str
    captured_at: str
    page_type: PageType
    page_confidence: Confidence
    match_identity_hints: MatchIdentityHints
    profile_observation: ProfileObservation
    conversation_observation: ConversationObservation
    element_observations: list[dict[str, object]]
    exception_state: ExceptionState
    provenance: dict[str, str]
    raw_ref: str | None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        data["page_type"] = self.page_type.value
        data["page_confidence"] = self.page_confidence.value
        data["exception_state"] = self.exception_state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppObservation":
        return cls(
            observation_id=data["observation_id"],
            source_type=SourceType(data["source_type"]),
            app_id=data["app_id"],
            adapter_id=data.get("adapter_id", ""),
            captured_at=data["captured_at"],
            page_type=PageType(data["page_type"]),
            page_confidence=Confidence(data["page_confidence"]),
            match_identity_hints=MatchIdentityHints.from_dict(data.get("match_identity_hints", {})),
            profile_observation=ProfileObservation.from_dict(data.get("profile_observation", {})),
            conversation_observation=ConversationObservation.from_dict(
                data.get("conversation_observation", {})
            ),
            element_observations=[dict(observation) for observation in data.get("element_observations", [])],
            exception_state=ExceptionState(data.get("exception_state", ExceptionState.NONE.value)),
            provenance=dict(data.get("provenance", {})),
            raw_ref=data.get("raw_ref"),
        )

    @classmethod
    def minimal(
        cls,
        observation_id: str,
        source_type: SourceType,
        app_id: str,
        captured_at: str,
        page_type: PageType,
    ) -> "AppObservation":
        return cls(
            observation_id=observation_id,
            source_type=source_type,
            app_id=app_id,
            adapter_id="",
            captured_at=captured_at,
            page_type=page_type,
            page_confidence=Confidence.LOW,
            match_identity_hints=MatchIdentityHints(
                visible_name=None,
                profile_cues=[],
                conversation_fingerprint=None,
                evidence="",
            ),
            profile_observation=ProfileObservation(
                profile_text="",
                photo_cues=[],
                hook_candidates=[],
                review_status="missing",
                evidence="",
            ),
            conversation_observation=ConversationObservation(
                visible_messages=[],
                input_state="",
                thread_cues=[],
                latest_inbound_messages=[],
            ),
            element_observations=[],
            exception_state=ExceptionState.NONE,
            provenance={},
            raw_ref=None,
        )


def _derive_latest_inbound_messages(visible_messages: list[dict[str, str]]) -> list[dict[str, str]]:
    latest_user_index = -1
    for index, message in enumerate(visible_messages):
        if message.get("sender") == "user":
            latest_user_index = index
    return [
        dict(message)
        for message in visible_messages[latest_user_index + 1 :]
        if message.get("sender") == "match"
    ]


def _profile_observation_has_visible_content(
    profile_text: str,
    photo_cues: list[str],
    hook_candidates: list[str],
) -> bool:
    return bool(
        str(profile_text).strip()
        or any(str(item).strip() for item in photo_cues)
        or any(str(item).strip() for item in hook_candidates)
    )
