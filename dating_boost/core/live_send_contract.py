from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.production_store import ProductionDataStore


BUMBLE_GENERIC_TARGET_BINDING_MARKERS = {
    "aa",
    "gif",
    "hi",
    "hello",
    "hey",
    "opening move",
    "send",
    "your turn",
    "reply time",
    "发送",
    "回复",
    "回复时间",
    "小时后失效",
    "轮到您了",
    "该您给对方回复了",
    "聊天",
    "配对列表",
    "聊天（最近）",
}


def validate_live_send_contract(
    authorization: dict[str, Any],
    action_request: dict[str, Any],
    *,
    app_id: str,
    draft_text: str,
    data_dir: Path | None,
    now: str | None = None,
) -> str | None:
    auth_reason = live_send_authorization_block_reason(authorization, app_id=app_id, now=now)
    if auth_reason is not None:
        return auth_reason
    return live_send_action_request_block_reason(
        action_request,
        draft_text,
        authorization=authorization,
        app_id=app_id,
        data_dir=data_dir,
        now=now,
    )


def live_send_authorization_block_reason(
    authorization: dict[str, Any],
    *,
    app_id: str,
    now: str | None = None,
) -> str | None:
    if authorization.get("scope") != "send_chat_messages":
        return "authorization_scope_not_send_chat_messages"
    if authorization.get("app_id") != app_id:
        return "authorization_app_mismatch"
    if authorization.get("revoked_at"):
        return "authorization_revoked"
    expires_at = authorization.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires = _parse_iso(expires_at)
            current = _parse_iso(now or _now_iso())
            if expires <= current:
                return "authorization_expired"
        except ValueError:
            return "authorization_expired"
    else:
        return "authorization_expired"
    if authorization.get("autonomous_send") is not True:
        return "authorization_autonomous_send_disabled"
    if authorization.get("live_send") is not True:
        return "live_send_authorization_required"
    if "send_message" not in authorization.get("allowed_actions", []):
        return "authorization_action_not_allowed"
    if authorization.get("requires_post_action_verification") is not True:
        return "authorization_requires_post_action_verification"
    return None


def live_send_action_request_block_reason(
    action_request: dict[str, Any],
    draft_text: str,
    *,
    authorization: dict[str, Any],
    app_id: str,
    data_dir: Path | None,
    now: str | None = None,
) -> str | None:
    if action_request.get("action") != "send_message":
        return "action_request_not_send_message"
    if not _non_empty(action_request.get("action_request_id")):
        return "action_request_id_required"

    request_app_id = _stripped_or_none(action_request.get("app_id"))
    if request_app_id is not None and request_app_id != app_id:
        return "action_request_app_mismatch"

    expected_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
    if action_request.get("payload_hash") != expected_hash:
        return "action_request_payload_hash_mismatch"
    if action_request.get("requires_post_action_verification") is not True:
        return "action_request_requires_post_action_verification"

    policy = action_request.get("policy")
    if not isinstance(policy, dict) or policy.get("allowed") is not True:
        return "action_request_policy_not_allowed"

    target_match_id, target_reason = live_send_target_match_id(action_request)
    if target_reason is not None:
        return target_reason
    allowed_reason = _authorization_target_block_reason(authorization, target_match_id)
    if allowed_reason is not None:
        return allowed_reason

    binding_reason = _target_binding_block_reason(action_request, target_match_id, app_id=app_id)
    if binding_reason is not None:
        return binding_reason

    contract_reason = _confirmation_or_audit_binding_block_reason(
        action_request,
        authorization=authorization,
        target_match_id=target_match_id,
        payload_hash=expected_hash,
        data_dir=data_dir,
        now=now,
    )
    if contract_reason is not None:
        return contract_reason
    return None


def live_send_target_match_id(action_request: dict[str, Any]) -> tuple[str, str | None]:
    match_id = _stripped_or_none(action_request.get("match_id"))
    target_match_id = _stripped_or_none(action_request.get("target_match_id"))
    if match_id and target_match_id and match_id != target_match_id:
        return target_match_id, "action_request_target_match_id_mismatch"
    target = target_match_id or match_id
    if target is None:
        return "", "action_request_target_match_id_required"
    return target, None


def _authorization_target_block_reason(authorization: dict[str, Any], target_match_id: str) -> str | None:
    allowed_match_ids = authorization.get("allowed_match_ids")
    if isinstance(allowed_match_ids, list) and allowed_match_ids:
        allowed = {str(item) for item in allowed_match_ids}
        if target_match_id not in allowed:
            return "authorization_match_not_allowed"
    return None


def _target_binding_block_reason(action_request: dict[str, Any], target_match_id: str, *, app_id: str) -> str | None:
    target_binding = action_request.get("target_binding")
    if not isinstance(target_binding, dict):
        return "action_request_target_binding_required"
    required_visible_text = target_binding.get("required_visible_text")
    visible_name = target_binding.get("visible_name")
    has_required_marker = (
        isinstance(required_visible_text, list)
        and any(isinstance(item, str) and item.strip() for item in required_visible_text)
    ) or _non_empty(visible_name)
    if not has_required_marker:
        return "action_request_target_binding_required"

    binding_target = _stripped_or_none(target_binding.get("target_match_id"))
    if binding_target is None:
        return "action_request_target_binding_target_required"
    if binding_target != target_match_id:
        return "action_request_target_binding_mismatch"

    binding_candidate = _stripped_or_none(target_binding.get("candidate_key"))
    request_candidate = _stripped_or_none(action_request.get("candidate_key"))
    if binding_candidate is not None and request_candidate is not None and binding_candidate != request_candidate:
        return "action_request_target_binding_mismatch"
    if app_id == "bumble" and not bumble_target_binding_specific_marker_present(target_binding):
        return "action_request_target_binding_not_target_specific"
    return None


def bumble_target_binding_specific_marker_present(target_binding: dict[str, Any]) -> bool:
    markers: list[str] = []
    required_visible_text = target_binding.get("required_visible_text")
    if isinstance(required_visible_text, list):
        markers.extend(str(item).strip() for item in required_visible_text if str(item).strip())
    visible_name = _stripped_or_none(target_binding.get("visible_name"))
    if visible_name is not None:
        markers.append(visible_name)
    return any(_bumble_marker_is_target_specific(marker) for marker in markers)


def _bumble_marker_is_target_specific(marker: str) -> bool:
    normalized = _normalize_bumble_marker(marker)
    if not normalized:
        return False
    if normalized in BUMBLE_GENERIC_TARGET_BINDING_MARKERS:
        return False
    return len(normalized) >= 2


def _normalize_bumble_marker(marker: str) -> str:
    stripped = marker.strip().lower().strip(" .,:;!?()[]{}<>，。！？（）【】")
    return " ".join(stripped.split())


def _confirmation_or_audit_binding_block_reason(
    action_request: dict[str, Any],
    *,
    authorization: dict[str, Any],
    target_match_id: str,
    payload_hash: str,
    data_dir: Path | None,
    now: str | None,
) -> str | None:
    precondition_hash = _stripped_or_none(action_request.get("precondition_hash"))
    confirmation_id = _stripped_or_none(action_request.get("confirmation_id"))
    if confirmation_id is not None:
        if data_dir is None:
            return "data_dir_required_for_confirmation_validation"
        confirmation_payload_hash = _stripped_or_none(action_request.get("confirmation_payload_hash"))
        confirmation_precondition_hash = _stripped_or_none(action_request.get("confirmation_precondition_hash"))
        if confirmation_payload_hash is None or confirmation_precondition_hash is None:
            return "confirmation_hashes_required"
        validation = ProductionDataStore(data_dir).validate_confirmation_hashes(
            confirmation_id=confirmation_id,
            action="send_message",
            target_match_id=target_match_id,
            payload_hash=confirmation_payload_hash,
            precondition_hash=confirmation_precondition_hash,
            now=now,
        )
        if validation.get("status") == "ok":
            return None
        return str(validation.get("reason") or "confirmation_contract_blocked")

    if precondition_hash is None:
        return "confirmation_contract_required"
    binding = action_request.get("autonomous_audit_binding")
    if not isinstance(binding, dict):
        return "confirmation_contract_required"
    if binding.get("binding_type") != "autonomous_authorization":
        return "autonomous_audit_binding_mismatch:binding_type"

    expected_authorization_id = _stripped_or_none(authorization.get("authorization_id"))
    if expected_authorization_id is not None and binding.get("authorization_id") != expected_authorization_id:
        return "autonomous_audit_binding_mismatch:authorization_id"
    expected = {
        "action": "send_message",
        "target_match_id": target_match_id,
        "payload_hash": payload_hash,
        "precondition_hash": precondition_hash,
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            return f"autonomous_audit_binding_mismatch:{key}"
    return None


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _stripped_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
