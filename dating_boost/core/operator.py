from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.draft_evidence import ConversationThreadRepository, LatestTurnRepository
from dating_boost.core.automation import (
    AutomationRepository,
    _next_priority_queue,
    _now_iso,
    _release_active_send_request_after_failure,
)
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.scan_authoring import validate_scan_batch
from dating_boost.core.storage import JsonStorage


STICKY_WORK_ITEM_TYPES = {"scan_message_list", "observe_current_thread", "open_thread", "send_message"}
INITIAL_SURFACES = {"message-list", "current-thread"}
MANAGEMENT_MODES = {"conservative", "high-throughput"}
DEFAULT_MAX_THREADS_PER_CYCLE = 5
DEFAULT_MAX_PAGES_PER_CYCLE = 1
DEFAULT_CYCLE_SEND_LIMIT = 1


class OperatorRepository:
    def __init__(self, root: Path, *, nudge_delay_minutes: int = 30):
        self.root = root
        self._storage = JsonStorage(root)
        self._automation = AutomationRepository(root, nudge_delay_minutes=nudge_delay_minutes)

    def start_session(
        self,
        authorization: dict[str, Any],
        *,
        initial_surface: str = "message-list",
        management_mode: str = "conservative",
        max_threads_per_cycle: int = DEFAULT_MAX_THREADS_PER_CYCLE,
        max_pages_per_cycle: int = DEFAULT_MAX_PAGES_PER_CYCLE,
        cycle_send_limit: int = DEFAULT_CYCLE_SEND_LIMIT,
    ) -> dict[str, Any]:
        if initial_surface not in INITIAL_SURFACES:
            raise ValueError("initial_surface must be message-list or current-thread")
        session_config = _session_config(
            management_mode=management_mode,
            max_threads_per_cycle=max_threads_per_cycle,
            max_pages_per_cycle=max_pages_per_cycle,
            cycle_send_limit=cycle_send_limit,
        )
        automation_session = self._automation.start_session(authorization, session_config=session_config)
        if automation_session.get("status") != "active":
            return {
                "schema_version": 1,
                "status": automation_session.get("status", "blocked"),
                "reason": automation_session.get("reason") or "automation_session_not_started",
                "authorization_id": automation_session.get("authorization_id"),
                "user_profile_readiness": automation_session.get("user_profile_readiness"),
                "resumed_from_report": automation_session.get("resumed_from_report"),
                "memory_review": automation_session.get("memory_review"),
                "warnings": automation_session.get("warnings", []),
            }
        session = {
            "schema_version": 1,
            "session_id": automation_session["session_id"],
            "authorization_id": automation_session["authorization_id"],
            "status": "active",
            "started_at": _now_iso(),
            "stopped_at": None,
            "current_work_item": None,
            "last_decision": None,
            "initial_surface": initial_surface,
            "initial_surface_consumed": False,
            **session_config,
            "pages_scanned_current_cycle": 0,
            "next_scan_cursor": {"current": None, "next": None, "exhausted": False},
            "cycle_send_count": 0,
        }
        self._write_session(session)
        self._clear_current_work_file()
        self._clear_work_queue_file()
        self._clear_pending_scan_file()
        return {
            "schema_version": 1,
            "status": "active",
            "session_id": session["session_id"],
            "authorization_id": session["authorization_id"],
            "initial_surface": initial_surface,
            **session_config,
            "resumed_from_report": automation_session.get("resumed_from_report"),
            "memory_review": automation_session.get("memory_review"),
            "warnings": automation_session.get("warnings", []),
        }

    def next_work_item(self) -> dict[str, Any]:
        session = self._load_session()
        if session.get("status") != "active":
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "operator_session_not_active",
                "work_item": None,
            }

        current = session.get("current_work_item")
        if isinstance(current, dict):
            return self._work_payload(current, reused=True)

        scan_batch = self._load_pending_scan_batch()
        pending_thread_observation = _scan_batch_has_thread_observation(scan_batch)
        if not (scan_batch is not None and (session.get("accumulating_scan_pages") or pending_thread_observation)):
            queued = self._pop_next_work_item(session)
            if queued is not None:
                return self._work_payload(queued)

        if scan_batch is None:
            if session.get("initial_surface") == "current-thread" and not session.get("initial_surface_consumed"):
                work_item = {
                    "schema_version": 1,
                    "work_item_id": f"work_observe_current_thread_{session['session_id']}",
                    "work_item_type": "observe_current_thread",
                    "reason": "operator_starts_from_current_thread",
                    "instructions": "Observe the currently open dating app thread and ingest a thread observation without returning to the message list.",
                }
                session["initial_surface_consumed"] = True
                self._set_current_work_item(session, work_item)
                return self._work_payload(work_item)
            work_item = _scan_work_item(session, reason="operator_needs_message_list_snapshot")
            self._set_current_work_item(session, work_item)
            return self._work_payload(work_item)

        decision = self._automation.step(scan_batch)
        session["last_decision"] = decision
        if decision.get("history_cutoff_reached"):
            cursor = _normalize_scan_cursor(session.get("next_scan_cursor"))
            session["next_scan_cursor"] = {**cursor, "current": None, "next": None, "exhausted": True}
            session["history_cutoff_reached"] = True
        self._write_session(session)
        new_work_items = _work_items_from_decision(decision, session["session_id"])
        if _should_continue_scan_before_work(session, decision):
            accumulated = self._load_work_queue() + _non_wait_work_items(new_work_items)
            self._write_work_queue(accumulated)
            session["accumulating_scan_pages"] = True
            self._write_session(session)
            self._clear_pending_scan_file()
            work_item = _scan_work_item(session, reason="scan_page_continuation_required")
            self._set_current_work_item(session, work_item)
            return self._work_payload(work_item, decision=decision)
        if session.get("accumulating_scan_pages"):
            existing = self._load_work_queue()
            work_items = existing + _non_wait_work_items(new_work_items)
            if not work_items:
                work_items = new_work_items
            session["accumulating_scan_pages"] = False
            self._write_session(session)
        elif pending_thread_observation:
            existing = self._load_work_queue()
            work_items = _non_wait_work_items(new_work_items) + existing
            if not work_items:
                work_items = new_work_items
        else:
            work_items = new_work_items
        self._write_work_queue(work_items)
        work_item = self._pop_next_work_item(session)
        if work_item is None:
            work_item = {
                "schema_version": 1,
                "work_item_id": f"work_wait_{session['session_id']}",
                "work_item_type": "wait",
                "reason": "no_eligible_operator_work",
            }
        payload = self._work_payload(work_item, decision=decision)
        return payload

    def ingest_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session()
        observation_type = payload.get("observation_type")
        if observation_type == "message_list":
            scan_batch = {
                "schema_version": 1,
                "session_id": payload.get("session_id") or session["session_id"],
                "app_id": payload.get("app_id") or "tinder",
                "captured_at": payload.get("captured_at") or _now_iso(),
                "scan_cursor": _normalize_scan_cursor(payload.get("scan_cursor")),
                "scan_budget": int(payload.get("scan_budget") or session.get("max_threads_per_cycle") or DEFAULT_MAX_THREADS_PER_CYCLE),
                "provenance": payload.get("provenance") or {
                    "author": "host_agent",
                    "evidence": "Operator message-list observation.",
                },
                "message_list_snapshot": payload.get("message_list_snapshot") or {"entries": []},
                "thread_observations": [],
            }
            _validate_or_raise(scan_batch)
            self._write_pending_scan_batch(scan_batch)
            current = session.get("current_work_item")
            preserve_accumulated_queue = (
                isinstance(current, dict)
                and current.get("reason") == "scan_page_continuation_required"
                and bool(session.get("accumulating_scan_pages"))
            )
            session["pages_scanned_current_cycle"] = int(session.get("pages_scanned_current_cycle") or 0) + 1
            session["cycle_send_count"] = 0
            session["last_scan_cursor"] = scan_batch["scan_cursor"]
            next_cursor = scan_batch["scan_cursor"].get("next")
            session["next_scan_cursor"] = {
                "current": next_cursor,
                "next": None,
                "exhausted": bool(scan_batch["scan_cursor"].get("exhausted")),
            }
            self._write_session(session)
            if not preserve_accumulated_queue:
                self._clear_work_queue_file()
            self._clear_current_work_item(session, expected_type="scan_message_list")
            return {
                "schema_version": 1,
                "status": "ok",
                "observation_type": "message_list",
                "entry_count": len(scan_batch["message_list_snapshot"].get("entries", [])),
                "scan_cursor": scan_batch["scan_cursor"],
            }

        if observation_type == "thread":
            candidate_key = _candidate_key_from_thread_payload(payload)
            scan_batch = self._load_pending_scan_batch()
            if scan_batch is None:
                scan_batch = _scan_batch_from_current_thread_payload(payload, session_id=session["session_id"], candidate_key=candidate_key)
            thread = {key: value for key, value in payload.items() if key not in {"schema_version", "observation_type"}}
            thread["candidate_key"] = candidate_key
            existing = [
                item
                for item in scan_batch.get("thread_observations", [])
                if item.get("candidate_key") != candidate_key
            ]
            existing.append(thread)
            scan_batch["thread_observations"] = existing
            entries = scan_batch.setdefault("message_list_snapshot", {}).setdefault("entries", [])
            if not any(isinstance(entry, dict) and entry.get("candidate_key") == candidate_key for entry in entries):
                entries.append(_message_list_entry_from_thread_payload(payload, candidate_key=candidate_key))
            _validate_or_raise(scan_batch)
            self._write_pending_scan_batch(scan_batch)
            self._clear_work_queue_file()
            self._clear_current_work_item(
                session,
                expected_type="open_thread",
                expected_candidate_key=candidate_key,
            )
            self._clear_current_work_item(
                session,
                expected_type="observe_current_thread",
            )
            return {
                "schema_version": 1,
                "status": "ok",
                "observation_type": "thread",
                "candidate_key": candidate_key,
                "thread_count": len(existing),
            }

        raise ValueError("observation_type must be message_list or thread")

    def record_action_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_confirmation_contract(payload)
        session = self._load_session()
        current_work_item = dict(session.get("current_work_item") or {})
        event = ActionAuditRepository(self.root).append_action_result(payload, created_at=_now_iso())
        self._automation.apply_action_result(event)
        if event.get("action") == "send_message":
            self._record_successful_conversation_turn(event, current_work_item)
            session["cycle_send_count"] = int(session.get("cycle_send_count") or 0) + 1
            self._write_session(session)
        self._clear_current_work_item(
            session,
            expected_type="send_message",
            expected_action_request_id=event.get("action_request_id"),
        )
        if not self._load_work_queue():
            self._clear_pending_scan_file()
        return {
            "schema_version": 1,
            "status": "ok",
            "event_id": event["event_id"],
            "action_request_id": event.get("action_request_id"),
            "result_status": event["result_status"],
            "path": "audit/action_results.jsonl",
        }

    def _record_successful_conversation_turn(self, event: dict[str, Any], work_item: dict[str, Any]) -> None:
        if event.get("result_status") != "succeeded":
            return
        if event.get("action_request_id") != work_item.get("action_request_id"):
            return
        match_id = str(work_item.get("match_id") or event.get("target_match_id") or "").strip()
        if not match_id:
            return
        confirmed_messages = _confirmed_outbound_payload_messages(event, work_item)
        if not confirmed_messages:
            return
        latest_repo = LatestTurnRepository(self.root)
        latest_turn = latest_repo.load(match_id)
        ConversationThreadRepository(self.root).append_confirmed_outbound_turn(
            match_id,
            latest_turn=latest_turn,
            payload_messages=confirmed_messages,
            action_request_id=str(event.get("action_request_id") or ""),
            created_at=str(event.get("created_at") or _now_iso()),
        )
        latest_repo.clear(match_id, reason="outbound_confirmed", cleared_at=str(event.get("created_at") or _now_iso()))

    def record_stage_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session()
        event = ActionAuditRepository(self.root).append_stage_result(payload, created_at=_now_iso())
        self._automation.apply_stage_result(event)
        session["cycle_send_count"] = int(session.get("cycle_send_count") or 0) + 1
        self._write_session(session)
        self._clear_current_work_item(
            session,
            expected_type="send_message",
            expected_action_request_id=event.get("action_request_id"),
        )
        if not self._load_work_queue():
            self._clear_pending_scan_file()
        return {
            "schema_version": 1,
            "status": "ok",
            "event_id": event["event_id"],
            "action_request_id": event.get("action_request_id"),
            "result_status": event["result_status"],
            "path": "audit/stage_results.jsonl",
        }

    def _validate_confirmation_contract(self, payload: dict[str, Any]) -> None:
        if payload.get("action") != "send_message" or payload.get("result_status") != "succeeded":
            return
        action_request_id = payload.get("action_request_id")
        state = next(
            (
                item
                for item in self._automation.load_states()
                if item.get("last_action_request_id") == action_request_id
            ),
            None,
        )
        if state is None:
            return
        expected_binding = state.get("last_autonomous_audit_binding")
        precondition_hash = state.get("last_precondition_hash")
        if not isinstance(precondition_hash, str) or not precondition_hash:
            return
        confirmation_id = payload.get("confirmation_id")
        if isinstance(confirmation_id, str) and confirmation_id.strip():
            validation = ProductionDataStore(self.root).validate_confirmation_hashes(
                confirmation_id=confirmation_id,
                action="send_message",
                target_match_id=str(payload.get("target_match_id") or ""),
                payload_hash=str(payload.get("payload_hash") or ""),
                precondition_hash=precondition_hash,
            )
            if validation.get("status") == "ok":
                return
            raise ValueError(f"confirmation_contract_blocked:{validation.get('reason')}")
        binding = payload.get("autonomous_audit_binding")
        if not isinstance(expected_binding, dict) or not isinstance(binding, dict):
            raise ValueError("confirmation_contract_required")
        if payload.get("precondition_hash") != precondition_hash:
            raise ValueError("precondition_hash_mismatch")
        for key in ("authorization_id", "action", "target_match_id", "payload_hash", "precondition_hash"):
            if binding.get(key) != expected_binding.get(key):
                raise ValueError(f"autonomous_audit_binding_mismatch:{key}")

    def cancel_current_work_item(self, work_item: dict[str, Any], *, reason: str) -> dict[str, Any]:
        session = self._load_session()
        self._clear_current_work_item(
            session,
            expected_type=str(work_item.get("work_item_type") or ""),
            expected_action_request_id=work_item.get("action_request_id"),
            expected_work_item_id=work_item.get("work_item_id"),
        )
        state_update_count = 0
        if work_item.get("work_item_type") == "send_message":
            states = self._automation.load_states()
            for state in states:
                if state.get("last_action_request_id") != work_item.get("action_request_id"):
                    continue
                state["state"] = "draft_ready"
                state["last_action_result_error"] = reason
                _release_active_send_request_after_failure(state, event_id=f"cancelled:{reason}")
                state["updated_at"] = _now_iso()
                state_update_count += 1
            if state_update_count:
                self._automation.save_states(states)
        return {
            "schema_version": 1,
            "status": "ok",
            "cancelled_work_item_id": work_item.get("work_item_id"),
            "action_request_id": work_item.get("action_request_id"),
            "state_update_count": state_update_count,
        }

    def stop_session(self) -> dict[str, Any]:
        automation_stop = self._automation.stop_session()
        session = self._load_session()
        session["status"] = "stopped"
        session["stopped_at"] = _now_iso()
        session["current_work_item"] = None
        self._write_session(session)
        self._clear_current_work_file()
        self._clear_work_queue_file()
        self._clear_pending_scan_file()
        return {
            "schema_version": 1,
            "status": "stopped",
            "session_id": session["session_id"],
            "machine_report_path": automation_stop["machine_report_path"],
            "human_report_path": automation_stop["human_report_path"],
            "summary": automation_stop["summary"],
            "relationship_progress_report": automation_stop.get("relationship_progress_report"),
            "next_host_action": automation_stop.get("next_host_action"),
        }

    def latest_report(self) -> dict[str, Any]:
        automation_report = self._automation.latest_report()
        return {
            "schema_version": 1,
            "status": automation_report["status"],
            "operator_session": self._load_session_or_none(),
            "automation_report": automation_report.get("machine_report"),
            "machine_report_path": automation_report.get("machine_report_path"),
        }

    def latest_human_report(self) -> str:
        return self._automation.latest_human_report()

    def needs_memory_review(self) -> dict[str, Any]:
        return self._automation.needs_memory_review()

    def get_state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "ok",
            "operator_session": self._load_session_or_none(),
            "pending_scan_batch": self._load_pending_scan_batch(),
            "work_queue": self._load_work_queue(),
            "automation": self._automation.get_state_payload(),
        }

    def reset_cycle_limits(self) -> dict[str, Any]:
        session = self._load_session()
        session["cycle_send_count"] = 0
        session["pages_scanned_current_cycle"] = 0
        self._write_session(session)
        return {"schema_version": 1, "status": "ok"}

    def _load_session(self) -> dict[str, Any]:
        session = self._load_session_or_none()
        if session is None:
            raise ValueError("operator session has not been started")
        return session

    def _load_session_or_none(self) -> dict[str, Any] | None:
        try:
            return self._storage.read_json(Path("operator") / "session.json", expected_schema_version=1)
        except FileNotFoundError:
            return None

    def _write_session(self, session: dict[str, Any]) -> None:
        self._storage.write_json(Path("operator") / "session.json", session)

    def _set_current_work_item(self, session: dict[str, Any], work_item: dict[str, Any]) -> None:
        session["current_work_item"] = work_item
        self._write_session(session)
        self._storage.write_json(Path("operator") / "current_work_item.json", work_item)

    def _pop_next_work_item(self, session: dict[str, Any]) -> dict[str, Any] | None:
        queue = self._load_work_queue()
        if not queue:
            return None
        states = self._automation.load_states()
        queue = _merge_missing_priority_open_threads(queue, states)
        queue = _prioritize_work_queue(queue, states)
        if _cycle_send_limit_reached(session, queue[0]):
            return {
                "schema_version": 1,
                "work_item_id": f"work_scheduled_cycle_send_limit_{session['session_id']}",
                "work_item_type": "scheduled_wait",
                "reason": "cycle_send_limit_reached",
                "cycle_send_limit": int(session.get("cycle_send_limit") or DEFAULT_CYCLE_SEND_LIMIT),
            }
        work_item = queue.pop(0)
        self._write_work_queue(queue)
        if work_item.get("work_item_type") in STICKY_WORK_ITEM_TYPES:
            self._set_current_work_item(session, work_item)
        elif (
            not queue
            and not (
                work_item.get("work_item_type") == "blocked"
                and work_item.get("reason") == "target_profile_required"
            )
        ):
            self._clear_pending_scan_file()
        return work_item

    def _clear_current_work_item(
        self,
        session: dict[str, Any],
        *,
        expected_type: str | None = None,
        expected_candidate_key: str | None = None,
        expected_action_request_id: Any = None,
        expected_work_item_id: Any = None,
    ) -> None:
        current = session.get("current_work_item")
        if not isinstance(current, dict):
            return
        if expected_type and current.get("work_item_type") != expected_type:
            return
        if expected_candidate_key and current.get("candidate_key") != expected_candidate_key:
            return
        if expected_action_request_id and current.get("action_request_id") != expected_action_request_id:
            return
        if expected_work_item_id and current.get("work_item_id") != expected_work_item_id:
            return
        session["current_work_item"] = None
        self._write_session(session)
        self._clear_current_work_file()

    def _clear_current_work_file(self) -> None:
        path = self._storage.root / "operator" / "current_work_item.json"
        if path.exists():
            path.unlink()

    def _load_work_queue(self) -> list[dict[str, Any]]:
        try:
            payload = self._storage.read_json(Path("operator") / "work_queue.json", expected_schema_version=1)
        except FileNotFoundError:
            return []
        items = payload.get("work_items", [])
        return [dict(item) for item in items if isinstance(item, dict)]

    def _write_work_queue(self, work_items: list[dict[str, Any]]) -> None:
        self._storage.write_json(
            Path("operator") / "work_queue.json",
            {"schema_version": 1, "work_items": list(work_items)},
        )

    def _clear_work_queue_file(self) -> None:
        path = self._storage.root / "operator" / "work_queue.json"
        if path.exists():
            path.unlink()

    def _clear_pending_scan_file(self) -> None:
        path = self._storage.root / "operator" / "pending_scan_batch.json"
        if path.exists():
            path.unlink()

    def _load_pending_scan_batch(self) -> dict[str, Any] | None:
        try:
            return self._storage.read_json(Path("operator") / "pending_scan_batch.json", expected_schema_version=1)
        except FileNotFoundError:
            return None

    def _write_pending_scan_batch(self, scan_batch: dict[str, Any]) -> None:
        self._storage.write_json(Path("operator") / "pending_scan_batch.json", scan_batch)

    def _work_payload(
        self,
        work_item: dict[str, Any],
        *,
        reused: bool = False,
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "status": "ok",
            "work_item": work_item,
            "reused_current_work_item": reused,
        }
        if decision is not None:
            payload["decision_summary"] = {
                "status": decision.get("status"),
                "state_update_count": len(decision.get("state_updates", [])),
                "action_request_count": len(decision.get("action_requests", [])),
                "handoff_count": len(decision.get("handoffs", [])),
                "scan_request_count": len(decision.get("scan_requests", [])),
                "scheduled_action_count": len(decision.get("scheduled_actions", [])),
                "history_cutoff_reached": bool(decision.get("history_cutoff_reached")),
                "historical_entry_count": int(decision.get("historical_entry_count") or 0),
                "warnings": decision.get("warnings", []),
            }
        return payload


def _work_items_from_decision(decision: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    if decision.get("status") == "blocked":
        return [
            {
                "schema_version": 1,
                "work_item_id": f"work_blocked_{session_id}",
                "work_item_type": "blocked",
                "reason": decision.get("reason") or "automation_blocked",
                "warnings": decision.get("warnings", []),
            }
        ]
    work_items: list[dict[str, Any]] = []
    action_requests = list(decision.get("action_requests", []))
    for action_request in action_requests:
        action = dict(action_request)
        action["work_item_type"] = "send_message"
        action["work_item_id"] = action["action_request_id"]
        work_items.append(action)
    handoffs = list(decision.get("handoffs", []))
    for handoff_payload in handoffs:
        handoff = dict(handoff_payload)
        handoff["schema_version"] = 1
        handoff["work_item_type"] = "handoff"
        handoff["work_item_id"] = f"work_handoff_{handoff.get('match_id') or handoff.get('candidate_key')}"
        work_items.append(handoff)
    scan_requests = list(decision.get("scan_requests", []))
    for scan_request in scan_requests:
        scan = dict(scan_request)
        scan["schema_version"] = 1
        scan["work_item_type"] = "open_thread"
        scan["work_item_id"] = f"work_open_thread_{scan.get('candidate_key')}"
        work_items.append(scan)
    scheduled_actions = list(decision.get("scheduled_actions", []))
    for scheduled_action in scheduled_actions:
        scheduled = dict(scheduled_action)
        scheduled["schema_version"] = 1
        scheduled["work_item_type"] = "scheduled_wait"
        scheduled["work_item_id"] = f"work_scheduled_{scheduled.get('type')}_{scheduled.get('candidate_key') or scheduled.get('match_id')}"
        work_items.append(scheduled)
    if work_items:
        return work_items
    warnings = [str(item) for item in decision.get("warnings", [])]
    if "target_profile_required" in warnings:
        return [
            {
                "schema_version": 1,
                "work_item_id": f"work_blocked_target_profile_required_{session_id}",
                "work_item_type": "blocked",
                "reason": "target_profile_required",
                "warnings": warnings,
            }
        ]
    return [
        {
            "schema_version": 1,
            "work_item_id": f"work_wait_{session_id}",
            "work_item_type": "wait",
            "reason": "no_eligible_operator_work",
            "next_priority_queue": decision.get("next_priority_queue", []),
        }
    ]


def _confirmed_outbound_payload_messages(event: dict[str, Any], work_item: dict[str, Any]) -> list[dict[str, Any]]:
    payload_messages = [
        dict(item)
        for item in work_item.get("payload_messages", [])
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    if not payload_messages and str(work_item.get("payload_text") or "").strip():
        text = str(work_item["payload_text"])
        payload_messages = [
            {
                "index": 1,
                "text": text,
                "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "character_count": len(text),
            }
        ]
    if not payload_messages:
        return []

    message_results = [dict(item) for item in event.get("message_results", []) if isinstance(item, dict)]
    if message_results:
        by_index = {int(item.get("index") or 0): item for item in message_results}
        confirmed: list[dict[str, Any]] = []
        for message in sorted(payload_messages, key=lambda item: int(item.get("index") or 0)):
            result = by_index.get(int(message.get("index") or 0))
            if not result or result.get("status") != "ok":
                break
            if result.get("message_hash") and result.get("message_hash") != message.get("message_hash"):
                break
            if not result.get("post_action_observation_id"):
                break
            confirmed.append(message)
        return confirmed

    evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
    expected_text = "\n".join(str(message.get("text") or "") for message in payload_messages)
    observed_text = str(
        evidence.get("post_send_visible_text")
        or evidence.get("outbound_visible_text")
        or evidence.get("sent_text")
        or ""
    )
    if observed_text != expected_text:
        return []
    return payload_messages


def _session_config(
    *,
    management_mode: str,
    max_threads_per_cycle: int,
    max_pages_per_cycle: int,
    cycle_send_limit: int,
) -> dict[str, Any]:
    mode = str(management_mode or "conservative")
    if mode not in MANAGEMENT_MODES:
        raise ValueError("management_mode must be conservative or high-throughput")
    return {
        "management_mode": mode,
        "max_threads_per_cycle": max(1, int(max_threads_per_cycle or DEFAULT_MAX_THREADS_PER_CYCLE)),
        "max_pages_per_cycle": max(1, int(max_pages_per_cycle or DEFAULT_MAX_PAGES_PER_CYCLE)),
        "cycle_send_limit": max(1, int(cycle_send_limit or DEFAULT_CYCLE_SEND_LIMIT)),
    }


def _scan_work_item(session: dict[str, Any], *, reason: str) -> dict[str, Any]:
    scan_cursor = _normalize_scan_cursor(session.get("next_scan_cursor"))
    pages_scanned = int(session.get("pages_scanned_current_cycle") or 0)
    max_pages = max(1, int(session.get("max_pages_per_cycle") or DEFAULT_MAX_PAGES_PER_CYCLE))
    max_threads = max(1, int(session.get("max_threads_per_cycle") or DEFAULT_MAX_THREADS_PER_CYCLE))
    return {
        "schema_version": 1,
        "work_item_id": f"work_scan_message_list_{session['session_id']}_{pages_scanned + 1}",
        "work_item_type": "scan_message_list",
        "reason": reason,
        "instructions": "Observe the visible dating app message list and ingest a message_list observation.",
        "scan_cursor": scan_cursor,
        "page_budget_remaining": max(0, max_pages - pages_scanned),
        "thread_budget_remaining": max_threads,
        "management_mode": session.get("management_mode") or "conservative",
    }


def _decision_has_no_immediate_work(decision: dict[str, Any]) -> bool:
    return not (
        decision.get("action_requests")
        or decision.get("handoffs")
        or decision.get("scan_requests")
        or decision.get("scheduled_actions")
    )


def _should_continue_scan_before_work(session: dict[str, Any], decision: dict[str, Any]) -> bool:
    if decision.get("history_cutoff_reached"):
        return False
    if not _can_continue_scan(session):
        return False
    if session.get("management_mode") == "high-throughput":
        return True
    return _decision_has_no_immediate_work(decision)


def _can_continue_scan(session: dict[str, Any]) -> bool:
    cursor = _normalize_scan_cursor(session.get("next_scan_cursor"))
    if cursor.get("exhausted"):
        return False
    if not cursor.get("current"):
        return False
    pages_scanned = int(session.get("pages_scanned_current_cycle") or 0)
    max_pages = max(1, int(session.get("max_pages_per_cycle") or DEFAULT_MAX_PAGES_PER_CYCLE))
    return pages_scanned < max_pages


def _cycle_send_limit_reached(session: dict[str, Any], work_item: dict[str, Any]) -> bool:
    if work_item.get("work_item_type") != "send_message":
        return False
    limit = max(1, int(session.get("cycle_send_limit") or DEFAULT_CYCLE_SEND_LIMIT))
    return int(session.get("cycle_send_count") or 0) >= limit


def _scan_batch_has_thread_observation(scan_batch: dict[str, Any] | None) -> bool:
    if not isinstance(scan_batch, dict):
        return False
    return any(isinstance(item, dict) for item in scan_batch.get("thread_observations", []))


def _non_wait_work_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("work_item_type") not in {"wait", "scheduled_wait"}]


def _prioritize_work_queue(work_items: list[dict[str, Any]], states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(work_items) <= 1:
        return list(work_items)
    priority_queue = _next_priority_queue(states)
    candidate_ranks: dict[str, tuple[int, int]] = {}
    match_ranks: dict[str, tuple[int, int]] = {}
    for index, item in enumerate(priority_queue):
        rank = (_safe_priority(item.get("priority")), index)
        candidate_key = item.get("candidate_key")
        if isinstance(candidate_key, str) and candidate_key:
            candidate_ranks[candidate_key] = rank
        match_id = item.get("match_id")
        if isinstance(match_id, str) and match_id:
            match_ranks[match_id] = rank

    def sort_key(indexed: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        original_index, item = indexed
        work_type = str(item.get("work_item_type") or "")
        type_priority = {
            "blocked": 0,
            "handoff": 1,
            "send_message": 2,
            "open_thread": 3,
            "observe_current_thread": 3,
            "scheduled_wait": 8,
            "wait": 9,
        }.get(work_type, 7)
        rank = candidate_ranks.get(str(item.get("candidate_key") or ""))
        if rank is None:
            rank = match_ranks.get(str(item.get("match_id") or ""))
        if rank is None:
            rank = (9, original_index)
        return (type_priority, rank[0], rank[1], original_index)

    return [item for _, item in sorted(enumerate(work_items), key=sort_key)]


def _merge_missing_priority_open_threads(work_items: list[dict[str, Any]], states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(work_items)


def _safe_priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 9


def _normalize_scan_cursor(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "current": value.get("current"),
            "next": value.get("next"),
            "exhausted": bool(value.get("exhausted")),
        }
    return {"current": value, "next": None, "exhausted": False}


def _candidate_key_from_thread_payload(payload: dict[str, Any]) -> str:
    value = payload.get("candidate_key")
    if isinstance(value, str) and value.strip():
        return value.strip()
    observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    hints = observation.get("match_identity_hints") if isinstance(observation.get("match_identity_hints"), dict) else {}
    assessment = payload.get("assessment") if isinstance(payload.get("assessment"), dict) else {}
    visible_name = str(hints.get("visible_name") or "current_thread").strip() or "current_thread"
    fingerprint = str(
        assessment.get("latest_inbound_fingerprint")
        or hints.get("conversation_fingerprint")
        or observation.get("observation_id")
        or ""
    ).strip()
    raw = "|".join([visible_name, fingerprint])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"current_thread_{digest}"


def _message_list_entry_from_thread_payload(payload: dict[str, Any], *, candidate_key: str) -> dict[str, Any]:
    observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    hints = observation.get("match_identity_hints") if isinstance(observation.get("match_identity_hints"), dict) else {}
    assessment = payload.get("assessment") if isinstance(payload.get("assessment"), dict) else {}
    visible_name = str(hints.get("visible_name") or candidate_key)
    latest_preview = str(assessment.get("latest_match_message") or assessment.get("latest_user_message") or "")
    return {
        "candidate_key": candidate_key,
        "visible_name": visible_name,
        "latest_preview": latest_preview,
        "latest_preview_hash": f"sha256:{hashlib.sha256(latest_preview.encode('utf-8')).hexdigest()}",
        "timestamp_cue": payload.get("timestamp_cue") or "current_thread",
        "unread_cue": payload.get("unread_cue") or "unknown",
        "identity_confidence": payload.get("identity_confidence") or "medium",
        "identity_evidence": payload.get("identity_evidence") or "Current thread observation.",
        "match_identity_hints": {
            "visible_name": visible_name,
            "profile_cues": list(hints.get("profile_cues") or []) if isinstance(hints.get("profile_cues"), list) else [],
            "conversation_fingerprint": hints.get("conversation_fingerprint") or assessment.get("latest_inbound_fingerprint") or "",
        },
        "evidence": "Synthetic message-list entry from current thread observation.",
    }


def _scan_batch_from_current_thread_payload(
    payload: dict[str, Any],
    *,
    session_id: str,
    candidate_key: str,
) -> dict[str, Any]:
    observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    scan_batch = {
        "schema_version": 1,
        "session_id": payload.get("session_id") or session_id,
        "app_id": observation.get("app_id") or payload.get("app_id") or "unknown",
        "captured_at": observation.get("captured_at") or payload.get("captured_at") or _now_iso(),
        "scan_cursor": "current_thread",
        "scan_budget": 1,
        "provenance": payload.get("provenance") or {
            "author": "host_agent",
            "evidence": "Operator started from the already-open current thread.",
        },
        "message_list_snapshot": {
            "entries": [
                _message_list_entry_from_thread_payload(payload, candidate_key=candidate_key)
            ]
        },
        "thread_observations": [],
    }
    _validate_or_raise(scan_batch)
    return scan_batch


def _validate_or_raise(scan_batch: dict[str, Any]) -> None:
    validation = validate_scan_batch(scan_batch)
    if validation["status"] != "ok":
        raise ValueError("; ".join(str(error) for error in validation["errors"]))


def _non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value
