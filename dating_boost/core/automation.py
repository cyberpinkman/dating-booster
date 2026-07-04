from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.automation_prioritization import (
    HISTORICAL_THREAD_CUTOFF_DAYS,
    _next_priority_queue,
    _prioritize_entries,
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

from dating_boost.core.automation_step import run_automation_step
from dating_boost.core.automation_send_gate import (
    _queue_send_request_for_repository,
    _release_active_send_request_after_failure,
)
from dating_boost.core.automation_state import (
    _action_result_mismatch,
    _digest,
    _goal_type_from_payload,
    _non_empty,
    _now_iso,
    _stage_result_mismatch,
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
        return run_automation_step(self, scan_batch)

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
