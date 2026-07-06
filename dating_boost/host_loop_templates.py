from __future__ import annotations

from dating_boost.host_loop_common import (
    annotations, argparse, hashlib, json,
    os, shutil, subprocess, sys,
    time, Path, Any, supported_app_ids,
    UserMemoryRepository, target_binding_structural_evidence_present, validate_live_send_contract, ManagedGuiSendError,
    ManagedGuiSendRunner, _managed_gui_send_required_evidence, _validate_managed_sequence_visual_confirmation, _work_item_payload_text,
    DEFAULT_MESSAGE_LIST_SCAN_BOUNDARY, OperatorRepository, ProductionDataStore, RELATIONSHIP_PROGRESS_NEXT_ACTION,
    build_relationship_progress_report, RuntimeScopeRepository, SafetyRepository, SupportLogRepository,
    ProfileObservation, ROOT, DEFAULT_DATA_DIR, DEFAULT_FIXTURE_NOW,
    REPORT_FINAL_STATUSES, MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE, IPHONE_MIRRORING_STRUCTURAL_BINDING_APP_IDS, HostLoopError,
    HostLoopCommandError,
)

def _message_list_template(work_item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    return {
        "schema_version": 1,
        "observation_type": "message_list",
        "session_id": _session_hint(work_item),
        "app_id": app_id,
        "captured_at": "TODO_ISO_TIMESTAMP",
        "scan_cursor": work_item.get("scan_cursor") or {"current": None, "next": None, "exhausted": False},
        "page_index": None,
        "visible_range": {"start": None, "end": None},
        "entries_observed_count": 0,
        "scan_budget": int(work_item.get("thread_budget_remaining") or 5),
        "screenshot_ref": "",
        "provenance": {
            "author": "host_agent",
            "evidence": _message_list_evidence(profile),
        },
        "message_list_snapshot": {
            "entries": [
                {
                    "candidate_key": "visible_name_row_1_latest_preview_hash",
                    "visible_name": "TODO",
                    "latest_preview": "TODO",
                    "latest_preview_hash": "TODO_STABLE_HASH",
                    "timestamp_cue": "TODO",
                    "last_activity_at": "",
                    "days_since_last_activity": None,
                    "freshness_bucket": "fresh|within_week|historical",
                    "unread_cue": "present|absent",
                    "candidate_type": "continuation_candidate|open_chat_candidate|new_match_candidate",
                    "position": 1,
                    "identity_confidence": "medium",
                    "identity_evidence": "Visible row, stable name, and preview.",
                    "match_identity_hints": {
                        "visible_name": "TODO",
                        "profile_cues": [],
                        "conversation_fingerprint": "TODO",
                    },
                    "evidence": f"Visible {display_name} row.",
                }
            ]
        },
    }


def _thread_template(work_item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    app_id = str(profile.get("app_id") or "unknown")
    candidate_key = str(work_item.get("candidate_key") or "TODO")
    return {
        "schema_version": 1,
        "observation_type": "thread",
        "candidate_key": candidate_key,
        "identity_confidence": "medium",
        "identity_evidence": "Visible chat header matches the selected message-list row.",
        "turn_boundary_evidence": {
            "latest_user_outbound_text": "",
            "latest_user_outbound_index": None,
            "latest_inbound_after_user": [],
        },
        "screenshot_ref": "",
        "assessment": {
            "schema_version": 1,
            "latest_match_message": "TODO",
            "latest_inbound_fingerprint": "TODO_STABLE_INBOUND_FINGERPRINT",
            "reply_window_status": "open",
            "continuation_opportunity": "yes|no|unknown",
            "appointment_stage": "none|soft_probe|details_requested|handoff",
            "recommended_next": "reply|nudge_later|wait|handoff",
            "confidence": "low|medium|high",
            "evidence": "TODO",
            "risk_flags": [],
        },
        "planner_assessment": {
            "schema_version": 1,
            "latest_turn_summary": "TODO",
            "latest_turn_type": "short_answer|question|delegate|refusal|other",
            "inbound_intent": "TODO",
            "topic": {
                "current_topic": "TODO",
                "topic_state": "active|saturating|exhausted",
                "new_information": [],
                "stale_hooks": [],
            },
            "scores": {
                "engagement": 50,
                "warmth": 50,
                "curiosity": 50,
                "comfort": 50,
                "momentum": 50,
                "topic_saturation": 30,
                "logistics_readiness": 0,
                "risk": 0,
            },
            "recommended_stage": "warmup",
            "recommended_move": "answer_or_riff",
            "next_milestone": "TODO",
            "avoid_next": [],
            "soft_invite_allowed": False,
            "confidence": "low|medium|high",
            "evidence": "TODO",
        },
        "observation": {
            "observation_id": f"obs_{_safe_name(candidate_key)}_TODO",
            "source_type": "live_screenshot",
            "app_id": app_id,
            "captured_at": "TODO_ISO_TIMESTAMP",
            "page_type": "chat_thread",
            "page_confidence": "high|medium|low",
            "match_identity_hints": {
                "visible_name": "TODO",
                "profile_cues": [],
                "conversation_fingerprint": "TODO",
                "evidence": _thread_identity_evidence(profile),
            },
            "profile_observation": {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
            },
            "conversation_observation": {
                "visible_messages": [],
                "latest_inbound_messages": [
                    {
                        "sender": "match",
                        "text": "TODO",
                        "is_after_latest_outbound": True,
                    }
                ],
                "input_state": "empty",
                "thread_cues": [],
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {
                "evidence": _thread_provenance_evidence(profile),
            },
            "raw_ref": None,
        },
        "draft": None,
    }


def _staged_verification_template(work_item: dict[str, Any]) -> dict[str, Any]:
    return _staged_verification(work_item, result_status="unknown", staged_text="")


def _staged_verification(work_item: dict[str, Any], *, result_status: str, staged_text: str | None = None) -> dict[str, Any]:
    payload_text = _work_item_payload_text(work_item)
    return {
        "schema_version": 1,
        "verification_type": "staged_text",
        "action_request_id": work_item.get("action_request_id"),
        "match_id": work_item.get("match_id"),
        "candidate_key": work_item.get("candidate_key"),
        "expected_payload_hash": work_item.get("payload_hash"),
        "expected_payload_text": payload_text,
        "result_status": result_status,
        "staged_text": payload_text if staged_text is None else staged_text,
        "evidence": {
            "verification": "Input box text was checked before send.",
            "input_method": "paste",
        },
    }


def _staged_verification_from_stage_draft(work_item: dict[str, Any], harness_payload: dict[str, Any]) -> dict[str, Any]:
    verification = _staged_verification(work_item, result_status="succeeded")
    staged_text_verification = harness_payload.get("staged_text_verification")
    if not isinstance(staged_text_verification, dict):
        staged_text_verification = {}
    screen = staged_text_verification.get("screen") if isinstance(staged_text_verification.get("screen"), dict) else {}
    screenshot_ref = str(screen.get("path") or "") if isinstance(screen, dict) else ""
    verification.update(
        {
            "stage_attempt_status": harness_payload.get("stage_attempt_status"),
            "staged_text_verified": harness_payload.get("staged_text_verified") is True,
            "staged_text_verification": staged_text_verification,
        }
    )
    if screenshot_ref:
        verification["screenshot_ref"] = screenshot_ref
    evidence = dict(verification.get("evidence") if isinstance(verification.get("evidence"), dict) else {})
    app_id = str(harness_payload.get("app_id") or work_item.get("app_id") or "dating_app")
    harness_backend = str(harness_payload.get("harness_backend") or "native_gui")
    evidence.update(
        {
            "verification": f"{app_id} {harness_backend} stage-draft verified the input box before stage-only audit.",
            "input_method": "harness_stage_draft",
            "harness_runtime": harness_payload.get("harness_runtime") or harness_backend,
            "stage_attempt_status": harness_payload.get("stage_attempt_status"),
            "staged_text_verification_status": staged_text_verification.get("status"),
            "screen_exact_text_ocr_verified": staged_text_verification.get("screen_exact_text_ocr_verified") is True,
            "exact_text_ocr_verified": staged_text_verification.get("exact_text_ocr_verified") is True,
            "exact_text_ax_verified": staged_text_verification.get("exact_text_ax_verified") is True,
        }
    )
    if screenshot_ref:
        evidence["screenshot_ref"] = screenshot_ref
    verification["evidence"] = evidence
    return verification


def _stage_result_from_verification(work_item: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    staged_text_verified = verification.get("staged_text_verified")
    evidence = {
        "verification": "Stage mode verified the payload text in the input box and did not send.",
        "sent": False,
    }
    if isinstance(verification.get("evidence"), dict):
        evidence.update(verification["evidence"])
        evidence["sent"] = False
    stage_result = {
        "schema_version": 1,
        "action_request_id": work_item.get("action_request_id"),
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "result_status": "succeeded",
        "staged_text_verified": staged_text_verified if isinstance(staged_text_verified, bool) else True,
        "staged_text_verification": verification.get("staged_text_verification") or verification,
        "evidence": evidence,
    }
    for key in ("stage_attempt_status", "screenshot_ref"):
        if verification.get(key) is not None:
            stage_result[key] = verification[key]
    return stage_result


def _action_result_template(work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_request_id": work_item.get("action_request_id"),
        "action": "send_message",
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": "",
        "result_status": "unknown",
        "evidence": {
            "verification": "Fill only after a fresh post-send observation confirms the sent bubble.",
        },
    }


def _action_result_fixture(work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_request_id": work_item.get("action_request_id"),
        "action": "send_message",
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": f"{work_item.get('pre_action_observation_id')}_sent",
        "result_status": "succeeded",
        "evidence": {
            "post_send_visible_text": work_item.get("payload_text"),
            "staged_text_verified": True,
        },
    }


def _validate_staged_verification(payload: dict[str, Any], work_item: dict[str, Any]) -> dict[str, Any]:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        return {"status": "blocked", "reason": "staged verification action_request_id mismatch"}
    if payload.get("expected_payload_hash") != work_item.get("payload_hash"):
        return {"status": "blocked", "reason": "staged verification payload_hash mismatch"}
    if payload.get("result_status") != "succeeded":
        return {"status": "blocked", "reason": "staged text was not verified as succeeded"}
    if payload.get("staged_text") != _work_item_payload_text(work_item):
        return {"status": "blocked", "reason": "staged text does not match payload_text"}
    result = {
        "status": "ok",
        "action_request_id": payload.get("action_request_id"),
        "payload_hash": payload.get("expected_payload_hash"),
    }
    for key in (
        "evidence",
        "stage_attempt_status",
        "staged_text_verified",
        "staged_text_verification",
        "screenshot_ref",
    ):
        if key in payload:
            result[key] = payload[key]
    return result


def _validate_action_result(payload: dict[str, Any], work_item: dict[str, Any]) -> None:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        raise HostLoopError("action_result action_request_id mismatch")
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        raise HostLoopError("action_result payload_hash mismatch")
    if payload.get("target_match_id") != work_item.get("match_id"):
        raise HostLoopError("action_result target_match_id mismatch")


def _session_hint(work_item: dict[str, Any]) -> str:
    value = str(work_item.get("work_item_id") or "host_loop")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"session_host_loop_{digest}"


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "unknown"


def _same_work_item(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_id = left.get("work_item_id")
    right_id = right.get("work_item_id")
    if left_id and right_id:
        return left_id == right_id
    left_action = left.get("action_request_id")
    right_action = right.get("action_request_id")
    return bool(left_action and right_action and left_action == right_action)


def _template_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.template{path.suffix}")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HostLoopError(f"{key} is required")
    return value


def _message_list_evidence(profile: dict[str, Any]) -> str:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    backend = _native_backend(profile)
    if backend == "iphone_mirroring_macos":
        return f"{display_name} message list observed through iPhone Mirroring."
    if backend == "macos_wechat_desktop":
        return f"{display_name} chat list observed from the macOS desktop window."
    return f"{display_name} visible message list observed by the host agent."


def _thread_identity_evidence(profile: dict[str, Any]) -> str:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    return f"Visible {display_name} chat header and messages."


def _thread_provenance_evidence(profile: dict[str, Any]) -> str:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    backend = _native_backend(profile)
    if backend == "iphone_mirroring_macos":
        return f"Host-agent screen read from iPhone Mirroring for {display_name}."
    if backend == "macos_wechat_desktop":
        return f"Host-agent screen read from the macOS {display_name} desktop window."
    return f"Host-agent screen read from visible {display_name} UI."


def _native_backend(profile: dict[str, Any]) -> str:
    native = profile.get("native_gui_harness")
    if not isinstance(native, dict):
        return ""
    backend = native.get("backend")
    return str(backend) if backend is not None else ""


__all__ = [
    'annotations', 'argparse', 'hashlib', 'json',
    'os', 'shutil', 'subprocess', 'sys',
    'time', 'Path', 'Any', 'supported_app_ids',
    'UserMemoryRepository', 'target_binding_structural_evidence_present', 'validate_live_send_contract', 'ManagedGuiSendError',
    'ManagedGuiSendRunner', '_managed_gui_send_required_evidence', '_validate_managed_sequence_visual_confirmation', '_work_item_payload_text',
    'DEFAULT_MESSAGE_LIST_SCAN_BOUNDARY', 'OperatorRepository', 'ProductionDataStore', 'RELATIONSHIP_PROGRESS_NEXT_ACTION',
    'build_relationship_progress_report', 'RuntimeScopeRepository', 'SafetyRepository', 'SupportLogRepository',
    'ProfileObservation', 'ROOT', 'DEFAULT_DATA_DIR', 'DEFAULT_FIXTURE_NOW',
    'REPORT_FINAL_STATUSES', 'MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE', 'IPHONE_MIRRORING_STRUCTURAL_BINDING_APP_IDS', 'HostLoopError',
    'HostLoopCommandError', '_message_list_template', '_thread_template', '_staged_verification_template',
    '_staged_verification', '_staged_verification_from_stage_draft', '_stage_result_from_verification', '_action_result_template',
    '_action_result_fixture', '_validate_staged_verification', '_validate_action_result', '_session_hint',
    '_safe_name', '_same_work_item', '_template_path', '_required_string',
    '_message_list_evidence', '_thread_identity_evidence', '_thread_provenance_evidence', '_native_backend',
]
