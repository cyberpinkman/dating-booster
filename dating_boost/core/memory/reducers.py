from __future__ import annotations

from dataclasses import replace
from typing import Any

from dating_boost.core.memory.models import (
    CommitmentMemory,
    IdentityTrustStatus,
    MatchMemoryProjection,
    MemoryConflict,
    MemoryEvent,
    MemoryEventType,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
)


def reduce_match_memory(match_id: str, events: list[MemoryEvent]) -> MatchMemoryProjection:
    facts_by_id: dict[str, MemoryFact] = {}
    fact_order: list[str] = []
    inferences: dict[str, MemoryFact] = {}
    inference_order: list[str] = []
    active_commitments: dict[str, CommitmentMemory] = {}
    resolved_commitments: dict[str, CommitmentMemory] = {}
    feedback_preferences: dict[str, Any] = {}
    conflicts: list[MemoryConflict] = []
    identity_status = IdentityTrustStatus.NEW
    trusted_for_context = True
    trusted_for_managed_send = False
    updated_at = ""
    last_event_id: str | None = None

    for event in events:
        if event.match_id != match_id:
            continue
        updated_at = event.created_at
        last_event_id = event.event_id

        if event.event_type == MemoryEventType.MATCH_IDENTITY_ASSESSED:
            if identity_status in {IdentityTrustStatus.CONFLICTED, IdentityTrustStatus.TRUSTED}:
                continue
            confidence = str(event.payload.get("confidence", "")).lower()
            requires_confirmation = bool(event.payload.get("requires_user_confirmation", False))
            if confidence == "high" and not requires_confirmation:
                identity_status = IdentityTrustStatus.TRUSTED
                trusted_for_context = True
                trusted_for_managed_send = True
            elif confidence == "new" and not requires_confirmation:
                identity_status = IdentityTrustStatus.NEW
                trusted_for_context = True
                trusted_for_managed_send = False
            else:
                identity_status = IdentityTrustStatus.NEEDS_CONFIRMATION
                trusted_for_context = False
                trusted_for_managed_send = False
        elif event.event_type == MemoryEventType.MATCH_IDENTITY_CONFLICT:
            identity_status = IdentityTrustStatus.CONFLICTED
            trusted_for_context = False
            trusted_for_managed_send = False
        elif event.event_type == MemoryEventType.MATCH_IDENTITY_CONFIRMED:
            identity_status = IdentityTrustStatus.TRUSTED
            trusted_for_context = True
            trusted_for_managed_send = True
        elif event.event_type in {
            MemoryEventType.PROFILE_FACT_OBSERVED,
            MemoryEventType.CONVERSATION_FACT_OBSERVED,
            MemoryEventType.INFERENCE_RECORDED,
        }:
            fact_payload = event.payload.get("fact")
            if isinstance(fact_payload, dict):
                fact = MemoryFact.from_dict(fact_payload)
                if event.event_type == MemoryEventType.INFERENCE_RECORDED or fact.fact_type in {
                    MemoryFactType.INFERENCE,
                    MemoryFactType.PHOTO_CUE,
                }:
                    _upsert_inference(fact, inferences, inference_order)
                else:
                    _upsert_fact(fact, facts_by_id, fact_order)
        elif event.event_type == MemoryEventType.FACT_CORRECTED:
            target_id = str(event.payload.get("target_fact_id", ""))
            if target_id in facts_by_id:
                facts_by_id[target_id] = replace(
                    facts_by_id[target_id],
                    status=MemoryFactStatus.ARCHIVED,
                )
            fact_payload = event.payload.get("fact")
            if isinstance(fact_payload, dict):
                fact = MemoryFact.from_dict(fact_payload)
                supersedes = list(fact.supersedes)
                if target_id and target_id not in supersedes:
                    supersedes.append(target_id)
                facts_by_id[fact.fact_id] = replace(
                    fact,
                    supersedes=supersedes,
                    status=MemoryFactStatus.ACTIVE,
                )
                if fact.fact_id not in fact_order:
                    fact_order.append(fact.fact_id)
        elif event.event_type == MemoryEventType.FACT_REJECTED:
            target_id = str(event.payload.get("target_fact_id", ""))
            if target_id in facts_by_id:
                facts_by_id[target_id] = replace(
                    facts_by_id[target_id],
                    status=MemoryFactStatus.REJECTED,
                )
            if target_id in inferences:
                inferences[target_id] = replace(
                    inferences[target_id],
                    status=MemoryFactStatus.REJECTED,
                )
        elif event.event_type == MemoryEventType.FACT_ARCHIVED:
            target_id = str(event.payload.get("target_fact_id", ""))
            if target_id in facts_by_id:
                facts_by_id[target_id] = replace(
                    facts_by_id[target_id],
                    status=MemoryFactStatus.ARCHIVED,
                )
            if target_id in inferences:
                inferences[target_id] = replace(
                    inferences[target_id],
                    status=MemoryFactStatus.ARCHIVED,
                )
        elif event.event_type == MemoryEventType.COMMITMENT_CREATED:
            commitment_payload = event.payload.get("commitment")
            if isinstance(commitment_payload, dict):
                commitment = CommitmentMemory.from_dict(commitment_payload)
                active_commitments[commitment.commitment_id] = commitment
        elif event.event_type == MemoryEventType.COMMITMENT_RESOLVED:
            commitment_id = str(event.payload.get("commitment_id", ""))
            if commitment_id in active_commitments:
                commitment = active_commitments.pop(commitment_id)
                resolved_commitments[commitment_id] = replace(
                    commitment,
                    status="resolved",
                    resolved_at=str(event.payload.get("resolved_at") or event.created_at),
                    last_seen_at=event.created_at,
                )
        elif event.event_type == MemoryEventType.FEEDBACK_RECORDED:
            mode = str(event.payload.get("mode", "unknown"))
            label = str(event.payload.get("label", "unknown"))
            mode_preferences = feedback_preferences.setdefault(mode, {"labels": {}})
            labels = mode_preferences.setdefault("labels", {})
            labels[label] = int(labels.get(label, 0)) + 1
            _apply_feedback_signal(
                event.payload,
                mode_preferences,
                facts_by_id,
                inferences,
            )

    conflicts = _recompute_fact_conflicts(
        facts_by_id,
        fact_order,
        created_at=updated_at,
    )

    return MatchMemoryProjection(
        match_id=match_id,
        facts=[facts_by_id[fact_id] for fact_id in fact_order],
        inferences=[inferences[fact_id] for fact_id in inference_order],
        active_commitments=sorted(
            active_commitments.values(),
            key=lambda item: item.commitment_id,
        ),
        resolved_commitments=sorted(
            resolved_commitments.values(),
            key=lambda item: item.commitment_id,
        ),
        feedback_preferences=feedback_preferences,
        conflicts=conflicts,
        identity_status=identity_status,
        trusted_for_context=trusted_for_context,
        trusted_for_managed_send=trusted_for_managed_send,
        last_event_id=last_event_id,
        updated_at=updated_at,
    )


def _upsert_fact(
    fact: MemoryFact,
    facts_by_id: dict[str, MemoryFact],
    fact_order: list[str],
) -> None:
    if not fact.normalized_key:
        _insert_fact(fact, facts_by_id, fact_order)
        return

    existing_same_key = [
        existing
        for existing in facts_by_id.values()
        if existing.normalized_key == fact.normalized_key
        and existing.status not in {MemoryFactStatus.ARCHIVED, MemoryFactStatus.REJECTED}
    ]
    for existing in existing_same_key:
        if existing.normalized_value == fact.normalized_value:
            facts_by_id[existing.fact_id] = replace(
                existing,
                last_seen_at=max(existing.last_seen_at, fact.last_seen_at),
            )
            return

    _insert_fact(fact, facts_by_id, fact_order)


def _insert_fact(
    fact: MemoryFact,
    facts_by_id: dict[str, MemoryFact],
    fact_order: list[str],
) -> None:
    facts_by_id[fact.fact_id] = fact
    if fact.fact_id not in fact_order:
        fact_order.append(fact.fact_id)


def _upsert_inference(
    fact: MemoryFact,
    inferences: dict[str, MemoryFact],
    inference_order: list[str],
) -> None:
    inferences[fact.fact_id] = fact
    if fact.fact_id not in inference_order:
        inference_order.append(fact.fact_id)


def _recompute_fact_conflicts(
    facts_by_id: dict[str, MemoryFact],
    fact_order: list[str],
    *,
    created_at: str,
) -> list[MemoryConflict]:
    groups: dict[str, list[str]] = {}
    for fact_id in fact_order:
        fact = facts_by_id[fact_id]
        if fact.status in {MemoryFactStatus.ARCHIVED, MemoryFactStatus.REJECTED}:
            continue
        if not fact.normalized_key:
            facts_by_id[fact_id] = replace(fact, status=MemoryFactStatus.ACTIVE)
            continue
        facts_by_id[fact_id] = replace(fact, status=MemoryFactStatus.ACTIVE)
        groups.setdefault(fact.normalized_key, []).append(fact_id)

    conflicts: list[MemoryConflict] = []
    for normalized_key, fact_ids in groups.items():
        values = {facts_by_id[fact_id].normalized_value for fact_id in fact_ids}
        if len(values) <= 1:
            continue
        for fact_id in fact_ids:
            facts_by_id[fact_id] = replace(
                facts_by_id[fact_id],
                status=MemoryFactStatus.CONFLICTED,
            )
        conflicts.append(
            MemoryConflict(
                conflict_id=f"conflict_{normalized_key}_{len(conflicts) + 1}",
                normalized_key=normalized_key,
                fact_ids=list(fact_ids),
                reason="Conflicting values were observed for the same fact key.",
                created_at=created_at,
            )
        )
    return conflicts


def _apply_feedback_signal(
    payload: dict[str, Any],
    mode_preferences: dict[str, Any],
    facts_by_id: dict[str, MemoryFact],
    inferences: dict[str, MemoryFact],
) -> None:
    label = str(payload.get("label", "unknown"))
    if label == "wrong_assumption":
        for memory_id in _string_list(payload.get("referenced_memory_ids")):
            if memory_id in facts_by_id:
                facts_by_id[memory_id] = replace(
                    facts_by_id[memory_id],
                    status=MemoryFactStatus.REJECTED,
                )
            if memory_id in inferences:
                inferences[memory_id] = replace(
                    inferences[memory_id],
                    status=MemoryFactStatus.REJECTED,
                )
    if label == "not_like_me":
        _increment(mode_preferences.setdefault("style", {}), "not_like_me")
    if label in {"too_flirty", "too_aggressive", "too_formal", "too_boring"}:
        _increment(mode_preferences.setdefault("tone_negative", {}), label)
    if label == "accepted":
        accepted = mode_preferences.setdefault(
            "accepted",
            {"conversation_moves": {}, "hook_sources": {}},
        )
        if payload.get("conversation_move"):
            _increment(accepted.setdefault("conversation_moves", {}), str(payload["conversation_move"]))
        if payload.get("hook_source"):
            _increment(accepted.setdefault("hook_sources", {}), str(payload["hook_source"]))
    if label == "edited":
        edited = mode_preferences.setdefault("edited", {})
        _increment(edited, "count")
        if payload.get("user_confirmed_style_promotion"):
            edited.setdefault("style_promotions", []).append(str(payload.get("edited_text_ref") or "confirmed_edit"))


def _increment(counter: dict[str, Any], key: str) -> None:
    counter[key] = int(counter.get(key, 0)) + 1


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []
