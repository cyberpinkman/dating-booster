from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.automation_prioritization import (
    _next_priority_queue,
    _prioritize_entries,
    _split_entries_at_history_cutoff,
)
from dating_boost.core.automation_send_gate import _authorization_revoked_or_expired
from dating_boost.core.automation_state import (
    _normalize_scan_cursor,
    _unique_strings,
)
from dating_boost.core.automation_step_entries import (
    _process_historical_entries,
    _process_over_budget_entries,
    _process_visible_entry,
)
from dating_boost.core.automation_step_models import _ScanWindow, _StepBuffers


def run_automation_step(repository: Any, scan_batch: dict[str, Any]) -> dict[str, Any]:
    session = repository._load_session()
    now = repository._now()
    authorization = repository.load_authorization() or {}
    if session.get("status") != "active":
        status = str(session.get("status") or "unknown")
        reason = "session_paused" if status == "paused" else "session_stopped" if status == "stopped" else "session_not_active"
        return _blocked_step_payload(reason, machine_report_ref=str(Path("automation") / "reports" / "machine_latest.json"))
    if _authorization_revoked_or_expired(authorization, now):
        return _blocked_step_payload("authorization_expired_or_revoked", machine_report_ref=None)

    states_by_match, states_by_candidate = _load_state_maps(repository)
    ledger = repository.load_ledger()
    window = _scan_window(scan_batch, states_by_candidate=states_by_candidate, now=now)
    buffers = _StepBuffers()
    if window.history_cutoff_reached:
        buffers.warnings.append("message_list_history_cutoff_reached")

    _process_historical_entries(
        window.historical_entries,
        states_by_match=states_by_match,
        states_by_candidate=states_by_candidate,
        buffers=buffers,
        session=session,
        window=window,
        now=now,
    )
    for entry in window.processed_entries:
        _process_visible_entry(
            repository,
            entry,
            states_by_match=states_by_match,
            states_by_candidate=states_by_candidate,
            ledger=ledger,
            buffers=buffers,
            session=session,
            window=window,
            authorization=authorization,
            now=now,
        )
    _process_over_budget_entries(
        window.over_budget_entries,
        states_by_match=states_by_match,
        states_by_candidate=states_by_candidate,
        buffers=buffers,
        session=session,
        window=window,
        now=now,
    )
    return _finish_step(
        repository,
        session=session,
        states_by_match=states_by_match,
        ledger=ledger,
        buffers=buffers,
        window=window,
    )

def _blocked_step_payload(reason: str, *, machine_report_ref: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": reason,
        "action_requests": [],
        "handoffs": [],
        "scan_requests": [],
        "scheduled_actions": [],
        "warnings": [reason],
        "machine_report_ref": machine_report_ref,
    }

def _load_state_maps(repository: Any) -> tuple[dict[Any, dict[str, Any]], dict[Any, dict[str, Any]]]:
    states = repository.load_states()
    states_by_match = {state["match_id"]: dict(state) for state in states}
    states_by_candidate = {
        state.get("candidate_key"): dict(state)
        for state in states
        if state.get("candidate_key")
    }
    return states_by_match, states_by_candidate

def _scan_window(
    scan_batch: dict[str, Any],
    *,
    states_by_candidate: dict[Any, dict[str, Any]],
    now: str,
) -> _ScanWindow:
    thread_items = {
        item.get("candidate_key"): dict(item)
        for item in scan_batch.get("thread_observations", [])
        if item.get("candidate_key")
    }
    visible_entries = list(scan_batch.get("message_list_snapshot", {}).get("entries", []))
    captured_at_for_age = str(scan_batch.get("captured_at") or now)
    entries_before_cutoff, historical_entries, history_cutoff_reached = _split_entries_at_history_cutoff(
        visible_entries,
        captured_at=captured_at_for_age,
    )
    entries = _prioritize_entries(
        entries_before_cutoff,
        states_by_candidate=states_by_candidate,
        thread_items=thread_items,
    )
    budget = int(scan_batch.get("scan_budget") or 5)
    return _ScanWindow(
        thread_items=thread_items,
        historical_entries=historical_entries,
        processed_entries=entries[:budget],
        over_budget_entries=entries[budget:],
        history_cutoff_reached=history_cutoff_reached,
        scan_cursor=_normalize_scan_cursor(scan_batch.get("scan_cursor")),
        budget=budget,
        captured_at_for_age=captured_at_for_age,
        captured_at_present="captured_at" in scan_batch,
        captured_at_value=scan_batch.get("captured_at"),
        updated_at=scan_batch.get("captured_at", now),
    )

def _finish_step(
    repository: Any,
    *,
    session: dict[str, Any],
    states_by_match: dict[Any, dict[str, Any]],
    ledger: list[dict[str, Any]],
    buffers: _StepBuffers,
    window: _ScanWindow,
) -> dict[str, Any]:
    repository.save_states(list(states_by_match.values()))
    repository.save_ledger(ledger)
    session["step_count"] = int(session.get("step_count") or 0) + 1
    session["last_scan_cursor"] = window.scan_cursor
    repository._storage.write_json(Path("automation") / "session.json", session)
    next_priority_queue = _next_priority_queue(list(states_by_match.values()))

    return {
        "schema_version": 1,
        "status": "ok",
        "session_id": session["session_id"],
        "scan_budget": window.budget,
        "processed_entry_count": len(window.processed_entries),
        "processed_match_count": buffers.processed_match_count,
        "state_updates": buffers.state_updates,
        "action_requests": buffers.action_requests,
        "handoffs": buffers.handoffs,
        "scan_requests": buffers.scan_requests,
        "scheduled_actions": buffers.scheduled_actions,
        "next_priority_queue": next_priority_queue,
        "warnings": _unique_strings(buffers.warnings),
        "history_cutoff_reached": window.history_cutoff_reached,
        "historical_entry_count": len(window.historical_entries),
        "machine_report_ref": str(Path("automation") / "reports" / "machine_latest.json"),
    }

