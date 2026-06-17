"""Unified draft review contract for display, staging, and managed live send."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

from dating_boost.core.models import Divergence
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.content import evaluate_draft_content


DRAFT_REVIEW_SCHEMA_VERSION = 1
DRAFT_REVIEW_MODES = {"display", "stage", "managed_live"}
DISCLOSURE_MOVES = {"light_self_disclosure", "reciprocal_disclosure", "low_investment_repair"}

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
ABSTRACT_AI_WORDS = ("路线", "放松方式", "选择倾向", "心理动机", "生活方式偏好")
DELEGATION_MARKERS = ("你定", "你安排", "听你的", "随你", "都行")
HISTORICAL_THREAD_CUTOFF_DAYS = 7


@dataclass(frozen=True)
class DraftReviewFinding:
    code: str
    category: str
    severity: str
    message: str
    revision_hint: str = ""
    blocks_display: bool = False
    blocks_stage: bool = False
    blocks_managed_send: bool = True
    requires_user_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DraftReviewDecision:
    schema_version: int
    status: str
    allowed_for_display: bool
    allowed_for_stage: bool
    allowed_for_managed_send: bool
    requires_user_confirmation: bool
    primary_reason: str
    summary: dict[str, Any]
    findings: list[DraftReviewFinding]
    revision_hints: list[str]
    payload_hash: str
    payload_format: str
    message_count: int
    review_id: str

    def to_dict(self, *, include_findings: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [finding.to_dict() for finding in self.findings] if include_findings else []
        return payload


def review_draft(
    draft_payload: Mapping[str, Any] | DraftResponse,
    context_pack: Mapping[str, Any],
    *,
    mode: str,
    observation: AppObservation | None = None,
    planner_recommendation: Mapping[str, Any] | None = None,
    disclosure_profile: Mapping[str, Any] | None = None,
) -> DraftReviewDecision:
    """Review one draft against the unified display/stage/live-send contract."""

    normalized_mode = _normalize_mode(mode)
    raw_draft = _draft_payload_dict(draft_payload)
    draft = _draft_from_payload(raw_draft)
    context = dict(context_pack)
    planner = dict(planner_recommendation or _planner_recommendation(context) or {})
    review_observation = observation or _observation_from_context_pack(context)
    review_disclosure_profile = disclosure_profile or _disclosure_profile_from_context_pack(context)
    messages = draft_payload_messages(raw_draft, draft.best_reply)
    payload_hash = draft_messages_payload_hash(messages)
    payload_format = "message_sequence" if len(messages) > 1 else "single_message"

    findings: list[DraftReviewFinding] = []
    findings.extend(_content_findings(draft, context))
    findings.extend(_planner_findings(raw_draft, planner))
    findings.extend(_disclosure_findings(raw_draft, draft, review_disclosure_profile))
    findings.extend(_low_investment_findings(raw_draft, draft, planner))
    findings.extend(_naturalness_findings(raw_draft, messages, review_observation))
    if planner and review_observation is not None:
        strategy_reason = draft_strategy_block_reason(raw_draft, planner, review_observation)
        if strategy_reason:
            findings.append(
                _finding(
                    strategy_reason,
                    "temporal_fit" if "temporal" in strategy_reason or "stale" in strategy_reason else "strategy",
                    "medium",
                    _message_for_code(strategy_reason),
                    _hint_for_code(strategy_reason),
                    blocks_managed_send=True,
                )
            )

    allowed_for_display = not any(finding.blocks_display for finding in findings)
    allowed_for_stage = allowed_for_display and not any(finding.blocks_stage for finding in findings)
    allowed_for_managed_send = (
        allowed_for_stage
        and not any(finding.blocks_managed_send for finding in findings)
        and not any(finding.requires_user_confirmation for finding in findings)
    )
    requires_user_confirmation = any(finding.requires_user_confirmation for finding in findings)
    selected_allowed = {
        "display": allowed_for_display,
        "stage": allowed_for_stage,
        "managed_live": allowed_for_managed_send,
    }[normalized_mode]
    primary = next((finding.code for finding in findings if _finding_blocks_mode(finding, normalized_mode)), None)
    if primary is None:
        primary = next((finding.code for finding in findings if finding.blocks_managed_send), "passed")
    status = _status_for_review(
        mode=normalized_mode,
        allowed=selected_allowed,
        findings=findings,
    )
    revision_hints = _unique_strings(
        [finding.revision_hint for finding in findings if finding.revision_hint]
    )
    finding_codes = [finding.code for finding in findings]
    summary = {
        "status": status,
        "mode": normalized_mode,
        "allowed_for_display": allowed_for_display,
        "allowed_for_stage": allowed_for_stage,
        "allowed_for_managed_send": allowed_for_managed_send,
        "requires_user_confirmation": requires_user_confirmation,
        "primary_reason": primary,
        "finding_codes": finding_codes,
        "finding_count": len(findings),
        "revision_hints": revision_hints,
        "payload_hash": payload_hash,
        "payload_format": payload_format,
        "message_count": len(messages),
    }
    review_id = f"draft_review_{_digest({'payload_hash': payload_hash, 'mode': normalized_mode, 'findings': finding_codes})[:16]}"
    return DraftReviewDecision(
        schema_version=DRAFT_REVIEW_SCHEMA_VERSION,
        status=status,
        allowed_for_display=allowed_for_display,
        allowed_for_stage=allowed_for_stage,
        allowed_for_managed_send=allowed_for_managed_send,
        requires_user_confirmation=requires_user_confirmation,
        primary_reason=primary,
        summary=summary,
        findings=findings,
        revision_hints=revision_hints,
        payload_hash=payload_hash,
        payload_format=payload_format,
        message_count=len(messages),
        review_id=review_id,
    )


def draft_payload_messages(draft_payload: Mapping[str, Any], fallback_text: str) -> list[dict[str, Any]]:
    raw_messages = draft_payload.get("message_sequence")
    if isinstance(raw_messages, list):
        texts = [str(item).strip() for item in raw_messages if str(item).strip()]
    else:
        texts = [str(fallback_text).strip()]
    if not texts:
        texts = [str(fallback_text)]
    return [
        {
            "index": index,
            "text": text,
            "message_hash": text_hash(text),
            "character_count": len(text),
        }
        for index, text in enumerate(texts, start=1)
    ]


def draft_messages_payload_hash(messages: list[dict[str, Any]]) -> str:
    texts = [str(message.get("text") or "") for message in messages]
    if len(texts) == 1:
        return text_hash(texts[0])
    return _digest({"payload_format": "message_sequence", "messages": texts})


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def draft_question_count(raw_draft: Mapping[str, Any], best_reply: str) -> int:
    explicit = raw_draft.get("question_count")
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 0:
        return explicit
    reply_shape = str(raw_draft.get("reply_shape") or "")
    if reply_shape in {"question", "contains_question"}:
        return 1
    texts = [str(message.get("text") or "") for message in draft_payload_messages(raw_draft, best_reply)]
    return sum(1 for text in texts if looks_like_direct_question(text))


def looks_like_direct_question(text: str) -> bool:
    stripped = text.strip()
    if "?" in stripped or "？" in stripped:
        return True
    question_phrases = ("是不是", "有没有", "会不会", "要不要", "能不能", "为什么", "怎么")
    if any(marker in stripped for marker in question_phrases):
        return True
    return bool(re.search(r"(吗|嘛|么|呢)[。！!…]*$", stripped))


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


def _content_findings(draft: DraftResponse, context_pack: Mapping[str, Any]) -> list[DraftReviewFinding]:
    policy = evaluate_draft_content(draft, context_pack)
    if policy.allowed and not policy.requires_user_confirmation:
        return []
    code = "content_user_confirmation_required"
    category = "content"
    blocks_managed = True
    blocks_display = False
    blocks_stage = False
    requires_confirmation = bool(policy.requires_user_confirmation)
    if not policy.allowed:
        blocks_display = True
        blocks_stage = True
        reason = policy.reason.lower()
        if "soft invite" in reason:
            code = "content_soft_invite_detail"
        elif "hard fact" in reason or "contradict" in reason or "overseas study" in reason:
            code = "content_hard_fact"
        else:
            code = "content_blocked"
    return [
        _finding(
            code,
            category,
            policy.severity,
            policy.reason,
            _hint_for_code(code),
            blocks_display=blocks_display,
            blocks_stage=blocks_stage,
            blocks_managed_send=blocks_managed,
            requires_user_confirmation=requires_confirmation,
        )
    ]


def _planner_findings(
    draft_payload: Mapping[str, Any],
    planner_recommendation: Mapping[str, Any],
) -> list[DraftReviewFinding]:
    if not planner_recommendation:
        return []
    findings: list[DraftReviewFinding] = []
    if not planner_recommendation.get("auto_send_allowed", True):
        reasons = [
            str(reason)
            for reason in planner_recommendation.get("block_reasons", [])
            if str(reason).strip()
        ]
        findings.append(
            _finding(
                "planner_auto_send_blocked",
                "planner",
                "high",
                "; ".join(reasons) or "Planner recommendation blocks automatic send.",
                "按 planner 重新起草，或交给用户处理。",
                blocks_managed_send=True,
                requires_user_confirmation=str(planner_recommendation.get("recommended_move") or "") == "handoff",
            )
        )
    recommended_move = str(planner_recommendation.get("recommended_move") or "")
    draft_move = str(draft_payload.get("conversation_move") or "")
    if recommended_move and draft_move and draft_move != recommended_move:
        findings.append(
            _finding(
                "planner_misaligned_draft",
                "planner",
                "medium",
                f"Draft move {draft_move!r} does not match planner move {recommended_move!r}.",
                "把 conversation_move 和正文推进方向改到 planner 推荐的下一步。",
                blocks_managed_send=True,
            )
        )
    return findings


def _disclosure_findings(
    raw_draft: Mapping[str, Any],
    draft: DraftResponse,
    disclosure_profile: Mapping[str, Any] | None,
) -> list[DraftReviewFinding]:
    if draft.conversation_move not in DISCLOSURE_MOVES:
        return []
    disclosure_source = str(raw_draft.get("disclosure_source") or "simulated_soft")
    used_material_ids = [
        str(item)
        for item in raw_draft.get("used_user_material_ids", [])
        if str(item).strip()
    ] if isinstance(raw_draft.get("used_user_material_ids"), list) else []
    if disclosure_source not in {"none", "user_material", "simulated_soft", "user_confirmed"}:
        return [
            _finding(
                "invalid_disclosure_source",
                "disclosure",
                "high",
                "Disclosure source is not a supported value.",
                "设置 disclosure_source 为 user_material、simulated_soft 或 user_confirmed。",
                blocks_managed_send=True,
            )
        ]
    if disclosure_profile is None:
        return [
            _finding(
                "user_disclosure_profile_required",
                "disclosure",
                "high",
                "Self-disclosure draft requires a user disclosure profile.",
                "先导入用户自我材料，或改成不自曝的回复。",
                blocks_managed_send=True,
                requires_user_confirmation=True,
            )
        ]
    simulation_policy = str(disclosure_profile.get("simulation_policy") or "free_simulation_soft")
    material_ids = {
        str(item.get("material_id"))
        for item in disclosure_profile.get("shareable_material", [])
        if isinstance(item, Mapping) and str(item.get("material_id") or "").strip()
    }
    if simulation_policy == "material_only":
        if disclosure_source != "user_material":
            return [
                _finding(
                    "simulated_disclosure_not_allowed",
                    "disclosure",
                    "high",
                    "Disclosure profile requires sourced user material.",
                    "改用 user_material 并附 used_user_material_ids，或改成不自曝。",
                    blocks_managed_send=True,
                )
            ]
        if not used_material_ids:
            return [
                _finding(
                    "disclosure_material_id_required",
                    "disclosure",
                    "high",
                    "material_only disclosure requires used_user_material_ids.",
                    "选择具体用户材料 id，或改成不自曝。",
                    blocks_managed_send=True,
                )
            ]
    if disclosure_source == "user_material":
        unknown_ids = [material_id for material_id in used_material_ids if material_id not in material_ids]
        if unknown_ids:
            return [
                _finding(
                    "unknown_disclosure_material_id",
                    "disclosure",
                    "high",
                    "Draft references disclosure material ids not present in the profile.",
                    "只使用 disclosure profile 中存在的 material_id。",
                    blocks_managed_send=True,
                )
            ]
    if simulation_policy == "user_confirmed_only":
        return [
            _finding(
                "disclosure_user_confirmation_required",
                "disclosure",
                "medium",
                "Disclosure profile requires user confirmation before self-disclosure.",
                "把草稿交给用户确认后再发送。",
                blocks_managed_send=True,
                requires_user_confirmation=True,
            )
        ]
    return []


def _low_investment_findings(
    raw_draft: Mapping[str, Any],
    draft: DraftResponse,
    planner_recommendation: Mapping[str, Any],
) -> list[DraftReviewFinding]:
    if not planner_recommendation:
        return []
    if (
        int(planner_recommendation.get("low_investment_streak") or 0) >= 2
        and int(planner_recommendation.get("question_debt") or 0) >= 2
        and draft_question_count(raw_draft, draft.best_reply) > 0
    ):
        return [
            _finding(
                "low_investment_direct_question_blocked",
                "strategy",
                "medium",
                "Low-investment thread with question debt should not receive another direct question.",
                "改成轻自曝、接梗或暂缓，不要继续采访。",
                blocks_managed_send=True,
            )
        ]
    return []


def _naturalness_findings(
    raw_draft: Mapping[str, Any],
    messages: list[dict[str, Any]],
    observation: AppObservation | None,
) -> list[DraftReviewFinding]:
    texts = [str(message.get("text") or "") for message in messages]
    combined = "\n".join(texts)
    findings: list[DraftReviewFinding] = []
    if len(messages) > 1:
        mechanical = [text for text in texts if text.endswith(("，", ",", "、", "。")) or len(_normalized_strategy_text(text)) < 4]
        if mechanical:
            findings.append(
                _finding(
                    "message_sequence_mechanical_split",
                    "naturalness",
                    "medium",
                    "message_sequence appears mechanically split instead of bubble-by-bubble.",
                    "每个气泡要有独立作用，不要只按标点切分。",
                    blocks_managed_send=True,
                )
            )
        final_text = texts[-1] if texts else ""
        if final_text and not _has_next_handle(final_text, raw_draft, ""):
            findings.append(
                _finding(
                    "message_sequence_final_bubble_no_push",
                    "naturalness",
                    "medium",
                    "Final message bubble does not carry the conversational push.",
                    "把推进、落点或自然交还话题放在最后一条。",
                    blocks_managed_send=True,
                )
            )
    if _has_tag_stacking(combined):
        findings.append(
            _finding(
                "naturalness_tag_stacking",
                "naturalness",
                "medium",
                "Draft stacks multiple profile labels in one phrase.",
                "减少标签堆叠，一个标签足够。",
                blocks_managed_send=True,
            )
        )
    if any(word in combined for word in ABSTRACT_AI_WORDS):
        findings.append(
            _finding(
                "naturalness_abstract_wording",
                "naturalness",
                "medium",
                "Draft uses abstract or AI-sounding Chinese wording.",
                "改成具体生活场景和正常聊天表达。",
                blocks_managed_send=True,
            )
        )
    if observation is not None:
        latest = "\n".join(
            str(message.get("text") or "")
            for message in observation.conversation_observation.latest_inbound_messages
        )
        if any(marker in latest for marker in DELEGATION_MARKERS) and looks_like_direct_question(combined):
            findings.append(
                _finding(
                    "naturalness_delegation_bounced",
                    "naturalness",
                    "medium",
                    "Match delegated the choice, but the draft asks them to decide again.",
                    "接过选择权，给一个轻量具体决定。",
                    blocks_managed_send=True,
                )
            )
        if _latest_asks_or_reacts(latest) and looks_like_direct_question(combined) and not _draft_answers_or_riffs(combined, latest):
            findings.append(
                _finding(
                    "naturalness_forced_question_after_match_prompt",
                    "naturalness",
                    "medium",
                    "Draft forces another question instead of answering or riffing on the latest inbound.",
                    "先回答、接梗或轻轻展开，再考虑是否需要问题。",
                    blocks_managed_send=True,
                )
            )
    return findings


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


def _normalize_mode(mode: str) -> str:
    normalized = str(mode).strip().replace("-", "_")
    if normalized not in DRAFT_REVIEW_MODES:
        raise ValueError(f"unsupported draft review mode: {mode}")
    return normalized


def _draft_payload_dict(draft_payload: Mapping[str, Any] | DraftResponse) -> dict[str, Any]:
    if isinstance(draft_payload, DraftResponse):
        data = asdict(draft_payload)
        data["persona_divergence"] = draft_payload.persona_divergence.value
        data["stance_divergence"] = draft_payload.stance_divergence.value
        return data
    return dict(draft_payload)


def _draft_from_payload(data: Mapping[str, Any]) -> DraftResponse:
    return DraftResponse(
        best_reply=str(data.get("best_reply") or ""),
        safer_reply=str(data.get("safer_reply") or data.get("best_reply") or ""),
        bolder_reply=str(data.get("bolder_reply") or data.get("best_reply") or ""),
        why_this_works=str(data.get("why_this_works") or ""),
        situation_read=str(data.get("situation_read") or ""),
        conversation_move=str(data.get("conversation_move") or ""),
        hook_source=str(data.get("hook_source") or ""),
        naturalness_notes=[str(item) for item in data.get("naturalness_notes", [])] if isinstance(data.get("naturalness_notes", []), list) else [],
        followup_if_match_replies=str(data.get("followup_if_match_replies") or ""),
        risk_flags=[str(item) for item in data.get("risk_flags", [])] if isinstance(data.get("risk_flags", []), list) else [],
        missing_info=[str(item) for item in data.get("missing_info", [])] if isinstance(data.get("missing_info", []), list) else [],
        mode_notes=str(data.get("mode_notes") or ""),
        persona_divergence=_divergence_value(data.get("persona_divergence")),
        stance_divergence=_divergence_value(data.get("stance_divergence")),
    )


def _divergence_value(value: Any) -> Divergence:
    try:
        if isinstance(value, Divergence):
            return value
        return Divergence(str(value or Divergence.LOW.value))
    except ValueError:
        return Divergence.HIGH


def _planner_recommendation(context_pack: Mapping[str, Any]) -> Mapping[str, Any]:
    direct = context_pack.get("planner_recommendation")
    if isinstance(direct, Mapping):
        return direct
    for item in context_pack.get("items", []):
        if isinstance(item, Mapping) and item.get("label") == "planner_recommendation":
            content = item.get("content")
            if isinstance(content, Mapping):
                return content
    return {}


def _disclosure_profile_from_context_pack(context_pack: Mapping[str, Any]) -> Mapping[str, Any] | None:
    content = _context_label_content(context_pack, "user_disclosure_profile")
    return content if isinstance(content, Mapping) else None


def _observation_from_context_pack(context_pack: Mapping[str, Any]) -> AppObservation | None:
    latest_inbound = _context_message_list(_context_label_content(context_pack, "latest_inbound_messages"))
    recent_messages = _context_message_list(_context_label_content(context_pack, "recent_messages"))
    latest_message = _context_message_list(_context_label_content(context_pack, "latest_message"))
    visible_messages = [*recent_messages, *latest_message, *latest_inbound]
    hooks = _context_string_list(_context_label_content(context_pack, "match_hooks"))
    thread_cues = _context_string_list(_context_label_content(context_pack, "open_threads"))
    send_time = _context_label_content(context_pack, "send_time_context")
    if not latest_inbound and not visible_messages and not hooks and not isinstance(send_time, Mapping):
        return None
    captured_at = _captured_at_from_send_time(send_time)
    profile_text = "\n".join(hooks)
    return AppObservation.from_dict(
        {
            "observation_id": "ctx_obs_" + _digest(
                {
                    "latest_inbound": latest_inbound,
                    "visible_messages": visible_messages,
                    "hooks": hooks,
                    "captured_at": captured_at,
                }
            )[:16],
            "source_type": "user_input",
            "app_id": str(context_pack.get("app_id") or "context"),
            "adapter_id": "draft_review.context.v1",
            "captured_at": captured_at,
            "page_type": "chat_thread",
            "page_confidence": "low",
            "match_identity_hints": {
                "visible_name": None,
                "profile_cues": hooks,
                "conversation_fingerprint": None,
                "evidence": "context_pack",
            },
            "profile_observation": {
                "profile_text": profile_text,
                "photo_cues": [],
                "hook_candidates": hooks,
                "review_status": "observed" if hooks else "missing",
                "evidence": "context_pack",
            },
            "conversation_observation": {
                "visible_messages": visible_messages,
                "input_state": "",
                "thread_cues": thread_cues,
                "latest_inbound_messages": latest_inbound,
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {"source": "context_pack"},
            "raw_ref": None,
        }
    )


def _context_label_content(context_pack: Mapping[str, Any], label: str) -> Any:
    direct = context_pack.get(label)
    if direct is not None:
        return direct
    items = context_pack.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if item.get("label") == label:
            return item.get("content")
    return None


def _context_message_list(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    messages: list[dict[str, str]] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("content") or "").strip()
            if not text:
                continue
            message = {
                "sender": str(item.get("sender") or "match"),
                "text": text,
            }
            timestamp = str(item.get("timestamp") or item.get("created_at") or "").strip()
            if timestamp:
                message["timestamp"] = timestamp
            messages.append(message)
        else:
            text = str(item).strip()
            if text:
                messages.append({"sender": "match", "text": text})
    return messages


def _context_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    strings: list[str] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("content") or item.get("label") or "").strip()
        else:
            text = str(item).strip()
        if text:
            strings.append(text)
    return strings


def _captured_at_from_send_time(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("current_utc", "current_local", "captured_at"):
            raw = str(value.get(key) or "").strip()
            if raw:
                return raw
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_for_review(
    *,
    mode: str,
    allowed: bool,
    findings: list[DraftReviewFinding],
) -> str:
    if not allowed:
        if any(
            finding.blocks_display
            or finding.blocks_stage
            or finding.requires_user_confirmation
            or finding.severity == "high"
            for finding in findings
        ):
            return "blocked"
        return "needs_revision"
    if findings:
        if mode in {"display", "stage"}:
            return "needs_revision"
        if any(finding.blocks_managed_send for finding in findings):
            return "needs_revision"
    return "ok"


def _finding_blocks_mode(finding: DraftReviewFinding, mode: str) -> bool:
    if mode == "display":
        return finding.blocks_display
    if mode == "stage":
        return finding.blocks_display or finding.blocks_stage
    return finding.blocks_display or finding.blocks_stage or finding.blocks_managed_send


def _finding(
    code: str,
    category: str,
    severity: str,
    message: str,
    revision_hint: str = "",
    *,
    blocks_display: bool = False,
    blocks_stage: bool = False,
    blocks_managed_send: bool = True,
    requires_user_confirmation: bool = False,
) -> DraftReviewFinding:
    return DraftReviewFinding(
        code=code,
        category=category,
        severity=severity,
        message=message,
        revision_hint=revision_hint,
        blocks_display=blocks_display,
        blocks_stage=blocks_stage,
        blocks_managed_send=blocks_managed_send,
        requires_user_confirmation=requires_user_confirmation,
    )


def _message_for_code(code: str) -> str:
    return {
        "draft_forced_choice_restates_confirmed_info": "A/B choice restates already-confirmed information.",
        "draft_stale_temporal_topic_without_bridge": "Draft treats a stale time-sensitive topic as current.",
        "draft_stale_reactivation_continues_old_topic": "Stale reactivation continues the old topic instead of acknowledging delay and bridging.",
        "draft_work_topic_not_preferred": "Draft leads with work while better lifestyle hooks are available.",
        "draft_ai_survey_choice_question": "Draft uses survey-style A/B wording in managed send.",
        "draft_redundant_confirmation_question": "Draft asks a low-value confirmation question from already implied context.",
        "draft_no_answerable_relationship_handle": "Draft lacks an answerable relationship handle.",
        "draft_strategy_no_delta": "Draft does not add strategic delta for a saturated or low-investment thread.",
    }.get(code, code)


def _hint_for_code(code: str) -> str:
    return {
        "content_hard_fact": "删除无法由用户硬事实支持的自我事实。",
        "content_soft_invite_detail": "保留低压线下试探，不给具体时间、地点或联系方式。",
        "content_user_confirmation_required": "让用户确认 persona/stance 偏移后再发送。",
        "draft_forced_choice_restates_confirmed_info": "不要把已确认事实做成选项，改问未知细节或用 yes/no 假设。",
        "draft_stale_temporal_topic_without_bridge": "把陈旧时间话题桥到现在仍成立的生活把手。",
        "draft_stale_reactivation_continues_old_topic": "先承认延迟，再换到可继续的新把手。",
        "draft_work_topic_not_preferred": "优先露营、咖啡、电影等生活钩子，除非对方主动聊工作。",
        "draft_ai_survey_choice_question": "改成一个自然问题或轻陈述，避免 A/B 调查感。",
        "draft_redundant_confirmation_question": "别确认显然结果，改问未知后续。",
        "draft_no_answerable_relationship_handle": "增加具体未知细节、用户侧小自曝或下一里程碑桥接。",
        "draft_strategy_no_delta": "加入非当前浅话题的新把手或选择等待。",
    }.get(code, "")


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
