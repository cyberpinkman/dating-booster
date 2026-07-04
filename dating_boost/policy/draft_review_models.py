"""Draft review public data model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

DRAFT_REVIEW_SCHEMA_VERSION = 1
DRAFT_REVIEW_MODES = {"display", "stage", "managed_live"}

__all__ = [
    "DRAFT_REVIEW_MODES",
    "DRAFT_REVIEW_SCHEMA_VERSION",
    "DraftReviewDecision",
    "DraftReviewFinding",
]

@dataclass(frozen=True)
class DraftReviewFinding:
    code: str
    category: str
    severity: str
    message: str
    revision_hint: str = ""
    blocks_display: bool = False
    blocks_stage: bool = False
    blocks_managed_send: bool = True
    requires_user_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DraftReviewDecision:
    schema_version: int
    status: str
    allowed_for_display: bool
    allowed_for_stage: bool
    allowed_for_managed_send: bool
    requires_user_confirmation: bool
    primary_reason: str
    summary: dict[str, Any]
    findings: list[DraftReviewFinding]
    revision_hints: list[str]
    payload_hash: str
    payload_format: str
    message_count: int
    review_id: str

    def to_dict(self, *, include_findings: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [finding.to_dict() for finding in self.findings] if include_findings else []
        return payload
