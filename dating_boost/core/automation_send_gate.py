from __future__ import annotations

from datetime import datetime
from typing import Any

from dating_boost.core.automation_send_evidence import (
    _draft_from_dict,
    _host_supplied_generation_binding,
    _host_supplied_generation_contract_block_reason,
    _prepare_send_draft_contract,
    _stage_only_generation_soft_accept_allowed,
    _stage_only_review_soft_accept_allowed,
)
from dating_boost.core.automation_send_payload import _append_send_action_request
from dating_boost.core.automation_send_retry import (
    _release_active_send_request_after_failure,
    _retry_suffix_number,
    _send_retry_suffix,
    _stale_same_payload_retry_suffix,
    _state_has_active_send_request,
)
from dating_boost.core.automation_send_revision import (
    _append_draft_revision_request,
    _mark_draft_revision_required,
)
from dating_boost.core.automation_state import (
    _parse_iso_local_clock,
    _parse_iso_utc,
    _safe_id,
)
from dating_boost.perception.observations import AppObservation


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
    prepared = _prepare_send_draft_contract(
        repository,
        scan_requests=scan_requests,
        warnings=warnings,
        state=state,
        match_id=match_id,
        candidate_key=candidate_key,
        observation=observation,
        draft_payload=draft_payload,
        is_nudge=is_nudge,
        authorization=authorization,
        review_draft_fn=review_draft_fn,
        planner_recommendation=planner_recommendation,
        standalone_draft_review=standalone_draft_review,
    )
    if prepared is None:
        return
    _append_send_action_request(
        action_requests=action_requests,
        warnings=warnings,
        state=state,
        match_id=match_id,
        candidate_key=candidate_key,
        observation=observation,
        latest_fingerprint=latest_fingerprint,
        is_nudge=is_nudge,
        authorization=authorization,
        planner_recommendation=planner_recommendation,
        target_binding=target_binding,
        prepared=prepared,
    )


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
