from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any

from dating_boost.core.models import ReplyMode


SAFETY_CONSTRAINTS = [
    "Do not invent or contradict hard facts.",
    "Do not rewrite historical events, past messages, or existing commitments.",
    (
        "Persona and stance may be modulated, but must not be presented as "
        "past fact, identity change, or contradiction of user boundaries."
    ),
    (
        "Medium or high persona/stance divergence must be labeled and "
        "explainable for downstream policy and generation."
    ),
]


def build_context_pack(
    user_profile: dict[str, Any],
    match_profile: dict[str, Any],
    conversation_memory: dict[str, Any],
    reply_mode: ReplyMode | str,
    max_items: int | None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    recent_messages = conversation_memory.get("recent_messages")
    previous_messages = recent_messages[:-1] if recent_messages else recent_messages

    _append(items, "user_boundaries", user_profile.get("boundaries"))
    _append(items, "user_hard_facts", user_profile.get("facts"))
    if recent_messages:
        _append(items, "latest_message", recent_messages[-1])
    _append(items, "open_threads", conversation_memory.get("open_threads"))
    _append(items, "historical_commitments", conversation_memory.get("commitments"))
    _append(items, "recent_messages", previous_messages)
    _append(items, "conversation_summary", conversation_memory.get("running_summary"))
    _append(items, "match_hooks", match_profile.get("conversation_hooks"))
    _append(items, "style_examples", user_profile.get("style_examples"))
    _append(
        items,
        "low_confidence_hypotheses",
        [
            interest
            for interest in match_profile.get("possible_interests", [])
            if interest.get("confidence") != "high"
        ],
    )

    if max_items is not None:
        items = items[:max_items]

    return {
        "reply_mode": _reply_mode_value(reply_mode),
        "items": items,
        "safety_constraints": list(SAFETY_CONSTRAINTS),
    }


def _append(items: list[dict[str, Any]], label: str, content: Any) -> None:
    if content:
        items.append({"label": label, "content": deepcopy(content)})


def _reply_mode_value(reply_mode: ReplyMode | str) -> str:
    if isinstance(reply_mode, Enum):
        return str(reply_mode.value)
    return str(reply_mode)
