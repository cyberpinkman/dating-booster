from __future__ import annotations

from dating_boost.apps.iphone_targeting_common import *
from dating_boost.apps.iphone_anchoring import _iphone_current_thread_visual_anchor

def _iphone_already_sent_payload_update(
    payload: dict[str, Any],
    *,
    screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    conversation_state: str,
) -> dict[str, Any]:
    post_id_source = f"{payload['draft_fingerprint']}:{screen.get('path') or _now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    exact_text_ocr_verified = bool(outbound_verification.get("exact_text_ocr_verified"))
    return {
        "post_action_observation": _redacted_screen(screen),
        "post_action_observation_id": post_observation_id,
        "outbound_message_verification": outbound_verification,
        "current_thread_visual_anchor": _iphone_current_thread_visual_anchor(
            screen,
            conversation_state=conversation_state,
        ),
        "already_sent": True,
        "staged_text_verified": False,
        "executed_steps": [],
        "evidence": {
            "staged_text_verified": False,
            "staged_exact_text_verified": False,
            "staged_exact_text_ocr_verified": False,
            "send_input_backend": "already_sent_idempotent_skip",
            "input_cleared_after_send": bool(outbound_verification.get("input_cleared_after_send")),
            "post_action_screen_captured": screen.get("status") == "ok",
            "outbound_message_verified": True,
            "outbound_exact_text_verified": exact_text_ocr_verified,
            "outbound_exact_text_ocr_verified": exact_text_ocr_verified,
            "visual_only_exact_verification_allowed": False,
            "post_action_observation_id": post_observation_id,
        },
    }


def _iphone_already_sent_idempotency_allowed(target_binding: dict[str, Any] | None) -> bool:
    return (
        isinstance(target_binding, dict)
        and target_binding.get("binding_type") == "current_thread_visual_identity"
    )


def _iphone_stage_needs_user_verification(
    staged_verification: dict[str, Any],
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    verification = copy.deepcopy(staged_verification)
    verification["status"] = "needs_user_verification"
    verification["reason"] = reason or verification.get("reason") or "staged_text_not_verified"
    return verification


def _iphone_stage_draft_payload_update(
    *,
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    executed_steps: list[dict[str, Any]],
    conversation_state: str,
    send_input_backend: Any,
) -> dict[str, Any]:
    staged_text_verified = staged_verification.get("status") == "ok"
    return {
        "status": "ok",
        "stage_attempt_status": "completed",
        "staged_text_verification": staged_verification,
        "staged_text_verified": staged_text_verified,
        "verification": _redacted_screen(staged_screen),
        "current_thread_visual_anchor": _iphone_current_thread_visual_anchor(
            staged_screen,
            conversation_state=conversation_state,
        ),
        "executed_steps": executed_steps,
        "send_action_executed": False,
        "requires_user_confirmation_before_send": True,
        "next_host_action": "verify_staged_text_before_send",
        "evidence": EvidencePayload(
            staging=StagingResult.from_verification(
                staged_verification,
                staged_text_verified=staged_text_verified,
            ),
            post_send=PostSendVerification(
                post_action_observation_id="stage_only_no_post_action",
                input_cleared_after_send=False,
                post_action_screen_captured=False,
                outbound_message_verified=False,
            ),
            send_input_backend=send_input_backend,
            extra_fields={
                "stage_mode": True,
                "live_send_executed": False,
                "outbound_exact_text_ocr_verified": False,
                "visual_only_exact_verification_allowed": False,
            },
        ).to_dict(),
    }


def _iphone_pre_stage_input_guard(
    *,
    app_id: str,
    screen: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    guard: dict[str, Any] = {
        "status": "ok",
        "app_id": app_id,
        "verification_method": f"{app_id}_pre_stage_input_occupied_guard",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        "observed_character_count": len(observed_text) if observed_text else None,
        "screen": _redacted_screen(screen),
    }
    if app_id == "bumble":
        from dating_boost.apps.bumble.runtime import _bumble_active_send_button_visual_visible

        active_send_button_visible = _bumble_active_send_button_visual_visible(screen)
        guard["active_send_button_visual_visible"] = active_send_button_visible
        if active_send_button_visible:
            guard.update({
                "status": "blocked",
                "reason": "message_input_not_empty_before_staging",
            })
        return guard
    if app_id == "tinder":
        from dating_boost.apps.tinder.runtime import (
            _tinder_message_input_placeholder_visible,
            _tinder_send_button_visual_visible,
            _tinder_send_marker_visible,
        )

        send_button_visual_visible = _tinder_send_button_visual_visible(screen)
        send_marker_visible = _tinder_send_marker_visible(observed_text)
        placeholder_visible = _tinder_message_input_placeholder_visible(observed_text)
        guard.update({
            "send_button_visual_visible": send_button_visual_visible,
            "send_marker_visible": send_marker_visible,
            "message_input_placeholder_visible": placeholder_visible,
        })
        if send_button_visual_visible and send_marker_visible and not placeholder_visible:
            guard.update({
                "status": "blocked",
                "reason": "message_input_not_empty_before_staging",
            })
        return guard
    return guard


def _verify_outbound_message(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    result = _outbound_text_ocr_evidence(
        verification_method="wechat_post_send_ocr_payload_text",
        observed_text=observed_text,
        expected_text=expected_text,
    )
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "post_action_screen_not_captured"}
    if not result["exact_text_ocr_verified"]:
        return {**result, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, "status": "ok"}


def _screen_region_stats(screen: dict[str, Any], x1: float, y1: float, x2: float, y2: float) -> dict[str, float] | None:
    path = screen.get("path")
    if not isinstance(path, str) or not path:
        return None
    try:
        pixels = _read_png_pixels_for_send_button(Path(path))
    except (OSError, ValueError, zlib.error, struct.error):
        return None
    return _region_stats_for_send_button(pixels, x1, y1, x2, y2)


__all__ = [name for name in globals() if not name.startswith("__")]
