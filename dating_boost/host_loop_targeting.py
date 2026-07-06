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

from dating_boost.host_loop_templates import _safe_name

def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise HostLoopError(f"expected JSON object in {path}")
    return data


def _try_read_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _redacted_stage_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "status",
        "reason",
        "app_id",
        "action",
        "harness_backend",
        "stage_attempt_status",
        "staged_text_verified",
        "staged_text_verification",
        "next_host_action",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _target_binding_for_work_item(work_item: dict[str, Any], pending_scan_batch: dict[str, Any] | None) -> dict[str, Any]:
    existing = work_item.get("target_binding")
    if isinstance(existing, dict):
        binding = dict(existing)
    else:
        binding = {}
    binding.setdefault("target_match_id", work_item.get("match_id"))
    binding.setdefault("candidate_key", work_item.get("candidate_key"))
    required = list(binding.get("required_visible_text") or []) if isinstance(binding.get("required_visible_text"), list) else []

    thread = _thread_observation_for_work_item(work_item, pending_scan_batch)
    entry = _message_list_entry_for_work_item(work_item, pending_scan_batch)
    thread_observation = thread.get("observation") if isinstance(thread, dict) else None
    thread_hints = thread_observation.get("match_identity_hints") if isinstance(thread_observation, dict) else None
    entry_hints = entry.get("match_identity_hints") if isinstance(entry, dict) else None
    visible_name = (
        _stripped_or_none(binding.get("visible_name"))
        or _stripped_or_none(thread_hints.get("visible_name") if isinstance(thread_hints, dict) else None)
        or _stripped_or_none(entry_hints.get("visible_name") if isinstance(entry_hints, dict) else None)
        or _stripped_or_none(entry.get("visible_name") if isinstance(entry, dict) else None)
    )
    fingerprint = (
        _stripped_or_none(binding.get("conversation_fingerprint"))
        or _stripped_or_none(thread_hints.get("conversation_fingerprint") if isinstance(thread_hints, dict) else None)
        or _stripped_or_none(entry_hints.get("conversation_fingerprint") if isinstance(entry_hints, dict) else None)
    )
    if visible_name:
        binding.setdefault("visible_name", visible_name)
        required.append(str(binding.get("visible_name") or visible_name).strip())
    if fingerprint:
        binding.setdefault("conversation_fingerprint", fingerprint)
    if isinstance(entry, dict):
        for evidence_key in ("message_list_evidence", "selection_evidence"):
            evidence = entry.get(evidence_key)
            if isinstance(evidence, dict) and evidence_key not in binding:
                binding[evidence_key] = dict(evidence)
        if isinstance(binding.get("selection_evidence"), dict):
            binding.setdefault("binding_type", "chat_list_row_to_thread")
    if isinstance(thread, dict):
        thread_binding = thread.get("target_binding")
        if isinstance(thread_binding, dict):
            for key, value in thread_binding.items():
                if key == "thread_evidence" and isinstance(value, dict):
                    existing_evidence = (
                        dict(binding.get("thread_evidence"))
                        if isinstance(binding.get("thread_evidence"), dict)
                        else {}
                    )
                    existing_evidence.update(value)
                    binding["thread_evidence"] = existing_evidence
                else:
                    binding.setdefault(key, value)
        binding_app_id = _thread_observation_app_id(thread)
        if binding_app_id and not target_binding_structural_evidence_present(binding_app_id, binding):
            derived_binding = _derive_current_thread_visual_target_binding(thread, binding, app_id=binding_app_id)
            if isinstance(derived_binding, dict):
                for key, value in derived_binding.items():
                    if key == "thread_evidence" and isinstance(value, dict):
                        existing_evidence = (
                            dict(binding.get("thread_evidence"))
                            if isinstance(binding.get("thread_evidence"), dict)
                            else {}
                        )
                        existing_evidence.update(value)
                        binding["thread_evidence"] = existing_evidence
                    else:
                        binding.setdefault(key, value)

    unique_required: list[str] = []
    for item in required:
        text = str(item).strip()
        if text and text not in unique_required:
            unique_required.append(text)
    binding["required_visible_text"] = unique_required
    return binding


def _derive_tashuo_current_thread_target_binding(
    thread: dict[str, Any],
    binding: dict[str, Any],
) -> dict[str, Any] | None:
    return _derive_current_thread_visual_target_binding(thread, binding, app_id="tashuo")


def _derive_current_thread_visual_target_binding(
    thread: dict[str, Any],
    binding: dict[str, Any],
    *,
    app_id: str,
) -> dict[str, Any] | None:
    observation = thread.get("observation")
    if not isinstance(observation, dict) or observation.get("app_id") != app_id:
        return None
    if app_id not in {"tashuo", "tinder", "bumble"}:
        return None
    hints = observation.get("match_identity_hints")
    if not isinstance(hints, dict):
        hints = {}
    visible_name = _stripped_or_none(binding.get("visible_name")) or _stripped_or_none(hints.get("visible_name"))
    fingerprint = (
        _stripped_or_none(binding.get("conversation_fingerprint"))
        or _stripped_or_none(hints.get("conversation_fingerprint"))
    )
    assessment = thread.get("assessment")
    latest_inbound_fingerprint = (
        _stripped_or_none(assessment.get("latest_inbound_fingerprint"))
        if isinstance(assessment, dict)
        else None
    )
    observation_id = _stripped_or_none(observation.get("observation_id"))
    screenshot_path = _thread_screenshot_path(thread, observation)
    if app_id == "tashuo" and not visible_name:
        return None
    if not (fingerprint and latest_inbound_fingerprint and observation_id and screenshot_path):
        return None
    if not screenshot_path.exists():
        return None
    config = _current_thread_visual_anchor_config_for_app(app_id)
    if not isinstance(config, dict):
        return None
    anchor_region = dict(config["visual_anchor_region"])
    hash_for_path = config["hash_for_path"]
    anchor = hash_for_path(screenshot_path, region=anchor_region)
    visual_anchor_hash = _stripped_or_none(anchor.get("visual_anchor_hash")) if isinstance(anchor, dict) else None
    if not visual_anchor_hash:
        return None
    result: dict[str, Any] = {
        "binding_type": "current_thread_visual_identity",
        "conversation_fingerprint": fingerprint,
        "thread_evidence": {
            "observation_id": observation_id,
            "screen_state": config["screen_state"],
            "latest_inbound_fingerprint": latest_inbound_fingerprint,
            "visual_anchor_hash": visual_anchor_hash,
            "visual_anchor_region": anchor_region,
        },
    }
    if visible_name:
        result["visible_name"] = visible_name
    return result


def _thread_observation_app_id(thread: dict[str, Any] | None) -> str | None:
    observation = thread.get("observation") if isinstance(thread, dict) else None
    if not isinstance(observation, dict):
        return None
    app_id = _stripped_or_none(observation.get("app_id"))
    return app_id if app_id in {"tashuo", "tinder", "bumble"} else None


def _current_thread_visual_anchor_config_for_app(app_id: str) -> dict[str, Any] | None:
    if app_id == "tashuo":
        try:
            from dating_boost.apps.tashuo.native import (
                TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
                _tashuo_visual_anchor_hash_for_path,
            )
        except Exception:
            return None
        return {
            "screen_state": "tashuo_conversation",
            "visual_anchor_region": TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
            "hash_for_path": _tashuo_visual_anchor_hash_for_path,
        }
    if app_id in {"tinder", "bumble"}:
        try:
            from dating_boost.apps.native_gui_session import (
                IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
                _iphone_visual_anchor_hash_for_path,
            )
        except Exception:
            return None
        return {
            "screen_state": f"{app_id}_conversation",
            "visual_anchor_region": IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
            "hash_for_path": _iphone_visual_anchor_hash_for_path,
        }
    return None


def _thread_screenshot_path(thread: dict[str, Any], observation: dict[str, Any]) -> Path | None:
    for value in (thread.get("screenshot_ref"), observation.get("raw_ref")):
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value.strip())
        return path if path.is_absolute() else ROOT / path
    return None


def _target_profile_ready_for_work_item(work_item: dict[str, Any], pending_scan_batch: dict[str, Any] | None) -> bool:
    profile_payload = _target_profile_payload_for_work_item(work_item, pending_scan_batch)
    if not isinstance(profile_payload, dict):
        return False
    profile = ProfileObservation.from_dict(profile_payload)
    return bool(
        profile.review_status == "observed"
        and (
            profile.profile_text.strip()
            or any(str(item).strip() for item in profile.photo_cues)
            or any(str(item).strip() for item in profile.hook_candidates)
        )
    )


def _target_profile_payload_for_work_item(
    work_item: dict[str, Any],
    pending_scan_batch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    embedded = work_item.get("target_profile_observation")
    if isinstance(embedded, dict):
        return embedded
    legacy = work_item.get("profile_observation")
    if isinstance(legacy, dict):
        return legacy
    thread = _thread_observation_for_work_item(work_item, pending_scan_batch)
    observation = thread.get("observation") if isinstance(thread, dict) else None
    profile = observation.get("profile_observation") if isinstance(observation, dict) else None
    return profile if isinstance(profile, dict) else None


def _scan_batch_from_consumed_observations(work_dir: Path, work_item: dict[str, Any]) -> dict[str, Any] | None:
    consumed_dir = work_dir / "consumed"
    if not consumed_dir.exists():
        return None
    candidate_key = str(work_item.get("candidate_key") or "")
    entry: dict[str, Any] | None = None
    thread: dict[str, Any] | None = None
    for path in sorted(consumed_dir.glob("*.json"), reverse=True):
        try:
            payload = _read_json(path)
        except HostLoopError:
            continue
        observation_type = str(payload.get("observation_type") or "")
        if observation_type == "thread" and thread is None and str(payload.get("candidate_key") or "") == candidate_key:
            thread = payload
            continue
        if observation_type != "message_list" or entry is not None:
            continue
        snapshot = payload.get("message_list_snapshot")
        entries = snapshot.get("entries", []) if isinstance(snapshot, dict) else []
        for item in entries:
            if isinstance(item, dict) and str(item.get("candidate_key") or "") == candidate_key:
                entry = item
                break
        if entry is not None and thread is not None:
            break
    if entry is None and thread is None:
        return None
    return {
        "schema_version": 1,
        "message_list_snapshot": {"entries": [entry] if entry is not None else []},
        "thread_observations": [thread] if thread is not None else [],
    }


def _thread_observation_for_work_item(
    work_item: dict[str, Any],
    pending_scan_batch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(pending_scan_batch, dict):
        return None
    candidate_key = str(work_item.get("candidate_key") or "")
    for item in pending_scan_batch.get("thread_observations", []):
        if isinstance(item, dict) and str(item.get("candidate_key") or "") == candidate_key:
            return item
    return None


def _message_list_entry_for_work_item(
    work_item: dict[str, Any],
    pending_scan_batch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(pending_scan_batch, dict):
        return None
    candidate_key = str(work_item.get("candidate_key") or "")
    snapshot = pending_scan_batch.get("message_list_snapshot")
    entries = snapshot.get("entries", []) if isinstance(snapshot, dict) else []
    for item in entries:
        if isinstance(item, dict) and str(item.get("candidate_key") or "") == candidate_key:
            return item
    return None


def _stripped_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _load_app_profile(app_id: str) -> dict[str, Any]:
    if app_id not in set(supported_app_ids()):
        raise HostLoopError(f"unsupported app profile: {app_id}")
    path = ROOT / "app_profiles" / f"{_safe_name(app_id)}.json"
    if not path.exists():
        raise HostLoopError(f"unsupported app profile: {app_id}")
    profile = _read_json(path)
    profile["_path"] = str(path)
    return profile


def _host_instructions(profile: dict[str, Any], work_item_type: str) -> dict[str, Any]:
    key = {
        "scan_message_list": "message_list_observation",
        "observe_current_thread": "thread_observation",
        "open_thread": "thread_observation",
        "send_message": "stage_send_verification",
    }.get(work_item_type, "known_gui_pitfalls")
    native = profile.get("native_gui_harness")
    native_blocked_actions = native.get("blocked_actions", []) if isinstance(native, dict) else []
    native_live_send = native.get("live_send") if isinstance(native, dict) else None
    return {
        "app_id": profile.get("app_id"),
        "display_name": profile.get("display_name"),
        "support_level": profile.get("support_level"),
        "host_loop_supported": profile.get("host_loop_supported"),
        "host_loop_send_modes": profile.get("host_loop_send_modes", []),
        "instructions": profile.get(key, []),
        "known_gui_pitfalls": profile.get("known_gui_pitfalls", []),
        "unsupported_actions": profile.get("unsupported_actions", []),
        "native_blocked_actions": native_blocked_actions,
        "native_live_send": native_live_send,
    }


def _normalized_harness_runtime(value: str) -> str:
    return value.strip().replace("-", "_")


def _next_host_action(status: str, work_item: dict[str, Any] | None, send_mode: str, *, reason: str | None = None) -> str:
    reason_action = _next_host_action_for_block_reason(reason)
    if reason_action is not None:
        return reason_action
    if not isinstance(work_item, dict):
        if status in {"blocked", "error"}:
            return "inspect_error_and_fix_configuration"
        return "run_or_resume_host_loop"
    work_type = str(work_item.get("work_item_type") or "")
    if status == "staged_waiting_user_confirmation":
        return "review_staged_text_and_confirm_or_cancel"
    if work_type == "scan_message_list":
        return "open_app_message_list_and_write_message_list_observation"
    if work_type == "open_thread":
        return "open_requested_thread_and_write_thread_observation"
    if work_type == "send_message":
        if send_mode == "stage":
            return "paste_payload_text_and_verify_staged_text"
        return "paste_verify_send_then_record_action_result"
    if work_type == "handoff":
        return "user_takeover_required"
    if work_type in {"wait", "scheduled_wait"}:
        return "wait_or_resume_later"
    return "inspect_current_work_item"


def _next_host_action_for_block_reason(reason: str | None) -> str | None:
    if reason == "target_profile_required":
        return "open_target_profile_and_ingest_memory"
    if reason == "target_binding_structural_evidence_required":
        return "provide_structural_target_binding_evidence"
    if reason == "target_binding_lost_current_thread":
        return "stop_do_not_send_recover_current_thread_binding"
    if reason == "staged_text_requires_visual_verification":
        return "visually_verify_staged_text_before_live_send"
    if reason == "outbound_message_requires_visual_verification":
        return "visually_verify_outbound_message_after_live_send_and_write_action_result"
    if isinstance(reason, str) and reason.startswith("runtime_live_send_not_supported:"):
        return "choose_supported_runtime_or_stage_only"
    return None


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


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
    'HostLoopCommandError', '_safe_name', '_read_json', '_try_read_json_object',
    '_redacted_stage_draft_payload', '_target_binding_for_work_item', '_derive_tashuo_current_thread_target_binding', '_derive_current_thread_visual_target_binding',
    '_thread_observation_app_id', '_current_thread_visual_anchor_config_for_app', '_thread_screenshot_path', '_target_profile_ready_for_work_item',
    '_target_profile_payload_for_work_item', '_scan_batch_from_consumed_observations', '_thread_observation_for_work_item', '_message_list_entry_for_work_item',
    '_stripped_or_none', '_load_app_profile', '_host_instructions', '_normalized_harness_runtime',
    '_next_host_action', '_next_host_action_for_block_reason', '_unique_strings',
]
