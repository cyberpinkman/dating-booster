from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.draft_evidence import build_draft_evidence
from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
from dating_boost.core.models import Divergence, ReplyMode
from dating_boost.core.production_store import payload_digest
from dating_boost.core.user_disclosure import UserDisclosureRepository
from dating_boost.core.automation_send_revision import _request_draft_revision
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation


STAGE_ONLY_SELF_REVIEW_SOFT_ACCEPT_THRESHOLD = 65


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


def _prepare_send_draft_contract(
    repository: Any,
    *,
    scan_requests: list[dict[str, Any]],
    warnings: list[str],
    state: dict[str, Any],
    match_id: str,
    candidate_key: str,
    observation: AppObservation,
    draft_payload: Any,
    is_nudge: bool,
    authorization: dict[str, Any],
    review_draft_fn: Any,
    planner_recommendation: dict[str, Any] | None,
    standalone_draft_review: Any,
) -> dict[str, Any] | None:
    raw_draft = dict(draft_payload)
    draft = _draft_from_dict(raw_draft)
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
        repository.root,
        match_id,
        reply_mode=ReplyMode.ADAPTIVE,
        observation=observation,
        draft_kind="nudge" if is_nudge else "reply",
        now=repository._now(),
        app_id=observation.app_id,
        runtime=observation.provenance.get("runtime") or observation.provenance.get("harness_runtime") or "default",
        require_user_profile_source=True,
    )
    if evidence.status != "ok":
        _request_draft_revision(
            state=state,
            scan_requests=scan_requests,
            warnings=warnings,
            candidate_key=candidate_key,
            match_id=match_id,
            visible_name=observation.match_identity_hints.visible_name,
            reason=evidence.primary_reason or "draft_evidence_blocked",
            extra_warning="draft_evidence_required",
        )
        return None

    generation_binding = _prepare_generation_binding(
        repository,
        raw_draft,
        evidence,
        authorization=authorization,
        standalone_draft_review=standalone_draft_review,
        state=state,
        scan_requests=scan_requests,
        warnings=warnings,
        candidate_key=candidate_key,
        match_id=match_id,
        visible_name=observation.match_identity_hints.visible_name,
    )
    if generation_binding is None:
        return None

    context_pack = evidence.context_pack
    review = review_draft_fn(
        raw_draft,
        context_pack,
        mode="managed_live",
        observation=observation,
        planner_recommendation=planner_recommendation,
        disclosure_profile=UserDisclosureRepository(repository.root).load_profile_or_none(),
    )
    DraftReviewAuditRepository(repository.root).append_review(
        review,
        draft_payload=raw_draft,
        context_pack=context_pack,
        mode="managed_live",
        target_match_id=match_id,
    )
    stage_only_review_soft_accept = _stage_only_review_soft_accept_allowed(
        authorization=authorization,
        review=review,
        standalone_draft_review=standalone_draft_review,
    )
    if not review.allowed_for_managed_send and not stage_only_review_soft_accept:
        _request_blocked_review_revision(
            review,
            state=state,
            scan_requests=scan_requests,
            warnings=warnings,
            candidate_key=candidate_key,
            match_id=match_id,
            visible_name=observation.match_identity_hints.visible_name,
        )
        return None
    if stage_only_review_soft_accept:
        warnings.append("stage_only_draft_review_soft_accepted")

    return {
        "raw_draft": raw_draft,
        "draft": draft,
        "disclosure_source": disclosure_source,
        "used_user_material_ids": used_material_ids,
        "evidence": evidence,
        "generation_binding": generation_binding,
        "review": review,
        "stage_only_review_soft_accept": stage_only_review_soft_accept,
    }


def _prepare_generation_binding(
    repository: Any,
    raw_draft: dict[str, Any],
    evidence: Any,
    *,
    authorization: dict[str, Any],
    standalone_draft_review: Any,
    state: dict[str, Any],
    scan_requests: list[dict[str, Any]],
    warnings: list[str],
    candidate_key: str,
    match_id: str,
    visible_name: str | None,
) -> dict[str, Any] | None:
    stage_only_generation_soft_accept = _stage_only_generation_soft_accept_allowed(
        raw_draft,
        authorization=authorization,
        standalone_draft_review=standalone_draft_review,
    )
    generation_contract_reason = _host_supplied_generation_contract_block_reason(
        raw_draft,
        allow_stage_only_soft_accept=stage_only_generation_soft_accept,
    )
    if generation_contract_reason is not None:
        _request_draft_revision(
            state=state,
            scan_requests=scan_requests,
            warnings=warnings,
            candidate_key=candidate_key,
            match_id=match_id,
            visible_name=visible_name,
            reason=generation_contract_reason,
            extra_warning="draft_generation_required",
        )
        return None

    generation_binding = _host_supplied_generation_binding(
        repository.root,
        evidence_id=evidence.evidence_id,
        context_pack=evidence.context_pack,
        draft_payload=raw_draft,
        created_at=repository._now(),
        allow_stage_only_soft_accept=stage_only_generation_soft_accept,
    )
    self_review_probability = int(generation_binding["draft_self_review_summary"]["ai_or_weird_probability"])
    if self_review_probability > 40 and not stage_only_generation_soft_accept:
        _request_draft_revision(
            state=state,
            scan_requests=scan_requests,
            warnings=warnings,
            candidate_key=candidate_key,
            match_id=match_id,
            visible_name=visible_name,
            reason="draft_self_review_probability_high",
            extra_warning="draft_revision_required",
        )
        return None
    if self_review_probability > 40:
        warnings.append("stage_only_draft_self_review_soft_accepted")
    return generation_binding


def _request_blocked_review_revision(
    review: Any,
    *,
    state: dict[str, Any],
    scan_requests: list[dict[str, Any]],
    warnings: list[str],
    candidate_key: str,
    match_id: str,
    visible_name: str | None,
) -> None:
    from dating_boost.core.automation_send_revision import (
        _append_draft_revision_request,
        _mark_draft_revision_required,
    )

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
        visible_name=visible_name,
        reason=review.primary_reason,
    )
