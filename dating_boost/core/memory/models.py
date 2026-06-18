from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


MATCH_MEMORY_PROJECTION_SCHEMA_VERSION = 1


class MemoryEventType(str, Enum):
    OBSERVATION_INGESTED = "observation_ingested"
    MATCH_IDENTITY_ASSESSED = "match_identity_assessed"
    PROFILE_FACT_OBSERVED = "profile_fact_observed"
    CONVERSATION_FACT_OBSERVED = "conversation_fact_observed"
    INFERENCE_RECORDED = "inference_recorded"
    FACT_CORRECTED = "fact_corrected"
    FACT_REJECTED = "fact_rejected"
    FACT_ARCHIVED = "fact_archived"
    MATCH_IDENTITY_CONFIRMED = "match_identity_confirmed"
    MATCH_IDENTITY_CONFLICT = "match_identity_conflict"
    COMMITMENT_CREATED = "commitment_created"
    COMMITMENT_RESOLVED = "commitment_resolved"
    FEEDBACK_RECORDED = "feedback_recorded"
    PROJECTION_REBUILT = "projection_rebuilt"


class MemoryScope(str, Enum):
    MATCH_PROFILE = "match_profile"
    CONVERSATION = "conversation"
    COMMITMENT = "commitment"
    FEEDBACK_PREFERENCE = "feedback_preference"


class MemoryFactType(str, Enum):
    VISIBLE_FACT = "visible_fact"
    USER_CONFIRMED = "user_confirmed"
    PHOTO_CUE = "photo_cue"
    INFERENCE = "inference"


class MemoryFactStatus(str, Enum):
    ACTIVE = "active"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class IdentityTrustStatus(str, Enum):
    NEW = "new"
    TRUSTED = "trusted"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"


@dataclass
class EvidenceRef:
    source_type: str
    evidence_text: str = ""
    confidence: str | None = None
    source_observation_id: str | None = None
    source_event_id: str | None = None
    message_index: int | None = None
    message_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_type == "observation" and not self.source_observation_id:
            raise ValueError("source_observation_id is required for observation evidence")
        self.metadata = dict(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRef":
        return cls(
            source_type=str(data["source_type"]),
            evidence_text=str(data.get("evidence_text", "")),
            confidence=data.get("confidence"),
            source_observation_id=data.get("source_observation_id"),
            source_event_id=data.get("source_event_id"),
            message_index=data.get("message_index"),
            message_hash=data.get("message_hash"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class MemoryFact:
    fact_id: str
    scope: MemoryScope | str
    fact_type: MemoryFactType | str
    subject: str
    predicate: str
    value: Any
    qualifiers: dict[str, Any]
    confidence: str
    evidence: EvidenceRef
    created_at: str
    last_seen_at: str
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes: list[str] = field(default_factory=list)
    status: MemoryFactStatus | str = MemoryFactStatus.ACTIVE
    normalized_key: str | None = None
    normalized_value: str | None = None

    def __post_init__(self) -> None:
        self.scope = MemoryScope(self.scope)
        self.fact_type = MemoryFactType(self.fact_type)
        self.status = MemoryFactStatus(self.status)
        self.qualifiers = dict(self.qualifiers)
        self.supersedes = list(self.supersedes)
        if not isinstance(self.evidence, EvidenceRef):
            self.evidence = EvidenceRef.from_dict(dict(self.evidence))
        computed_key = normalized_fact_key(
            self.subject,
            self.predicate,
            self.qualifiers,
        )
        if self.normalized_key is not None and self.normalized_key != computed_key:
            raise ValueError("normalized_key does not match subject, predicate, and qualifiers")
        self.normalized_key = self.normalized_key or computed_key
        self.normalized_value = self.normalized_value or normalize_memory_value(self.value)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = self.scope.value
        data["fact_type"] = self.fact_type.value
        data["status"] = self.status.value
        data["evidence"] = self.evidence.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryFact":
        return cls(
            fact_id=str(data["fact_id"]),
            scope=MemoryScope(data["scope"]),
            fact_type=MemoryFactType(data["fact_type"]),
            subject=_optional_text(data.get("subject")),
            predicate=_optional_text(data.get("predicate")),
            value=data.get("value"),
            qualifiers=dict(data.get("qualifiers", {})),
            confidence=str(data.get("confidence", "low")),
            evidence=EvidenceRef.from_dict(dict(data["evidence"])),
            created_at=str(data["created_at"]),
            last_seen_at=str(data["last_seen_at"]),
            valid_from=data.get("valid_from"),
            valid_until=data.get("valid_until"),
            supersedes=list(data.get("supersedes", [])),
            status=MemoryFactStatus(data.get("status", MemoryFactStatus.ACTIVE.value)),
            normalized_key=data.get("normalized_key"),
            normalized_value=data.get("normalized_value"),
        )


@dataclass
class CommitmentMemory:
    commitment_id: str
    text: str
    evidence: EvidenceRef
    created_at: str
    last_seen_at: str
    resolved_at: str | None = None
    status: str = "active"

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EvidenceRef):
            self.evidence = EvidenceRef.from_dict(dict(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = self.evidence.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommitmentMemory":
        return cls(
            commitment_id=str(data["commitment_id"]),
            text=str(data.get("text", "")),
            evidence=EvidenceRef.from_dict(dict(data["evidence"])),
            created_at=str(data["created_at"]),
            last_seen_at=str(data["last_seen_at"]),
            resolved_at=data.get("resolved_at"),
            status=str(data.get("status", "active")),
        )


@dataclass
class MemoryConflict:
    conflict_id: str
    normalized_key: str
    fact_ids: list[str]
    reason: str
    created_at: str

    def __post_init__(self) -> None:
        self.fact_ids = list(self.fact_ids)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryConflict":
        return cls(
            conflict_id=str(data["conflict_id"]),
            normalized_key=str(data["normalized_key"]),
            fact_ids=list(data.get("fact_ids", [])),
            reason=str(data.get("reason", "")),
            created_at=str(data["created_at"]),
        )


@dataclass
class MemoryEvent:
    event_id: str
    event_type: MemoryEventType | str
    match_id: str
    scope: MemoryScope | str
    created_at: str
    payload: dict[str, Any]
    evidence: EvidenceRef | None = None

    def __post_init__(self) -> None:
        self.event_type = MemoryEventType(self.event_type)
        self.scope = MemoryScope(self.scope)
        self.payload = dict(self.payload)
        if self.evidence is not None and not isinstance(self.evidence, EvidenceRef):
            self.evidence = EvidenceRef.from_dict(dict(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "match_id": self.match_id,
            "scope": self.scope.value,
            "created_at": self.created_at,
            "payload": self.payload,
            "evidence": self.evidence.to_dict() if self.evidence is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEvent":
        evidence = data.get("evidence")
        return cls(
            event_id=str(data["event_id"]),
            event_type=MemoryEventType(data["event_type"]),
            match_id=str(data["match_id"]),
            scope=MemoryScope(data["scope"]),
            created_at=str(data["created_at"]),
            payload=dict(data.get("payload", {})),
            evidence=EvidenceRef.from_dict(evidence) if isinstance(evidence, dict) else None,
        )


@dataclass
class MatchMemoryProjection:
    match_id: str
    identity_status: IdentityTrustStatus | str = IdentityTrustStatus.NEW
    trusted_for_context: bool = True
    trusted_for_managed_send: bool = False
    updated_at: str = ""
    matched_at: str | None = None
    profile_last_observed_at: str | None = None
    profile_source_runtime: dict[str, Any] = field(default_factory=dict)
    schema_version: int = MATCH_MEMORY_PROJECTION_SCHEMA_VERSION
    facts: list[MemoryFact] = field(default_factory=list)
    inferences: list[MemoryFact] = field(default_factory=list)
    conversation_threads: list[dict[str, Any]] = field(default_factory=list)
    active_commitments: list[CommitmentMemory] = field(default_factory=list)
    resolved_commitments: list[CommitmentMemory] = field(default_factory=list)
    feedback_preferences: dict[str, Any] = field(default_factory=dict)
    conflicts: list[MemoryConflict] = field(default_factory=list)
    last_event_id: str | None = None

    def __post_init__(self) -> None:
        self.identity_status = IdentityTrustStatus(self.identity_status)
        self.facts = [
            fact if isinstance(fact, MemoryFact) else MemoryFact.from_dict(dict(fact))
            for fact in self.facts
        ]
        self.inferences = [
            fact if isinstance(fact, MemoryFact) else MemoryFact.from_dict(dict(fact))
            for fact in self.inferences
        ]
        self.conversation_threads = [dict(item) for item in self.conversation_threads]
        self.active_commitments = [
            item if isinstance(item, CommitmentMemory) else CommitmentMemory.from_dict(dict(item))
            for item in self.active_commitments
        ]
        self.resolved_commitments = [
            item if isinstance(item, CommitmentMemory) else CommitmentMemory.from_dict(dict(item))
            for item in self.resolved_commitments
        ]
        self.feedback_preferences = dict(self.feedback_preferences)
        self.profile_source_runtime = dict(self.profile_source_runtime)
        self.conflicts = [
            item if isinstance(item, MemoryConflict) else MemoryConflict.from_dict(dict(item))
            for item in self.conflicts
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "match_id": self.match_id,
            "identity_status": self.identity_status.value,
            "trusted_for_context": self.trusted_for_context,
            "trusted_for_managed_send": self.trusted_for_managed_send,
            "updated_at": self.updated_at,
            "matched_at": self.matched_at,
            "profile_last_observed_at": self.profile_last_observed_at,
            "profile_source_runtime": dict(self.profile_source_runtime),
            "facts": [fact.to_dict() for fact in self.facts],
            "inferences": [fact.to_dict() for fact in self.inferences],
            "conversation_threads": [dict(item) for item in self.conversation_threads],
            "active_commitments": [item.to_dict() for item in self.active_commitments],
            "resolved_commitments": [item.to_dict() for item in self.resolved_commitments],
            "feedback_preferences": dict(self.feedback_preferences),
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            "last_event_id": self.last_event_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchMemoryProjection":
        return cls(
            schema_version=int(data.get("schema_version", MATCH_MEMORY_PROJECTION_SCHEMA_VERSION)),
            match_id=str(data["match_id"]),
            identity_status=IdentityTrustStatus(data.get("identity_status", IdentityTrustStatus.NEW.value)),
            trusted_for_context=bool(data.get("trusted_for_context", True)),
            trusted_for_managed_send=bool(data.get("trusted_for_managed_send", False)),
            updated_at=str(data.get("updated_at", "")),
            matched_at=data.get("matched_at"),
            profile_last_observed_at=data.get("profile_last_observed_at"),
            profile_source_runtime=dict(data.get("profile_source_runtime", {})),
            facts=[MemoryFact.from_dict(item) for item in data.get("facts", [])],
            inferences=[MemoryFact.from_dict(item) for item in data.get("inferences", [])],
            conversation_threads=[dict(item) for item in data.get("conversation_threads", [])],
            active_commitments=[
                CommitmentMemory.from_dict(item)
                for item in data.get("active_commitments", [])
            ],
            resolved_commitments=[
                CommitmentMemory.from_dict(item)
                for item in data.get("resolved_commitments", [])
            ],
            feedback_preferences=dict(data.get("feedback_preferences", {})),
            conflicts=[MemoryConflict.from_dict(item) for item in data.get("conflicts", [])],
            last_event_id=data.get("last_event_id"),
        )


def normalized_fact_key(subject: str, predicate: str, qualifiers: dict[str, Any]) -> str | None:
    normalized_subject = _normalize_text(subject)
    normalized_predicate = _normalize_text(predicate)
    if not normalized_subject or not normalized_predicate:
        return None
    qualifier_text = "|".join(
        f"{_normalize_text(key)}={normalize_memory_value(value)}"
        for key, value in sorted(qualifiers.items(), key=lambda item: str(item[0]))
    )
    return "|".join([normalized_subject, normalized_predicate, qualifier_text])


def normalize_memory_value(value: Any) -> str:
    if isinstance(value, str):
        return _normalize_text(value)
    return _normalize_text(json.dumps(value, sort_keys=True, ensure_ascii=True))


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
