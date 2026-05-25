"""Content policy checks for generated reply drafts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


@dataclass(frozen=True)
class ContentPolicyDecision:
    allowed: bool
    severity: str
    reason: str
    requires_user_confirmation: bool = False


def evaluate_draft_content(draft: Any, context_pack: Mapping[str, Any]) -> ContentPolicyDecision:
    """Evaluate generated reply variants against MVP content safety rules."""

    if _forbids_overseas_study(context_pack) and _draft_contains(draft, "studied in london"):
        return ContentPolicyDecision(
            allowed=False,
            severity="high",
            reason="Draft claims overseas study despite a user boundary forbidding it.",
        )

    if _requires_labeled_divergence_confirmation(draft):
        return ContentPolicyDecision(
            allowed=True,
            severity="medium",
            reason="Medium or high persona/stance divergence needs user confirmation when unlabeled.",
            requires_user_confirmation=True,
        )

    return ContentPolicyDecision(
        allowed=True,
        severity="low",
        reason="Draft content passed MVP policy checks.",
    )


def _forbids_overseas_study(context_pack: Mapping[str, Any]) -> bool:
    for item in context_pack.get("items", []):
        if not isinstance(item, Mapping) or item.get("label") != "user_boundaries":
            continue
        content = item.get("content", "")
        if _mentions_forbidden_overseas_study(_flatten_text(content).lower()):
            return True
    return False


def _mentions_forbidden_overseas_study(text: str) -> bool:
    forbid_terms = ("do not", "don't", "dont", "never", "avoid", "forbid", "forbids", "forbidden")
    return any(term in text for term in forbid_terms) and "overseas study" in text


def _draft_contains(draft: Any, needle: str) -> bool:
    for field_name in ("best_reply", "safer_reply", "bolder_reply"):
        value = getattr(draft, field_name, "")
        if isinstance(value, str) and needle in value.lower():
            return True
    return False


def _requires_labeled_divergence_confirmation(draft: Any) -> bool:
    mode_notes = getattr(draft, "mode_notes", "")
    if isinstance(mode_notes, str) and mode_notes.strip():
        return False

    return any(
        _normalize_divergence(getattr(draft, field_name, "")) in {"medium", "high"}
        for field_name in ("stance_divergence", "persona_divergence")
    )


def _normalize_divergence(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value).lower()
    return str(value).lower()


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)
