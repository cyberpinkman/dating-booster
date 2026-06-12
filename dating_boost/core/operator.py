from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.automation import AutomationRepository, _now_iso
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.scan_authoring import validate_scan_batch
from dating_boost.core.storage import JsonStorage


STICKY_WORK_ITEM_TYPES = {"scan_message_list", "observe_current_thread", "open_thread", "send_message"}
INITIAL_SURFACES = {"message-list", "current-thread"}


class OperatorRepository:
    def __init__(self, root: Path, *, nudge_delay_minutes: int = 30):
        self.root = root
        self._storage = JsonStorage(root)
        self._automation = AutomationRepository(root, nudge_delay_minutes=nudge_delay_minutes)

    def start_session(self, authorization: dict[str, Any], *, initial_surface: str = "message-list") -> dict[str, Any]:
        if initial_surface not in INITIAL_SURFACES:
            raise ValueError("initial_surface must be message-list or current-thread")
        automation_session = self._automation.start_session(authorization)
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

        queued = self._pop_next_work_item(session)
        if queued is not None:
            return self._work_payload(queued)

        scan_batch = self._load_pending_scan_batch()
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
            work_item = {
                "schema_version": 1,
                "work_item_id": f"work_scan_message_list_{session['session_id']}",
                "work_item_type": "scan_message_list",
                "reason": "operator_needs_message_list_snapshot",
                "instructions": "Observe the visible dating app message list and ingest a message_list observation.",
            }
            self._set_current_work_item(session, work_item)
            return self._work_payload(work_item)

        decision = self._automation.step(scan_batch)
        session["last_decision"] = decision
        self._write_session(session)
        self._write_work_queue(_work_items_from_decision(decision, session["session_id"]))
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
                "scan_cursor": payload.get("scan_cursor"),
                "scan_budget": int(payload.get("scan_budget") or 5),
                "provenance": payload.get("provenance") or {
                    "author": "host_agent",
                    "evidence": "Operator message-list observation.",
                },
                "message_list_snapshot": payload.get("message_list_snapshot") or {"entries": []},
                "thread_observations": [],
            }
            _validate_or_raise(scan_batch)
            self._write_pending_scan_batch(scan_batch)
            self._clear_work_queue_file()
            self._clear_current_work_item(session, expected_type="scan_message_list")
            return {
                "schema_version": 1,
                "status": "ok",
                "observation_type": "message_list",
                "entry_count": len(scan_batch["message_list_snapshot"].get("entries", [])),
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
        event = ActionAuditRepository(self.root).append_action_result(payload, created_at=_now_iso())
        self._automation.apply_action_result(event)
        session = self._load_session()
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

    def record_stage_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = ActionAuditRepository(self.root).append_stage_result(payload, created_at=_now_iso())
        self._automation.apply_stage_result(event)
        session = self._load_session()
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
        }
    ]


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


def _scan_batch_from_current_thread_payload(
    payload: dict[str, Any],
    *,
    session_id: str,
    candidate_key: str,
) -> dict[str, Any]:
    observation = payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    hints = observation.get("match_identity_hints") if isinstance(observation.get("match_identity_hints"), dict) else {}
    assessment = payload.get("assessment") if isinstance(payload.get("assessment"), dict) else {}
    visible_name = str(hints.get("visible_name") or candidate_key)
    latest_preview = str(assessment.get("latest_match_message") or assessment.get("latest_user_message") or "")
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
                {
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
                    "evidence": "Synthetic single-entry scan batch from current thread.",
                }
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
