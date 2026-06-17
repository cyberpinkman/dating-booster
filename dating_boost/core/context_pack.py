from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dating_boost.core.models import ReplyMode

DEFAULT_LOCAL_TIMEZONE = "Asia/Shanghai"


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
    current_time_iso: str | None = None,
    local_timezone: str = DEFAULT_LOCAL_TIMEZONE,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    recent_messages = conversation_memory.get("recent_messages")
    previous_messages = recent_messages[:-1] if recent_messages else recent_messages
    latest_inbound_messages = conversation_memory.get("latest_inbound_messages")

    _append(items, "user_boundaries", user_profile.get("boundaries"))
    _append(items, "user_hard_facts", user_profile.get("facts"))
    _append(items, "user_disclosure_profile", user_profile.get("disclosure_profile"))
    _append(items, "user_disclosure_readiness", user_profile.get("disclosure_readiness"))
    _append(items, "goal_plan", conversation_memory.get("goal_plan"))
    _append(items, "planner_recommendation", conversation_memory.get("planner_recommendation"))
    _append_memory_items(items, conversation_memory.get("memory_items"))
    _append(items, "excluded_memory", conversation_memory.get("excluded_memory"))
    _append(items, "conversation_scores", conversation_memory.get("conversation_scores"))
    _append(items, "topic_lifecycle", conversation_memory.get("topic_lifecycle"))
    _append(items, "avoid_next", conversation_memory.get("avoid_next"))
    _append(items, "appointment_constraints", conversation_memory.get("appointment_constraints"))
    _append(items, "global_slot_conflicts", conversation_memory.get("global_slot_conflicts"))
    _append(items, "send_time_context", _send_time_context(current_time_iso, local_timezone))
    if latest_inbound_messages:
        _append(items, "latest_inbound_messages", latest_inbound_messages)
        _append(
            items,
            "turn_boundary",
            {
                "primary_hook": latest_inbound_messages[-1],
                "rule": (
                    "Draft from match messages after the user's latest outbound. "
                    "Older visible messages are background only."
                ),
            },
        )
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
    if content and not any(item["label"] == label for item in items):
        items.append({"label": label, "content": deepcopy(content)})


def _append_memory_items(items: list[dict[str, Any]], memory_items: Any) -> None:
    if not isinstance(memory_items, list):
        return
    for item in memory_items:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str):
            continue
        _append(items, label, item.get("content"))


def _reply_mode_value(reply_mode: ReplyMode | str) -> str:
    if isinstance(reply_mode, Enum):
        return str(reply_mode.value)
    return str(reply_mode)


def _send_time_context(current_time_iso: str | None, local_timezone: str) -> dict[str, Any] | None:
    if not current_time_iso:
        return None
    try:
        parsed = datetime.fromisoformat(current_time_iso.replace("Z", "+00:00"))
    except ValueError:
        return {"current_utc": current_time_iso, "local_timezone": local_timezone, "time_parse_status": "invalid"}
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    utc_time = parsed.astimezone(timezone.utc)
    try:
        tz = ZoneInfo(local_timezone)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
        local_timezone = "UTC"
    local_time = utc_time.astimezone(tz)
    return {
        "current_utc": utc_time.isoformat().replace("+00:00", "Z"),
        "current_local": local_time.isoformat(),
        "local_timezone": local_timezone,
        "local_hour": local_time.hour,
        "local_weekday": local_time.weekday(),
    }
