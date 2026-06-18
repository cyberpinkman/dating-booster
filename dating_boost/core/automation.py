from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.draft_evidence import build_draft_evidence
from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
from dating_boost.core.goals import DEFAULT_GOAL_TYPE, get_goal_type_definition
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.proposals import extract_proposals
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.memory.retrieval import build_memory_context
from dating_boost.core.memory.review_queue import ReviewQueueRepository, review_item_display
from dating_boost.core.models import Divergence, ReplyMode
from dating_boost.core.planner import PlannerRepository, planner_context_items
from dating_boost.core.production_store import payload_digest
from dating_boost.core.relationship_report import (
    RELATIONSHIP_PROGRESS_NEXT_ACTION,
    build_relationship_progress_report,
)
from dating_boost.core.repositories import JsonMemoryRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.core.user_disclosure import UserDisclosureRepository
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import (
    draft_messages_payload_hash,
    draft_payload_messages,
    draft_strategy_evidence,
    review_draft,
)


ACTIVE_SLOT_STATUSES = {"soft_mentioned", "handoff_pending", "user_confirmed"}

WORK_TOPIC_KEYWORDS = (
    "工作",
    "上班",
    "公司",
    "职业",
    "事业",
    "职场",
    "同事",
    "老板",
    "客户",
    "项目",
    "业务",
    "运营",
    "产品",
    "销售",
    "kpi",
    "绩效",
    "加班",
    "救火",
    "救火队长",
    "提前把坑",
    "坑都填",
    "开会",
    "汇报",
)

WORK_HIGH_SALIENCE_MARKERS = (
    "热爱工作",
    "喜欢工作",
    "很喜欢工作",
    "事业心",
    "搞事业",
    "创业",
    "工作狂",
    "职业规划",
    "职场",
    "管理者",
    "带团队",
)

LIFESTYLE_HOOK_KEYWORDS = (
    "露营",
    "咖啡",
    "电影",
    "音乐",
    "唱歌",
    "旅行",
    "看展",
    "健身",
    "瑜伽",
    "美食",
    "日料",
    "宠物",
    "猫",
    "狗",
    "桌游",
    "狼人杀",
    "户外",
    "滑雪",
    "爬山",
    "摄影",
    "阅读",
    "酒吧",
    "live",
    "concert",
)

SLOW_WARM_CONTEXT_MARKERS = ("慢热", "慢慢熟", "慢慢来", "熟了")
SLOW_WARM_RESTATEMENTS = (
    "聊天慢慢熟",
    "慢慢熟",
    "刚开始话少",
    "熟了",
    "熟了会",
    "慢热",
)
TRANSIENT_TOPIC_KEYWORDS = (
    "天气",
    "下雨",
    "雨",
    "太阳",
    "雪",
    "降温",
    "升温",
    "今天",
    "今晚",
    "刚才",
    "现在",
    "weather",
    "rain",
    "sun",
    "sunny",
    "today",
    "tonight",
    "now",
)
WEAK_STRATEGIC_DELTA_MARKERS = (
    "keep",
    "light exchange",
    "natural exchange",
    "继续聊",
    "轻松",
    "自然",
    "接梗",
    "气氛",
)
LOW_VALUE_CONFIRMATION_MARKERS = (
    "是不是",
    "是不是也",
    "是不是还",
    "是不是就",
    "是不是直接",
    "有没有",
    "有没有也",
    "会不会",
    "会不会也",
    "你是不是也",
    "你那天是不是",
)
UNKNOWN_FOLLOWUP_MARKERS = (
    "一般",
    "平时",
    "通常",
    "习惯",
    "会先",
    "后来",
    "最后",
    "怎么",
    "什么",
    "干嘛",
    "玩什么",
    "做什么",
    "哪",
    "安排",
    "处理",
    "改成",
    "变成",
)
ANSWERABLE_HANDLE_MARKERS = (
    "?",
    "？",
    "吗",
    "嘛",
    "么",
    "呢",
    "是不是",
    "会不会",
    "哪",
    "什么",
    "怎么",
    "谁",
    "几",
    "多少",
    "我",
    "咱",
    "我们",
    "下次",
    "改天",
    "周末",
    "见",
    "线下",
    "咖啡",
    "吃",
    "喝",
    "一起",
)
HISTORICAL_THREAD_CUTOFF_DAYS = 7


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
    ) -> None:
        raw_draft = dict(draft_payload)
        draft = _draft_from_dict(raw_draft)
        disclosure_repo = UserDisclosureRepository(self.root)
        disclosure_source = str(
            raw_draft.get("disclosure_source") or ("simulated_soft" if draft.conversation_move in {
                "light_self_disclosure",
                "reciprocal_disclosure",
                "low_investment_repair",
            } else "none")
        )
        used_material_ids = [
            str(item)
            for item in raw_draft.get("used_user_material_ids", [])
            if str(item).strip()
        ] if isinstance(raw_draft.get("used_user_material_ids"), list) else []

        evidence = build_draft_evidence(
            self.root,
            match_id,
            reply_mode=ReplyMode.ADAPTIVE,
            observation=observation,
            draft_kind=str(raw_draft.get("draft_kind") or "reply"),
            now=self._now(),
            app_id=observation.app_id,
            runtime=observation.provenance.get("runtime") or observation.provenance.get("harness_runtime") or "default",
            require_user_profile_source=True,
        )
        if evidence.status != "ok":
            _mark_draft_revision_required(state, reason=evidence.primary_reason or "draft_evidence_blocked")
            warnings.append(evidence.primary_reason or "draft_evidence_blocked")
            warnings.append("draft_evidence_required")
            _append_draft_revision_request(
                scan_requests,
                candidate_key=candidate_key,
                match_id=match_id,
                visible_name=observation.match_identity_hints.visible_name,
                reason=evidence.primary_reason or "draft_evidence_blocked",
            )
            return

        generation_contract_reason = _host_supplied_generation_contract_block_reason(raw_draft)
        if generation_contract_reason is not None:
            _mark_draft_revision_required(state, reason=generation_contract_reason)
            warnings.append(generation_contract_reason)
            warnings.append("draft_generation_required")
            _append_draft_revision_request(
                scan_requests,
                candidate_key=candidate_key,
                match_id=match_id,
                visible_name=observation.match_identity_hints.visible_name,
                reason=generation_contract_reason,
            )
            return

        generation_binding = _host_supplied_generation_binding(
            self.root,
            evidence_id=evidence.evidence_id,
            context_pack=evidence.context_pack,
            draft_payload=raw_draft,
            created_at=self._now(),
        )
        self_review_probability = int(generation_binding["draft_self_review_summary"]["ai_or_weird_probability"])
        if self_review_probability > 40:
            _mark_draft_revision_required(state, reason="draft_self_review_probability_high")
            warnings.append("draft_self_review_probability_high")
            warnings.append("draft_revision_required")
            _append_draft_revision_request(
                scan_requests,
                candidate_key=candidate_key,
                match_id=match_id,
                visible_name=observation.match_identity_hints.visible_name,
                reason="draft_self_review_probability_high",
            )
            return

        context_pack = evidence.context_pack
        review = review_draft(
            raw_draft,
            context_pack,
            mode="managed_live",
            observation=observation,
            planner_recommendation=planner_recommendation,
            disclosure_profile=disclosure_repo.load_profile_or_none(),
        )
        DraftReviewAuditRepository(self.root).append_review(
            review,
            draft_payload=raw_draft,
            context_pack=context_pack,
            mode="managed_live",
            target_match_id=match_id,
        )
        if not review.allowed_for_managed_send:
            _mark_draft_revision_required(state, reason=review.primary_reason)
            finding_codes = [finding.code for finding in review.findings]
            warnings.extend(code for code in finding_codes if code not in warnings)
            if any(finding.category == "content" for finding in review.findings):
                warnings.append("draft_blocked")
            warnings.append("draft_revision_required")
            _append_draft_revision_request(
                scan_requests,
                candidate_key=candidate_key,
                match_id=match_id,
                visible_name=observation.match_identity_hints.visible_name,
                reason=review.primary_reason,
            )
            return

        payload_messages = draft_payload_messages(raw_draft, draft.best_reply)
        payload_hash = draft_messages_payload_hash(payload_messages)
        retry_suffix = _send_retry_suffix(state, payload_hash)
        if state.get("last_outbound_payload_hash") == payload_hash:
            if _state_has_active_send_request(state):
                warnings.append("duplicate_send_request_suppressed")
                return
            retry_suffix = retry_suffix or _stale_same_payload_retry_suffix(state)
        if retry_suffix:
            state["send_retry_count"] = max(int(state.get("send_retry_count") or 0), _retry_suffix_number(retry_suffix))

        action_request_id = f"action_request_{match_id}_{payload_hash[:12]}{retry_suffix}"
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
        payload_text = "\n".join(message["text"] for message in payload_messages)
        action_request = {
            "schema_version": 1,
            "action_request_id": action_request_id,
            "match_id": match_id,
            "candidate_key": candidate_key,
            "action": "send_message",
            "payload_text": payload_text,
            "payload_hash": payload_hash,
            "payload_format": "message_sequence" if len(payload_messages) > 1 else "single_message",
            "payload_messages": payload_messages,
            "message_count": len(payload_messages),
            "precondition_hash": precondition_hash,
            "autonomous_audit_binding": autonomous_audit_binding,
            "pre_action_observation_id": observation.observation_id,
            "target_profile_observation": observation.profile_observation.to_dict(),
            "requires_post_action_verification": True,
            "policy": {
                "allowed": review.allowed_for_managed_send,
                "severity": "low" if review.allowed_for_managed_send else "high",
                "reason": review.primary_reason,
                "requires_user_confirmation": review.requires_user_confirmation,
                "draft_review_id": review.review_id,
            },
            "draft_evidence_id": evidence.evidence_id,
            "draft_generation_id": generation_binding["draft_generation_id"],
            "latest_turn_id": evidence.latest_turn_id,
            "conversation_thread_revision": evidence.conversation_thread_revision,
            "draft_self_review_summary": generation_binding["draft_self_review_summary"],
            "draft_review_id": review.review_id,
            "draft_review_summary": review.summary,
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
            "draft_strategy_evidence": draft_strategy_evidence(
                raw_draft,
                planner_recommendation,
                observation,
            ),
        }
        if isinstance(target_binding, dict):
            action_request["target_binding"] = dict(target_binding)
        action_requests.append(action_request)
        state.pop("draft_revision_required", None)
        state.pop("draft_revision_reason", None)
        state.pop("draft_strategy_block_reason", None)
        state["state"] = "send_requested"
        state["last_action"] = "send_message"
        state["last_action_request_id"] = action_request_id
        state["last_outbound_payload_hash"] = payload_hash
        state["last_precondition_hash"] = precondition_hash
        state["last_autonomous_audit_binding"] = autonomous_audit_binding
        state["last_pre_action_observation_id"] = observation.observation_id
        state["last_draft_id"] = f"draft_{payload_hash[:12]}"
        state.pop("last_action_result_error", None)
        state["last_disclosure_source"] = disclosure_source if disclosure_source != "none" else None
        state["used_user_material_ids"] = used_material_ids
        state["low_investment_repair_applied"] = low_investment_repair_applied
        if is_nudge:
            state["last_nudged_inbound_fingerprint"] = latest_fingerprint
            state["nudge_count_since_inbound"] = int(state.get("nudge_count_since_inbound") or 0) + 1
            state["next_due_at"] = None


def _mark_draft_revision_required(state: dict[str, Any], *, reason: str) -> None:
    state["state"] = "needs_reply"
    state["draft_revision_required"] = True
    state["draft_revision_reason"] = str(reason)
    state.pop("handoff_reason", None)


def _append_draft_revision_request(
    scan_requests: list[dict[str, Any]],
    *,
    candidate_key: str,
    match_id: str,
    visible_name: str | None,
    reason: str,
) -> None:
    if any(
        item.get("candidate_key") == candidate_key
        and item.get("reason") == "draft_revision_required"
        for item in scan_requests
    ):
        return
    scan_requests.append(
        {
            "candidate_key": candidate_key,
            "match_id": match_id,
            "visible_name": visible_name,
            "reason": "draft_revision_required",
            "draft_revision_reason": str(reason),
            "requires_revised_draft": True,
        }
    )


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


def _target_profile_ready_for_send(observation: AppObservation) -> bool:
    profile = observation.profile_observation
    if profile.review_status != "observed":
        return False
    return bool(
        profile.profile_text.strip()
        or any(str(item).strip() for item in profile.photo_cues)
        or any(str(item).strip() for item in profile.hook_candidates)
    )


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


def _host_supplied_generation_binding(
    root: Path,
    *,
    evidence_id: str,
    context_pack: dict[str, Any],
    draft_payload: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    raw_summary = draft_payload.get("draft_self_review_summary")
    if not isinstance(raw_summary, dict):
        raise ValueError("draft_self_review_summary is required")
    probability = int(raw_summary["ai_or_weird_probability"])
    source = str(raw_summary.get("source") or "host_supplied")
    reason = str(raw_summary.get("reason") or "")
    prompt_id = str(draft_payload.get("draft_prompt_id") or "host_supplied_draft_prompt")
    draft_hash = payload_digest(draft_payload)
    context_hash = payload_digest(context_pack)
    generation_id = str(
        draft_payload["draft_generation_id"]
    )
    self_review_summary = {
        "schema_version": 1,
        "ai_or_weird_probability": probability,
        "status": "ok" if probability <= 40 else "needs_revision",
        "source": source,
        "reason": reason,
    }
    DraftGenerationAuditRepository(root).append_generation(
        generation_id=generation_id,
        evidence_id=evidence_id,
        prompt_id=prompt_id,
        status="ok" if probability <= 40 else "blocked",
        primary_reason=None if probability <= 40 else "draft_self_review_probability_high",
        prompt_hash=str(draft_payload.get("draft_prompt_hash") or "host_supplied"),
        context_hash=context_hash,
        draft_hash=draft_hash,
        attempt_count=1,
        self_review_attempts=[self_review_summary],
        created_at=created_at,
    )
    return {
        "draft_generation_id": generation_id,
        "draft_self_review_summary": self_review_summary,
    }


def _host_supplied_generation_contract_block_reason(draft_payload: dict[str, Any]) -> str | None:
    if not str(draft_payload.get("draft_generation_id") or "").strip():
        return "draft_generation_required"
    raw_summary = draft_payload.get("draft_self_review_summary")
    if not isinstance(raw_summary, dict):
        return "draft_self_review_required"
    probability = raw_summary.get("ai_or_weird_probability")
    if not isinstance(probability, int) or isinstance(probability, bool) or probability < 0 or probability > 100:
        return "draft_self_review_invalid"
    if probability > 40:
        return "draft_self_review_probability_high"
    return None


def _send_retry_suffix(state: dict[str, Any], payload_hash: str) -> str:
    if state.get("last_failed_outbound_payload_hash") != payload_hash:
        return ""
    retry_count = int(state.get("send_retry_count") or 0)
    if retry_count <= 0:
        return ""
    return f"_retry{retry_count}"


def _state_has_active_send_request(state: dict[str, Any]) -> bool:
    return str(state.get("state") or "") in {
        "send_requested",
        "stage_needs_verification",
        "staged_pending_user",
        "sent_waiting",
        "waiting_for_match",
    }


def _stale_same_payload_retry_suffix(state: dict[str, Any]) -> str:
    retry_count = int(state.get("send_retry_count") or 0)
    return f"_retry{retry_count if retry_count > 0 else 1}"


def _retry_suffix_number(suffix: str) -> int:
    if not suffix.startswith("_retry"):
        return 0
    try:
        return int(suffix.removeprefix("_retry"))
    except ValueError:
        return 0


def _release_active_send_request_after_failure(state: dict[str, Any], *, event_id: str) -> None:
    payload_hash = state.get("last_outbound_payload_hash")
    action_request_id = state.get("last_action_request_id")
    if payload_hash:
        state["last_failed_outbound_payload_hash"] = payload_hash
    if action_request_id:
        state["last_failed_action_request_id"] = action_request_id
    state["last_failed_action_result_event_id"] = event_id
    state["send_retry_count"] = int(state.get("send_retry_count") or 0) + 1
    for key in (
        "last_action_request_id",
        "last_outbound_payload_hash",
        "last_precondition_hash",
        "last_autonomous_audit_binding",
        "last_pre_action_observation_id",
    ):
        state.pop(key, None)


def _stage_result_mismatch(event: dict[str, Any], state: dict[str, Any]) -> str | None:
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


def _split_entries_at_history_cutoff(
    entries: list[dict[str, Any]],
    *,
    captured_at: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    active: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    cutoff_reached = False
    for entry in entries:
        if cutoff_reached:
            historical.append(entry)
            continue
        if _is_non_chat_message_list_entry(entry):
            active.append(entry)
            continue
        if _entry_is_historical(entry, captured_at=captured_at):
            cutoff_reached = True
            historical.append(entry)
            continue
        active.append(entry)
    return active, historical, cutoff_reached


def _entry_is_historical(entry: dict[str, Any], *, captured_at: str) -> bool:
    if _entry_has_reply_cue(entry):
        return False
    return _entry_history_age_days(entry, captured_at=captured_at) >= HISTORICAL_THREAD_CUTOFF_DAYS


def _entry_has_reply_cue(entry: dict[str, Any]) -> bool:
    cue = str(entry.get("unread_cue") or "").strip().lower()
    if cue in {
        "present",
        "reply_badge",
        "unread",
        "new_message",
        "new_inbound",
        "needs_reply",
        "go_reply",
        "去回复",
    }:
        return True
    for key in ("evidence", "identity_evidence", "timestamp_cue"):
        if "去回复" in str(entry.get(key) or ""):
            return True
    return False


def _entry_history_reason(entry: dict[str, Any], *, captured_at: str) -> str:
    age = _entry_history_age_days(entry, captured_at=captured_at)
    if age >= HISTORICAL_THREAD_CUTOFF_DAYS:
        return f"last_progress_older_than_{HISTORICAL_THREAD_CUTOFF_DAYS}_days"
    bucket = str(entry.get("freshness_bucket") or entry.get("timeline_status") or "").strip().lower()
    if bucket:
        return f"timeline_status:{bucket}"
    cue = str(entry.get("timestamp_cue") or "").strip()
    return f"historical_cutoff_reached:{cue or 'unknown_time'}"


def _entry_history_age_days(entry: dict[str, Any], *, captured_at: str) -> float:
    for key in (
        "days_since_last_progress",
        "days_since_last_activity",
        "days_since_latest_message",
        "age_days",
    ):
        value = entry.get(key)
        try:
            if value is not None and str(value).strip() != "":
                return float(value)
        except (TypeError, ValueError):
            continue
    bucket = str(entry.get("freshness_bucket") or entry.get("timeline_status") or "").strip().lower()
    if bucket in {
        "historical",
        "history",
        "historical_thread",
        "historical_process",
        "older_than_7_days",
        "older_than_one_week",
        "stale_history",
    }:
        return float(HISTORICAL_THREAD_CUTOFF_DAYS)
    if bucket in {"fresh", "recent", "active", "current", "within_week"}:
        return 0.0
    captured = _parse_optional_iso(captured_at)
    for key in ("last_progress_at", "last_activity_at", "latest_message_at", "matched_at"):
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip() or captured is None:
            continue
        parsed = _parse_optional_iso(value)
        if parsed is None:
            continue
        return max(0.0, (captured - parsed).total_seconds() / 86400.0)
    cue_age = _timestamp_cue_age_days(str(entry.get("timestamp_cue") or ""), captured_at=captured_at)
    if cue_age is not None:
        return cue_age
    return -1.0


def _parse_optional_iso(value: str) -> datetime | None:
    try:
        return _parse_iso_utc(value)
    except (TypeError, ValueError):
        return None


def _timestamp_cue_age_days(cue: str, *, captured_at: str) -> float | None:
    normalized = cue.strip().lower()
    if not normalized:
        return None
    if any(token in normalized for token in ("刚刚", "刚才", "现在", "today", "now", "current_thread")):
        return 0.0
    if any(token in normalized for token in ("今天", "分钟前", "小时前", "小时内", "剩余")):
        return 0.0
    if "昨天" in normalized:
        return 1.0
    if "前天" in normalized:
        return 2.0
    day_match = re.search(r"(\d+(?:\.\d+)?)\s*天前", normalized)
    if day_match:
        return float(day_match.group(1))
    week_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:周|週|星期)\s*前", normalized)
    if week_match:
        return float(week_match.group(1)) * 7.0
    month_match = re.search(r"(\d+(?:\.\d+)?)\s*个?月前", normalized)
    if month_match:
        return float(month_match.group(1)) * 30.0
    year_match = re.search(r"(\d+(?:\.\d+)?)\s*年前", normalized)
    if year_match:
        return float(year_match.group(1)) * 365.0
    if any(token in normalized for token in ("上周", "一周前")):
        return 7.0
    if any(token in normalized for token in ("上个月", "几个月", "很久", "半年前", "去年")):
        return float(HISTORICAL_THREAD_CUTOFF_DAYS)
    captured = _parse_optional_iso(captured_at)
    if captured is None:
        return None
    date_match = re.search(r"(?:(\d{4})[-/年])?\s*(\d{1,2})[-/月](\d{1,2})日?", normalized)
    if date_match:
        year = int(date_match.group(1) or captured.year)
        month = int(date_match.group(2))
        day = int(date_match.group(3))
        try:
            parsed = datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
        if parsed > captured and date_match.group(1) is None:
            try:
                parsed = datetime(year - 1, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None
        return max(0.0, (captured - parsed).total_seconds() / 86400.0)
    return None


def _entry_priority(
    entry: dict[str, Any],
    state: dict[str, Any] | None,
    thread_item: dict[str, Any] | None,
) -> int:
    assessment = dict(thread_item.get("assessment", {})) if thread_item else {}
    latest_fingerprint = assessment.get("latest_inbound_fingerprint")
    unread_present = _entry_has_reply_cue(entry)
    waiting_state = state is not None and state.get("state") in {
        "sent_waiting",
        "waiting_for_match",
        "staged_pending_user",
    }
    if (state is not None and state.get("state") == "appointment_handoff") or _is_handoff_assessment(assessment):
        return 0
    if state is not None and state.get("state") == "nudge_scheduled":
        return 1
    if (
        state is not None
        and unread_present
        and state.get("state") not in {"sent_waiting", "waiting_for_match", "staged_pending_user"}
    ):
        return 2
    if state is not None and unread_present and state.get("candidate_type") == "continuation_candidate":
        return 2
    if state is not None and state.get("state") == "needs_reply":
        return 2
    if latest_fingerprint and state is not None and latest_fingerprint != state.get("latest_inbound_fingerprint"):
        return 2
    latest_preview_hash = entry.get("latest_preview_hash")
    if state is not None and unread_present and latest_preview_hash != state.get("last_preview_hash"):
        return 2
    if waiting_state:
        return 6
    if (
        thread_item is not None
        and assessment.get("recommended_next") in {"reply", "nudge_later"}
        and assessment.get("continuation_opportunity") == "yes"
    ):
        return 2
    if state is not None and state.get("state") == "needs_target_profile":
        return 3
    if state is None:
        return 4
    if state.get("state") == "scan_later":
        return 5
    return 7


def _candidate_type_for_entry(state: dict[str, Any], entry: dict[str, Any]) -> str:
    if state.get("seen_before"):
        return "continuation_candidate"
    if _entry_is_open_chat_candidate(entry):
        return "open_chat_candidate"
    return "new_match_candidate"


def _entry_is_open_chat_candidate(entry: dict[str, Any]) -> bool:
    candidate_type = str(entry.get("candidate_type") or "").strip().lower()
    if candidate_type in {"open_chat_candidate", "new_open_chat_candidate", "ordinary_chat_open_candidate"}:
        return True
    preview = str(entry.get("latest_preview") or "").strip()
    evidence = str(entry.get("evidence") or "").strip()
    return "开启聊天" in preview or "开启聊天" in evidence


def _stable_waiting_state_without_new_inbound(state: dict[str, Any], entry: dict[str, Any]) -> bool:
    if state.get("state") not in {"sent_waiting", "waiting_for_match", "staged_pending_user"}:
        return False
    entry_hash = entry.get("latest_preview_hash")
    state_hash = state.get("last_preview_hash")
    if _entry_has_reply_cue(entry) and not state.get("last_outbound_action_id"):
        return False
    return bool(entry_hash and state_hash and entry_hash == state_hash)


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


def _build_summary(
    states: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    user_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "match_count": len(states),
        "new_match_count": sum(1 for state in states if state.get("candidate_type") == "new_match_candidate"),
        "open_chat_candidate_count": sum(1 for state in states if state.get("candidate_type") == "open_chat_candidate"),
        "action_request_count": sum(1 for state in states if state.get("state") == "send_requested"),
        "staged_pending_user_count": sum(1 for state in states if state.get("state") == "staged_pending_user"),
        "waiting_count": sum(1 for state in states if state.get("state") in {"sent_waiting", "waiting_for_match"}),
        "historical_thread_count": sum(1 for state in states if state.get("state") == "historical_thread"),
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
        "send_requested": 1,
        "nudge_scheduled": 1,
        "needs_reply": 2,
        "needs_target_profile": 3,
        "new_match": 4,
        "needs_thread_scan": 4,
        "scan_later": 5,
        "staged_pending_user": 6,
        "sent_waiting": 6,
        "waiting_for_match": 6,
    }
    items = [
        {
            "match_id": state["match_id"],
            "candidate_key": state.get("candidate_key"),
            "state": state.get("state"),
            "priority": 2
            if state.get("state") in {"draft_ready", "needs_thread_scan"}
            and state.get("candidate_type") == "continuation_candidate"
            and _entry_has_reply_cue(state)
            else 2
            if state.get("state") == "scan_later"
            and state.get("candidate_type") == "continuation_candidate"
            and state.get("latest_inbound_fingerprint")
            else priority.get(str(state.get("state")), 9),
            "next_due_at": state.get("next_due_at"),
            "last_scan_cursor": state.get("last_scan_cursor"),
            "unread_cue": state.get("unread_cue"),
        }
        for state in states
        if state.get("state") not in {"closed", "paused", "historical_thread"}
        and not _is_non_chat_message_list_state(state)
        and not _state_is_stale_autonomous_activation_candidate(state)
    ]
    return sorted(items, key=lambda item: (item["priority"], str(item["match_id"])))


def _state_is_stale_autonomous_activation_candidate(state: dict[str, Any]) -> bool:
    if _entry_has_reply_cue(state):
        return False
    if state.get("state") not in {"draft_ready", "needs_reply", "needs_thread_scan", "scan_later", "new_match"}:
        return False
    updated = state.get("updated_at") or state.get("last_activity_at") or state.get("last_progress_at")
    if not isinstance(updated, str) or not updated.strip():
        return False
    parsed = _parse_optional_iso(updated)
    now = _parse_optional_iso(_now_iso())
    if parsed is None or now is None:
        return False
    return (now - parsed).total_seconds() / 86400.0 >= HISTORICAL_THREAD_CUTOFF_DAYS


def _normalize_scan_cursor(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "current": value.get("current"),
            "next": value.get("next"),
            "exhausted": bool(value.get("exhausted")),
        }
    return {"current": value, "next": None, "exhausted": value is None}


def _report_with_memory_display(report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    memory_review = normalized.get("memory_review")
    if not isinstance(memory_review, dict):
        return normalized
    review = dict(memory_review)
    items: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()
    for item in review.get("items", []):
        if not isinstance(item, dict):
            continue
        review_item_id = str(item.get("review_item_id") or "")
        if review_item_id and review_item_id in seen_review_ids:
            continue
        if review_item_id:
            seen_review_ids.add(review_item_id)
        enriched = dict(item)
        enriched["display"] = review_item_display(enriched)
        items.append(enriched)
    review["items"] = items
    normalized["memory_review"] = review
    return normalized


def _human_report(report: dict[str, Any]) -> str:
    report = _report_with_memory_display(report)
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
        f"- Staged drafts pending user: {summary.get('staged_pending_user_count', 0)}",
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

    memory_review = report.get("memory_review", {})
    pending_items = list(memory_review.get("items", []))
    lines.extend(["", "## Memory Suggestions", ""])
    if pending_items:
        for item in pending_items:
            display = item.get("display") if isinstance(item.get("display"), dict) else {}
            lines.append(
                f"- id={item.get('review_item_id')} | "
                f"{display.get('summary') or '可能要记住一条新的聊天线索。'} "
                f"({display.get('accept_label') or '接受'} / {display.get('reject_label') or '拒绝'})"
            )
        lines.append("")
        lines.append("接受或拒绝时仍使用上面的 id。")
        lines.append("To accept: memory review decide --data-dir DIR --accept <id> --confirm memory-review:<session_id>")
        lines.append("To reject: memory review decide --data-dir DIR --reject <id> --confirm memory-review:<session_id>")
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
    if state_name == "staged_pending_user":
        return "wait_for_user_send_confirmation"
    if state_name == "stage_needs_verification":
        return "verify_staged_text"
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


def _is_non_chat_message_list_entry(entry: dict[str, Any]) -> bool:
    candidate_type = str(entry.get("candidate_type") or "").strip().lower()
    if candidate_type in {
        "liked_you_gate",
        "premium_or_liked_you_gate",
        "premium_gate",
        "paywall_gate",
        "non_chat_gate",
    }:
        return True
    return _looks_like_non_chat_message_list_gate(
        key=str(entry.get("candidate_key") or ""),
        visible_name=str(entry.get("visible_name") or ""),
        latest_preview=str(entry.get("latest_preview") or ""),
    )


def _is_non_chat_message_list_state(state: dict[str, Any]) -> bool:
    candidate_type = str(state.get("candidate_type") or "").strip().lower()
    if candidate_type in {
        "liked_you_gate",
        "premium_or_liked_you_gate",
        "premium_gate",
        "paywall_gate",
        "non_chat_gate",
    }:
        return True
    return _looks_like_non_chat_message_list_gate(
        key=str(state.get("candidate_key") or ""),
        visible_name=str(state.get("visible_name") or ""),
        latest_preview=str(state.get("latest_preview") or state.get("last_preview") or ""),
    )


def _looks_like_non_chat_message_list_gate(*, key: str, visible_name: str, latest_preview: str) -> bool:
    normalized_key = key.strip().lower()
    normalized_name = visible_name.strip().lower()
    normalized_preview = latest_preview.strip().lower()
    if any(token in normalized_key for token in ("liked_you_gate", "premium_gate", "paywall_gate")):
        return True
    if "\u559c\u6b22\u4e86\u4f60" in normalized_name and (
        "\u4eba" in normalized_name or normalized_name[:1].isdigit()
    ):
        return True
    if normalized_name in {
        "\u559c\u6b22\u4f60\u7684\u4eba",
        "\u8c01\u559c\u6b22\u4e86\u6211",
        "\u6709\u4eba\u559c\u6b22\u4f60",
    }:
        return True
    if "\u53bb\u6253\u4e2a\u62db\u547c" in normalized_preview and "\u6d3b\u8dc3" in normalized_preview:
        return True
    return False


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
