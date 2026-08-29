"""Finding generation for draft review."""

from __future__ import annotations

from typing import Any, Mapping

from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.content import evaluate_draft_content
from dating_boost.policy.draft_review_models import DraftReviewFinding
from dating_boost.policy.draft_review_payload import draft_question_count, looks_like_direct_question
from dating_boost.policy.draft_review_strategy import (
    _draft_answers_or_riffs, _has_next_handle, _has_tag_stacking, _latest_asks_or_reacts,
    _normalized_strategy_text,
)

DISCLOSURE_MOVES = {"light_self_disclosure", "reciprocal_disclosure", "low_investment_repair"}
ABSTRACT_AI_WORDS = ("路线", "放松方式", "选择倾向", "心理动机", "生活方式偏好")
DELEGATION_MARKERS = ("你定", "你安排", "听你的", "随你", "都行")

__all__ = [
    "ABSTRACT_AI_WORDS",
    "DELEGATION_MARKERS",
    "DISCLOSURE_MOVES",
    "_content_findings",
    "_disclosure_findings",
    "_finding",
    "_finding_blocks_mode",
    "_hint_for_code",
    "_low_investment_findings",
    "_message_for_code",
    "_naturalness_findings",
    "_planner_findings",
    "_status_for_review",
]

def _content_findings(
    draft: DraftResponse,
    context_pack: Mapping[str, Any],
    final_messages: list[dict[str, Any]],
) -> list[DraftReviewFinding]:
    policy = evaluate_draft_content(
        draft,
        context_pack,
        final_texts=(str(message.get("text") or "") for message in final_messages),
    )
    if policy.allowed and not policy.requires_user_confirmation:
        return []
    code = "content_user_confirmation_required"
    category = "content"
    blocks_managed = True
    blocks_display = False
    blocks_stage = False
    requires_confirmation = bool(policy.requires_user_confirmation)
    reason = policy.reason.lower()
    if "user handoff" in reason:
        code = "content_managed_handoff_required"
    if not policy.allowed:
        blocks_display = True
        blocks_stage = True
        if "hard fact" in reason or "contradict" in reason or "overseas study" in reason:
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
        "content_managed_handoff_required": "自动托管只保留低压试探；联系方式或具体时间地点交给用户接管。",
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
