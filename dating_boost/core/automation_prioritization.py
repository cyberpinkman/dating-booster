from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any


HISTORICAL_THREAD_CUTOFF_DAYS = 7


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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
        candidate_type = str(entry.get("candidate_type") or "").strip().lower()
        if candidate_type == "continuation_candidate":
            return 4
        if _entry_is_open_chat_candidate(entry):
            return 5
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
            "priority": _state_priority_for_queue(state, priority),
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


def _state_priority_for_queue(state: dict[str, Any], priority: dict[str, int]) -> int:
    if (
        state.get("state") in {"draft_ready", "needs_thread_scan"}
        and state.get("candidate_type") == "continuation_candidate"
        and _entry_has_reply_cue(state)
    ):
        return 2
    if (
        state.get("state") == "scan_later"
        and state.get("candidate_type") == "continuation_candidate"
        and state.get("latest_inbound_fingerprint")
    ):
        return 2
    if state.get("state") == "needs_thread_scan" and state.get("candidate_type") == "open_chat_candidate":
        return 5
    return priority.get(str(state.get("state")), 9)


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
    combined = f"{normalized_key} {normalized_name} {normalized_preview}"
    if normalized_key.startswith("tashuo_visual_") and not normalized_name:
        return True
    if any(token in normalized_key for token in ("liked_you_gate", "premium_gate", "paywall_gate")):
        return True
    if normalized_name.startswith("tab header"):
        return True
    if "消息" in visible_name and "动态" in visible_name and len(visible_name.strip()) <= 24:
        return True
    if "开启通知" in combined or "接收通知" in combined:
        return True
    if any(
        token in combined
        for token in (
            "pending_question",
            "pending question",
            "question_gate",
            "question gate",
            "question row avatar",
            "anonymous_question",
            "anonymous question",
            "tab header",
            "message tab header",
            "notification banner",
            "search icon",
            "filter icon",
            "list icon",
        )
    ):
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
    if any(token in normalized_name or token in normalized_preview for token in ("匿名提问", "提问卡片", "问题卡片")):
        return True
    return False


def _now_iso() -> str:
    override = os.environ.get("DATING_BOOST_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
