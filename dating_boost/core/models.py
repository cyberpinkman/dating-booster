from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    USER_CONFIRMED = "user_confirmed"


class MemoryKind(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    BOUNDARY = "boundary"
    INFERENCE = "inference"
    SUMMARY = "summary"
    HOOK = "hook"
    COMMITMENT = "commitment"
    RISK = "risk"
    FEEDBACK = "feedback"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    CONFLICTED = "conflicted"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ReplyMode(str, Enum):
    SELF = "self"
    ADAPTIVE = "adaptive"
    RECIPIENT_OPTIMIZED = "recipient_optimized"


class Divergence(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class MemoryItem:
    id: str
    kind: MemoryKind
    content: dict[str, Any]
    source_type: str
    evidence: str
    confidence: Confidence
    created_at: str
    last_seen_at: str
    supersedes: list[str] = field(default_factory=list)
    status: MemoryStatus = MemoryStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["confidence"] = self.confidence.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        return cls(
            id=data["id"],
            kind=MemoryKind(data["kind"]),
            content=dict(data["content"]),
            source_type=data["source_type"],
            evidence=data["evidence"],
            confidence=Confidence(data["confidence"]),
            created_at=data["created_at"],
            last_seen_at=data["last_seen_at"],
            supersedes=list(data.get("supersedes", [])),
            status=MemoryStatus(data.get("status", MemoryStatus.ACTIVE.value)),
        )


@dataclass(frozen=True)
class UserProfile:
    schema_version: int
    user_id: str
    facts: list[MemoryItem]
    preferences: list[MemoryItem]
    boundaries: list[MemoryItem]
    style_examples: list[str]
    goals: list[str]
    persona_baseline: str
    persona_range: list[str]
    stance_range: list[str]
    updated_at: str
    default_reply_mode: ReplyMode = ReplyMode.ADAPTIVE
