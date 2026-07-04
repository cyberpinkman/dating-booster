from __future__ import annotations

from typing import Any

from dating_boost.apps.registry import manifest_for_app
from dating_boost.core.managed_gui_send_common import _normalized_harness_runtime


def _redacted_managed_send_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "status",
        "reason",
        "app_id",
        "action",
        "mode",
        "draft_fingerprint",
        "draft_character_count",
        "staged_text_verification",
        "post_send_verification",
        "post_action_observation_id",
        "evidence",
        "clipboard_restored",
        "next_host_action",
        "visual_verification_request",
        "current_thread_visual_anchor",
        "message_sequence_index",
        "message_sequence_count",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _managed_gui_send_normalized_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(evidence)
    normalized["staged_exact_text_verified"] = bool(
        evidence.get("staged_exact_text_verified")
        or evidence.get("staged_exact_text_ax_verified")
        or evidence.get("staged_exact_text_ocr_verified")
    )
    normalized["outbound_exact_text_verified"] = bool(
        evidence.get("outbound_exact_text_verified")
        or evidence.get("outbound_exact_text_ax_verified")
        or evidence.get("outbound_exact_text_ocr_verified")
    )
    return normalized


def _managed_gui_send_message_evidence(evidence: dict[str, Any]) -> dict[str, bool]:
    return {
        "staged_text_verified": bool(evidence.get("staged_text_verified")),
        "staged_exact_text_verified": bool(evidence.get("staged_exact_text_verified")),
        "input_cleared_after_send": bool(evidence.get("input_cleared_after_send")),
        "post_action_screen_captured": bool(evidence.get("post_action_screen_captured")),
        "outbound_message_verified": bool(evidence.get("outbound_message_verified")),
        "outbound_exact_text_verified": bool(evidence.get("outbound_exact_text_verified")),
    }


def _managed_gui_send_message_result(message: dict[str, Any], harness_payload: dict[str, Any]) -> dict[str, Any]:
    evidence = _managed_gui_send_normalized_evidence(
        harness_payload.get("evidence") if isinstance(harness_payload.get("evidence"), dict) else {}
    )
    result = {
        "index": int(message.get("index") or 0),
        "message_hash": str(message.get("message_hash") or ""),
        "character_count": int(message.get("character_count") or 0),
        "post_action_observation_id": harness_payload.get("post_action_observation_id"),
        "status": harness_payload.get("status"),
        "evidence": _managed_gui_send_message_evidence(evidence),
    }
    if harness_payload.get("already_sent") is True:
        result["already_sent"] = True
    if harness_payload.get("reason"):
        result["reason"] = harness_payload.get("reason")
    return result


def _managed_gui_send_required_evidence_for_payload(
    required_evidence: tuple[str, ...],
    harness_payload: dict[str, Any],
) -> tuple[str, ...]:
    if harness_payload.get("already_sent") is not True:
        return required_evidence
    return tuple(
        key
        for key in required_evidence
        if key not in {"staged_text_verified", "staged_exact_text_verified", "staged_exact_text_ocr_verified"}
    )


def _managed_gui_send_refreshed_target_binding(
    target_binding: dict[str, Any] | None,
    harness_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(target_binding, dict):
        return target_binding
    anchor = harness_payload.get("current_thread_visual_anchor")
    if not isinstance(anchor, dict) or anchor.get("status") != "ok":
        return target_binding
    visual_hash = str(anchor.get("visual_anchor_hash") or "").strip()
    if not visual_hash:
        return target_binding

    refreshed = dict(target_binding)
    thread_evidence = (
        dict(refreshed.get("thread_evidence"))
        if isinstance(refreshed.get("thread_evidence"), dict)
        else {}
    )
    thread_evidence["visual_anchor_hash"] = visual_hash
    if isinstance(anchor.get("visual_anchor_region"), dict):
        thread_evidence["visual_anchor_region"] = anchor.get("visual_anchor_region")
    screen_state = anchor.get("screen_state") or thread_evidence.get("screen_state")
    if screen_state:
        thread_evidence["screen_state"] = str(screen_state)
    if harness_payload.get("post_action_observation_id"):
        thread_evidence["observation_id"] = harness_payload.get("post_action_observation_id")
    refreshed["thread_evidence"] = thread_evidence
    return refreshed


def _managed_gui_send_required_evidence(app_id: str, runtime: str | None = None) -> tuple[str, ...]:
    manifest = manifest_for_app(app_id)
    runtime_key = _normalized_harness_runtime(str(runtime or ""))
    if runtime_key and runtime_key != "default":
        runtime_profile = manifest.runtime_profiles.get(runtime_key)
        requirements = (
            runtime_profile.get("live_send_requirements")
            if isinstance(runtime_profile, dict) and isinstance(runtime_profile.get("live_send_requirements"), dict)
            else {}
        )
        evidence = requirements.get("required_evidence")
        if isinstance(evidence, list) and evidence:
            return tuple(str(item) for item in evidence)
    return manifest.required_send_evidence
