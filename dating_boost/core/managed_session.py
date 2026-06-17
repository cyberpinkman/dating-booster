from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.registry import create_adapter, managed_session_policy, supported_app_ids
from dating_boost.core.automation import AutomationRepository
from dating_boost.core.operator import (
    DEFAULT_CYCLE_SEND_LIMIT,
    DEFAULT_MAX_PAGES_PER_CYCLE,
    DEFAULT_MAX_THREADS_PER_CYCLE,
    OperatorRepository,
)
from dating_boost.core.relationship_report import RELATIONSHIP_PROGRESS_NEXT_ACTION
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.core.safety import SafetyRepository
from dating_boost.core.storage import JsonStorage


MANAGED_SESSION_SCHEMA_VERSION = 1
MANAGED_WAKE_EVENT_SCHEMA_VERSION = 1
MANAGED_SESSION_PATH = Path("managed_session") / "session.json"
MANAGED_WAKE_EVENTS_PATH = Path("managed_session") / "wake_events.jsonl"
SUPPORTED_MANAGED_APPS = set(supported_app_ids())
DEFAULT_SCAN_INTERVAL_SECONDS = 120
DEFAULT_NUDGE_DELAY_MINUTES = 30


AdapterFactory = Callable[..., Any]


class ManagedSessionRepository:
    def __init__(self, root: Path, *, harness_factory: AdapterFactory | None = None):
        self.root = root
        self._storage = JsonStorage(root)
        self._automation = AutomationRepository(root)
        self._operator = OperatorRepository(root)
        self._harness_factory = harness_factory or (lambda app_id, runtime=None: create_adapter(app_id, runtime=runtime))

    def start(
        self,
        *,
        app_id: str,
        authorization: dict[str, Any],
        goal: dict[str, Any] | None,
        availability: dict[str, Any] | None,
        send_mode: str,
        managed_gui_send: bool,
        scan_interval_seconds: int = DEFAULT_SCAN_INTERVAL_SECONDS,
        nudge_delay_minutes: int = DEFAULT_NUDGE_DELAY_MINUTES,
        management_mode: str = "conservative",
        max_threads_per_cycle: int | None = None,
        max_pages_per_cycle: int | None = None,
        cycle_send_limit: int | None = None,
        harness_runtime: str | None = None,
    ) -> dict[str, Any]:
        app_id = _validate_app_id(app_id)
        normalized_runtime = _normalize_runtime(harness_runtime)
        policy = _managed_session_policy(app_id)
        session_config = _resolve_session_config(
            policy,
            management_mode=management_mode,
            max_threads_per_cycle=max_threads_per_cycle,
            max_pages_per_cycle=max_pages_per_cycle,
            cycle_send_limit=cycle_send_limit,
        )
        memory_review = self._automation.needs_memory_review()
        if send_mode == "live":
            block_reason = _live_send_start_block_reason(authorization, managed_gui_send=managed_gui_send, app_id=app_id)
            if block_reason:
                return _payload("blocked", reason=block_reason, app_id=app_id)
        if goal is not None:
            try:
                self._automation.save_goal(goal)
            except ValueError as exc:
                return _payload("blocked", reason=str(exc), app_id=app_id)
        if availability is not None:
            self._automation.save_availability(availability)
        runtime_scope = RuntimeScopeRepository(self.root).ensure_selected(
            app_id=app_id,
            runtime=normalized_runtime,
            source="managed_session_start",
            require_explicit_runtime_choice=True,
        )
        if runtime_scope.get("status") == "blocked":
            return runtime_scope
        app_check = self._app_precheck(app_id, runtime=normalized_runtime)
        operator_start = self._operator.start_session(authorization, **session_config)
        if operator_start.get("status") != "active":
            return _payload(
                str(operator_start.get("status") or "blocked"),
                reason=str(operator_start.get("reason") or "operator_session_not_active"),
                app_id=app_id,
                operator=operator_start,
            )
        now = _now_iso()
        initial_status = "active"
        stop_reason = None
        stopped_at = None
        next_host_action = "run_managed_session_wait_loop"
        if app_check["status"] != "ok":
            policy = _managed_session_policy(app_id)
            initial_status = _precheck_failure_status(policy, runtime=normalized_runtime)
            failure_reason = str(app_check.get("reason") or policy.get("precheck_failure_reason") or "app_unavailable")
            stop_reason = failure_reason if initial_status == "stopped" else None
            stopped_at = now if initial_status == "stopped" else None
            next_host_action = _precheck_failure_next_host_action(
                policy,
                app_check,
                runtime=normalized_runtime,
            )
        session = {
            "schema_version": MANAGED_SESSION_SCHEMA_VERSION,
            "session_id": operator_start["session_id"],
            "authorization_id": operator_start.get("authorization_id"),
            "app_id": app_id,
            "status": initial_status,
            "send_mode": send_mode,
            "managed_gui_send": bool(managed_gui_send),
            "scan_interval_seconds": max(1, int(scan_interval_seconds)),
            "nudge_delay_minutes": max(1, int(nudge_delay_minutes)),
            **session_config,
            "harness_runtime": normalized_runtime,
            "started_at": now,
            "updated_at": now,
            "stopped_at": stopped_at,
            "stop_reason": stop_reason,
            "pause_reason": failure_reason if initial_status == "paused" else None,
            "last_tick_at": None,
            "last_scan_at": None,
            "last_app_precheck": app_check,
            "last_host_work_item_id": None,
            "last_status": initial_status,
            "wake_event_cursor": _wake_event_count(self.root, app_id=app_id),
            "wake_event_cursor_app_id": app_id,
            "runtime_scope": runtime_scope,
        }
        self._write_session(session)
        stopped_operator = None
        if initial_status == "stopped":
            try:
                stopped_operator = self._operator.stop_session()
            except (FileNotFoundError, ValueError):
                stopped_operator = {"status": "not_found"}
        return {
            **_payload(
                initial_status,
                reason=stop_reason or session.get("pause_reason"),
                app_id=app_id,
                session=session,
                app_precheck=app_check,
            ),
            "operator_session": operator_start,
            "operator_stop": stopped_operator,
            "memory_review": memory_review if memory_review.get("needs_memory_review") else None,
            "warnings": ["pending_memory_suggestions_require_review"]
            if memory_review.get("needs_memory_review")
            else [],
            "next_host_action": next_host_action,
        }

    def status(self) -> dict[str, Any]:
        session = self._load_session()
        if session is None:
            return _payload("not_found", reason="managed_session_not_started")
        return _payload(str(session.get("status") or "unknown"), app_id=str(session.get("app_id")), session=session)

    def stop(self, *, reason: str = "manual_stop") -> dict[str, Any]:
        session = self._load_session()
        if session is None:
            return _payload("stopped", reason=reason)
        now = _now_iso()
        session["status"] = "stopped"
        session["stopped_at"] = now
        session["updated_at"] = now
        session["stop_reason"] = reason
        self._write_session(session)
        try:
            operator_stop = self._operator.stop_session()
        except (FileNotFoundError, ValueError):
            operator_stop = {"status": "not_found"}
        relationship_report = operator_stop.get("relationship_progress_report") if isinstance(operator_stop, dict) else None
        return _payload(
            "stopped",
            reason=reason,
            app_id=str(session.get("app_id")),
            session=session,
            operator=operator_stop,
            machine_report_path=operator_stop.get("machine_report_path") if isinstance(operator_stop, dict) else None,
            human_report_path=operator_stop.get("human_report_path") if isinstance(operator_stop, dict) else None,
            report_summary=operator_stop.get("summary") if isinstance(operator_stop, dict) else None,
            relationship_progress_report=relationship_report if isinstance(relationship_report, dict) else None,
            next_host_action=RELATIONSHIP_PROGRESS_NEXT_ACTION if isinstance(relationship_report, dict) else None,
        )

    def notify(self, *, source: str, app_id: str) -> dict[str, Any]:
        app_id = _validate_app_id(app_id)
        if source not in {"host_notification", "manual"}:
            return _payload("blocked", reason="unsupported_notify_source", app_id=app_id)
        event = {
            "schema_version": MANAGED_WAKE_EVENT_SCHEMA_VERSION,
            "event_id": f"wake_{_digest({'source': source, 'app_id': app_id, 'now': _now_iso()})[:16]}",
            "source": source,
            "app_id": app_id,
            "created_at": _now_iso(),
            "reason": "external_wake_event",
        }
        self._storage.append_jsonl(MANAGED_WAKE_EVENTS_PATH, event)
        return _payload("ok", app_id=app_id, wake_event=event, next_host_action="run_managed_session_tick")

    def tick(self) -> dict[str, Any]:
        session = self._load_session()
        if session is None:
            return _payload("stopped", reason="managed_session_not_started")
        if session.get("status") == "stopped":
            return _payload("stopped", reason=str(session.get("stop_reason") or "session_stopped"), app_id=str(session.get("app_id")), session=session)
        app_id = _validate_app_id(str(session.get("app_id") or ""))
        runtime = _normalize_runtime(session.get("harness_runtime"))
        now = _now_iso()
        relationship_snapshot = self._relationship_progress_snapshot()
        session["last_tick_at"] = now
        session["updated_at"] = now
        safety_status = SafetyRepository(self.root).status()
        if safety_status.get("paused"):
            self._write_session(session)
            return _payload(
                "paused",
                reason="safety_paused",
                app_id=app_id,
                session=session,
                safety=safety_status,
                relationship_progress_snapshot=relationship_snapshot,
                next_host_action="resume_safety_or_stop_managed_session",
            )
        authorization = self._automation.load_authorization() or {}
        auth_reason = _authorization_block_reason(authorization, now)
        if auth_reason:
            session["status"] = "stopped" if auth_reason == "authorization_expired_or_revoked" else "paused"
            session["stop_reason"] = auth_reason if session["status"] == "stopped" else None
            if session["status"] == "stopped":
                session["stopped_at"] = now
            self._write_session(session)
            return _payload(
                str(session["status"]),
                reason=auth_reason,
                app_id=app_id,
                session=session,
                relationship_progress_snapshot=relationship_snapshot,
            )

        runtime_scope = RuntimeScopeRepository(self.root).ensure_selected(
            app_id=app_id,
            runtime=runtime,
            source="managed_session_tick",
            require_explicit_runtime_choice=True,
        )
        if runtime_scope.get("status") == "blocked":
            session["last_runtime_scope"] = runtime_scope
            self._write_session(session)
            return {
                **runtime_scope,
                "app_id": app_id,
                "session": session,
                "relationship_progress_snapshot": relationship_snapshot,
            }
        session["runtime_scope"] = runtime_scope
        app_check = self._app_precheck(app_id, runtime=runtime)
        session["last_app_precheck"] = app_check
        if app_check["status"] != "ok":
            policy = _managed_session_policy(app_id)
            failure_status = _precheck_failure_status(policy, runtime=runtime)
            failure_reason = str(app_check.get("reason") or policy.get("precheck_failure_reason") or "app_unavailable")
            session["status"] = failure_status
            session["stop_reason"] = failure_reason if failure_status == "stopped" else None
            session["pause_reason"] = failure_reason if failure_status == "paused" else None
            if failure_status == "stopped":
                session["stopped_at"] = now
            self._write_session(session)
            return _payload(
                failure_status,
                reason=failure_reason,
                app_id=app_id,
                session=session,
                app_precheck=app_check,
                relationship_progress_snapshot=relationship_snapshot,
                next_host_action=_precheck_failure_next_host_action(policy, app_check, runtime=runtime),
            )
        if session.get("status") == "paused" and app_check["status"] == "ok":
            session["status"] = "active"
            session["pause_reason"] = None

        existing_operator_work = _operator_has_pending_work(self._operator.get_state_payload())
        automation_states = self._automation.load_states()
        wake_event_count = _wake_event_count(self.root, app_id=app_id)
        reasons = _wake_reasons(
            session,
            app_check=app_check,
            automation_states=automation_states,
            wake_event_count=wake_event_count,
            now=now,
        )
        if existing_operator_work:
            reasons = _unique(["existing_operator_work", *reasons])
        if not reasons:
            self._write_session(session)
            return _payload(
                "no_work",
                reason="no_wake_condition",
                app_id=app_id,
                session=session,
                app_precheck=app_check,
                relationship_progress_snapshot=relationship_snapshot,
                **_next_wake(session, automation_states),
            )

        self._operator = OperatorRepository(
            self.root,
            nudge_delay_minutes=int(session.get("nudge_delay_minutes") or DEFAULT_NUDGE_DELAY_MINUTES),
        )
        if "scan_interval_due" in reasons:
            self._operator.reset_cycle_limits()
        operator_payload = self._operator.next_work_item()
        work_item = operator_payload.get("work_item") if isinstance(operator_payload, dict) else None
        if not isinstance(work_item, dict):
            self._write_session(session)
            return _payload("blocked", reason="operator_returned_no_work_item", app_id=app_id, operator=operator_payload)
        work_type = str(work_item.get("work_item_type") or "")
        relationship_snapshot_with_work = _snapshot_with_current_work(
            relationship_snapshot,
            work_item,
            wake_reasons=reasons,
        )
        if work_type in {"wait", "scheduled_wait"}:
            session["last_scan_at"] = now if "scan_interval_due" in reasons or "notify" in " ".join(reasons) else session.get("last_scan_at")
            self._write_session(session)
            return _payload(
                "no_work",
                reason=str(work_item.get("reason") or "operator_wait"),
                app_id=app_id,
                session=session,
                app_precheck=app_check,
                wake_reasons=reasons,
                operator=operator_payload,
                relationship_progress_snapshot=relationship_snapshot_with_work,
                **_next_wake(session, self._automation.load_states()),
            )
        session["last_host_work_item_id"] = work_item.get("work_item_id")
        session["last_status"] = "host_work_required"
        session["wake_event_cursor"] = _wake_event_count(self.root, app_id=app_id)
        session["wake_event_cursor_app_id"] = app_id
        if work_type == "scan_message_list":
            session["last_scan_at"] = now
        self._write_session(session)
        return _payload(
            "host_work_required",
            reason="wake_condition_requires_host_work",
            app_id=app_id,
            session=session,
            app_precheck=app_check,
            wake_reasons=reasons,
            work_item=work_item,
            operator=operator_payload,
            relationship_progress_snapshot=relationship_snapshot_with_work,
            next_host_action=_next_host_action(work_type),
        )

    def _relationship_progress_snapshot(self) -> dict[str, Any]:
        try:
            latest = self._automation.latest_report()
            report = latest.get("machine_report") if isinstance(latest, dict) else None
        except Exception:
            report = None
        if not isinstance(report, dict):
            return {"summary": {}, "next_priority_queue": [], "object_states": []}
        object_states = []
        for state in report.get("states", []):
            if not isinstance(state, dict):
                continue
            object_states.append(
                {
                    "match_id": state.get("match_id"),
                    "candidate_key": state.get("candidate_key"),
                    "state": state.get("state"),
                    "candidate_type": state.get("candidate_type"),
                    "next_due_at": state.get("next_due_at"),
                    "pause_reason": state.get("pause_reason"),
                    "handoff_reason": state.get("handoff_reason"),
                    "last_scan_cursor": state.get("last_scan_cursor"),
                }
            )
        return {
            "summary": dict(report.get("summary") or {}),
            "next_priority_queue": list(report.get("next_priority_queue") or []),
            "object_states": object_states,
        }

    def run(self, *, wait: bool, wait_timeout_seconds: float | None = None, poll_interval_seconds: float = 1.0) -> dict[str, Any]:
        if not wait:
            return self.tick()
        deadline = None if wait_timeout_seconds is None else time.time() + max(0.0, wait_timeout_seconds)
        payload = self.tick()
        if payload.get("status") != "no_work":
            return payload
        while True:
            if deadline is not None and time.time() >= deadline:
                payload["wait_result"] = "timeout"
                return payload
            if self._local_wake_due():
                payload = self.tick()
                if payload.get("status") != "no_work":
                    return payload
            time.sleep(max(0.1, poll_interval_seconds))

    def _local_wake_due(self) -> bool:
        session = self._load_session()
        if session is None or session.get("status") in {"stopped", "paused"}:
            return True
        now = _now_iso()
        if SafetyRepository(self.root).is_paused():
            return True
        if _authorization_block_reason(self._automation.load_authorization() or {}, now):
            return True
        if _operator_has_pending_work(self._operator.get_state_payload()):
            return True
        app_id = _validate_app_id(str(session.get("app_id") or ""))
        if _wake_event_count(self.root, app_id=app_id) > int(session.get("wake_event_cursor") or 0):
            return True
        if _scan_interval_due(session, now):
            return True
        states = self._automation.load_states()
        return _nudge_due(states, now) or _scan_later_pending(states)

    def _load_session(self) -> dict[str, Any] | None:
        path = self.root / MANAGED_SESSION_PATH
        if not path.exists():
            return None
        return self._storage.read_json(MANAGED_SESSION_PATH, expected_schema_version=MANAGED_SESSION_SCHEMA_VERSION)

    def _write_session(self, payload: dict[str, Any]) -> None:
        self._storage.write_json(MANAGED_SESSION_PATH, payload)

    def _app_precheck(self, app_id: str, *, runtime: str | None = None) -> dict[str, Any]:
        try:
            adapter = self._harness_factory(app_id, runtime=runtime)
            observed = adapter.observe()
            return _safe_app_check(observed, app_id=app_id)
        except Exception as exc:
            return {
                "schema_version": MANAGED_SESSION_SCHEMA_VERSION,
                "status": "blocked",
                "app_id": app_id,
                "reason": "app_precheck_failed",
                "error_type": type(exc).__name__,
            }


def _safe_app_check(payload: dict[str, Any], *, app_id: str) -> dict[str, Any]:
    status = str(payload.get("status") or "unknown")
    layout = payload.get("layout_hints") if isinstance(payload.get("layout_hints"), dict) else {}
    screen = payload.get("screen") if isinstance(payload.get("screen"), dict) else {}
    result = {
        "schema_version": MANAGED_SESSION_SCHEMA_VERSION,
        "status": "ok" if status == "ok" else "blocked",
        "app_id": app_id,
        "reason": payload.get("reason"),
        "screen_state": payload.get("screen_state"),
        "layout_hints": layout,
        "screen_fingerprint": screen.get("text_fingerprint"),
        "screen_character_count": screen.get("text_character_count"),
    }
    window_probe = payload.get("window_probe")
    if not isinstance(window_probe, dict):
        preflight = payload.get("preflight")
        if isinstance(preflight, dict):
            window_probe = preflight.get("window_probe")
    if isinstance(window_probe, dict):
        result["window_probe"] = window_probe
    if _unread_marker_present(layout):
        result["unread_possible"] = True
    if layout.get("reply_required_marker_present") or layout.get("reply_deadline_marker_present"):
        result["unread_possible"] = True
    return result


def _managed_session_policy(app_id: str) -> dict[str, Any]:
    try:
        return managed_session_policy(app_id)
    except KeyError:
        return {}


def _normalize_runtime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _runtime_key(value: str | None) -> str:
    return (value or "").strip().replace("-", "_")


def _precheck_failure_status(policy: dict[str, Any], *, runtime: str | None) -> str:
    runtime_key = _runtime_key(runtime)
    runtime_statuses = policy.get("runtime_precheck_failure_statuses")
    if runtime_key and isinstance(runtime_statuses, dict):
        configured = runtime_statuses.get(runtime_key)
        if isinstance(configured, str) and configured.strip():
            return configured
    return str(policy.get("precheck_failure_status") or "stopped")


def _precheck_failure_next_host_action(
    policy: dict[str, Any],
    app_check: dict[str, Any],
    *,
    runtime: str | None,
) -> str:
    runtime_key = _runtime_key(runtime)
    runtime_actions = policy.get("runtime_precheck_failure_next_host_actions")
    if runtime_key and isinstance(runtime_actions, dict):
        configured = runtime_actions.get(runtime_key)
        if isinstance(configured, str) and configured.strip():
            return configured
    return str(policy.get("precheck_failure_next_host_action") or "restore_app_or_stop_managed_session")


def _snapshot_with_current_work(
    snapshot: dict[str, Any],
    work_item: dict[str, Any],
    *,
    wake_reasons: list[str],
) -> dict[str, Any]:
    enriched = dict(snapshot)
    enriched["current_work_item"] = {
        "work_item_id": work_item.get("work_item_id"),
        "work_item_type": work_item.get("work_item_type"),
        "reason": work_item.get("reason"),
        "candidate_key": work_item.get("candidate_key"),
        "match_id": work_item.get("match_id"),
        "next_priority_queue": work_item.get("next_priority_queue"),
    }
    enriched["wake_reasons"] = list(wake_reasons)
    return enriched


def _resolve_session_config(
    policy: dict[str, Any],
    *,
    management_mode: str,
    max_threads_per_cycle: int | None,
    max_pages_per_cycle: int | None,
    cycle_send_limit: int | None,
) -> dict[str, Any]:
    mode = str(management_mode or "conservative")
    if mode not in {"conservative", "high-throughput"}:
        raise ValueError("management_mode must be conservative or high-throughput")
    default_threads_key = (
        "high_throughput_max_threads_per_cycle"
        if mode == "high-throughput"
        else "default_max_threads_per_cycle"
    )
    default_pages_key = (
        "high_throughput_max_pages_per_cycle"
        if mode == "high-throughput"
        else "default_max_pages_per_cycle"
    )
    return {
        "management_mode": mode,
        "max_threads_per_cycle": max(
            1,
            int(
                max_threads_per_cycle
                or policy.get(default_threads_key)
                or DEFAULT_MAX_THREADS_PER_CYCLE
            ),
        ),
        "max_pages_per_cycle": max(
            1,
            int(
                max_pages_per_cycle
                or policy.get(default_pages_key)
                or DEFAULT_MAX_PAGES_PER_CYCLE
            ),
        ),
        "cycle_send_limit": max(
            1,
            int(cycle_send_limit or policy.get("cycle_send_limit") or DEFAULT_CYCLE_SEND_LIMIT),
        ),
    }


def _wake_reasons(
    session: dict[str, Any],
    *,
    app_check: dict[str, Any],
    automation_states: list[dict[str, Any]],
    wake_event_count: int,
    now: str,
) -> list[str]:
    reasons: list[str] = []
    if wake_event_count > int(session.get("wake_event_cursor") or 0):
        reasons.append("notify_event")
    if bool(app_check.get("unread_possible")):
        reasons.append("unread_possible")
    if _scan_interval_due(session, now):
        reasons.append("scan_interval_due")
    if _nudge_due(automation_states, now):
        reasons.append("nudge_due")
    if _scan_later_pending(automation_states):
        reasons.append("scan_later_pending")
    return _unique(reasons)


def _operator_has_pending_work(operator_state: dict[str, Any]) -> bool:
    session = operator_state.get("operator_session")
    if isinstance(session, dict) and isinstance(session.get("current_work_item"), dict):
        return True
    queue = operator_state.get("work_queue")
    return isinstance(queue, list) and any(isinstance(item, dict) for item in queue)


def _scan_later_pending(states: list[dict[str, Any]]) -> bool:
    return any(state.get("state") == "scan_later" for state in states)


def _scan_interval_due(session: dict[str, Any], now: str) -> bool:
    last_scan_at = session.get("last_scan_at")
    if not isinstance(last_scan_at, str) or not last_scan_at:
        return True
    try:
        elapsed = (_parse_iso(now) - _parse_iso(last_scan_at)).total_seconds()
    except ValueError:
        return True
    return elapsed >= float(session.get("scan_interval_seconds") or DEFAULT_SCAN_INTERVAL_SECONDS)


def _nudge_due(states: list[dict[str, Any]], now: str) -> bool:
    now_dt = _parse_iso(now)
    for state in states:
        if state.get("state") != "nudge_scheduled":
            continue
        fingerprint = state.get("latest_inbound_fingerprint")
        if fingerprint and state.get("last_nudged_inbound_fingerprint") == fingerprint:
            continue
        due_at = state.get("next_due_at")
        if not isinstance(due_at, str):
            continue
        try:
            if _parse_iso(due_at) <= now_dt:
                return True
        except ValueError:
            continue
    return False


def _next_wake(session: dict[str, Any], states: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[tuple[datetime, str, str]] = []
    scan_wake_at = _next_scan_wake_at(session)
    if scan_wake_at is not None:
        try:
            candidates.append((_parse_iso(scan_wake_at), scan_wake_at, "scan_interval_due"))
        except ValueError:
            pass
    nudge_wake_at = _earliest_eligible_nudge_due_at(states)
    if nudge_wake_at is not None:
        try:
            candidates.append((_parse_iso(nudge_wake_at), nudge_wake_at, "nudge_due"))
        except ValueError:
            pass
    if not candidates:
        return {"next_wake_at": None, "next_wake_reason": None}
    _, wake_at, reason = min(candidates, key=lambda item: item[0])
    return {"next_wake_at": wake_at, "next_wake_reason": reason}


def _next_scan_wake_at(session: dict[str, Any]) -> str | None:
    last_scan_at = session.get("last_scan_at")
    if not isinstance(last_scan_at, str):
        return None
    try:
        seconds = int(session.get("scan_interval_seconds") or DEFAULT_SCAN_INTERVAL_SECONDS)
        wake_at = datetime.fromtimestamp(_parse_iso(last_scan_at).timestamp() + seconds, timezone.utc)
        return wake_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError):
        return None


def _earliest_eligible_nudge_due_at(states: list[dict[str, Any]]) -> str | None:
    candidates: list[tuple[datetime, str]] = []
    for state in states:
        if state.get("state") != "nudge_scheduled":
            continue
        fingerprint = state.get("latest_inbound_fingerprint")
        if fingerprint and state.get("last_nudged_inbound_fingerprint") == fingerprint:
            continue
        due_at = state.get("next_due_at")
        if not isinstance(due_at, str):
            continue
        try:
            candidates.append((_parse_iso(due_at), due_at))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def _authorization_block_reason(authorization: dict[str, Any], now: str) -> str | None:
    if not authorization:
        return "authorization_missing"
    if authorization.get("revoked_at"):
        return "authorization_expired_or_revoked"
    expires_at = authorization.get("expires_at")
    if isinstance(expires_at, str):
        try:
            if _parse_iso(expires_at) <= _parse_iso(now):
                return "authorization_expired_or_revoked"
        except ValueError:
            return "authorization_invalid_expires_at"
    if _quiet_hours_active(authorization.get("quiet_hours"), now):
        return "authorization_quiet_hours"
    return None


def _live_send_start_block_reason(authorization: dict[str, Any], *, managed_gui_send: bool, app_id: str) -> str | None:
    if not managed_gui_send:
        return "managed_gui_send_required_for_live_mode"
    if authorization.get("app_id") != app_id:
        return "authorization_app_mismatch"
    if authorization.get("autonomous_send") is not True:
        return "autonomous_send_authorization_required"
    if authorization.get("live_send") is not True:
        return "live_send_authorization_required"
    if "send_message" not in authorization.get("allowed_actions", []):
        return "send_message_not_allowed"
    if authorization.get("requires_post_action_verification") is not True:
        return "post_action_verification_required"
    return None


def _quiet_hours_active(value: Any, now: str) -> bool:
    if not isinstance(value, list):
        return False
    current = _parse_iso(now)
    current_minutes = current.hour * 60 + current.minute
    for item in value:
        window = _quiet_window_minutes(item)
        if window is None:
            continue
        start, end = window
        if start <= end and start <= current_minutes < end:
            return True
        if start > end and (current_minutes >= start or current_minutes < end):
            return True
    return False


def _quiet_window_minutes(item: Any) -> tuple[int, int] | None:
    if not isinstance(item, dict):
        return None
    start = _hhmm_to_minutes(item.get("start"))
    end = _hhmm_to_minutes(item.get("end"))
    if start is None or end is None:
        return None
    return start, end


def _hhmm_to_minutes(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now_iso() -> str:
    override = os.environ.get("DATING_BOOST_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_app_id(app_id: str) -> str:
    if app_id not in SUPPORTED_MANAGED_APPS:
        raise ValueError(f"unsupported managed app: {app_id}")
    return app_id


def _wake_event_count(root: Path, *, app_id: str | None = None) -> int:
    path = root / MANAGED_WAKE_EVENTS_PATH
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if app_id is None:
            count += 1
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("app_id") == app_id:
            count += 1
    return count


def _unread_marker_present(layout: dict[str, Any]) -> bool:
    return bool(layout.get("unread_marker_present") or layout.get("reply_required_marker_present"))


def _payload(status: str, **kwargs: Any) -> dict[str, Any]:
    payload = {"schema_version": MANAGED_SESSION_SCHEMA_VERSION, "status": status}
    payload.update({key: value for key, value in kwargs.items() if value is not None})
    return payload


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _next_host_action(work_type: str) -> str:
    if work_type == "scan_message_list":
        return "open_app_message_list_and_write_message_list_observation"
    if work_type == "open_thread":
        return "open_requested_thread_and_write_thread_observation"
    if work_type == "send_message":
        return "execute_managed_send_or_stage_according_to_send_mode"
    return "process_operator_work_item"
