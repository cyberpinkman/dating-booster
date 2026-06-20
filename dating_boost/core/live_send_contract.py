from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.draft_generation_audit import DraftGenerationAuditRepository
from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
from dating_boost.core.production_store import ProductionDataStore


def managed_live_send_guidance(reason: str | None = None) -> dict[str, Any]:
    """Machine-readable recovery contract for host agents handling live sends."""
    next_host_action = live_send_next_host_action(reason)
    return {
        "schema_version": 1,
        "next_host_action": next_host_action,
        "primary_path": "managed_session",
        "executor_path": "host_loop",
        "direct_harness_scope": "executor_internal_only",
        "allowed_action_request_sources": [
            "operator next send_message work item",
            "automation session step send_message work item",
            "confirmed confirmation flow with confirmation_payload_hash and confirmation_precondition_hash",
        ],
        "forbidden_actions": [
            "do_not_handcraft_action_request_json",
            "do_not_copy_placeholder_action_request_json",
            "do_not_add_confirmation_id_without_confirmation_hashes",
            "do_not_call_direct_harness_send_as_managed_shortcut",
            "do_not_use_host_tool_approval_as_send_authorization",
            "do_not_direct_type_non_ascii_or_cjk_payload_text",
            "do_not_fallback_to_computer_use_typing_when_managed_send_channel_is_blocked",
            "do_not_prefer_stale_console_script_over_module_cli",
        ],
        "host_tool_approval_scope": "tool_execution_only_not_dating_booster_send_authorization",
        "payload_text_entry_policy": {
            "preferred": ["clipboard_paste", "accessibility_set_text_when_supported"],
            "direct_keystroke_payload_allowed": "printable_ascii_only_after_verified_staging_fallback",
            "direct_keystroke_payload_forbidden": ["cjk", "non_ascii", "emoji", "multiline"],
            "blocked_reason_for_cjk": "cjk_direct_type_not_supported",
            "verification_required": "exact_staged_text_before_submit_and_fresh_post_action_evidence",
        },
        "preferred_cli": "python3 -m dating_boost.cli",
        "preferred_host_loop_cli": "python3 -m dating_boost.host_loop",
        "canonical_commands": {
            "capabilities": "python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost",
            "readiness": "python3 -m dating_boost.cli user readiness --data-dir .local/dating-boost --mode autonomous --json",
            "managed_start_live": (
                "python3 -m dating_boost.cli managed-session start --app-id <app_id> --data-dir .local/dating-boost "
                "--authorization auth.json --goal goal.json --availability availability.json "
                "--send-mode live --managed-gui-send --json"
            ),
            "managed_run": "python3 -m dating_boost.cli managed-session run --data-dir .local/dating-boost --wait --json",
            "host_loop_live": (
                "python3 -m dating_boost.host_loop run --data-dir .local/dating-boost --authorization auth.json "
                "--goal goal.json --availability availability.json --app-id <app_id> "
                "--send-mode live --managed-gui-send --work-dir .local/dating-boost-host-loop --json"
            ),
            "host_loop_resume": (
                "python3 -m dating_boost.host_loop resume --data-dir .local/dating-boost "
                "--work-dir .local/dating-boost-host-loop --json"
            ),
            "operator_next": "python3 -m dating_boost.cli operator next --data-dir .local/dating-boost",
            "automation_step": "python3 -m dating_boost.cli automation session step --data-dir .local/dating-boost --scan-batch scan_batch.json",
            "confirmation_validate": (
                "python3 -m dating_boost.cli confirmation validate --data-dir .local/dating-boost "
                "--confirmation-id <confirmation_id> --action send_message "
                "--target-match-id <match_id> --payload-json payload.json --precondition-json precondition.json --json"
            ),
        },
        "console_commands": {
            "capabilities": "dating-boost capabilities --json --data-dir .local/dating-boost",
            "managed_run": "dating-boost managed-session run --data-dir .local/dating-boost --wait --json",
            "host_loop_live": (
                "dating-boost-host-loop run --data-dir .local/dating-boost --authorization auth.json "
                "--goal goal.json --availability availability.json --app-id <app_id> "
                "--send-mode live --managed-gui-send --work-dir .local/dating-boost-host-loop --json"
            ),
        },
        "recovery_commands": _live_send_recovery_commands(next_host_action),
    }


def live_send_next_host_action(reason: str | None) -> str:
    if reason is None:
        return "ready"
    if reason.startswith("authorization_") or reason == "live_send_authorization_required":
        return "provide_explicit_live_send_authorization"
    if reason == "confirmation_hashes_required":
        return "use_confirmation_validate_hashes_or_operator_work_item"
    if reason in {
        "action_request_required_for_live_send",
        "confirmation_contract_required",
        "planner_evidence_missing",
        "planner_alignment_not_ok",
        "conversation_stage_required",
        "conversation_move_required",
        "action_request_draft_review_required",
        "action_request_draft_review_mismatch",
        "draft_review_audit_not_found",
        "draft_review_audit_not_managed_live",
        "draft_review_audit_not_allowed",
        "draft_review_audit_payload_hash_mismatch",
        "draft_review_audit_target_missing",
        "draft_review_audit_target_mismatch",
    }:
        return "use_operator_or_managed_session_work_item"
    return "use_operator_or_managed_session_work_item"


def _live_send_recovery_commands(next_host_action: str) -> list[str]:
    if next_host_action == "provide_explicit_live_send_authorization":
        return [
            "create or update auth.json with live_send true, autonomous_send true, send_message allowed, and a valid expiry",
            "rerun the python3 -m dating_boost.cli managed-session or python3 -m dating_boost.host_loop command with --authorization auth.json",
        ]
    if next_host_action == "use_confirmation_validate_hashes_or_operator_work_item":
        return [
            "prefer python3 -m dating_boost.cli managed-session run --data-dir .local/dating-boost --wait --json",
            "or execute the send_message work item returned by python3 -m dating_boost.cli operator next",
            "or run python3 -m dating_boost.cli confirmation validate and copy its payload_hash/precondition_hash into the existing confirmed request",
        ]
    return [
        "prefer python3 -m dating_boost.cli managed-session run --data-dir .local/dating-boost --wait --json",
        "or run python3 -m dating_boost.host_loop run/resume with --send-mode live --managed-gui-send",
        "do not create action_request.json by hand",
    ]


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

    expected_hash, payload_reason = _expected_action_payload_hash(action_request, draft_text)
    if payload_reason is not None:
        return payload_reason
    if action_request.get("payload_hash") != expected_hash:
        return "action_request_payload_hash_mismatch"
    if action_request.get("requires_post_action_verification") is not True:
        return "action_request_requires_post_action_verification"

    policy = action_request.get("policy")
    if not isinstance(policy, dict) or policy.get("allowed") is not True:
        return "action_request_policy_not_allowed"
    draft_review_id = _stripped_or_none(action_request.get("draft_review_id"))
    if draft_review_id is None:
        return "action_request_draft_review_required"
    if _stripped_or_none(policy.get("draft_review_id")) != draft_review_id:
        return "action_request_draft_review_mismatch"

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

    planner_reason = _planner_evidence_block_reason(action_request)
    if planner_reason is not None:
        return planner_reason
    if data_dir is not None:
        draft_review_reason = DraftReviewAuditRepository(data_dir).managed_send_block_reason(
            draft_review_id,
            payload_hash=expected_hash,
            target_match_id=target_match_id,
        )
        if draft_review_reason is not None:
            return draft_review_reason
        draft_generation_reason = _draft_generation_binding_block_reason(action_request, data_dir=data_dir)
        if draft_generation_reason is not None:
            return draft_generation_reason
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


def _planner_evidence_block_reason(action_request: dict[str, Any]) -> str | None:
    if action_request.get("planner_alignment") != "ok":
        return "action_request_planner_alignment_required"
    if not _non_empty(action_request.get("conversation_stage")) or not _non_empty(
        action_request.get("conversation_move")
    ):
        return "action_request_planner_context_required"
    return None


def _draft_generation_binding_block_reason(action_request: dict[str, Any], *, data_dir: Path) -> str | None:
    generation_id = _stripped_or_none(action_request.get("draft_generation_id"))
    evidence_id = _stripped_or_none(action_request.get("draft_evidence_id"))
    if generation_id is None:
        return "action_request_draft_generation_required"
    if evidence_id is None:
        return "action_request_draft_evidence_required"
    if _stripped_or_none(action_request.get("latest_turn_id")) is None:
        return "action_request_latest_turn_required"
    if not isinstance(action_request.get("conversation_thread_revision"), int):
        return "action_request_conversation_thread_required"
    self_review = action_request.get("draft_self_review_summary")
    if not isinstance(self_review, dict):
        return "action_request_draft_self_review_required"
    probability = self_review.get("ai_or_weird_probability")
    if not isinstance(probability, int) or isinstance(probability, bool) or probability < 0 or probability > 100:
        return "action_request_draft_self_review_invalid"
    if probability > 40:
        return "action_request_draft_self_review_not_passed"
    return DraftGenerationAuditRepository(data_dir).generation_block_reason(
        generation_id,
        evidence_id=evidence_id,
    )


def _expected_action_payload_hash(action_request: dict[str, Any], draft_text: str) -> tuple[str, str | None]:
    if action_request.get("payload_format") != "message_sequence":
        return hashlib.sha256(draft_text.encode("utf-8")).hexdigest(), None
    raw_messages = action_request.get("payload_messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return "", "action_request_payload_messages_required"
    texts: list[str] = []
    for expected_index, item in enumerate(raw_messages, start=1):
        if not isinstance(item, dict):
            return "", "action_request_payload_messages_invalid"
        if item.get("index") != expected_index:
            return "", "action_request_payload_messages_invalid"
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            return "", "action_request_payload_messages_invalid"
        if item.get("message_hash") != hashlib.sha256(text.encode("utf-8")).hexdigest():
            return "", "action_request_payload_message_hash_mismatch"
        if item.get("character_count") != len(text):
            return "", "action_request_payload_messages_invalid"
        texts.append(text)
    joined = "\n".join(texts)
    if action_request.get("payload_text") not in {None, joined}:
        return "", "action_request_payload_text_mismatch"
    if draft_text != joined:
        return "", "action_request_payload_text_mismatch"
    payload = {"payload_format": "message_sequence", "messages": texts}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest(), None


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

    binding_target = _stripped_or_none(target_binding.get("target_match_id"))
    if binding_target is None:
        return "action_request_target_binding_target_required"
    if binding_target != target_match_id:
        return "action_request_target_binding_mismatch"

    binding_candidate = _stripped_or_none(target_binding.get("candidate_key"))
    request_candidate = _stripped_or_none(action_request.get("candidate_key"))
    if binding_candidate is not None and request_candidate is not None and binding_candidate != request_candidate:
        return "action_request_target_binding_mismatch"
    try:
        policy = _target_binding_policy(app_id)
    except Exception:
        return "target_binding_policy_unavailable"
    has_text_marker = _target_binding_text_marker_present(target_binding)
    has_allowed_structural_evidence = _target_binding_allowed_structural_evidence_present(target_binding, policy)
    if not has_text_marker and not has_allowed_structural_evidence:
        return "action_request_target_binding_required"
    has_specific_text_marker = _target_binding_specific_marker_present(
        target_binding,
        generic_marker_blacklist=policy.get("generic_marker_blacklist"),
    )
    if policy.get("requires_target_specific_marker") is True and not (
        has_specific_text_marker or has_allowed_structural_evidence
    ):
        return "action_request_target_binding_not_target_specific"
    return None


def bumble_target_binding_specific_marker_present(target_binding: dict[str, Any]) -> bool:
    return target_binding_specific_marker_present("bumble", target_binding)


def target_binding_specific_marker_present(app_id: str, target_binding: dict[str, Any]) -> bool:
    try:
        policy = _target_binding_policy(app_id)
    except Exception:
        return False
    return _target_binding_specific_marker_present(
        target_binding,
        generic_marker_blacklist=policy.get("generic_marker_blacklist"),
    )


def target_binding_structural_evidence_present(app_id: str, target_binding: dict[str, Any]) -> bool:
    try:
        policy = _target_binding_policy(app_id)
    except Exception:
        return False
    return _target_binding_allowed_structural_evidence_present(target_binding, policy)


def _target_binding_text_marker_present(target_binding: dict[str, Any]) -> bool:
    required_visible_text = target_binding.get("required_visible_text")
    visible_name = target_binding.get("visible_name")
    return (
        isinstance(required_visible_text, list)
        and any(isinstance(item, str) and item.strip() for item in required_visible_text)
    ) or _non_empty(visible_name)


def _target_binding_specific_marker_present(
    target_binding: dict[str, Any],
    *,
    generic_marker_blacklist: Any,
) -> bool:
    markers: list[str] = []
    required_visible_text = target_binding.get("required_visible_text")
    if isinstance(required_visible_text, list):
        markers.extend(str(item).strip() for item in required_visible_text if str(item).strip())
    visible_name = _stripped_or_none(target_binding.get("visible_name"))
    if visible_name is not None:
        markers.append(visible_name)
    generic_marker_items = generic_marker_blacklist if isinstance(generic_marker_blacklist, list) else []
    generic_markers = {_normalize_target_binding_marker(str(item)) for item in generic_marker_items}
    return any(_target_binding_marker_is_specific(marker, generic_markers=generic_markers) for marker in markers)


def _target_binding_allowed_structural_evidence_present(
    target_binding: dict[str, Any],
    policy: dict[str, Any],
) -> bool:
    binding_type = _stripped_or_none(target_binding.get("binding_type"))
    allowed_items = policy.get("allowed_structural_binding_types")
    allowed_types = {str(item) for item in allowed_items} if isinstance(allowed_items, list) else set()
    if binding_type is None or binding_type not in allowed_types:
        return False
    if binding_type == "current_thread_visual_identity":
        thread_evidence = target_binding.get("thread_evidence")
        if not isinstance(thread_evidence, dict):
            return False
        return (
            _non_empty(target_binding.get("conversation_fingerprint"))
            and _non_empty(thread_evidence.get("observation_id"))
            and _non_empty(thread_evidence.get("screen_state"))
            and _non_empty(thread_evidence.get("latest_inbound_fingerprint"))
            and _non_empty(thread_evidence.get("visual_anchor_hash"))
        )
    selection_evidence = target_binding.get("selection_evidence")
    if not isinstance(selection_evidence, dict):
        return False
    if not _positive_int(selection_evidence.get("row_index")):
        return False
    required_strings = ("source_state", "opened_state", "open_action")
    return all(_non_empty(selection_evidence.get(key)) for key in required_strings)


def _target_binding_marker_is_specific(marker: str, *, generic_markers: set[str]) -> bool:
    normalized = _normalize_target_binding_marker(marker)
    if not normalized:
        return False
    if normalized in generic_markers:
        return False
    return len(normalized) >= 2


def _normalize_target_binding_marker(marker: str) -> str:
    stripped = marker.strip().lower().strip(" .,:;!?()[]{}<>，。！？（）【】")
    return " ".join(stripped.split())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _target_binding_policy(app_id: str) -> dict[str, Any]:
    from dating_boost.apps.registry import target_binding_policy

    return target_binding_policy(app_id)


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
