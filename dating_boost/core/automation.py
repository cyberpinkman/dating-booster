from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from dating_boost.core.automation_prioritization import (
    HISTORICAL_THREAD_CUTOFF_DAYS,
    _candidate_type_for_entry,
    _entry_history_reason,
    _is_handoff_assessment,
    _is_non_chat_message_list_entry,
    _next_priority_queue,
    _prioritize_entries,
    _split_entries_at_history_cutoff,
    _stable_waiting_state_without_new_inbound,
)
from dating_boost.core.automation_report import (
    _build_summary,
    _human_report,
    _report_with_memory_display,
)
from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.goals import DEFAULT_GOAL_TYPE, get_goal_type_definition
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.proposals import extract_proposals
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.memory.retrieval import build_memory_context
from dating_boost.core.memory.review_queue import ReviewQueueRepository
from dating_boost.core.models import ReplyMode
from dating_boost.core.planner import PlannerRepository, planner_context_items
from dating_boost.core.relationship_report import (
    RELATIONSHIP_PROGRESS_NEXT_ACTION,
    build_relationship_progress_report,
)
from dating_boost.core.repositories import JsonMemoryRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.core.user_disclosure import UserDisclosureRepository
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import review_draft

from dating_boost.core.automation_send_gate import (
    _authorization_revoked_or_expired,
    _can_request_nudge,
    _can_request_send,
    _handoff_reason,
    _queue_send_request_for_repository,
    _release_active_send_request_after_failure,
    _send_authorization_block_reason,
    _target_profile_ready_for_send,
)
from dating_boost.core.automation_state import (
    _action_result_mismatch,
    _digest,
    _draft_payload_hash,
    _goal_type_from_payload,
    _new_state,
    _non_empty,
    _normalize_scan_cursor,
    _now_iso,
    _parse_iso_utc,
    _provisional_match_id,
    _reserve_slot,
    _stage_result_mismatch,
    _state_update,
    _unique_strings,
)


class AutomationRepository:
    def __init__(self, root: Path, *, nudge_delay_minutes: int = 30):
        self.root = root
        self._storage = JsonStorage(root)
        self._nudge_delay_minutes = max(1, int(nudge_delay_minutes))

    def _now(self) -> str:
        return _now_iso()

    def save_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        goal_id = _non_empty(payload.get("goal_id"), "goal_id")
        goal_type = _goal_type_from_payload(payload)
        try:
            get_goal_type_definition(goal_type)
        except ValueError as exc:
            raise ValueError(f"unsupported_goal_type: {goal_type}") from exc
        normalized = {key: value for key, value in payload.items() if key != "kind"}
        normalized["goal_type"] = goal_type
        document = self._load_collection(Path("automation") / "goals.json", "goals")
        items = {item["goal_id"]: dict(item) for item in document["goals"]}
        items[goal_id] = normalized
        document["goals"] = sorted(items.values(), key=lambda item: str(item["goal_id"]))
        self._storage.write_json(Path("automation") / "goals.json", document)
        return {"schema_version": 1, "status": "ok", "goal_id": goal_id, "goal_type": goal_type}

    def load_goals_payload(self) -> dict[str, Any]:
        document = self._load_collection(Path("automation") / "goals.json", "goals")
        return {"schema_version": 1, "status": "ok", "goals": list(document["goals"])}

    def save_availability(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = list(payload.get("availability", []))
        self._storage.write_json(
            Path("automation") / "availability.json",
            {"schema_version": 1, "availability": items},
        )
        return {"schema_version": 1, "status": "ok", "availability_count": len(items)}

    def save_authorization(self, payload: dict[str, Any]) -> dict[str, Any]:
        authorization_id = _non_empty(payload.get("authorization_id"), "authorization_id")
        self._storage.write_json(
            Path("automation") / "authorization.json",
            dict(payload),
        )
        return {
            "schema_version": 1,
            "status": "ok",
            "authorization_id": authorization_id,
            "autonomous_send": bool(payload.get("autonomous_send")),
            "revoked": bool(payload.get("revoked_at")),
        }

    def load_authorization(self) -> dict[str, Any] | None:
        try:
            return self._storage.read_json(Path("automation") / "authorization.json", expected_schema_version=1)
        except FileNotFoundError:
            return None

    def start_session(self, authorization: dict[str, Any], *, session_config: dict[str, Any] | None = None) -> dict[str, Any]:
        memory_review = self.needs_memory_review()
        auth_result = self.save_authorization(authorization)
        readiness = UserDisclosureRepository(self.root).readiness(mode="autonomous")
        if authorization.get("autonomous_send") and not readiness["ready"]:
            return {
                "schema_version": 1,
                "status": "needs_user_profile",
                "reason": "autonomous_requires_user_profile",
                "authorization_id": auth_result["authorization_id"],
                "user_profile_readiness": readiness,
                "resumed_from_report": None,
                "memory_review": memory_review if memory_review.get("needs_memory_review") else None,
            }
        latest_report_path = self._latest_machine_report_path()
        session_id = f"session_{auth_result['authorization_id']}_{_digest(authorization)[:8]}"
        now = self._now()
        session = {
            "schema_version": 1,
            "session_id": session_id,
            "authorization_id": auth_result["authorization_id"],
            "status": "active",
            "started_at": now,
            "stopped_at": None,
            "step_count": 0,
            "last_scan_cursor": None,
            "session_config": dict(session_config or {}),
            "resumed_from_report": str(latest_report_path) if latest_report_path else None,
            "user_profile_readiness": readiness,
        }
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "active",
            "session_id": session_id,
            "authorization_id": auth_result["authorization_id"],
            "resumed_from_report": session["resumed_from_report"],
            "memory_review": memory_review if memory_review.get("needs_memory_review") else None,
            "warnings": ["pending_memory_suggestions_require_review"]
            if memory_review.get("needs_memory_review")
            else [],
        }

    def stop_session(self) -> dict[str, Any]:
        session = self._load_session()
        states = self.load_states()
        ledger = self.load_ledger()
        user_readiness = UserDisclosureRepository(self.root).readiness(mode="autonomous")
        summary = _build_summary(states, ledger, user_readiness)
        now = self._now()
        machine_path = Path("automation") / "reports" / "machine_latest.json"
        human_path = Path("automation") / "reports" / "human_latest.md"
        review_repo = ReviewQueueRepository(self.root)
        pending_items = review_repo.load_items(session_id=session["session_id"], status="pending")
        now_iso = now
        for item in pending_items:
            item.reported_at = now_iso
        review_repo._storage.write_jsonl(
            Path("memory") / "review_queue.jsonl",
            [row.to_dict() for row in review_repo.load_items()],
        )
        memory_review = {
            "required": len(pending_items) > 0,
            "pending_count": len(pending_items),
            "items": [item.to_dict() for item in pending_items],
            "accept_command_template": "memory review decide --data-dir DIR --accept {review_item_id}",
            "reject_command_template": "memory review decide --data-dir DIR --reject {review_item_id}",
        }
        machine_report = {
            "schema_version": 1,
            "session_id": session["session_id"],
            "authorization_id": session.get("authorization_id"),
            "started_at": session.get("started_at"),
            "stopped_at": now,
            "summary": summary,
            "user_profile_readiness": user_readiness,
            "memory_review": memory_review,
            "states": states,
            "conversation_plans": self._planner_plans(states),
            "appointment_ledger": ledger,
            "next_priority_queue": _next_priority_queue(states),
        }
        self._storage.write_json(machine_path, machine_report)
        self._write_text(human_path, _human_report(machine_report))
        session["status"] = "stopped"
        session["stopped_at"] = now
        self._storage.write_json(Path("automation") / "session.json", session)
        relationship_report = build_relationship_progress_report(
            data_dir=self.root,
            human_report_path=human_path,
            machine_report_path=machine_path,
            summary=summary,
        )
        return {
            "schema_version": 1,
            "status": "stopped",
            "session_id": session["session_id"],
            "machine_report_path": str(machine_path),
            "human_report_path": str(human_path),
            "summary": summary,
            "memory_review": memory_review,
            "relationship_progress_report": relationship_report,
            "next_host_action": RELATIONSHIP_PROGRESS_NEXT_ACTION,
        }

    def latest_report(self) -> dict[str, Any]:
        path = self._latest_machine_report_path()
        session = self._load_session_or_none()
        if session and session.get("status") == "active":
            return {
                "schema_version": 1,
                "status": "ok",
                "machine_report_path": None,
                "machine_report": _report_with_memory_display(self._active_machine_report(session)),
            }
        if path is None:
            return {"schema_version": 1, "status": "not_found"}
        report = _report_with_memory_display(self._refresh_report_current_state(self._storage.read_json(path, expected_schema_version=1)))
        return {
            "schema_version": 1,
            "status": "ok",
            "machine_report_path": str(path),
            "machine_report": report,
        }

    def latest_human_report(self) -> str:
        latest = self.latest_report()
        if latest.get("status") == "ok" and isinstance(latest.get("machine_report"), dict):
            return _human_report(latest["machine_report"]).rstrip()
        raise FileNotFoundError(Path("automation") / "reports" / "machine_latest.json")

    def _refresh_report_current_state(self, report: dict[str, Any]) -> dict[str, Any]:
        refreshed = dict(report)
        states = self.load_states()
        ledger = self.load_ledger()
        user_readiness = UserDisclosureRepository(self.root).readiness(mode="autonomous")
        refreshed["states"] = states
        refreshed["summary"] = _build_summary(states, ledger, user_readiness)
        refreshed["user_profile_readiness"] = user_readiness
        refreshed["conversation_plans"] = self._planner_plans(states)
        refreshed["appointment_ledger"] = ledger
        refreshed["next_priority_queue"] = _next_priority_queue(states)
        return refreshed

    def _active_machine_report(self, session: dict[str, Any]) -> dict[str, Any]:
        states = self.load_states()
        ledger = self.load_ledger()
        user_readiness = UserDisclosureRepository(self.root).readiness(mode="autonomous")
        review_repo = ReviewQueueRepository(self.root)
        pending_items = review_repo.load_items(session_id=session["session_id"], status="pending")
        memory_review = {
            "required": len(pending_items) > 0,
            "pending_count": len(pending_items),
            "items": [item.to_dict() for item in pending_items],
            "accept_command_template": "memory review decide --data-dir DIR --accept {review_item_id}",
            "reject_command_template": "memory review decide --data-dir DIR --reject {review_item_id}",
        }
        return {
            "schema_version": 1,
            "session_id": session["session_id"],
            "authorization_id": session.get("authorization_id"),
            "started_at": session.get("started_at"),
            "stopped_at": None,
            "report_status": "active",
            "summary": _build_summary(states, ledger, user_readiness),
            "user_profile_readiness": user_readiness,
            "memory_review": memory_review,
            "states": states,
            "conversation_plans": self._planner_plans(states),
            "appointment_ledger": ledger,
            "next_priority_queue": _next_priority_queue(states),
        }

    def load_states(self) -> list[dict[str, Any]]:
        return list(self._load_collection(Path("automation") / "states.json", "states")["states"])

    def save_states(self, states: list[dict[str, Any]]) -> None:
        self._storage.write_json(
            Path("automation") / "states.json",
            {"schema_version": 1, "states": sorted(states, key=lambda item: str(item["match_id"]))},
        )

    def get_state_payload(self) -> dict[str, Any]:
        return {"schema_version": 1, "status": "ok", "states": self.load_states()}

    def pause_session(self) -> dict[str, Any]:
        session = self._load_session()
        session["status"] = "paused"
        session["paused_at"] = self._now()
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": session["session_id"],
            "paused": True,
        }

    def resume_session(self) -> dict[str, Any]:
        session = self._load_session()
        session["status"] = "active"
        session["resumed_at"] = self._now()
        self._storage.write_json(Path("automation") / "session.json", session)
        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": session["session_id"],
            "paused": False,
        }

    def load_ledger(self) -> list[dict[str, Any]]:
        return list(self._load_collection(Path("automation") / "appointment_ledger.json", "slots")["slots"])

    def save_ledger(self, slots: list[dict[str, Any]]) -> None:
        self._storage.write_json(
            Path("automation") / "appointment_ledger.json",
            {"schema_version": 1, "slots": sorted(slots, key=lambda item: str(item["slot_id"]))},
        )

    def _active_goal_id(self) -> str:
        return str(self._active_goal_payload()["goal_id"])

    def _active_goal_payload(self) -> dict[str, str]:
        goals = list(self._load_collection(Path("automation") / "goals.json", "goals")["goals"])
        for goal in goals:
            if _goal_type_from_payload(goal) == DEFAULT_GOAL_TYPE:
                return {
                    "goal_id": str(goal.get("goal_id") or "goal_meet"),
                    "goal_type": _goal_type_from_payload(goal),
                }
        if goals:
            goal = goals[0]
            return {
                "goal_id": str(goal.get("goal_id") or "goal_meet"),
                "goal_type": _goal_type_from_payload(goal),
            }
        return {"goal_id": "goal_meet", "goal_type": DEFAULT_GOAL_TYPE}

    def _planner_plans(self, states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        planner = PlannerRepository(self.root)
        plans: list[dict[str, Any]] = []
        for state in states:
            plan = planner.load_plan(str(state.get("match_id")))
            if plan:
                plans.append(plan)
        return sorted(plans, key=lambda item: str(item.get("match_id")))

    def apply_action_result(self, event: dict[str, Any]) -> None:
        action_request_id = event.get("action_request_id")
        if not action_request_id:
            return
        now = self._now()
        states = self.load_states()
        changed = False
        for state in states:
            if state.get("last_action_request_id") != action_request_id:
                continue
            mismatch = _action_result_mismatch(event, state)
            if mismatch:
                state["last_action_result_event_id"] = event["event_id"]
                state["last_action_result_error"] = mismatch
                state["updated_at"] = event.get("created_at", now)
                changed = True
                continue
            state["last_action_result_event_id"] = event["event_id"]
            state.pop("last_action_result_error", None)
            if event.get("result_status") == "succeeded":
                state["last_outbound_action_id"] = event["event_id"]
                state["state"] = "sent_waiting"
            elif event.get("result_status") == "failed":
                state["state"] = "draft_ready"
                _release_active_send_request_after_failure(state, event_id=event["event_id"])
            state["updated_at"] = event.get("created_at", now)
            changed = True
        if changed:
            self.save_states(states)

    def apply_stage_result(self, event: dict[str, Any]) -> None:
        action_request_id = event.get("action_request_id")
        if not action_request_id:
            return
        now = self._now()
        states = self.load_states()
        changed = False
        for state in states:
            if state.get("last_action_request_id") != action_request_id:
                continue
            mismatch = _stage_result_mismatch(event, state)
            if mismatch:
                state["last_stage_result_event_id"] = event["event_id"]
                state["last_stage_result_error"] = mismatch
                state["updated_at"] = event.get("created_at", now)
                changed = True
                continue
            state["last_stage_result_event_id"] = event["event_id"]
            state.pop("last_stage_result_error", None)
            if event.get("result_status") == "succeeded":
                state["state"] = "staged_pending_user"
            elif event.get("result_status") == "failed":
                state["state"] = "draft_ready"
                _release_active_send_request_after_failure(state, event_id=event["event_id"])
            else:
                state["state"] = "stage_needs_verification"
            state["updated_at"] = event.get("created_at", now)
            changed = True
        if changed:
            self.save_states(states)

    def step(self, scan_batch: dict[str, Any]) -> dict[str, Any]:
        session = self._load_session()
        now = self._now()
        authorization = self.load_authorization() or {}
        if session.get("status") != "active":
            status = str(session.get("status") or "unknown")
            reason = "session_paused" if status == "paused" else "session_stopped" if status == "stopped" else "session_not_active"
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": reason,
                "action_requests": [],
                "handoffs": [],
                "scan_requests": [],
                "scheduled_actions": [],
                "warnings": [reason],
                "machine_report_ref": str(Path("automation") / "reports" / "machine_latest.json"),
            }
        if _authorization_revoked_or_expired(authorization, now):
            return {
                "schema_version": 1,
                "status": "blocked",
                "reason": "authorization_expired_or_revoked",
                "action_requests": [],
                "handoffs": [],
                "scan_requests": [],
                "scheduled_actions": [],
                "warnings": ["authorization_expired_or_revoked"],
                "machine_report_ref": None,
            }

        states = self.load_states()
        states_by_match = {state["match_id"]: dict(state) for state in states}
        states_by_candidate = {
            state.get("candidate_key"): dict(state)
            for state in states
            if state.get("candidate_key")
        }
        ledger = self.load_ledger()
        thread_items = {
            item.get("candidate_key"): dict(item)
            for item in scan_batch.get("thread_observations", [])
            if item.get("candidate_key")
        }
        visible_entries = list(scan_batch.get("message_list_snapshot", {}).get("entries", []))
        entries_before_cutoff, historical_entries, history_cutoff_reached = _split_entries_at_history_cutoff(
            visible_entries,
            captured_at=str(scan_batch.get("captured_at") or now),
        )
        entries = _prioritize_entries(
            entries_before_cutoff,
            states_by_candidate=states_by_candidate,
            thread_items=thread_items,
        )
        budget = int(scan_batch.get("scan_budget") or 5)
        processed_entries = entries[:budget]
        over_budget_entries = entries[budget:]
        scan_cursor = _normalize_scan_cursor(scan_batch.get("scan_cursor"))

        action_requests: list[dict[str, Any]] = []
        handoffs: list[dict[str, Any]] = []
        scan_requests: list[dict[str, Any]] = []
        scheduled_actions: list[dict[str, Any]] = []
        state_updates: list[dict[str, Any]] = []
        warnings: list[str] = []
        processed_match_count = 0
        if history_cutoff_reached:
            warnings.append("message_list_history_cutoff_reached")

        for entry in historical_entries:
            if _is_non_chat_message_list_entry(entry):
                warnings.append("non_chat_message_list_entry_skipped")
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
            state["last_scan_cursor"] = scan_cursor
            state["history_cutoff_reason"] = _entry_history_reason(entry, captured_at=str(scan_batch.get("captured_at") or now))
            state["updated_at"] = scan_batch.get("captured_at", now)
            states_by_match[state["match_id"]] = state
            state_updates.append(_state_update(state))
            scheduled_actions.append(
                {
                    "type": "historical_thread_skipped",
                    "candidate_key": candidate_key,
                    "visible_name": entry.get("visible_name"),
                    "reason": state["history_cutoff_reason"],
                    "scan_cursor": scan_cursor,
                }
            )

        for entry in processed_entries:
            if _is_non_chat_message_list_entry(entry):
                warnings.append("non_chat_message_list_entry_skipped")
                continue
            candidate_key = _non_empty(entry.get("candidate_key"), "candidate_key")
            thread_item = thread_items.get(candidate_key)
            if thread_item is None:
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
                    state["updated_at"] = scan_batch.get("captured_at", now)
                    states_by_match[state["match_id"]] = state
                    state_updates.append(_state_update(state))
                    continue
                state["state"] = "needs_thread_scan"
                state["candidate_type"] = _candidate_type_for_entry(state, entry)
                state["visible_name"] = entry.get("visible_name")
                state["last_preview_hash"] = entry.get("latest_preview_hash")
                state["unread_cue"] = entry.get("unread_cue")
                state["updated_at"] = scan_batch.get("captured_at", now)
                states_by_match[state["match_id"]] = state
                scan_requests.append(
                    {
                        "candidate_key": candidate_key,
                        "reason": "thread_observation_required",
                        "visible_name": entry.get("visible_name"),
                    }
                )
                state_updates.append(_state_update(state))
                continue

            processed_match_count += 1
            observation = AppObservation.from_dict(thread_item["observation"])
            ingest = self._store_observation(observation)
            match_id = ingest["match_id"]
            self._extract_and_enqueue_proposals(
                match_id, observation, session_id=session["session_id"],
                observation_id=observation.observation_id, created_at=now,
            )
            assessment = dict(thread_item.get("assessment", {}))
            host_identity_confidence = str(thread_item.get("identity_confidence") or "medium")
            latest_fingerprint = assessment.get("latest_inbound_fingerprint")
            state = states_by_match.get(match_id)
            if state is None:
                state = states_by_candidate.get(candidate_key)
                if state is not None:
                    previous_match_id = state["match_id"]
                    if previous_match_id != match_id:
                        states_by_match.pop(previous_match_id, None)
                        if str(previous_match_id).startswith("provisional_"):
                            state["previous_provisional_match_id"] = previous_match_id
                        state["match_id"] = match_id
                else:
                    state = _new_state(
                        match_id=match_id,
                        candidate_key=candidate_key,
                        session_id=session["session_id"],
                        timestamp=now,
                    )
            state["candidate_key"] = candidate_key
            state["visible_name"] = entry.get("visible_name") or observation.match_identity_hints.visible_name
            state["last_session_id"] = session["session_id"]
            state["last_inbound_observation_id"] = observation.observation_id
            state["latest_inbound_fingerprint"] = latest_fingerprint
            state["last_preview_hash"] = entry.get("latest_preview_hash")
            state["unread_cue"] = entry.get("unread_cue")
            state["last_assessment"] = assessment
            state["updated_at"] = scan_batch.get("captured_at", observation.captured_at)
            state["candidate_type"] = _candidate_type_for_entry(state, entry)
            state["seen_before"] = True
            planner_payload: dict[str, Any] | None = None
            planner_recommendation: dict[str, Any] | None = None
            planner_assessment = thread_item.get("planner_assessment")
            if planner_assessment is not None:
                try:
                    active_goal = self._active_goal_payload()
                    planner_payload = PlannerRepository(self.root).update_plan(
                        match_id=match_id,
                        goal_id=str(state.get("goal_id") or active_goal["goal_id"]),
                        observation=observation,
                        assessment=dict(planner_assessment),
                        now=now,
                        goal_type=str(active_goal["goal_type"]),
                    )
                except (TypeError, ValueError) as exc:
                    warnings.append("planner_assessment_invalid")
                    state["state"] = "needs_reply"
                    state["planner_error"] = str(exc)
                    states_by_match[match_id] = state
                    state_updates.append(_state_update(state))
                    continue
                goal_plan = dict(planner_payload["goal_plan"])
                planner_recommendation = dict(planner_payload["recommendation"])
                state["goal_id"] = goal_plan.get("goal_id")
                state["conversation_stage"] = goal_plan.get("stage")
                state["planner_revision"] = goal_plan.get("plan_revision")
                state["planner_recommended_move"] = goal_plan.get("recommended_move")
                state["next_milestone"] = goal_plan.get("next_milestone")
                state["question_debt"] = goal_plan.get("question_debt")
                state["self_disclosure_debt"] = goal_plan.get("self_disclosure_debt")
                state["reciprocity_balance"] = goal_plan.get("reciprocity_balance")
                state["low_investment_streak"] = goal_plan.get("low_investment_streak")
                state["match_curiosity_about_user"] = goal_plan.get("match_curiosity_about_user")
                state["topic_exit_pressure"] = goal_plan.get("topic_exit_pressure")
                if goal_plan.get("recommended_move") == "slow_down_wait":
                    state["pause_reason"] = "low_reciprocity"

            if planner_recommendation and planner_recommendation.get("requires_handoff"):
                handoff_reason = str(planner_recommendation.get("handoff_reason") or "appointment_details_requested")
                slot_conflict = False
                if thread_item.get("appointment_slot"):
                    slot, slot_conflict = _reserve_slot(
                        ledger,
                        match_id=match_id,
                        candidate_key=candidate_key,
                        slot_payload=dict(thread_item["appointment_slot"]),
                        timestamp=now,
                    )
                    state["appointment_slot_id"] = slot["slot_id"]
                state["state"] = "appointment_handoff"
                state["handoff_reason"] = handoff_reason
                handoffs.append(
                    {
                        "match_id": match_id,
                        "candidate_key": candidate_key,
                        "reason": handoff_reason,
                        "slot_conflict": slot_conflict,
                        "assessment": assessment,
                        "planner_stage": planner_recommendation.get("conversation_stage"),
                        "planner_revision": planner_recommendation.get("planner_revision"),
                        "suggested_user_decision": "选择具体日期、时间段、区域",
                    }
                )
                states_by_match[match_id] = state
                state_updates.append(_state_update(state))
                continue

            if _is_handoff_assessment(assessment):
                handoff_reason = _handoff_reason(assessment)
                slot_conflict = False
                if thread_item.get("appointment_slot"):
                    slot, slot_conflict = _reserve_slot(
                        ledger,
                        match_id=match_id,
                        candidate_key=candidate_key,
                        slot_payload=dict(thread_item["appointment_slot"]),
                        timestamp=now,
                    )
                    state["appointment_slot_id"] = slot["slot_id"]
                state["state"] = "appointment_handoff"
                state["handoff_reason"] = handoff_reason
                handoffs.append(
                    {
                        "match_id": match_id,
                        "candidate_key": candidate_key,
                        "reason": handoff_reason,
                        "slot_conflict": slot_conflict,
                        "assessment": assessment,
                        "planner_stage": planner_recommendation.get("conversation_stage") if planner_recommendation else None,
                        "planner_revision": planner_recommendation.get("planner_revision") if planner_recommendation else None,
                    }
                )
                states_by_match[match_id] = state
                state_updates.append(_state_update(state))
                continue

            draft_payload = thread_item.get("draft")
            if planner_recommendation is None and draft_payload and assessment.get("recommended_next") in {"reply", "nudge_later"}:
                state["state"] = "needs_reply"
                warnings.append("planner_assessment_required")
            elif planner_recommendation and not planner_recommendation.get("auto_send_allowed"):
                if planner_recommendation.get("recommended_move") in {"wait", "slow_down_wait"}:
                    state["state"] = "waiting_for_match"
                    state["pause_reason"] = "low_reciprocity" if planner_recommendation.get("recommended_move") == "slow_down_wait" else "planner_wait"
                else:
                    state["state"] = "needs_reply"
                warnings.extend(str(reason) for reason in planner_recommendation.get("block_reasons", []))
            elif host_identity_confidence == "low":
                state["state"] = "needs_reply"
                warnings.append("low_identity_confidence")
            elif draft_payload and not _target_profile_ready_for_send(observation):
                state["state"] = "needs_target_profile"
                warnings.append("target_profile_required")
            elif draft_payload and (
                auth_block := _send_authorization_block_reason(
                    authorization,
                    match_id=match_id,
                    app_id=observation.app_id,
                    now=now,
                )
            ):
                state["state"] = "needs_reply"
                warnings.append(auth_block)
            elif _can_request_send(
                authorization,
                ingest,
                assessment,
                state,
                draft_payload,
                match_id=match_id,
                app_id=observation.app_id,
                now=now,
            ):
                self._queue_send_request(
                    action_requests=action_requests,
                    scan_requests=scan_requests,
                    warnings=warnings,
                    state=state,
                    match_id=match_id,
                    candidate_key=candidate_key,
                    observation=observation,
                    draft_payload=draft_payload,
                    latest_fingerprint=latest_fingerprint,
                    is_nudge=False,
                    authorization=authorization,
                    planner_recommendation=planner_recommendation,
                    target_binding=thread_item.get("target_binding"),
                    standalone_draft_review=thread_item.get("standalone_draft_review"),
                )
            elif assessment.get("recommended_next") == "reply":
                state["state"] = "needs_reply"
            elif assessment.get("recommended_next") == "nudge_later":
                if host_identity_confidence == "low":
                    state["state"] = "needs_reply"
                    warnings.append("low_identity_confidence")
                elif draft_payload and (
                    auth_block := _send_authorization_block_reason(
                        authorization,
                        match_id=match_id,
                        app_id=observation.app_id,
                        now=now,
                    )
                ):
                    state["state"] = "nudge_scheduled" if auth_block == "authorization_quiet_hours" else "needs_reply"
                    warnings.append(auth_block)
                elif _can_request_nudge(
                    authorization,
                    ingest,
                    assessment,
                    state,
                    draft_payload,
                    now,
                    match_id=match_id,
                    app_id=observation.app_id,
                ):
                    self._queue_send_request(
                        action_requests=action_requests,
                        scan_requests=scan_requests,
                        warnings=warnings,
                        state=state,
                        match_id=match_id,
                        candidate_key=candidate_key,
                        observation=observation,
                        draft_payload=draft_payload,
                        latest_fingerprint=latest_fingerprint,
                        is_nudge=True,
                        authorization=authorization,
                        planner_recommendation=planner_recommendation,
                        target_binding=thread_item.get("target_binding"),
                        standalone_draft_review=thread_item.get("standalone_draft_review"),
                    )
                elif state.get("last_nudged_inbound_fingerprint") == latest_fingerprint:
                    if draft_payload and _draft_payload_hash(dict(draft_payload)) == state.get("last_outbound_payload_hash"):
                        warnings.append("duplicate_send_request_suppressed")
                    state["state"] = state.get("state") if state.get("state") == "send_requested" else "waiting_for_match"
                elif state.get("state") == "nudge_scheduled" and state.get("latest_inbound_fingerprint") == latest_fingerprint:
                    state["state"] = "nudge_scheduled"
                else:
                    due_at = (
                        _parse_iso_utc(now) + timedelta(minutes=self._nudge_delay_minutes)
                    ).isoformat().replace("+00:00", "Z")
                    state["state"] = "nudge_scheduled"
                    state["next_due_at"] = due_at
                    scheduled_actions.append(
                        {
                            "type": "nudge_later",
                            "match_id": match_id,
                            "candidate_key": candidate_key,
                            "latest_inbound_fingerprint": latest_fingerprint,
                            "due_at": due_at,
                            "reason": "host_assessed_continuation_opportunity",
                        }
                    )
            else:
                state["state"] = "sent_waiting"

            states_by_match[match_id] = state
            state_updates.append(_state_update(state))

        for entry in over_budget_entries:
            if _is_non_chat_message_list_entry(entry):
                warnings.append("non_chat_message_list_entry_skipped")
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
                state["last_scan_cursor"] = scan_cursor
                state["updated_at"] = scan_batch.get("captured_at", now)
                states_by_match[state["match_id"]] = state
                state_updates.append(_state_update(state))
                continue
            state["state"] = "scan_later"
            state["candidate_key"] = candidate_key
            state["candidate_type"] = _candidate_type_for_entry(state, entry)
            state["visible_name"] = entry.get("visible_name")
            state["last_preview_hash"] = entry.get("latest_preview_hash")
            state["unread_cue"] = entry.get("unread_cue")
            state["last_scan_cursor"] = scan_cursor
            state["updated_at"] = scan_batch.get("captured_at", now)
            states_by_match[state["match_id"]] = state
            scheduled_actions.append(
                {
                    "type": "scan_later",
                    "candidate_key": candidate_key,
                    "visible_name": entry.get("visible_name"),
                    "reason": "scan_budget_exceeded",
                    "scan_cursor": scan_cursor,
                }
            )

        self.save_states(list(states_by_match.values()))
        self.save_ledger(ledger)
        session["step_count"] = int(session.get("step_count") or 0) + 1
        session["last_scan_cursor"] = scan_cursor
        self._storage.write_json(Path("automation") / "session.json", session)
        next_priority_queue = _next_priority_queue(list(states_by_match.values()))

        return {
            "schema_version": 1,
            "status": "ok",
            "session_id": session["session_id"],
            "scan_budget": budget,
            "processed_entry_count": len(processed_entries),
            "processed_match_count": processed_match_count,
            "state_updates": state_updates,
            "action_requests": action_requests,
            "handoffs": handoffs,
            "scan_requests": scan_requests,
            "scheduled_actions": scheduled_actions,
            "next_priority_queue": next_priority_queue,
            "warnings": _unique_strings(warnings),
            "history_cutoff_reached": history_cutoff_reached,
            "historical_entry_count": len(historical_entries),
            "machine_report_ref": str(Path("automation") / "reports" / "machine_latest.json"),
        }

    def _load_session(self) -> dict[str, Any]:
        try:
            return self._storage.read_json(Path("automation") / "session.json", expected_schema_version=1)
        except FileNotFoundError:
            session = {
                "schema_version": 1,
                "session_id": "session_implicit",
                "authorization_id": None,
                "status": "active",
                "started_at": self._now(),
                "stopped_at": None,
                "step_count": 0,
                "last_scan_cursor": None,
                "resumed_from_report": None,
            }
            self._storage.write_json(Path("automation") / "session.json", session)
            return session

    def _load_collection(self, path: Path, key: str) -> dict[str, Any]:
        try:
            return self._storage.read_json(path, expected_schema_version=1)
        except FileNotFoundError:
            return {"schema_version": 1, key: []}

    def _latest_machine_report_path(self) -> Path | None:
        path = Path("automation") / "reports" / "machine_latest.json"
        absolute = (self._storage.root / path).resolve()
        return path if absolute.exists() else None

    def _write_text(self, relative_path: Path, text: str) -> None:
        path = (self._storage.root / relative_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _store_observation(self, observation: AppObservation) -> dict[str, Any]:
        return store_observation_with_memory(self.root, observation)

    def _extract_and_enqueue_proposals(
        self,
        match_id: str,
        observation: AppObservation,
        *,
        session_id: str,
        observation_id: str,
        created_at: str,
    ) -> int:
        memory_repo = MemoryRepository(self.root)
        projection = memory_repo.load_projection(match_id)
        if projection is None:
            return 0
        proposals = extract_proposals(
            match_id,
            observation,
            projection,
            session_id=session_id,
            observation_id=observation_id,
            created_at=created_at,
            source="deterministic",
        )
        review_repo = ReviewQueueRepository(self.root)
        enqueued = 0
        for proposal in proposals:
            if review_repo.reject_dedupe_key_exists(proposal.dedupe_key):
                continue
            review_repo.enqueue(proposal)
            enqueued += 1
        return enqueued

    def needs_memory_review(self) -> dict[str, Any]:
        review_repo = ReviewQueueRepository(self.root)
        if not review_repo.has_pending():
            return {"schema_version": 1, "status": "ok", "needs_memory_review": False}
        session = self._load_session_or_none()
        session_id = session.get("session_id") if session else None
        pending = review_repo.load_items(status="pending", session_id=session_id)
        latest_report_path = self._latest_machine_report_path()
        return {
            "schema_version": 1,
            "status": "needs_memory_review",
            "needs_memory_review": True,
            "pending_count": len(pending),
            "report_path": str(latest_report_path) if latest_report_path else None,
        }

    def _load_session_or_none(self) -> dict[str, Any] | None:
        try:
            return self._storage.read_json(Path("automation") / "session.json", expected_schema_version=1)
        except FileNotFoundError:
            return None

    def _context_pack(self, match_id: str, observation: AppObservation) -> dict[str, Any]:
        now = self._now()
        profile = JsonMemoryRepository(self.root).load_user_profile()
        user_profile = {
            "facts": [item.to_dict() for item in profile.facts],
            "preferences": [item.to_dict() for item in profile.preferences],
            "boundaries": [item.to_dict() for item in profile.boundaries],
            "style_examples": list(profile.style_examples),
            "goals": list(profile.goals),
            "persona_baseline": profile.persona_baseline,
            "persona_range": list(profile.persona_range),
            "stance_range": list(profile.stance_range),
        }
        disclosure_repo = UserDisclosureRepository(self.root)
        disclosure_profile = disclosure_repo.load_profile_or_none()
        if disclosure_profile is not None:
            user_profile["disclosure_profile"] = disclosure_profile
        user_profile["disclosure_readiness"] = disclosure_repo.readiness(mode="draft")
        projection = MemoryRepository(self.root).load_projection(match_id)
        if projection is not None:
            memory_context = build_memory_context(
                match_id,
                projection,
                latest_observation=observation,
                now=now,
                max_items=None,
                reply_mode=ReplyMode.ADAPTIVE.value,
            )
            match_profile = memory_context["match_profile"]
            conversation_memory = dict(memory_context["conversation_memory"])
            conversation_memory["memory_items"] = memory_context.get("memory_items")
        else:
            match_profile = {
                "match_id": match_id,
                "display_name": observation.match_identity_hints.visible_name,
                "profile_text": observation.profile_observation.profile_text,
                "conversation_hooks": list(observation.profile_observation.hook_candidates),
                "possible_interests": [
                    {"name": cue, "confidence": "medium"}
                    for cue in [
                        *observation.profile_observation.photo_cues,
                        *observation.profile_observation.hook_candidates,
                    ]
                ],
            }
            messages = [dict(message) for message in observation.conversation_observation.visible_messages]
            latest_inbound_messages = [
                dict(message)
                for message in observation.conversation_observation.latest_inbound_messages
            ]
            conversation_memory = {
                "recent_messages": messages,
                "latest_inbound_messages": latest_inbound_messages,
                "open_threads": list(observation.conversation_observation.thread_cues),
                "commitments": [],
                "running_summary": " ".join(message.get("text", "") for message in messages).strip(),
            }
        conversation_memory.update(planner_context_items(PlannerRepository(self.root).load_plan(match_id)))
        conversation_memory["appointment_constraints"] = self._load_collection(
            Path("automation") / "availability.json",
            "availability",
        ).get("availability", [])
        conversation_memory["global_slot_conflicts"] = [
            slot for slot in self.load_ledger() if slot.get("conflict")
        ]
        return build_context_pack(
            user_profile=user_profile,
            match_profile=match_profile,
            conversation_memory=conversation_memory,
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
            current_time_iso=now,
        )

    def _queue_send_request(
        self,
        *,
        action_requests: list[dict[str, Any]],
        scan_requests: list[dict[str, Any]],
        warnings: list[str],
        state: dict[str, Any],
        match_id: str,
        candidate_key: str,
        observation: AppObservation,
        draft_payload: Any,
        latest_fingerprint: str | None,
        is_nudge: bool,
        authorization: dict[str, Any],
        planner_recommendation: dict[str, Any] | None = None,
        target_binding: Any = None,
        standalone_draft_review: Any = None,
    ) -> None:
        _queue_send_request_for_repository(
            self,
            action_requests=action_requests,
            scan_requests=scan_requests,
            warnings=warnings,
            state=state,
            match_id=match_id,
            candidate_key=candidate_key,
            observation=observation,
            draft_payload=draft_payload,
            latest_fingerprint=latest_fingerprint,
            is_nudge=is_nudge,
            authorization=authorization,
            review_draft_fn=review_draft,
            planner_recommendation=planner_recommendation,
            target_binding=target_binding,
            standalone_draft_review=standalone_draft_review,
        )
