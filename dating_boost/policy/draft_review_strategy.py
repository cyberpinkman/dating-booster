"""Strategic-fit rules for draft review."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review_payload import draft_payload_messages, looks_like_direct_question

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

__all__ = [
    "_draft_answers_or_riffs",
    "_draft_lines",
    "_has_next_handle",
    "_has_tag_stacking",
    "_latest_asks_or_reacts",
    "_normalized_strategy_text",
    "draft_strategy_block_reason",
    "draft_strategy_evidence",
]

def draft_strategy_block_reason(
    draft_payload: Mapping[str, Any],
    planner_recommendation: Mapping[str, Any],
    observation: AppObservation,
) -> str | None:
    raw_draft = dict(draft_payload)
    planner = dict(planner_recommendation)
    low_investment_streak = int(planner.get("low_investment_streak") or 0)
    topic_lifecycle = planner.get("topic_lifecycle")
    topic = dict(topic_lifecycle) if isinstance(topic_lifecycle, dict) else {}
    current_topic = str(topic.get("current_topic") or "").strip()
    topic_state = str(topic.get("topic_state") or "").strip()
    texts = [
        message["text"]
        for message in draft_payload_messages(
            raw_draft,
            str(raw_draft.get("best_reply") or ""),
        )
    ]
    combined = "\n".join(texts)

    if _draft_forced_choice_restates_confirmed_info(
        texts,
        current_topic=current_topic,
        topic=topic,
        observation=observation,
    ):
        return "draft_forced_choice_restates_confirmed_info"
    if _draft_stale_temporal_topic_without_bridge(
        raw_draft,
        texts,
        current_topic=current_topic,
        topic=topic,
        observation=observation,
    ):
        return "draft_stale_temporal_topic_without_bridge"
    if _draft_stale_reactivation_continues_old_topic(
        raw_draft,
        texts,
        current_topic=current_topic,
        topic=topic,
    ):
        return "draft_stale_reactivation_continues_old_topic"
    if _draft_work_topic_not_preferred(raw_draft, texts, observation):
        return "draft_work_topic_not_preferred"
    if any(_looks_like_ab_choice_question(line) for line in _draft_lines(texts)):
        return "draft_ai_survey_choice_question"
    if _draft_redundant_confirmation_question(
        raw_draft,
        texts,
        current_topic=current_topic,
        topic=topic,
        observation=observation,
    ):
        return "draft_redundant_confirmation_question"
    if _draft_lacks_answerable_relationship_handle(
        raw_draft,
        texts,
        planner_recommendation=planner,
        current_topic=current_topic,
    ):
        return "draft_no_answerable_relationship_handle"

    if str(planner.get("recommended_move") or "") != "low_investment_repair":
        return None
    if low_investment_streak < 2 and topic_state not in {"saturating", "exhausted"}:
        return None

    hooks = [
        str(item).strip()
        for item in observation.profile_observation.hook_candidates
        if str(item).strip()
    ]
    non_topic_hooks = [hook for hook in hooks if hook != current_topic]
    selected_hook = str(raw_draft.get("selected_hook") or "").strip()
    strategic_delta = str(raw_draft.get("strategic_delta") or "").strip()
    if selected_hook and selected_hook != current_topic and selected_hook in combined + strategic_delta:
        return None
    if strategic_delta and any(hook and hook != current_topic and hook in strategic_delta + combined for hook in hooks):
        return None
    if any(hook and hook != current_topic and hook in combined for hook in non_topic_hooks):
        return None
    if current_topic and current_topic not in combined:
        return None
    return "draft_strategy_no_delta"


def draft_strategy_evidence(
    draft_payload: Mapping[str, Any],
    planner_recommendation: Mapping[str, Any] | None,
    observation: AppObservation,
) -> dict[str, Any]:
    profile_hooks = [
        str(item)
        for item in observation.profile_observation.hook_candidates
        if str(item).strip()
    ]
    return {
        "selected_hook": str(draft_payload.get("selected_hook") or draft_payload.get("hook_source") or "unknown"),
        "strategic_delta": str(draft_payload.get("strategic_delta") or draft_payload.get("why_this_works") or ""),
        "meeting_path": str(draft_payload.get("meeting_path") or ""),
        "why_not_ask_question": str(draft_payload.get("why_not_ask_question") or ""),
        "why_not_invite_now": str(draft_payload.get("why_not_invite_now") or ""),
        "planner_move": planner_recommendation.get("recommended_move") if planner_recommendation else None,
        "topic_state": (
            dict(planner_recommendation.get("topic_lifecycle") or {}).get("topic_state")
            if planner_recommendation
            else None
        ),
        "available_profile_hooks": profile_hooks,
    }

def _draft_stale_temporal_topic_without_bridge(
    draft_payload: Mapping[str, Any],
    texts: list[str],
    *,
    current_topic: str,
    topic: dict[str, Any],
    observation: AppObservation,
) -> bool:
    age_days = _latest_inbound_age_days(topic, observation, draft_payload)
    if age_days is None or age_days < 2:
        return False
    combined = "\n".join(
        [
            *texts,
            current_topic,
            str(draft_payload.get("selected_hook") or ""),
            str(draft_payload.get("strategic_delta") or ""),
        ]
    )
    if not _has_transient_topic(combined):
        return False
    strategic_delta = str(draft_payload.get("strategic_delta") or "")
    selected_hook = str(draft_payload.get("selected_hook") or "")
    if _has_non_transient_substantial_hook(strategic_delta) or _has_non_transient_substantial_hook(selected_hook):
        return False
    return True


def _draft_lacks_answerable_relationship_handle(
    draft_payload: Mapping[str, Any],
    texts: list[str],
    *,
    planner_recommendation: Mapping[str, Any],
    current_topic: str,
) -> bool:
    recommended_move = str(planner_recommendation.get("recommended_move") or "")
    if recommended_move in {"wait", "slow_down_wait", "handoff"}:
        return False
    conversation_move = str(draft_payload.get("conversation_move") or "")
    if conversation_move in {"wait", "slow_down_wait", "handoff"}:
        return False
    combined = "\n".join(texts)
    if _has_next_handle(combined, draft_payload, current_topic):
        return False
    return True


def _has_next_handle(text: str, draft_payload: Mapping[str, Any], current_topic: str) -> bool:
    if any(marker in text for marker in ANSWERABLE_HANDLE_MARKERS):
        return True
    selected_hook = str(draft_payload.get("selected_hook") or "").strip()
    strategic_delta = str(draft_payload.get("strategic_delta") or "").strip()
    if selected_hook and selected_hook != current_topic and selected_hook in text + strategic_delta:
        return True
    if _has_non_transient_substantial_hook(strategic_delta) and not _strategic_delta_is_weak(strategic_delta):
        return True
    return False


def _draft_redundant_confirmation_question(
    draft_payload: Mapping[str, Any],
    texts: list[str],
    *,
    current_topic: str,
    topic: dict[str, Any],
    observation: AppObservation,
) -> bool:
    latest_texts = [
        str(message.get("text") or "").strip()
        for message in observation.conversation_observation.latest_inbound_messages
    ]
    latest_texts = [text for text in latest_texts if text]
    if not latest_texts:
        return False
    latest_context = "\n".join(
        [
            *latest_texts,
            current_topic,
            *[str(item) for item in topic.get("new_information", []) if str(item).strip()],
        ]
    )
    latest_normalized = _normalized_strategy_text(latest_context)
    if not latest_normalized:
        return False
    selected_hook = str(draft_payload.get("selected_hook") or "")
    strategic_delta = str(draft_payload.get("strategic_delta") or "")
    for line in _draft_lines(texts):
        normalized = _normalized_strategy_text(line)
        if not normalized:
            continue
        if not any(marker in normalized for marker in LOW_VALUE_CONFIRMATION_MARKERS):
            continue
        if any(marker in normalized for marker in UNKNOWN_FOLLOWUP_MARKERS):
            continue
        combined = _normalized_strategy_text("\n".join([line, selected_hook, strategic_delta]))
        if _shares_latest_context(combined, latest_normalized) or _asks_obvious_latest_consequence(
            latest_normalized,
            normalized,
        ):
            return True
    return False


def _asks_obvious_latest_consequence(latest_text: str, draft_text: str) -> bool:
    if not latest_text or not draft_text:
        return False
    latest_constraint_markers = (
        "太大",
        "太晚",
        "太累",
        "太冷",
        "太热",
        "大雨",
        "下雨",
        "雨大",
        "暴雨",
    )
    obvious_consequence_markers = (
        "被困",
        "困住",
        "出不了门",
        "不能出门",
        "没出门",
        "不出门",
        "回不去",
        "动不了",
        "睡着",
        "倒头就睡",
    )
    return any(marker in latest_text for marker in latest_constraint_markers) and any(
        marker in draft_text for marker in obvious_consequence_markers
    )


def _latest_inbound_age_days(
    topic: dict[str, Any],
    observation: AppObservation,
    draft_payload: Mapping[str, Any],
) -> float | None:
    for source in (topic, draft_payload):
        for key in (
            "latest_inbound_age_days",
            "days_since_latest_inbound",
            "days_since_last_inbound",
            "days_since_last_activity",
            "elapsed_days",
            "age_days",
        ):
            value = source.get(key)
            try:
                if value is not None and str(value).strip() != "":
                    return float(value)
            except (TypeError, ValueError):
                continue
    captured = _parse_optional_iso(observation.captured_at)
    if captured is None:
        return None
    for message in reversed(observation.conversation_observation.latest_inbound_messages):
        if not isinstance(message, dict):
            continue
        for key in ("sent_at", "timestamp", "created_at", "time"):
            value = message.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            parsed = _parse_optional_iso(value)
            if parsed is not None:
                return max(0.0, (captured - parsed).total_seconds() / 86400.0)
        cue = str(message.get("timestamp_cue") or message.get("time_cue") or "")
        cue_age = _timestamp_cue_age_days(cue, captured_at=observation.captured_at)
        if cue_age is not None:
            return cue_age
    return None


def _has_transient_topic(text: str) -> bool:
    normalized = str(text).lower()
    return any(marker.lower() in normalized for marker in TRANSIENT_TOPIC_KEYWORDS)


def _has_non_transient_substantial_hook(text: str) -> bool:
    normalized = _normalized_strategy_text(text)
    if len(normalized) < 6:
        return False
    return not _has_transient_topic(text)


def _shares_latest_context(draft_text: str, latest_text: str) -> bool:
    if not draft_text or not latest_text:
        return False
    for marker in TRANSIENT_TOPIC_KEYWORDS:
        marker_norm = _normalized_strategy_text(marker)
        if marker_norm and marker_norm in draft_text and marker_norm in latest_text:
            return True
    for marker in ("上班", "下班", "慢热", "忙", "累", "晚班", "昨天", "那天"):
        marker_norm = _normalized_strategy_text(marker)
        if marker_norm and marker_norm in draft_text and marker_norm in latest_text:
            return True
    shared_chars = {
        char
        for char in set(draft_text)
        if "\u4e00" <= char <= "\u9fff"
        and char not in {"你", "我", "她", "他", "的", "了", "是", "也", "就", "那", "这", "有", "在"}
    }
    return len(shared_chars.intersection(set(latest_text))) >= 2


def _strategic_delta_is_weak(text: str) -> bool:
    normalized = str(text).lower()
    return any(marker.lower() in normalized for marker in WEAK_STRATEGIC_DELTA_MARKERS)


def _draft_forced_choice_restates_confirmed_info(
    texts: list[str],
    *,
    current_topic: str,
    topic: dict[str, Any],
    observation: AppObservation,
) -> bool:
    confirmed_items = [current_topic]
    new_information = topic.get("new_information")
    if isinstance(new_information, list):
        confirmed_items.extend(str(item) for item in new_information if str(item).strip())
    confirmed_items.extend(
        str(message.get("text") or "")
        for message in observation.conversation_observation.latest_inbound_messages
        if str(message.get("text") or "").strip()
    )
    confirmed_items.extend(
        str(item)
        for item in observation.conversation_observation.thread_cues
        if str(item).strip()
    )
    confirmed_context = "\n".join(confirmed_items)
    for line in _draft_lines(texts):
        if not _looks_like_ab_choice_question(line):
            continue
        left_side = line.split("还是", 1)[0]
        if _text_restates_confirmed_info(left_side, confirmed_context, current_topic):
            return True
    return False


def _draft_work_topic_not_preferred(
    draft_payload: Mapping[str, Any],
    texts: list[str],
    observation: AppObservation,
) -> bool:
    selected_hook = str(draft_payload.get("selected_hook") or "").strip()
    strategic_delta = str(draft_payload.get("strategic_delta") or "").strip()
    hook_source = str(draft_payload.get("hook_source") or "").strip()
    draft_context = "\n".join([*texts, selected_hook, strategic_delta, hook_source])
    if not _has_work_topic(draft_context):
        return False
    latest_inbound_text = "\n".join(
        str(message.get("text") or "")
        for message in observation.conversation_observation.latest_inbound_messages
    )
    if _has_work_topic(latest_inbound_text):
        return False
    if _has_work_high_salience(observation.profile_observation.profile_text):
        return False
    hooks = [
        str(item).strip()
        for item in observation.profile_observation.hook_candidates
        if str(item).strip()
    ]
    if not any(_is_lifestyle_hook(hook) for hook in hooks):
        return False
    return True


def _draft_stale_reactivation_continues_old_topic(
    draft_payload: Mapping[str, Any],
    texts: list[str],
    *,
    current_topic: str,
    topic: dict[str, Any],
) -> bool:
    risk_flags = [
        str(item)
        for item in draft_payload.get("risk_flags", [])
        if str(item).strip()
    ] if isinstance(draft_payload.get("risk_flags"), list) else []
    stale_hooks = [
        str(item)
        for item in topic.get("stale_hooks", [])
        if str(item).strip()
    ] if isinstance(topic.get("stale_hooks"), list) else []
    stale_reactivation = (
        "stale_thread_reactivation" in risk_flags
        or any("visible timestamp" in hook or "旧" in hook or "stale" in hook.lower() for hook in stale_hooks)
    )
    if not stale_reactivation or not current_topic:
        return False
    selected_hook = str(draft_payload.get("selected_hook") or "").strip()
    if selected_hook and _normalized_strategy_text(selected_hook) == _normalized_strategy_text(current_topic):
        return True
    strategic_delta = str(draft_payload.get("strategic_delta") or "").strip()
    combined = "\n".join([*texts, strategic_delta])
    normalized_topic = _normalized_strategy_text(current_topic)
    if not normalized_topic:
        return False
    return normalized_topic in _normalized_strategy_text(combined)


def _draft_lines(texts: list[str]) -> list[str]:
    lines: list[str] = []
    for text in texts:
        lines.extend(part.strip() for part in str(text).splitlines() if part.strip())
    return lines


def _looks_like_ab_choice_question(line: str) -> bool:
    if "还是" not in line:
        return False
    if re.search(r"(你|平时|一般|通常|喜欢|爱|会|是|更|偏).{0,40}还是", line):
        return True
    return bool(re.search(r"还是.{0,24}[?？吗嘛么呢]", line))


def _text_restates_confirmed_info(text: str, confirmed_context: str, current_topic: str) -> bool:
    if current_topic and current_topic in text:
        return True
    if _has_slow_warm_context(confirmed_context) and any(marker in text for marker in SLOW_WARM_RESTATEMENTS):
        return True
    normalized_confirmed = _normalized_strategy_text(confirmed_context)
    normalized_text = _normalized_strategy_text(text)
    return bool(
        normalized_text
        and len(normalized_text) >= 4
        and normalized_text in normalized_confirmed
    )


def _has_slow_warm_context(text: str) -> bool:
    return any(marker in text for marker in SLOW_WARM_CONTEXT_MARKERS)


def _has_work_topic(text: str) -> bool:
    normalized = str(text).lower()
    return any(marker in normalized for marker in WORK_TOPIC_KEYWORDS)


def _has_work_high_salience(text: str) -> bool:
    normalized = str(text).lower()
    return any(marker in normalized for marker in WORK_HIGH_SALIENCE_MARKERS)


def _is_lifestyle_hook(hook: str) -> bool:
    normalized = str(hook).lower()
    return any(marker in normalized for marker in LIFESTYLE_HOOK_KEYWORDS)


def _has_tag_stacking(text: str) -> bool:
    return bool(
        re.search(r"\b(?:ESFP|ENFP|INFP|INTJ|INFJ|ISFP|ENTP|ENTJ|ISTJ|ISFJ|ESTP|ESTJ)\b.{0,8}(夜猫子|慢热|i人|e人|社恐)", text, re.I)
        or re.search(r"(夜猫子|慢热|i人|e人|社恐).{0,8}\b(?:ESFP|ENFP|INFP|INTJ|INFJ|ISFP|ENTP|ENTJ|ISTJ|ISFJ|ESTP|ESTJ)\b", text, re.I)
    )


def _latest_asks_or_reacts(text: str) -> bool:
    return bool(text and (looks_like_direct_question(text) or any(marker in text for marker in ("咋想", "怎么会", "哈哈", "？", "?"))))


def _draft_answers_or_riffs(draft_text: str, latest_text: str) -> bool:
    if not draft_text:
        return False
    riff_markers = ("我也", "感觉", "可能", "确实", "哈哈", "懂了", "那我")
    if any(marker in draft_text for marker in riff_markers):
        return True
    latest_norm = _normalized_strategy_text(latest_text)
    draft_norm = _normalized_strategy_text(draft_text)
    return bool(latest_norm and len(set(latest_norm) & set(draft_norm)) >= 2)


def _normalized_strategy_text(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;“”\"'（）()]+", "", str(text))


def _parse_optional_iso(value: str) -> datetime | None:
    try:
        return _parse_iso_utc(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
