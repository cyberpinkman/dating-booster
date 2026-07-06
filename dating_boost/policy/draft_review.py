"""Unified draft review contract for display, staging, and managed live send."""

from __future__ import annotations

from typing import Any, Mapping

from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review_context import (
    _disclosure_profile_from_context_pack,
    _observation_from_context_pack,
    _planner_recommendation,
)
from dating_boost.policy.draft_review_findings import (
    _content_findings, _disclosure_findings, _finding, _finding_blocks_mode,
    _hint_for_code, _low_investment_findings, _message_for_code, _naturalness_findings,
    _planner_findings, _status_for_review,
)
from dating_boost.policy.draft_review_models import (
    DRAFT_REVIEW_MODES,
    DRAFT_REVIEW_SCHEMA_VERSION,
    DraftReviewDecision,
    DraftReviewFinding,
)
from dating_boost.policy.draft_review_payload import (
    _draft_from_payload, _draft_payload_dict, _normalize_mode, draft_messages_payload_hash,
    draft_payload_messages, draft_question_count, looks_like_direct_question, text_hash,
)
from dating_boost.policy.draft_review_strategy import draft_strategy_block_reason, draft_strategy_evidence
from dating_boost.policy.draft_review_utils import _digest, _unique_strings

__all__ = [
    "DRAFT_REVIEW_MODES",
    "DRAFT_REVIEW_SCHEMA_VERSION",
    "DraftReviewDecision",
    "DraftReviewFinding",
    "draft_messages_payload_hash",
    "draft_payload_messages",
    "draft_question_count",
    "draft_strategy_block_reason",
    "draft_strategy_evidence",
    "looks_like_direct_question",
    "review_draft",
    "text_hash",
]

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
