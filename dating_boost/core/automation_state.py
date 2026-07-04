from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from dating_boost.core.goals import DEFAULT_GOAL_TYPE


ACTIVE_SLOT_STATUSES = {"soft_mentioned", "handoff_pending", "user_confirmed"}


def _action_result_mismatch(event: dict[str, Any], state: dict[str, Any]) -> str | None:
    if event.get("action") != state.get("last_action"):
        return "action_mismatch"
    if event.get("target_match_id") != state.get("match_id"):
        return "target_match_id_mismatch"
    if event.get("payload_hash") != state.get("last_outbound_payload_hash"):
        return "payload_hash_mismatch"
    if event.get("pre_action_observation_id") != state.get("last_pre_action_observation_id"):
        return "pre_action_observation_id_mismatch"
    return None


def _stage_result_mismatch(event: dict[str, Any], state: dict[str, Any]) -> str | None:
    if event.get("target_match_id") != state.get("match_id"):
        return "target_match_id_mismatch"
    if event.get("payload_hash") != state.get("last_outbound_payload_hash"):
        return "payload_hash_mismatch"
    if event.get("pre_action_observation_id") != state.get("last_pre_action_observation_id"):
        return "pre_action_observation_id_mismatch"
    return None


def _reserve_slot(
    ledger: list[dict[str, Any]],
    *,
    match_id: str,
    candidate_key: str,
    slot_payload: dict[str, Any],
    timestamp: str,
) -> tuple[dict[str, Any], bool]:
    slot_id = f"slot_{slot_payload.get('date')}_{slot_payload.get('time_window')}"
    conflict = any(
        slot.get("slot_id") == slot_id
        and slot.get("status") in ACTIVE_SLOT_STATUSES
        and slot.get("match_id") != match_id
        for slot in ledger
    )
    existing = [
        slot
        for slot in ledger
        if slot.get("slot_id") == slot_id and slot.get("match_id") == match_id
    ]
    if existing:
        existing[0]["conflict"] = bool(existing[0].get("conflict") or conflict)
        return existing[0], conflict
    slot = {
        "schema_version": 1,
        "slot_id": slot_id,
        "match_id": match_id,
        "candidate_key": candidate_key,
        "date": slot_payload.get("date"),
        "time_window": slot_payload.get("time_window"),
        "area": slot_payload.get("area"),
        "status": "handoff_pending",
        "conflict": conflict,
        "created_at": timestamp,
    }
    ledger.append(slot)
    return slot, conflict


def _new_state(*, match_id: str, candidate_key: str, session_id: str, timestamp: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "match_id": match_id,
        "candidate_key": candidate_key,
        "state": "new_match",
        "stage": "new_match",
        "goal_id": None,
        "latest_inbound_fingerprint": None,
        "last_inbound_observation_id": None,
        "last_outbound_payload_hash": None,
        "last_nudged_inbound_fingerprint": None,
        "nudge_count_since_inbound": 0,
        "next_due_at": None,
        "last_action": None,
        "last_action_request_id": None,
        "last_pre_action_observation_id": None,
        "handoff_reason": None,
        "question_debt": 0,
        "self_disclosure_debt": 0,
        "reciprocity_balance": "unknown",
        "low_investment_streak": 0,
        "match_curiosity_about_user": "unknown",
        "topic_exit_pressure": "low",
        "last_user_turn_type": "unknown",
        "last_disclosure_source": None,
        "low_investment_repair_applied": False,
        "pause_reason": None,
        "last_session_id": session_id,
        "updated_at": timestamp,
        "seen_before": False,
    }


def _state_update(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": state["match_id"],
        "candidate_key": state.get("candidate_key"),
        "state": state["state"],
        "candidate_type": state.get("candidate_type"),
        "history_cutoff_reason": state.get("history_cutoff_reason"),
        "latest_inbound_fingerprint": state.get("latest_inbound_fingerprint"),
        "handoff_reason": state.get("handoff_reason"),
        "conversation_stage": state.get("conversation_stage"),
        "planner_revision": state.get("planner_revision"),
        "planner_recommended_move": state.get("planner_recommended_move"),
        "next_milestone": state.get("next_milestone"),
        "question_debt": state.get("question_debt"),
        "reciprocity_balance": state.get("reciprocity_balance"),
        "low_investment_streak": state.get("low_investment_streak"),
    }


def _normalize_scan_cursor(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "current": value.get("current"),
            "next": value.get("next"),
            "exhausted": bool(value.get("exhausted")),
        }
    return {"current": value, "next": None, "exhausted": value is None}


def _provisional_match_id(entry: dict[str, Any]) -> str:
    key = entry.get("candidate_key") or entry.get("visible_name") or "unknown"
    return f"provisional_{_safe_id(str(key))}"


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_") or "unknown"


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _draft_payload_hash(payload: dict[str, Any]) -> str:
    return _text_hash(str(payload.get("best_reply", "")))


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _goal_type_from_payload(payload: dict[str, Any]) -> str:
    value = payload.get("goal_type") or payload.get("kind") or DEFAULT_GOAL_TYPE
    return str(value).strip() or DEFAULT_GOAL_TYPE


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _now_iso() -> str:
    override = os.environ.get("DATING_BOOST_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso_local_clock(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


__all__ = [
    "ACTIVE_SLOT_STATUSES",
    "_action_result_mismatch",
    "_stage_result_mismatch",
    "_reserve_slot",
    "_new_state",
    "_state_update",
    "_normalize_scan_cursor",
    "_provisional_match_id",
    "_safe_id",
    "_text_hash",
    "_draft_payload_hash",
    "_digest",
    "_non_empty",
    "_goal_type_from_payload",
    "_unique_strings",
    "_now_iso",
    "_parse_iso_utc",
    "_parse_iso_local_clock",
]
