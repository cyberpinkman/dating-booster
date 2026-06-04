from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.goals import DEFAULT_GOAL_TYPE, get_goal_type_definition
from dating_boost.core.identity import resolve_match_identity
from dating_boost.core.models import Divergence, ReplyMode
from dating_boost.core.planner import PlannerRepository, planner_context_items
from dating_boost.core.production_store import payload_digest
from dating_boost.core.repositories import JsonMemoryRepository, MatchRepository, ObservationRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.core.user_disclosure import UserDisclosureRepository
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.content import evaluate_draft_content


ACTIVE_SLOT_STATUSES = {"soft_mentioned", "handoff_pending", "user_confirmed"}


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

    def start_session(self, authorization: dict[str, Any]) -> dict[str, Any]:
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
        machine_report = {
            "schema_version": 1,
            "session_id": session["session_id"],
            "authorization_id": session.get("authorization_id"),
            "started_at": session.get("started_at"),
            "stopped_at": now,
            "summary": summary,
            "user_profile_readiness": user_readiness,
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
        return {
            "schema_version": 1,
            "status": "stopped",
            "session_id": session["session_id"],
            "machine_report_path": str(machine_path),
            "human_report_path": str(human_path),
            "summary": summary,
        }

    def latest_report(self) -> dict[str, Any]:
        path = self._latest_machine_report_path()
        if path is None:
            return {"schema_version": 1, "status": "not_found"}
        report = self._storage.read_json(path, expected_schema_version=1)
        return {
            "schema_version": 1,
            "status": "ok",
            "machine_report_path": str(path),
            "machine_report": report,
        }

    def latest_human_report(self) -> str:
        path = Path("automation") / "reports" / "human_latest.md"
        absolute = (self._storage.root / path).resolve()
        if not absolute.exists():
            raise FileNotFoundError(path)
        return absolute.read_text(encoding="utf-8").rstrip()

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
            state["last_outbound_action_id"] = event["event_id"]
            state.pop("last_action_result_error", None)
            if event.get("result_status") == "succeeded":
                state["state"] = "sent_waiting"
            elif event.get("result_status") == "failed":
                state["state"] = "draft_ready"
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
        entries = _prioritize_entries(
            list(scan_batch.get("message_list_snapshot", {}).get("entries", [])),
            states_by_candidate=states_by_candidate,
            thread_items=thread_items,
        )
        budget = int(scan_batch.get("scan_budget") or 5)
        processed_entries = entries[:budget]
        over_budget_entries = entries[budget:]

        action_requests: list[dict[str, Any]] = []
        handoffs: list[dict[str, Any]] = []
        scan_requests: list[dict[str, Any]] = []
        scheduled_actions: list[dict[str, Any]] = []
        state_updates: list[dict[str, Any]] = []
        warnings: list[str] = []
        processed_match_count = 0

        for entry in processed_entries:
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
                state["state"] = "needs_thread_scan"
                state["candidate_type"] = "continuation_candidate" if state.get("seen_before") else "new_match_candidate"
                state["visible_name"] = entry.get("visible_name")
                state["last_preview_hash"] = entry.get("latest_preview_hash")
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
            state["last_assessment"] = assessment
            state["updated_at"] = scan_batch.get("captured_at", observation.captured_at)
            state["candidate_type"] = "new_match_candidate" if not state.get("seen_before") else "continuation_candidate"
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
            elif planner_recommendation and draft_payload and not _draft_aligns_with_planner(dict(draft_payload), planner_recommendation):
                state["state"] = "needs_reply"
                warnings.append("planner_misaligned_draft")
            elif host_identity_confidence == "low":
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
            scheduled_actions.append(
                {
                    "type": "scan_later",
                    "candidate_key": entry.get("candidate_key"),
                    "visible_name": entry.get("visible_name"),
                    "reason": "scan_budget_exceeded",
                }
            )

        self.save_states(list(states_by_match.values()))
        self.save_ledger(ledger)
        session["step_count"] = int(session.get("step_count") or 0) + 1
        session["last_scan_cursor"] = scan_batch.get("scan_cursor")
        self._storage.write_json(Path("automation") / "session.json", session)

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
            "warnings": _unique_strings(warnings),
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
        match_repo = MatchRepository(self.root)
        identity = resolve_match_identity(observation, existing_matches=match_repo.list_match_candidates())
        ObservationRepository(self.root).save_observation(identity.match_id, observation)
        match_repo.upsert_match_from_observation(
            match_id=identity.match_id,
            observation=observation,
            confidence=identity.confidence.value,
            requires_user_confirmation=identity.requires_user_confirmation,
        )
        return {
            "match_id": identity.match_id,
            "confidence": identity.confidence.value,
            "requires_user_confirmation": identity.requires_user_confirmation,
            "observation_id": observation.observation_id,
        }

    def _context_pack(self, match_id: str, observation: AppObservation) -> dict[str, Any]:
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
        )

    def _queue_send_request(
        self,
        *,
        action_requests: list[dict[str, Any]],
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
    ) -> None:
        raw_draft = dict(draft_payload)
        draft = _draft_from_dict(raw_draft)
        disclosure_moves = {"light_self_disclosure", "reciprocal_disclosure", "low_investment_repair"}
        disclosure_repo = UserDisclosureRepository(self.root)
        disclosure_readiness = disclosure_repo.readiness(mode="autonomous")
        if draft.conversation_move in disclosure_moves and not disclosure_readiness["ready"]:
            state["state"] = "needs_reply"
            warnings.append("user_disclosure_profile_required")
            return
        disclosure_source = str(
            raw_draft.get("disclosure_source")
            or ("simulated_soft" if draft.conversation_move in disclosure_moves else "none")
        )
        used_material_ids = [
            str(item)
            for item in raw_draft.get("used_user_material_ids", [])
            if str(item).strip()
        ] if isinstance(raw_draft.get("used_user_material_ids"), list) else []
        disclosure_error = _disclosure_policy_error(
            draft_move=draft.conversation_move,
            disclosure_moves=disclosure_moves,
            disclosure_source=disclosure_source,
            used_material_ids=used_material_ids,
            disclosure_profile=disclosure_repo.load_profile_or_none(),
        )
        if disclosure_error:
            state["state"] = "needs_reply"
            warnings.append(disclosure_error)
            return

        question_count = _draft_question_count(raw_draft, draft.best_reply)
        if (
            planner_recommendation
            and int(planner_recommendation.get("low_investment_streak") or 0) >= 2
            and int(planner_recommendation.get("question_debt") or 0) >= 2
            and question_count > 0
        ):
            state["state"] = "needs_reply"
            warnings.append("low_investment_direct_question_blocked")
            return

        context_pack = self._context_pack(match_id, observation)
        policy = evaluate_draft_content(draft, context_pack)
        if not policy.allowed:
            state["state"] = "draft_ready"
            state["handoff_reason"] = "draft_blocked"
            warnings.append("draft_blocked")
            return

        payload_hash = _text_hash(draft.best_reply)
        if state.get("last_outbound_payload_hash") == payload_hash:
            warnings.append("duplicate_send_request_suppressed")
            return

        action_request_id = f"action_request_{match_id}_{payload_hash[:12]}"
        precondition = {
            "schema_version": 1,
            "action": "send_message",
            "target_match_id": match_id,
            "candidate_key": candidate_key,
            "pre_action_observation_id": observation.observation_id,
            "latest_inbound_fingerprint": latest_fingerprint,
        }
        precondition_hash = payload_digest(precondition)
        autonomous_audit_binding = {
            "schema_version": 1,
            "binding_type": "autonomous_authorization",
            "authorization_id": authorization.get("authorization_id"),
            "action": "send_message",
            "target_match_id": match_id,
            "payload_hash": payload_hash,
            "precondition_hash": precondition_hash,
        }
        low_investment_repair_applied = draft.conversation_move == "low_investment_repair"
        action_requests.append(
            {
                "schema_version": 1,
                "action_request_id": action_request_id,
                "match_id": match_id,
                "candidate_key": candidate_key,
                "action": "send_message",
                "payload_text": draft.best_reply,
                "payload_hash": payload_hash,
                "precondition_hash": precondition_hash,
                "autonomous_audit_binding": autonomous_audit_binding,
                "pre_action_observation_id": observation.observation_id,
                "requires_post_action_verification": True,
                "policy": {
                    "allowed": policy.allowed,
                    "severity": policy.severity,
                    "reason": policy.reason,
                    "requires_user_confirmation": policy.requires_user_confirmation,
                },
                "planner_revision": planner_recommendation.get("planner_revision") if planner_recommendation else None,
                "conversation_stage": planner_recommendation.get("conversation_stage") if planner_recommendation else None,
                "conversation_move": draft.conversation_move,
                "planner_alignment": "ok" if planner_recommendation else "not_provided",
                "next_milestone": planner_recommendation.get("next_milestone") if planner_recommendation else None,
                "disclosure_source": disclosure_source,
                "used_user_material_ids": used_material_ids,
                "question_debt_after": planner_recommendation.get("question_debt") if planner_recommendation else state.get("question_debt"),
                "reciprocity_balance_after": planner_recommendation.get("reciprocity_balance") if planner_recommendation else state.get("reciprocity_balance"),
                "low_investment_repair_applied": low_investment_repair_applied,
            }
        )
        state["state"] = "send_requested"
        state["last_action"] = "send_message"
        state["last_action_request_id"] = action_request_id
        state["last_outbound_payload_hash"] = payload_hash
        state["last_precondition_hash"] = precondition_hash
        state["last_autonomous_audit_binding"] = autonomous_audit_binding
        state["last_pre_action_observation_id"] = observation.observation_id
        state["last_draft_id"] = f"draft_{payload_hash[:12]}"
        state["last_disclosure_source"] = disclosure_source if disclosure_source != "none" else None
        state["used_user_material_ids"] = used_material_ids
        state["low_investment_repair_applied"] = low_investment_repair_applied
        if is_nudge:
            state["last_nudged_inbound_fingerprint"] = latest_fingerprint
            state["nudge_count_since_inbound"] = int(state.get("nudge_count_since_inbound") or 0) + 1
            state["next_due_at"] = None


def _draft_from_dict(data: dict[str, Any]) -> DraftResponse:
    return DraftResponse(
        best_reply=str(data["best_reply"]),
        safer_reply=str(data["safer_reply"]),
        bolder_reply=str(data["bolder_reply"]),
        why_this_works=str(data["why_this_works"]),
        situation_read=str(data["situation_read"]),
        conversation_move=str(data["conversation_move"]),
        hook_source=str(data["hook_source"]),
        naturalness_notes=[str(item) for item in data["naturalness_notes"]],
        followup_if_match_replies=str(data["followup_if_match_replies"]),
        risk_flags=[str(item) for item in data["risk_flags"]],
        missing_info=[str(item) for item in data["missing_info"]],
        mode_notes=str(data["mode_notes"]),
        persona_divergence=Divergence(str(data["persona_divergence"])),
        stance_divergence=Divergence(str(data["stance_divergence"])),
    )


def _disclosure_policy_error(
    *,
    draft_move: str,
    disclosure_moves: set[str],
    disclosure_source: str,
    used_material_ids: list[str],
    disclosure_profile: dict[str, Any] | None,
) -> str | None:
    valid_sources = {"none", "user_material", "simulated_soft", "user_confirmed"}
    if disclosure_source not in valid_sources:
        return "invalid_disclosure_source"
    if draft_move not in disclosure_moves:
        return None
    if disclosure_profile is None:
        return "user_disclosure_profile_required"

    simulation_policy = str(disclosure_profile.get("simulation_policy") or "free_simulation_soft")
    material_ids = {
        str(item.get("material_id"))
        for item in disclosure_profile.get("shareable_material", [])
        if (
            isinstance(item, dict)
            and str(item.get("material_id") or "").strip()
            and isinstance(item.get("text"), str)
            and item["text"].strip()
            and str(item.get("sensitivity") or "low") in {"low", "medium"}
        )
    }

    if disclosure_source == "simulated_soft":
        if simulation_policy != "free_simulation_soft":
            return "simulated_disclosure_not_allowed"
        return None
    if disclosure_source == "user_material":
        if not used_material_ids:
            return "user_material_disclosure_requires_material_ids"
        if not set(used_material_ids).issubset(material_ids):
            return "user_material_disclosure_unknown_material_id"
        return None
    if disclosure_source == "user_confirmed":
        return "user_confirmed_disclosure_requires_handoff"
    return "disclosure_source_required"


def _draft_question_count(raw_draft: dict[str, Any], best_reply: str) -> int:
    explicit = raw_draft.get("question_count")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 0:
        return explicit
    reply_shape = str(raw_draft.get("reply_shape") or "")
    if reply_shape in {"question", "contains_question"}:
        return 1
    return 1 if _looks_like_direct_question(best_reply) else 0


def _looks_like_direct_question(text: str) -> bool:
    stripped = text.strip()
    if "?" in stripped or "？" in stripped:
        return True
    question_phrases = ("是不是", "有没有", "会不会", "要不要", "能不能", "为什么", "怎么")
    if any(marker in stripped for marker in question_phrases):
        return True
    return bool(re.search(r"(吗|嘛|么|呢)[。！!…]*$", stripped))


def _can_request_send(
    authorization: dict[str, Any],
    ingest: dict[str, Any],
    assessment: dict[str, Any],
    state: dict[str, Any],
    draft_payload: Any,
    *,
    match_id: str,
    app_id: str,
    now: str,
) -> bool:
    if not draft_payload:
        return False
    if state.get("state") == "appointment_handoff":
        return False
    if _send_authorization_block_reason(authorization, match_id=match_id, app_id=app_id, now=now):
        return False
    if not authorization.get("autonomous_send"):
        return False
    if "send_message" not in authorization.get("allowed_actions", []):
        return False
    if ingest.get("confidence") == "low" or ingest.get("requires_user_confirmation"):
        return False
    return (
        assessment.get("recommended_next") == "reply"
        and assessment.get("continuation_opportunity") == "yes"
        and assessment.get("reply_window_status") == "open"
        and assessment.get("confidence") in {"high", "medium"}
    )


def _can_request_nudge(
    authorization: dict[str, Any],
    ingest: dict[str, Any],
    assessment: dict[str, Any],
    state: dict[str, Any],
    draft_payload: Any,
    now: str,
    *,
    match_id: str,
    app_id: str,
) -> bool:
    if not draft_payload:
        return False
    if state.get("state") == "appointment_handoff":
        return False
    if _send_authorization_block_reason(authorization, match_id=match_id, app_id=app_id, now=now):
        return False
    if not authorization.get("autonomous_send") or not authorization.get("autonomous_nudge", True):
        return False
    if "send_message" not in authorization.get("allowed_actions", []):
        return False
    if ingest.get("confidence") == "low" or ingest.get("requires_user_confirmation"):
        return False
    if assessment.get("recommended_next") != "nudge_later":
        return False
    if assessment.get("continuation_opportunity") != "yes":
        return False
    if assessment.get("reply_window_status") != "open":
        return False
    if assessment.get("confidence") not in {"high", "medium"}:
        return False
    latest_fingerprint = assessment.get("latest_inbound_fingerprint")
    if state.get("last_nudged_inbound_fingerprint") == latest_fingerprint:
        return False
    due_at = state.get("next_due_at")
    if not isinstance(due_at, str):
        return False
    try:
        return _parse_iso_utc(due_at) <= _parse_iso_utc(now)
    except ValueError:
        return False


def _authorization_revoked_or_expired(authorization: dict[str, Any], now: str) -> bool:
    if not authorization:
        return True
    if authorization.get("revoked_at"):
        return True
    expires_at = authorization.get("expires_at")
    if isinstance(expires_at, str):
        try:
            return _parse_iso_utc(expires_at) <= _parse_iso_utc(now)
        except ValueError:
            return True
    return False


def _send_authorization_block_reason(
    authorization: dict[str, Any],
    *,
    match_id: str,
    app_id: str,
    now: str,
) -> str | None:
    if not authorization:
        return "authorization_missing"
    if authorization.get("scope") != "send_chat_messages":
        return "authorization_scope_not_send_chat_messages"
    if str(authorization.get("app_id") or "") != app_id:
        return "authorization_app_mismatch"
    if not authorization.get("autonomous_send"):
        return "authorization_autonomous_send_disabled"
    if "send_message" not in authorization.get("allowed_actions", []):
        return "authorization_action_not_allowed"
    if authorization.get("requires_post_action_verification") is not True:
        return "authorization_requires_post_action_verification"
    allowed_match_ids = authorization.get("allowed_match_ids")
    if isinstance(allowed_match_ids, list) and allowed_match_ids:
        allowed = {str(item) for item in allowed_match_ids}
        if match_id not in allowed:
            return "authorization_match_not_allowed"
    if _quiet_hours_active(authorization.get("quiet_hours"), now):
        return "authorization_quiet_hours"
    return None


def _quiet_hours_active(value: Any, now: str) -> bool:
    if not isinstance(value, list) or not value:
        return False
    try:
        current = _clock_minutes(_parse_iso_local_clock(now))
    except ValueError:
        return True
    for item in value:
        window = _quiet_window_minutes(item)
        if window is None:
            continue
        start, end = window
        if _minutes_in_window(current, start, end):
            return True
    return False


def _quiet_window_minutes(item: Any) -> tuple[int, int] | None:
    if isinstance(item, dict):
        start = item.get("start") or item.get("start_time")
        end = item.get("end") or item.get("end_time")
        start_minutes = _parse_clock_minutes(start)
        end_minutes = _parse_clock_minutes(end)
        if start_minutes is None or end_minutes is None:
            return None
        return start_minutes, end_minutes
    if isinstance(item, str) and "-" in item:
        start, end = item.split("-", 1)
        start_minutes = _parse_clock_minutes(start.strip())
        end_minutes = _parse_clock_minutes(end.strip())
        if start_minutes is None or end_minutes is None:
            return None
        return start_minutes, end_minutes
    return None


def _parse_clock_minutes(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour * 60 + minute


def _clock_minutes(value: datetime) -> int:
    return value.hour * 60 + value.minute


def _minutes_in_window(current: int, start: int, end: int) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


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


def _prioritize_entries(
    entries: list[dict[str, Any]],
    *,
    states_by_candidate: dict[str | None, dict[str, Any]],
    thread_items: dict[str | None, dict[str, Any]],
) -> list[dict[str, Any]]:
    indexed_entries = list(enumerate(entries))
    return [
        entry
        for _, entry in sorted(
            indexed_entries,
            key=lambda item: (
                _entry_priority(
                    item[1],
                    states_by_candidate.get(item[1].get("candidate_key")),
                    thread_items.get(item[1].get("candidate_key")),
                ),
                item[0],
            ),
        )
    ]


def _entry_priority(
    entry: dict[str, Any],
    state: dict[str, Any] | None,
    thread_item: dict[str, Any] | None,
) -> int:
    if state is None:
        return 0
    assessment = dict(thread_item.get("assessment", {})) if thread_item else {}
    latest_fingerprint = assessment.get("latest_inbound_fingerprint")
    if latest_fingerprint and latest_fingerprint != state.get("latest_inbound_fingerprint"):
        return 1
    latest_preview_hash = entry.get("latest_preview_hash")
    if entry.get("unread_cue") == "present" and latest_preview_hash != state.get("last_preview_hash"):
        return 1
    if state.get("state") == "appointment_handoff" or _is_handoff_assessment(assessment):
        return 2
    if state.get("state") == "nudge_scheduled" or assessment.get("recommended_next") == "nudge_later":
        return 3
    return 4


def _is_handoff_assessment(assessment: dict[str, Any]) -> bool:
    return (
        assessment.get("appointment_stage") in {"details_requested", "scheduled"}
        or assessment.get("recommended_next") == "handoff"
        or "appointment_details" in assessment.get("risk_flags", [])
    )


def _handoff_reason(assessment: dict[str, Any]) -> str:
    risk_flags = [str(flag) for flag in assessment.get("risk_flags", [])]
    if "contact_exchange" in risk_flags:
        return "contact_exchange"
    if "appointment_details" in risk_flags:
        return "appointment_details_requested"
    if assessment.get("appointment_stage") in {"details_requested", "scheduled"}:
        return "appointment_details_requested"
    if risk_flags:
        return f"risk_flag_{_safe_id(risk_flags[0])}"
    if assessment.get("recommended_next") == "handoff":
        return "host_requested_handoff"
    return "unknown_handoff"


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


def _build_summary(
    states: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    user_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "match_count": len(states),
        "new_match_count": sum(1 for state in states if state.get("candidate_type") == "new_match_candidate"),
        "action_request_count": sum(1 for state in states if state.get("state") == "send_requested"),
        "waiting_count": sum(1 for state in states if state.get("state") in {"sent_waiting", "waiting_for_match"}),
        "nudge_count": sum(1 for state in states if state.get("state") == "nudge_scheduled"),
        "handoff_count": sum(1 for state in states if state.get("state") == "appointment_handoff"),
        "slot_count": len(ledger),
        "slot_conflict_count": sum(1 for slot in ledger if slot.get("conflict")),
        "user_profile_ready": bool(user_readiness and user_readiness.get("ready")),
        "disclosure_usage_count": sum(1 for state in states if state.get("last_disclosure_source")),
        "low_investment_repair_count": sum(1 for state in states if state.get("low_investment_repair_applied")),
        "paused_due_to_low_reciprocity": sum(
            1
            for state in states
            if state.get("state") in {"paused", "waiting_for_match"}
            and state.get("pause_reason") == "low_reciprocity"
        ),
    }


def _next_priority_queue(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {
        "appointment_handoff": 0,
        "needs_reply": 1,
        "needs_thread_scan": 2,
        "nudge_scheduled": 3,
        "sent_waiting": 4,
    }
    items = [
        {
            "match_id": state["match_id"],
            "candidate_key": state.get("candidate_key"),
            "state": state.get("state"),
            "priority": priority.get(str(state.get("state")), 9),
        }
        for state in states
        if state.get("state") not in {"closed", "paused"}
    ]
    return sorted(items, key=lambda item: (item["priority"], str(item["match_id"])))


def _human_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    states = list(report.get("states", []))
    plans = list(report.get("conversation_plans", []))
    plans_by_match = {plan.get("match_id"): dict(plan) for plan in plans if isinstance(plan, dict)}
    ledger = list(report.get("appointment_ledger", []))
    queue = list(report.get("next_priority_queue", []))

    lines = [
        "# Dating Booster Session Report",
        "",
        "## Summary",
        "",
        f"- Session: {report['session_id']}",
        f"- Matches tracked: {summary['match_count']}",
        f"- New matches: {summary['new_match_count']}",
        f"- Send requests pending: {summary['action_request_count']}",
        f"- Waiting: {summary['waiting_count']}",
        f"- Nudge scheduled: {summary['nudge_count']}",
        f"- Handoffs: {summary['handoff_count']}",
        f"- Slot conflicts: {summary['slot_conflict_count']}",
        f"- User profile ready: {summary.get('user_profile_ready')}",
        f"- Disclosure usage: {summary.get('disclosure_usage_count')}",
        f"- Low-investment repairs: {summary.get('low_investment_repair_count')}",
        f"- Paused for low reciprocity: {summary.get('paused_due_to_low_reciprocity')}",
        "",
        "## Match States",
        "",
    ]
    if states:
        for state in states:
            plan = plans_by_match.get(state.get("match_id"), {})
            scores = dict(plan.get("scores", {}))
            lines.append(
                "- "
                + " | ".join(
                    [
                        f"match={state.get('match_id')}",
                        f"candidate={state.get('candidate_key')}",
                        f"state={state.get('state')}",
                        f"stage={state.get('conversation_stage') or plan.get('stage') or 'unknown'}",
                        f"topic={plan.get('current_topic') or 'unknown'}",
                        f"topic_state={plan.get('topic_state') or state.get('topic_exit_pressure') or 'unknown'}",
                        f"engagement={scores.get('engagement')}",
                        f"momentum={scores.get('momentum')}",
                        f"handoff={state.get('handoff_reason') or 'none'}",
                        f"next_due_at={state.get('next_due_at') or 'none'}",
                        f"question_debt={state.get('question_debt', 0)}",
                        f"self_disclosure_debt={state.get('self_disclosure_debt', 0)}",
                        f"low_investment={state.get('low_investment_streak', 0)}",
                        f"next_milestone={state.get('next_milestone') or plan.get('next_milestone') or 'none'}",
                        f"next_host_action={_state_next_host_action(state)}",
                        f"failure_hypothesis={_failure_hypothesis(state, plan)}",
                    ]
                )
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Conversation Plans", ""])
    if plans:
        for plan in plans:
            scores = dict(plan.get("scores", {}))
            lines.append(
                "- "
                + " | ".join(
                    [
                        f"match={plan.get('match_id')}",
                        f"stage={plan.get('stage')}",
                        f"move={plan.get('recommended_move')}",
                        f"topic={plan.get('current_topic')}",
                        f"milestone={plan.get('next_milestone')}",
                        f"engagement={scores.get('engagement')}",
                        f"warmth={scores.get('warmth')}",
                        f"logistics={scores.get('logistics_readiness')}",
                    ]
                )
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Handoffs", ""])
    handoff_states = [state for state in states if state.get("state") == "appointment_handoff"]
    if handoff_states:
        for state in handoff_states:
            lines.append(
                f"- match={state.get('match_id')} candidate={state.get('candidate_key')} "
                f"reason={state.get('handoff_reason') or 'unknown'}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Appointment Ledger", ""])
    if ledger:
        for slot in ledger:
            lines.append(
                f"- slot={slot.get('slot_id')} match={slot.get('match_id')} "
                f"status={slot.get('status')} conflict={bool(slot.get('conflict'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Next Priority Queue", ""])
    if queue:
        for item in queue:
            lines.append(
                f"- priority={item.get('priority')} match={item.get('match_id')} "
                f"candidate={item.get('candidate_key')} state={item.get('state')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _state_next_host_action(state: dict[str, Any]) -> str:
    state_name = str(state.get("state") or "")
    if state_name == "needs_thread_scan":
        return "open_thread"
    if state_name in {"needs_reply", "draft_ready"}:
        return "author_or_review_draft"
    if state_name == "send_requested":
        return "verify_or_record_pending_send"
    if state_name == "appointment_handoff":
        return "user_takeover"
    if state_name == "nudge_scheduled":
        return "wait_until_due"
    if state_name in {"sent_waiting", "waiting_for_match"}:
        return "wait_for_match"
    return "none"


def _failure_hypothesis(state: dict[str, Any], plan: dict[str, Any]) -> str:
    if state.get("handoff_reason"):
        return f"handoff:{state.get('handoff_reason')}"
    if state.get("pause_reason") == "low_reciprocity":
        return "low_reciprocity_or_over_questioning"
    if int(state.get("low_investment_streak") or 0) >= 2:
        return "match_low_investment"
    scores = dict(plan.get("scores", {}))
    if int(scores.get("topic_saturation") or 0) >= 70:
        return "topic_saturated"
    if state.get("last_action_result_error"):
        return f"action_result:{state.get('last_action_result_error')}"
    return "none"


def _provisional_match_id(entry: dict[str, Any]) -> str:
    key = entry.get("candidate_key") or entry.get("visible_name") or "unknown"
    return f"provisional_{_safe_id(str(key))}"


def _safe_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_") or "unknown"


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _draft_payload_hash(payload: dict[str, Any]) -> str:
    return _text_hash(str(payload.get("best_reply", "")))


def _draft_aligns_with_planner(draft_payload: dict[str, Any], planner_recommendation: dict[str, Any]) -> bool:
    recommended_move = str(planner_recommendation.get("recommended_move") or "")
    draft_move = str(draft_payload.get("conversation_move") or "")
    return bool(recommended_move and draft_move == recommended_move)


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
