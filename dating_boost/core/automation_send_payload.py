from __future__ import annotations

from typing import Any

from dating_boost.core.automation_send_retry import (
    _retry_suffix_number,
    _send_retry_suffix,
    _stale_same_payload_retry_suffix,
    _state_has_active_send_request,
)
from dating_boost.core.production_store import payload_digest
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import (
    draft_messages_payload_hash,
    draft_payload_messages,
    draft_strategy_evidence,
)


def _append_send_action_request(
    *,
    action_requests: list[dict[str, Any]],
    warnings: list[str],
    state: dict[str, Any],
    match_id: str,
    candidate_key: str,
    observation: AppObservation,
    latest_fingerprint: str | None,
    is_nudge: bool,
    authorization: dict[str, Any],
    planner_recommendation: dict[str, Any] | None,
    target_binding: Any,
    prepared: dict[str, Any],
) -> None:
    raw_draft = prepared["raw_draft"]
    draft = prepared["draft"]
    review = prepared["review"]
    evidence = prepared["evidence"]
    generation_binding = prepared["generation_binding"]
    stage_only_review_soft_accept = bool(prepared["stage_only_review_soft_accept"])
    disclosure_source = str(prepared["disclosure_source"])
    used_material_ids = list(prepared["used_user_material_ids"])

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
    action_request = _build_send_action_request(
        raw_draft=raw_draft,
        draft=draft,
        review=review,
        evidence=evidence,
        generation_binding=generation_binding,
        action_request_id=action_request_id,
        match_id=match_id,
        candidate_key=candidate_key,
        observation=observation,
        payload_messages=payload_messages,
        payload_hash=payload_hash,
        precondition_hash=precondition_hash,
        autonomous_audit_binding=autonomous_audit_binding,
        stage_only_review_soft_accept=stage_only_review_soft_accept,
        planner_recommendation=planner_recommendation,
        disclosure_source=disclosure_source,
        used_material_ids=used_material_ids,
        state=state,
        low_investment_repair_applied=low_investment_repair_applied,
    )
    if isinstance(target_binding, dict):
        action_request["target_binding"] = dict(target_binding)
    action_requests.append(action_request)
    _apply_send_request_state(
        state,
        is_nudge=is_nudge,
        latest_fingerprint=latest_fingerprint,
        action_request_id=action_request_id,
        payload_hash=payload_hash,
        precondition_hash=precondition_hash,
        autonomous_audit_binding=autonomous_audit_binding,
        observation_id=observation.observation_id,
        disclosure_source=disclosure_source,
        used_material_ids=used_material_ids,
        low_investment_repair_applied=low_investment_repair_applied,
    )


def _build_send_action_request(
    *,
    raw_draft: dict[str, Any],
    draft: Any,
    review: Any,
    evidence: Any,
    generation_binding: dict[str, Any],
    action_request_id: str,
    match_id: str,
    candidate_key: str,
    observation: AppObservation,
    payload_messages: list[dict[str, Any]],
    payload_hash: str,
    precondition_hash: str,
    autonomous_audit_binding: dict[str, Any],
    stage_only_review_soft_accept: bool,
    planner_recommendation: dict[str, Any] | None,
    disclosure_source: str,
    used_material_ids: list[Any],
    state: dict[str, Any],
    low_investment_repair_applied: bool,
) -> dict[str, Any]:
    payload_text = "\n".join(message["text"] for message in payload_messages)
    return {
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


def _apply_send_request_state(
    state: dict[str, Any],
    *,
    is_nudge: bool,
    latest_fingerprint: str | None,
    action_request_id: str,
    payload_hash: str,
    precondition_hash: str,
    autonomous_audit_binding: dict[str, Any],
    observation_id: str,
    disclosure_source: str,
    used_material_ids: list[Any],
    low_investment_repair_applied: bool,
) -> None:
    state.pop("draft_revision_required", None)
    state.pop("draft_revision_reason", None)
    state.pop("draft_strategy_block_reason", None)
    state["state"] = "send_requested"
    state["last_action"] = "send_message"
    state["last_action_request_id"] = action_request_id
    state["last_outbound_payload_hash"] = payload_hash
    state["last_precondition_hash"] = precondition_hash
    state["last_autonomous_audit_binding"] = autonomous_audit_binding
    state["last_pre_action_observation_id"] = observation_id
    state["last_draft_id"] = f"draft_{payload_hash[:12]}"
    state.pop("last_action_result_error", None)
    state["last_disclosure_source"] = disclosure_source if disclosure_source != "none" else None
    state["used_user_material_ids"] = used_material_ids
    state["low_investment_repair_applied"] = low_investment_repair_applied
    if is_nudge:
        state["last_nudged_inbound_fingerprint"] = latest_fingerprint
        state["nudge_count_since_inbound"] = int(state.get("nudge_count_since_inbound") or 0) + 1
        state["next_due_at"] = None
