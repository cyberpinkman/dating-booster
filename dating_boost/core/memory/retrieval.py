from __future__ import annotations

from typing import Any

from dating_boost.core.memory.models import (
    MatchMemoryProjection,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
)
from dating_boost.core.memory.semantic import SemanticHookProvider
from dating_boost.perception.observations import AppObservation


def build_memory_context(
    match_id: str,
    projection: MatchMemoryProjection,
    latest_observation: AppObservation | None,
    now: str,
    max_items: int | None,
    reply_mode: str | None = None,
    semantic_hook_provider: SemanticHookProvider | None = None,
    semantic_query: str | None = None,
) -> dict[str, Any]:
    latest_messages, latest_inbound_messages = _messages_from_observation(latest_observation)
    memory_items: list[dict[str, Any]] = []
    excluded_memory: list[dict[str, Any]] = []

    identity_item = {
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }
    if not projection.trusted_for_context:
        memory_items.append({"label": "identity_trust", "content": identity_item})
        for fact in [*projection.facts, *projection.inferences]:
            excluded_memory.append({"fact_id": fact.fact_id, "reason": "untrusted_identity"})
        return {
            "match_profile": {
                "match_id": match_id,
                "conversation_hooks": [],
                "possible_interests": [],
            },
            "conversation_memory": {
                "recent_messages": [],
                "latest_inbound_messages": [],
                "open_threads": [],
                "commitments": [],
                "running_summary": "",
            },
            "memory_items": _apply_budget(memory_items, max_items, excluded_memory),
            "excluded_memory": excluded_memory,
        }

    active_facts = _active_facts(projection.facts, now, excluded_memory)
    active_inferences = _active_facts(projection.inferences, now, excluded_memory)
    profile_text = " ".join(
        str(fact.value)
        for fact in active_facts
        if fact.predicate == "profile_text"
    ).strip()
    hooks = [
        str(fact.value)
        for fact in active_facts
        if fact.predicate in {"profile_cue", "hook_candidate"}
    ]
    hooks.extend(
        str(fact.value)
        for fact in active_inferences
        if fact.predicate == "hook_candidate"
    )
    hooks = _unique_texts(
        [
            *hooks,
            *_semantic_hooks(
                active_facts,
                active_inferences,
                provider=semantic_hook_provider,
                query=semantic_query,
                existing_hooks=hooks,
            ),
        ]
    )
    possible_interests = [
        {"name": str(fact.value), "confidence": fact.confidence, "source": fact.fact_type.value}
        for fact in active_inferences
    ]
    commitments = [commitment.to_dict() for commitment in projection.active_commitments]
    mode_feedback = _mode_feedback_preferences(projection, reply_mode)
    running_summary = _summary(profile_text, hooks)

    if latest_inbound_messages:
        memory_items.append({"label": "latest_inbound_messages", "content": latest_inbound_messages})
        memory_items.append(
            {
                "label": "turn_boundary",
                "content": {
                    "primary_hook": latest_inbound_messages[-1],
                    "rule": (
                        "Draft from match messages after the user's latest outbound. "
                        "Older visible messages are background only."
                    ),
                },
            }
        )
    if commitments:
        memory_items.append({"label": "active_commitments", "content": commitments})
    if mode_feedback:
        memory_items.append({"label": "mode_feedback_preferences", "content": mode_feedback})
    if active_facts:
        memory_items.append({"label": "match_facts", "content": [fact.to_dict() for fact in active_facts]})
    if running_summary:
        memory_items.append({"label": "conversation_summary", "content": running_summary})
    if hooks:
        memory_items.append({"label": "match_hooks", "content": hooks})
    if possible_interests:
        memory_items.append({"label": "low_confidence_hypotheses", "content": possible_interests})

    return {
        "match_profile": {
            "match_id": match_id,
            "profile_text": profile_text,
            "conversation_hooks": hooks,
            "possible_interests": possible_interests,
        },
        "conversation_memory": {
            "recent_messages": latest_messages,
            "latest_inbound_messages": latest_inbound_messages,
            "open_threads": _thread_cues(latest_observation),
            "commitments": commitments,
            "running_summary": running_summary,
        },
        "memory_items": _apply_budget(memory_items, max_items, excluded_memory),
        "excluded_memory": excluded_memory,
    }


def _active_facts(
    facts: list[MemoryFact],
    now: str,
    excluded_memory: list[dict[str, Any]],
) -> list[MemoryFact]:
    active: list[MemoryFact] = []
    for fact in facts:
        reason = _exclusion_reason(fact, now)
        if reason:
            excluded_memory.append({"fact_id": fact.fact_id, "reason": reason})
            continue
        active.append(fact)
    return active


def _exclusion_reason(fact: MemoryFact, now: str) -> str | None:
    if fact.status == MemoryFactStatus.CONFLICTED:
        return "conflicted"
    if fact.status == MemoryFactStatus.REJECTED:
        return "rejected"
    if fact.status == MemoryFactStatus.ARCHIVED:
        return "archived"
    if fact.valid_until and fact.valid_until < now:
        return "stale"
    if fact.confidence == "low" and fact.fact_type not in {MemoryFactType.INFERENCE, MemoryFactType.PHOTO_CUE}:
        return "low_confidence"
    return None


def _messages_from_observation(
    observation: AppObservation | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if observation is None:
        return [], []
    conversation = observation.conversation_observation
    return (
        [dict(message) for message in conversation.visible_messages],
        [dict(message) for message in conversation.latest_inbound_messages],
    )


def _thread_cues(observation: AppObservation | None) -> list[str]:
    if observation is None:
        return []
    return list(observation.conversation_observation.thread_cues)


def _summary(profile_text: str, hooks: list[str]) -> str:
    parts = [profile_text, *hooks[:3]]
    return " ".join(part for part in parts if part).strip()


def _mode_feedback_preferences(projection: MatchMemoryProjection, reply_mode: str | None) -> dict[str, Any]:
    if not reply_mode:
        return {}
    preferences = projection.feedback_preferences.get(str(reply_mode))
    if not isinstance(preferences, dict):
        mode_preferences = projection.feedback_preferences.get("mode_preferences")
        preferences = mode_preferences.get(str(reply_mode)) if isinstance(mode_preferences, dict) else None
    return dict(preferences) if isinstance(preferences, dict) and preferences else {}


def _semantic_hooks(
    active_facts: list[MemoryFact],
    active_inferences: list[MemoryFact],
    *,
    provider: SemanticHookProvider | None,
    query: str | None,
    existing_hooks: list[str],
) -> list[str]:
    if provider is None or not query:
        return []
    allowed_facts = {
        fact.fact_id: fact
        for fact in [*active_facts, *active_inferences]
        if _semantic_hook_fact_allowed(fact)
    }
    if not allowed_facts:
        return []
    existing = {str(item) for item in existing_hooks}
    hooks: list[str] = []
    for candidate in provider.retrieve_hooks(query, list(allowed_facts.values()), limit=5):
        fact = allowed_facts.get(candidate.fact_id)
        if fact is None:
            continue
        hook = str(fact.value).strip()
        if hook and hook not in existing:
            hooks.append(hook)
            existing.add(hook)
    return hooks


def _semantic_hook_fact_allowed(fact: MemoryFact) -> bool:
    if fact.fact_type == MemoryFactType.PHOTO_CUE:
        return False
    return fact.predicate in {"profile_text", "profile_cue", "hook_candidate"}


def _unique_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _apply_budget(
    items: list[dict[str, Any]],
    max_items: int | None,
    excluded_memory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if max_items is None or len(items) <= max_items:
        return items
    if max_items < 1:
        for item in items:
            excluded_memory.append({"label": item.get("label"), "reason": "budget"})
        return []

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()

    if max_items == 1:
        _select_first_label(items, "turn_boundary", selected, selected_ids)
    else:
        _select_first_label(items, "latest_inbound_messages", selected, selected_ids)
        _select_first_label(items, "turn_boundary", selected, selected_ids)

    for item in items:
        if len(selected) >= max_items:
            break
        if id(item) in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(id(item))

    for item in items:
        if id(item) not in selected_ids:
            excluded_memory.append({"label": item.get("label"), "reason": "budget"})
    return selected


def _select_first_label(
    items: list[dict[str, Any]],
    label: str,
    selected: list[dict[str, Any]],
    selected_ids: set[int],
) -> None:
    for item in items:
        if item.get("label") == label:
            selected.append(item)
            selected_ids.add(id(item))
            return
