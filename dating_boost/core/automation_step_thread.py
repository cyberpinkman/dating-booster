from __future__ import annotations

from datetime import timedelta
from typing import Any

from dating_boost.core.automation_prioritization import (
    _candidate_type_for_entry,
    _is_handoff_assessment,
)
from dating_boost.core.automation_send_gate import (
    _can_request_nudge,
    _can_request_send,
    _handoff_reason,
    _send_authorization_block_reason,
    _target_profile_ready_for_send,
)
from dating_boost.core.automation_state import (
    _draft_payload_hash,
    _new_state,
    _parse_iso_utc,
    _reserve_slot,
    _state_update,
)
from dating_boost.core.automation_step_models import _ObservedThreadContext, _ScanWindow, _StepBuffers
from dating_boost.core.planner import PlannerRepository
from dating_boost.perception.observations import AppObservation


def _handle_thread_observation_entry(
    repository: Any,
    entry: Any,
    thread_item: dict[str, Any],
    *,
    candidate_key: str,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    ledger: list[dict[str, Any]],
    buffers: _StepBuffers,
    session: dict[str, Any],
    window: _ScanWindow,
    authorization: dict[str, Any],
    now: str,
) -> None:
    buffers.processed_match_count += 1
    context = _observed_thread_context(
        repository,
        entry,
        thread_item,
        states_by_match=states_by_match,
        states_by_candidate=states_by_candidate,
        candidate_key=candidate_key,
        session_id=session["session_id"],
        window=window,
        now=now,
    )
    planner_recommendation, planner_error = _apply_planner_assessment(
        repository,
        context.state,
        observation=context.observation,
        assessment=thread_item.get("planner_assessment"),
        match_id=context.match_id,
        now=now,
    )
    if planner_error is not None:
        buffers.warnings.append("planner_assessment_invalid")
        context.state["state"] = "needs_reply"
        context.state["planner_error"] = planner_error
        _record_thread_state(states_by_match, buffers, match_id=context.match_id, state=context.state)
        return

    if _handle_thread_handoff(
        thread_item,
        planner_recommendation=planner_recommendation,
        context=context,
        candidate_key=candidate_key,
        ledger=ledger,
        buffers=buffers,
        now=now,
    ):
        _record_thread_state(states_by_match, buffers, match_id=context.match_id, state=context.state)
        return

    _apply_send_or_nudge_decision(
        repository,
        thread_item=thread_item,
        authorization=authorization,
        ingest=context.ingest,
        assessment=context.assessment,
        state=context.state,
        buffers=buffers,
        observation=context.observation,
        match_id=context.match_id,
        candidate_key=candidate_key,
        latest_fingerprint=context.latest_fingerprint,
        planner_recommendation=planner_recommendation,
        host_identity_confidence=str(thread_item.get("identity_confidence") or "medium"),
        now=now,
    )
    _record_thread_state(states_by_match, buffers, match_id=context.match_id, state=context.state)

def _observed_thread_context(
    repository: Any,
    entry: Any,
    thread_item: dict[str, Any],
    *,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    candidate_key: str,
    session_id: str,
    window: _ScanWindow,
    now: str,
) -> _ObservedThreadContext:
    observation = AppObservation.from_dict(thread_item["observation"])
    ingest = repository._store_observation(observation)
    match_id = ingest["match_id"]
    repository._extract_and_enqueue_proposals(
        match_id, observation, session_id=session_id,
        observation_id=observation.observation_id, created_at=now,
    )
    assessment = dict(thread_item.get("assessment", {}))
    latest_fingerprint = assessment.get("latest_inbound_fingerprint")
    state = _state_for_observed_thread(
        entry,
        states_by_match=states_by_match,
        states_by_candidate=states_by_candidate,
        match_id=match_id,
        candidate_key=candidate_key,
        session_id=session_id,
        timestamp=now,
    )
    _apply_observed_thread_metadata(
        state,
        entry,
        observation=observation,
        assessment=assessment,
        latest_fingerprint=latest_fingerprint,
        candidate_key=candidate_key,
        session_id=session_id,
        updated_at=_observed_thread_updated_at(window, observation),
    )
    return _ObservedThreadContext(
        observation=observation,
        ingest=ingest,
        match_id=match_id,
        assessment=assessment,
        latest_fingerprint=latest_fingerprint,
        state=state,
    )

def _record_thread_state(
    states_by_match: dict[Any, dict[str, Any]],
    buffers: _StepBuffers,
    *,
    match_id: str,
    state: dict[str, Any],
) -> None:
    states_by_match[match_id] = state
    buffers.state_updates.append(_state_update(state))

def _handle_thread_handoff(
    thread_item: dict[str, Any],
    *,
    planner_recommendation: dict[str, Any] | None,
    context: _ObservedThreadContext,
    candidate_key: str,
    ledger: list[dict[str, Any]],
    buffers: _StepBuffers,
    now: str,
) -> bool:
    if _append_planner_handoff_if_needed(
        thread_item,
        planner_recommendation=planner_recommendation,
        assessment=context.assessment,
        state=context.state,
        ledger=ledger,
        buffers=buffers,
        match_id=context.match_id,
        candidate_key=candidate_key,
        now=now,
    ):
        return True
    return _append_assessment_handoff_if_needed(
        thread_item,
        planner_recommendation=planner_recommendation,
        assessment=context.assessment,
        state=context.state,
        ledger=ledger,
        buffers=buffers,
        match_id=context.match_id,
        candidate_key=candidate_key,
        now=now,
    )

def _state_for_observed_thread(
    entry: Any,
    *,
    states_by_match: dict[Any, dict[str, Any]],
    states_by_candidate: dict[Any, dict[str, Any]],
    match_id: str,
    candidate_key: str,
    session_id: str,
    timestamp: str,
) -> dict[str, Any]:
    state = states_by_match.get(match_id)
    if state is not None:
        return state
    state = states_by_candidate.get(candidate_key)
    if state is None:
        return _new_state(
            match_id=match_id,
            candidate_key=candidate_key,
            session_id=session_id,
            timestamp=timestamp,
        )
    previous_match_id = state["match_id"]
    if previous_match_id != match_id:
        states_by_match.pop(previous_match_id, None)
        if str(previous_match_id).startswith("provisional_"):
            state["previous_provisional_match_id"] = previous_match_id
        state["match_id"] = match_id
    return state

def _apply_observed_thread_metadata(
    state: dict[str, Any],
    entry: Any,
    *,
    observation: AppObservation,
    assessment: dict[str, Any],
    latest_fingerprint: Any,
    candidate_key: str,
    session_id: str,
    updated_at: Any,
) -> None:
    state["candidate_key"] = candidate_key
    state["visible_name"] = entry.get("visible_name") or observation.match_identity_hints.visible_name
    state["last_session_id"] = session_id
    state["last_inbound_observation_id"] = observation.observation_id
    state["latest_inbound_fingerprint"] = latest_fingerprint
    state["last_preview_hash"] = entry.get("latest_preview_hash")
    state["unread_cue"] = entry.get("unread_cue")
    state["last_assessment"] = assessment
    state["updated_at"] = updated_at
    state["candidate_type"] = _candidate_type_for_entry(state, entry)
    state["seen_before"] = True

def _observed_thread_updated_at(window: _ScanWindow, observation: AppObservation) -> Any:
    if window.captured_at_present:
        return window.captured_at_value
    return observation.captured_at

def _apply_planner_assessment(
    repository: Any,
    state: dict[str, Any],
    *,
    observation: AppObservation,
    assessment: Any,
    match_id: str,
    now: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if assessment is None:
        return None, None
    try:
        active_goal = repository._active_goal_payload()
        planner_payload = PlannerRepository(repository.root).update_plan(
            match_id=match_id,
            goal_id=str(state.get("goal_id") or active_goal["goal_id"]),
            observation=observation,
            assessment=dict(assessment),
            now=now,
            goal_type=str(active_goal["goal_type"]),
        )
    except (TypeError, ValueError) as exc:
        return None, str(exc)
    goal_plan = dict(planner_payload["goal_plan"])
    planner_recommendation = dict(planner_payload["recommendation"])
    state["goal_id"] = goal_plan.get("goal_id")
    state["conversation_stage"] = goal_plan.get("stage")
    state["planner_revision"] = goal_plan.get("plan_revision")
    state["planner_recommended_move"] = goal_plan.get("recommended_move")
    state["next_milestone"] = goal_plan.get("next_milestone")
    state["question_debt"] = goal_plan.get("question_debt")
    state["self_disclosure_debt"] = goal_plan.get("self_disclosure_debt")
    state["reciprocity_balance"] = goal_plan.get("reciprocity_balance")
    state["low_investment_streak"] = goal_plan.get("low_investment_streak")
    state["match_curiosity_about_user"] = goal_plan.get("match_curiosity_about_user")
    state["topic_exit_pressure"] = goal_plan.get("topic_exit_pressure")
    if goal_plan.get("recommended_move") == "slow_down_wait":
        state["pause_reason"] = "low_reciprocity"
    return planner_recommendation, None

def _append_planner_handoff_if_needed(
    thread_item: dict[str, Any],
    *,
    planner_recommendation: dict[str, Any] | None,
    assessment: dict[str, Any],
    state: dict[str, Any],
    ledger: list[dict[str, Any]],
    buffers: _StepBuffers,
    match_id: str,
    candidate_key: str,
    now: str,
) -> bool:
    if not planner_recommendation or not planner_recommendation.get("requires_handoff"):
        return False
    handoff_reason = str(planner_recommendation.get("handoff_reason") or "appointment_details_requested")
    slot_conflict = _reserve_appointment_slot_if_present(
        thread_item,
        state=state,
        ledger=ledger,
        match_id=match_id,
        candidate_key=candidate_key,
        now=now,
    )
    state["state"] = "appointment_handoff"
    state["handoff_reason"] = handoff_reason
    buffers.handoffs.append(
        {
            "match_id": match_id,
            "candidate_key": candidate_key,
            "reason": handoff_reason,
            "slot_conflict": slot_conflict,
            "assessment": assessment,
            "planner_stage": planner_recommendation.get("conversation_stage"),
            "planner_revision": planner_recommendation.get("planner_revision"),
            "suggested_user_decision": "选择具体日期、时间段、区域",
        }
    )
    return True

def _append_assessment_handoff_if_needed(
    thread_item: dict[str, Any],
    *,
    planner_recommendation: dict[str, Any] | None,
    assessment: dict[str, Any],
    state: dict[str, Any],
    ledger: list[dict[str, Any]],
    buffers: _StepBuffers,
    match_id: str,
    candidate_key: str,
    now: str,
) -> bool:
    if not _is_handoff_assessment(assessment):
        return False
    handoff_reason = _handoff_reason(assessment)
    slot_conflict = _reserve_appointment_slot_if_present(
        thread_item,
        state=state,
        ledger=ledger,
        match_id=match_id,
        candidate_key=candidate_key,
        now=now,
    )
    state["state"] = "appointment_handoff"
    state["handoff_reason"] = handoff_reason
    buffers.handoffs.append(
        {
            "match_id": match_id,
            "candidate_key": candidate_key,
            "reason": handoff_reason,
            "slot_conflict": slot_conflict,
            "assessment": assessment,
            "planner_stage": planner_recommendation.get("conversation_stage") if planner_recommendation else None,
            "planner_revision": planner_recommendation.get("planner_revision") if planner_recommendation else None,
        }
    )
    return True

def _reserve_appointment_slot_if_present(
    thread_item: dict[str, Any],
    *,
    state: dict[str, Any],
    ledger: list[dict[str, Any]],
    match_id: str,
    candidate_key: str,
    now: str,
) -> bool:
    if not thread_item.get("appointment_slot"):
        return False
    slot, slot_conflict = _reserve_slot(
        ledger,
        match_id=match_id,
        candidate_key=candidate_key,
        slot_payload=dict(thread_item["appointment_slot"]),
        timestamp=now,
    )
    state["appointment_slot_id"] = slot["slot_id"]
    return slot_conflict

def _apply_send_or_nudge_decision(
    repository: Any,
    *,
    thread_item: dict[str, Any],
    authorization: dict[str, Any],
    ingest: dict[str, Any],
    assessment: dict[str, Any],
    state: dict[str, Any],
    buffers: _StepBuffers,
    observation: AppObservation,
    match_id: str,
    candidate_key: str,
    latest_fingerprint: Any,
    planner_recommendation: dict[str, Any] | None,
    host_identity_confidence: str,
    now: str,
) -> None:
    draft_payload = thread_item.get("draft")
    if _apply_send_precondition_block(
        authorization=authorization,
        assessment=assessment,
        state=state,
        buffers=buffers,
        observation=observation,
        match_id=match_id,
        planner_recommendation=planner_recommendation,
        host_identity_confidence=host_identity_confidence,
        draft_payload=draft_payload,
        now=now,
    ):
        return
    if _can_request_send(
        authorization,
        ingest,
        assessment,
        state,
        draft_payload,
        match_id=match_id,
        app_id=observation.app_id,
        now=now,
    ):
        _queue_send_request(
            repository,
            buffers=buffers,
            state=state,
            match_id=match_id,
            candidate_key=candidate_key,
            observation=observation,
            draft_payload=draft_payload,
            latest_fingerprint=latest_fingerprint,
            is_nudge=False,
            authorization=authorization,
            planner_recommendation=planner_recommendation,
            thread_item=thread_item,
        )
    elif assessment.get("recommended_next") == "reply":
        state["state"] = "needs_reply"
    elif assessment.get("recommended_next") == "nudge_later":
        _apply_nudge_decision(
            repository,
            thread_item=thread_item,
            authorization=authorization,
            ingest=ingest,
            assessment=assessment,
            state=state,
            buffers=buffers,
            observation=observation,
            match_id=match_id,
            candidate_key=candidate_key,
            latest_fingerprint=latest_fingerprint,
            planner_recommendation=planner_recommendation,
            host_identity_confidence=host_identity_confidence,
            draft_payload=draft_payload,
            now=now,
        )
    else:
        state["state"] = "sent_waiting"

def _apply_send_precondition_block(
    *,
    authorization: dict[str, Any],
    assessment: dict[str, Any],
    state: dict[str, Any],
    buffers: _StepBuffers,
    observation: AppObservation,
    match_id: str,
    planner_recommendation: dict[str, Any] | None,
    host_identity_confidence: str,
    draft_payload: Any,
    now: str,
) -> bool:
    if planner_recommendation is None and draft_payload and assessment.get("recommended_next") in {"reply", "nudge_later"}:
        state["state"] = "needs_reply"
        buffers.warnings.append("planner_assessment_required")
        return True
    if planner_recommendation and not planner_recommendation.get("auto_send_allowed"):
        _apply_planner_send_block(state, planner_recommendation=planner_recommendation, buffers=buffers)
        return True
    if host_identity_confidence == "low":
        state["state"] = "needs_reply"
        buffers.warnings.append("low_identity_confidence")
        return True
    if draft_payload and not _target_profile_ready_for_send(observation):
        state["state"] = "needs_target_profile"
        buffers.warnings.append("target_profile_required")
        return True
    if draft_payload and (
        auth_block := _send_authorization_block_reason(
            authorization,
            match_id=match_id,
            app_id=observation.app_id,
            now=now,
        )
    ):
        state["state"] = "needs_reply"
        buffers.warnings.append(auth_block)
        return True
    return False

def _apply_planner_send_block(
    state: dict[str, Any],
    *,
    planner_recommendation: dict[str, Any],
    buffers: _StepBuffers,
) -> None:
    if planner_recommendation.get("recommended_move") in {"wait", "slow_down_wait"}:
        state["state"] = "waiting_for_match"
        state["pause_reason"] = "low_reciprocity" if planner_recommendation.get("recommended_move") == "slow_down_wait" else "planner_wait"
    else:
        state["state"] = "needs_reply"
    buffers.warnings.extend(str(reason) for reason in planner_recommendation.get("block_reasons", []))

def _apply_nudge_decision(
    repository: Any,
    *,
    thread_item: dict[str, Any],
    authorization: dict[str, Any],
    ingest: dict[str, Any],
    assessment: dict[str, Any],
    state: dict[str, Any],
    buffers: _StepBuffers,
    observation: AppObservation,
    match_id: str,
    candidate_key: str,
    latest_fingerprint: Any,
    planner_recommendation: dict[str, Any] | None,
    host_identity_confidence: str,
    draft_payload: Any,
    now: str,
) -> None:
    if host_identity_confidence == "low":
        state["state"] = "needs_reply"
        buffers.warnings.append("low_identity_confidence")
    elif draft_payload and (
        auth_block := _send_authorization_block_reason(
            authorization,
            match_id=match_id,
            app_id=observation.app_id,
            now=now,
        )
    ):
        state["state"] = "nudge_scheduled" if auth_block == "authorization_quiet_hours" else "needs_reply"
        buffers.warnings.append(auth_block)
    elif _can_request_nudge(
        authorization,
        ingest,
        assessment,
        state,
        draft_payload,
        now,
        match_id=match_id,
        app_id=observation.app_id,
    ):
        _queue_send_request(
            repository,
            buffers=buffers,
            state=state,
            match_id=match_id,
            candidate_key=candidate_key,
            observation=observation,
            draft_payload=draft_payload,
            latest_fingerprint=latest_fingerprint,
            is_nudge=True,
            authorization=authorization,
            planner_recommendation=planner_recommendation,
            thread_item=thread_item,
        )
    elif state.get("last_nudged_inbound_fingerprint") == latest_fingerprint:
        if draft_payload and _draft_payload_hash(dict(draft_payload)) == state.get("last_outbound_payload_hash"):
            buffers.warnings.append("duplicate_send_request_suppressed")
        state["state"] = state.get("state") if state.get("state") == "send_requested" else "waiting_for_match"
    elif state.get("state") == "nudge_scheduled" and state.get("latest_inbound_fingerprint") == latest_fingerprint:
        state["state"] = "nudge_scheduled"
    else:
        due_at = (
            _parse_iso_utc(now) + timedelta(minutes=repository._nudge_delay_minutes)
        ).isoformat().replace("+00:00", "Z")
        state["state"] = "nudge_scheduled"
        state["next_due_at"] = due_at
        buffers.scheduled_actions.append(
            {
                "type": "nudge_later",
                "match_id": match_id,
                "candidate_key": candidate_key,
                "latest_inbound_fingerprint": latest_fingerprint,
                "due_at": due_at,
                "reason": "host_assessed_continuation_opportunity",
            }
        )

def _queue_send_request(
    repository: Any,
    *,
    buffers: _StepBuffers,
    state: dict[str, Any],
    match_id: str,
    candidate_key: str,
    observation: AppObservation,
    draft_payload: Any,
    latest_fingerprint: Any,
    is_nudge: bool,
    authorization: dict[str, Any],
    planner_recommendation: dict[str, Any] | None,
    thread_item: dict[str, Any],
) -> None:
    repository._queue_send_request(
        action_requests=buffers.action_requests,
        scan_requests=buffers.scan_requests,
        warnings=buffers.warnings,
        state=state,
        match_id=match_id,
        candidate_key=candidate_key,
        observation=observation,
        draft_payload=draft_payload,
        latest_fingerprint=latest_fingerprint,
        is_nudge=is_nudge,
        authorization=authorization,
        planner_recommendation=planner_recommendation,
        target_binding=thread_item.get("target_binding"),
        standalone_draft_review=thread_item.get("standalone_draft_review"),
    )

