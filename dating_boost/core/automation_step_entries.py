from __future__ import annotations

from typing import Any

from dating_boost.core.automation_prioritization import (
    _candidate_type_for_entry,
    _entry_history_reason,
    _is_non_chat_message_list_entry,
    _stable_waiting_state_without_new_inbound,
)
from dating_boost.core.automation_state import (
    _new_state,
    _non_empty,
    _provisional_match_id,
    _state_update,
)
from dating_boost.core.automation_step_models import _ScanWindow, _StepBuffers
from dating_boost.core.automation_step_thread import _handle_thread_observation_entry


def _process_historical_entries(
    entries: list[Any],
    *,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    buffers: _StepBuffers,
    session: dict[str, Any],
    window: _ScanWindow,
    now: str,
) -> None:
    for entry in entries:
        if _is_non_chat_message_list_entry(entry):
            buffers.warnings.append("non_chat_message_list_entry_skipped")
            continue
        candidate_key = _non_empty(entry.get("candidate_key"), "candidate_key")
        provisional_id = _provisional_match_id(entry)
        state = states_by_match.get(provisional_id) or states_by_candidate.get(candidate_key) or _new_state(
            match_id=provisional_id,
            candidate_key=candidate_key,
            session_id=session["session_id"],
            timestamp=now,
        )
        state["state"] = "historical_thread"
        state["candidate_key"] = candidate_key
        state["candidate_type"] = "historical_thread"
        state["visible_name"] = entry.get("visible_name")
        state["last_preview_hash"] = entry.get("latest_preview_hash")
        state["unread_cue"] = entry.get("unread_cue")
        state["last_scan_cursor"] = window.scan_cursor
        state["history_cutoff_reason"] = _entry_history_reason(entry, captured_at=window.captured_at_for_age)
        state["updated_at"] = window.updated_at
        states_by_match[state["match_id"]] = state
        buffers.state_updates.append(_state_update(state))
        buffers.scheduled_actions.append(
            {
                "type": "historical_thread_skipped",
                "candidate_key": candidate_key,
                "visible_name": entry.get("visible_name"),
                "reason": state["history_cutoff_reason"],
                "scan_cursor": window.scan_cursor,
            }
        )

def _process_visible_entry(
    repository: Any,
    entry: Any,
    *,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    ledger: list[dict[str, Any]],
    buffers: _StepBuffers,
    session: dict[str, Any],
    window: _ScanWindow,
    authorization: dict[str, Any],
    now: str,
) -> None:
    if _is_non_chat_message_list_entry(entry):
        buffers.warnings.append("non_chat_message_list_entry_skipped")
        return
    candidate_key = _non_empty(entry.get("candidate_key"), "candidate_key")
    thread_item = window.thread_items.get(candidate_key)
    if thread_item is None:
        _handle_entry_without_thread_observation(
            entry,
            candidate_key=candidate_key,
            states_by_match=states_by_match,
            states_by_candidate=states_by_candidate,
            buffers=buffers,
            session=session,
            window=window,
            now=now,
        )
        return
    _handle_thread_observation_entry(
        repository,
        entry,
        thread_item,
        candidate_key=candidate_key,
        states_by_match=states_by_match,
        states_by_candidate=states_by_candidate,
        ledger=ledger,
        buffers=buffers,
        session=session,
        window=window,
        authorization=authorization,
        now=now,
    )

def _handle_entry_without_thread_observation(
    entry: Any,
    *,
    candidate_key: str,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    buffers: _StepBuffers,
    session: dict[str, Any],
    window: _ScanWindow,
    now: str,
) -> None:
    provisional_id = _provisional_match_id(entry)
    state = states_by_match.get(provisional_id) or states_by_candidate.get(candidate_key) or _new_state(
        match_id=provisional_id,
        candidate_key=candidate_key,
        session_id=session["session_id"],
        timestamp=now,
    )
    if _stable_waiting_state_without_new_inbound(state, entry):
        state["visible_name"] = entry.get("visible_name")
        state["last_preview_hash"] = entry.get("latest_preview_hash") or state.get("last_preview_hash")
        state["unread_cue"] = entry.get("unread_cue")
        state["updated_at"] = window.updated_at
        states_by_match[state["match_id"]] = state
        buffers.state_updates.append(_state_update(state))
        return
    state["state"] = "needs_thread_scan"
    state["candidate_type"] = _candidate_type_for_entry(state, entry)
    state["visible_name"] = entry.get("visible_name")
    state["last_preview_hash"] = entry.get("latest_preview_hash")
    state["unread_cue"] = entry.get("unread_cue")
    state["updated_at"] = window.updated_at
    states_by_match[state["match_id"]] = state
    buffers.scan_requests.append(
        {
            "candidate_key": candidate_key,
            "reason": "thread_observation_required",
            "visible_name": entry.get("visible_name"),
        }
    )
    buffers.state_updates.append(_state_update(state))

def _process_over_budget_entries(
    entries: list[Any],
    *,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    buffers: _StepBuffers,
    session: dict[str, Any],
    window: _ScanWindow,
    now: str,
) -> None:
    for entry in entries:
        if _is_non_chat_message_list_entry(entry):
            buffers.warnings.append("non_chat_message_list_entry_skipped")
            continue
        candidate_key = _non_empty(entry.get("candidate_key"), "candidate_key")
        provisional_id = _provisional_match_id(entry)
        state = states_by_match.get(provisional_id) or states_by_candidate.get(candidate_key) or _new_state(
            match_id=provisional_id,
            candidate_key=candidate_key,
            session_id=session["session_id"],
            timestamp=now,
        )
        if _stable_waiting_state_without_new_inbound(state, entry):
            state["visible_name"] = entry.get("visible_name")
            state["last_preview_hash"] = entry.get("latest_preview_hash") or state.get("last_preview_hash")
            state["unread_cue"] = entry.get("unread_cue")
            state["last_scan_cursor"] = window.scan_cursor
            state["updated_at"] = window.updated_at
            states_by_match[state["match_id"]] = state
            buffers.state_updates.append(_state_update(state))
            continue
        state["state"] = "scan_later"
        state["candidate_key"] = candidate_key
        state["candidate_type"] = _candidate_type_for_entry(state, entry)
        state["visible_name"] = entry.get("visible_name")
        state["last_preview_hash"] = entry.get("latest_preview_hash")
        state["unread_cue"] = entry.get("unread_cue")
        state["last_scan_cursor"] = window.scan_cursor
        state["updated_at"] = window.updated_at
        states_by_match[state["match_id"]] = state
        buffers.scheduled_actions.append(
            {
                "type": "scan_later",
                "candidate_key": candidate_key,
                "visible_name": entry.get("visible_name"),
                "reason": "scan_budget_exceeded",
                "scan_cursor": window.scan_cursor,
            }
        )

