from __future__ import annotations

from typing import Any


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
