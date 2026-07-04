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

from dating_boost.core.automation_state import *


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


def _host_supplied_generation_binding(
    root: Path,
    *,
    evidence_id: str,
    context_pack: dict[str, Any],
    draft_payload: dict[str, Any],
    created_at: str,
    allow_stage_only_soft_accept: bool = False,
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
    accepted = probability <= 40 or bool(allow_stage_only_soft_accept)
    self_review_summary = {
        "schema_version": 1,
        "ai_or_weird_probability": probability,
        "status": "ok" if probability <= 40 else ("stage_only_soft_accepted" if accepted else "needs_revision"),
        "source": source,
        "reason": reason,
    }
    DraftGenerationAuditRepository(root).append_generation(
        generation_id=generation_id,
        evidence_id=evidence_id,
        prompt_id=prompt_id,
        status="ok" if accepted else "blocked",
        primary_reason=(
            None
            if probability <= 40
            else ("stage_only_draft_self_review_soft_accepted" if accepted else "draft_self_review_probability_high")
        ),
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


def _host_supplied_generation_contract_block_reason(
    draft_payload: dict[str, Any],
    *,
    allow_stage_only_soft_accept: bool = False,
) -> str | None:
    if not str(draft_payload.get("draft_generation_id") or "").strip():
        return "draft_generation_required"
    raw_summary = draft_payload.get("draft_self_review_summary")
    if not isinstance(raw_summary, dict):
        return "draft_self_review_required"
    probability = raw_summary.get("ai_or_weird_probability")
    if not isinstance(probability, int) or isinstance(probability, bool) or probability < 0 or probability > 100:
        return "draft_self_review_invalid"
    if probability > 40 and not allow_stage_only_soft_accept:
        return "draft_self_review_probability_high"
    return None


STAGE_ONLY_SELF_REVIEW_SOFT_ACCEPT_THRESHOLD = 65


def _stage_only_generation_soft_accept_allowed(
    draft_payload: dict[str, Any],
    *,
    authorization: dict[str, Any],
    standalone_draft_review: Any,
) -> bool:
    if authorization.get("live_send") is True:
        return False
    if not isinstance(standalone_draft_review, dict):
        return False
    if standalone_draft_review.get("allowed_for_stage") is not True:
        return False
    raw_summary = draft_payload.get("draft_self_review_summary")
    if not isinstance(raw_summary, dict):
        return False
    probability = raw_summary.get("ai_or_weird_probability")
    if not isinstance(probability, int) or isinstance(probability, bool):
        return False
    return 40 < probability <= STAGE_ONLY_SELF_REVIEW_SOFT_ACCEPT_THRESHOLD


def _stage_only_review_soft_accept_allowed(
    *,
    authorization: dict[str, Any],
    review: Any,
    standalone_draft_review: Any,
) -> bool:
    if authorization.get("live_send") is True:
        return False
    if not isinstance(standalone_draft_review, dict):
        return False
    if standalone_draft_review.get("allowed_for_stage") is not True:
        return False
    return getattr(review, "allowed_for_stage", False) is True


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


__all__ = [name for name in globals() if not name.startswith("__")]
