from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.automation_prioritization import (
    HISTORICAL_THREAD_CUTOFF_DAYS,
    _candidate_type_for_entry,
    _entry_has_reply_cue,
    _entry_history_reason,
    _is_handoff_assessment,
    _is_non_chat_message_list_entry,
    _is_non_chat_message_list_state,
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
from dating_boost.core.draft_evidence import build_draft_evidence
from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
from dating_boost.core.goals import DEFAULT_GOAL_TYPE, get_goal_type_definition
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.proposals import extract_proposals
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.memory.retrieval import build_memory_context
from dating_boost.core.memory.review_queue import ReviewQueueRepository
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


__all__ = [name for name in globals() if not name.startswith("__")]
