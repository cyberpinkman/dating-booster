from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from dating_boost.core.draft_evidence import build_draft_evidence
from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
from dating_boost.core.models import Divergence, ReplyMode
from dating_boost.core.production_store import payload_digest
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import (
    draft_messages_payload_hash,
    draft_payload_messages,
    draft_strategy_evidence,
)
from dating_boost.core.user_disclosure import UserDisclosureRepository
from dating_boost.core.automation_state import (
    _parse_iso_local_clock,
    _parse_iso_utc,
    _safe_id,
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


def _queue_send_request_for_repository(
    repository: Any,
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
    review_draft_fn: Any,
    planner_recommendation: dict[str, Any] | None = None,
    target_binding: Any = None,
    standalone_draft_review: Any = None,
) -> None:
    raw_draft = dict(draft_payload)
    draft = _draft_from_dict(raw_draft)
    disclosure_repo = UserDisclosureRepository(repository.root)
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
        repository.root,
        evidence_id=evidence.evidence_id,
        context_pack=evidence.context_pack,
        draft_payload=raw_draft,
        created_at=repository._now(),
        allow_stage_only_soft_accept=stage_only_generation_soft_accept,
    )
    self_review_probability = int(generation_binding["draft_self_review_summary"]["ai_or_weird_probability"])
    if self_review_probability > 40 and not stage_only_generation_soft_accept:
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
    if self_review_probability > 40:
        warnings.append("stage_only_draft_self_review_soft_accepted")

    context_pack = evidence.context_pack
    review = review_draft_fn(
        raw_draft,
        context_pack,
        mode="managed_live",
        observation=observation,
        planner_recommendation=planner_recommendation,
        disclosure_profile=disclosure_repo.load_profile_or_none(),
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
    if stage_only_review_soft_accept:
        warnings.append("stage_only_draft_review_soft_accepted")

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
            "allowed": review.allowed_for_managed_send or stage_only_review_soft_accept,
            "allowed_for_stage": review.allowed_for_stage,
            "allowed_for_managed_send": review.allowed_for_managed_send,
            "severity": "low" if (review.allowed_for_managed_send or stage_only_review_soft_accept) else "high",
            "reason": "stage_only_draft_review_soft_accepted" if stage_only_review_soft_accept else review.primary_reason,
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


__all__ = [
    "_mark_draft_revision_required",
    "_append_draft_revision_request",
    "_draft_from_dict",
    "_target_profile_ready_for_send",
    "_can_request_send",
    "_can_request_nudge",
    "_authorization_revoked_or_expired",
    "_send_authorization_block_reason",
    "_quiet_hours_active",
    "_quiet_window_minutes",
    "_parse_clock_minutes",
    "_clock_minutes",
    "_minutes_in_window",
    "_host_supplied_generation_binding",
    "_host_supplied_generation_contract_block_reason",
    "_stage_only_generation_soft_accept_allowed",
    "_stage_only_review_soft_accept_allowed",
    "_send_retry_suffix",
    "_state_has_active_send_request",
    "_stale_same_payload_retry_suffix",
    "_retry_suffix_number",
    "_release_active_send_request_after_failure",
    "_handoff_reason",
    "_queue_send_request_for_repository",
]
