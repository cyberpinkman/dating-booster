from __future__ import annotations

from .runtime_common import (
    annotations, copy, hashlib, json,
    Path, re, Any, uuid4,
    time, TASHUO_FOREGROUND_STATES, classify_tashuo_screen_image, classify_tashuo_capture,
    tashuo_layout_hints, tashuo_message_list_top_anchor_present, tashuo_top_level_bottom_nav_present, TASHUO_MESSAGES_TAB_TAP_RATIO,
    TASHUO_MINE_TAB_TAP_RATIO, _has_tashuo_step_postcondition, _has_tashuo_step_precondition, _tap_ratio_option,
    _tashuo_action_steps, _tashuo_profile_field_coverage, _tashuo_step_expects_state, _tashuo_workflow_steps,
    _verify_tashuo_step_state, platform, target_binding_specific_marker_present, target_binding_structural_evidence_present,
    EvidencePayload, PostSendVerification, SendAttemptContext, StagingResult,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    SubprocessRunner, _read_png_pixels, normalize_text, TASHUO_BLOCKED_GUI_ACTIONS,
    TASHUO_SEND_BLOCKED_GUI_ACTIONS, TASHUO_QUESTION_GATE_POLICY, TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO, TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO,
    TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO, TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO, TASHUO_CONVERSATION_NAVBACK_TAP_RATIO, TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO,
    TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO, TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS, TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS, TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_MAC_IOS_APP_INPUT_OCR_REGION, TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO, TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA, TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS, TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION,
    TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO, TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y, TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD,
    TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX, TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION,
    TASHUO_PROFILE_BOTTOM_MAX_SCROLLS, _capture_tashuo_window, _tashuo_post_action_observation_delay_seconds, _sleep_for_tashuo_post_action_observation,
    tashuo_guardrails_payload, _is_mac_ios_app_session, _tashuo_capture_prefix, _copy_tap_ratio,
    _applescript_literal, _tashuo_window_missing_payload, _tashuo_message_input_tap_ratio, _tashuo_input_coordinate_model,
)
from .launch_runtime import (
    _force_recover_tashuo_mac_ios_app_window,
    _open_tashuo_mac_ios_app_bundle,
    _recover_tashuo_mac_ios_app_window,
    _tashuo_mac_ios_window_recoverable_reason,
)

def prepare_tashuo_message_page(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "prepare-message-page",
            "target": "tashuo_message_page",
            "reason": "tashuo_prepare_message_page_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    bundle_id = str(runtime_config.get("bundle_id") or "com.intelcupid.tashuo")
    planned_steps = _tashuo_prepare_message_page_steps(runtime_config, bundle_id=bundle_id)
    payload = {
        **session._base_payload("ok"),
        "action": "prepare-message-page",
        "target": "tashuo_message_page",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "visual_only_navigation": True,
        "ocr_used": False,
        "message_page_followup": "visual_analysis_only",
        "next_host_action": "visual_plan_message_list",
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    executed_steps: list[dict[str, Any]] = []
    prepared = _open_preflight_capture_tashuo_message_page(
        session,
        payload,
        planned_steps,
        bundle_id=bundle_id,
        runtime_config=runtime_config,
        output_dir=output_dir,
        executed_steps=executed_steps,
    )
    if prepared.get("return_payload") is not None:
        return prepared["return_payload"]

    window = prepared["window"]
    initial_screen = prepared["screen"]
    for resolver in (
        _dismiss_tashuo_liked_you_modal_if_present,
        _return_tashuo_conversation_to_message_list_if_needed,
        _return_tashuo_secondary_page_if_needed,
    ):
        resolved = resolver(
            session,
            payload,
            planned_steps,
            window=window,
            screen=initial_screen,
            output_dir=output_dir,
            executed_steps=executed_steps,
        )
        if resolved.get("return_payload") is not None:
            return resolved["return_payload"]
        window = resolved["window"]
        initial_screen = resolved["screen"]

    return _settle_or_open_tashuo_messages_page(
        session,
        payload,
        planned_steps,
        window=window,
        screen=initial_screen,
        output_dir=output_dir,
        executed_steps=executed_steps,
    )


def _tashuo_prepare_message_page_steps(runtime_config: dict[str, Any], *, bundle_id: str) -> list[dict[str, Any]]:
    return [
        {
            "intent": "open_tashuo_mac_ios_app_bundle",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "wait_after_seconds": 0.8,
        },
        {
            "intent": "activate_tashuo_mac_ios_process",
            "process_name": str(runtime_config.get("process_name") or "tashuo"),
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "capture_tashuo_top_level_bottom_nav_visual",
            "risk": "visual_observation_only",
            "ocr_used": False,
        },
        {
            "intent": "dismiss_tashuo_liked_you_modal_later",
            "tap_ratio": _copy_tap_ratio(TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO),
            "risk": "dismiss_recoverable_modal_only",
            "does_not_purchase": True,
            "conditional_on_visual_state": "tashuo_liked_you_modal",
            "wait_after_seconds": 0.45,
        },
        {
            "intent": "click_tashuo_conversation_navback_accessibility",
            "ax_description": "thin left navback",
            "risk": "navigation_only",
            "conditional_on_visual_state": "tashuo_conversation",
            "wait_after_seconds": 0.45,
        },
        {
            "intent": "tap_tashuo_conversation_navback_visual_fallback",
            "tap_ratio": _copy_tap_ratio(TASHUO_CONVERSATION_NAVBACK_TAP_RATIO),
            "risk": "navigation_only",
            "conditional_on_visual_state": "tashuo_conversation",
            "fallback_for": "click_tashuo_conversation_navback_accessibility",
            "wait_after_seconds": 0.45,
        },
        {
            "intent": "tap_tashuo_secondary_page_navback_visual",
            "tap_ratio": _copy_tap_ratio(TASHUO_CONVERSATION_NAVBACK_TAP_RATIO),
            "risk": "navigation_only",
            "conditional_on_visual_state": "tashuo_secondary_page_without_bottom_nav",
            "wait_after_seconds": 0.45,
        },
        {
            "intent": "click_tashuo_messages_tab_accessibility",
            "radio_button_index": 3,
            "risk": "navigation_only",
            "conditional_on_active_tab_not": "messages",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "tap_tashuo_messages_tab_fallback",
            "tap_ratio": _copy_tap_ratio(TASHUO_MESSAGES_TAB_TAP_RATIO),
            "risk": "navigation_only",
            "conditional_on_active_tab_not": "messages",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "wait_tashuo_messages_page_content_visual_settle",
            "risk": "visual_observation_only",
            "conditional_on_active_tab": "messages",
            "ocr_used": False,
            "timeout_seconds": TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS,
        },
        {
            "intent": "handoff_to_visual_message_list_planning",
            "risk": "visual_observation_only",
            "does_not_open_conversation": True,
            "ocr_used": False,
        },
    ]


def _open_preflight_capture_tashuo_message_page(
    session: Any,
    payload: dict[str, Any],
    planned_steps: list[dict[str, Any]],
    *,
    bundle_id: str,
    runtime_config: dict[str, Any],
    output_dir: Path | None,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    open_payload = _open_tashuo_mac_ios_app_bundle(session, bundle_id)
    executed_steps.append({**planned_steps[0], "result": open_payload})
    if open_payload["status"] != "ok":
        payload.update({"status": "blocked", "reason": "mac_ios_app_open_failed", "executed_steps": executed_steps})
        return {"return_payload": payload}
    time.sleep(float(planned_steps[0]["wait_after_seconds"]))

    activate_payload = session._activate_window()
    executed_steps.append({**planned_steps[1], "result": activate_payload})
    if activate_payload["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": activate_payload.get("reason") or "mac_ios_app_activation_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(float(planned_steps[1]["wait_after_seconds"]))

    doctor = session.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        if _tashuo_mac_ios_window_recoverable_reason(doctor.get("reason")):
            recovery_steps = _recover_tashuo_mac_ios_app_window(
                session,
                bundle_id=bundle_id,
                process_name=str(runtime_config.get("process_name") or "tashuo"),
            )
            payload["recovery_steps"] = recovery_steps
            doctor = session.doctor(capture=False)
            if doctor["status"] == "blocked" and _tashuo_mac_ios_window_recoverable_reason(doctor.get("reason")):
                force_recovery_steps = _force_recover_tashuo_mac_ios_app_window(
                    session,
                    bundle_id=bundle_id,
                    process_name=str(runtime_config.get("process_name") or "tashuo"),
                )
                payload["force_recovery_steps"] = force_recovery_steps
                doctor = session.doctor(capture=False)
            payload["preflight"] = doctor
            if doctor["status"] == "blocked":
                payload.update({"status": "blocked", "reason": doctor.get("reason"), "executed_steps": executed_steps})
                return {"return_payload": payload}
        else:
            payload.update({"status": "blocked", "reason": doctor.get("reason"), "executed_steps": executed_steps})
            return {"return_payload": payload}

    window = platform._window_from_payload(doctor.get("window") or {})
    initial_output = output_dir / "mac_ios_app.tashuo.prepare_message_page.initial.png" if output_dir is not None else None
    initial_screen = _capture_tashuo_visual_screen(session, window, output=initial_output)
    payload["initial_screen"] = platform._redacted_screen(initial_screen)
    payload["initial_visual_state"] = initial_screen.get("visual_state", "unknown")
    payload["initial_active_tab"] = initial_screen.get("visual_active_tab", "unknown")
    executed_steps.append({**planned_steps[2], "result": {"status": initial_screen.get("status", "blocked")}})
    if initial_screen.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": initial_screen.get("reason") or "tashuo_visual_capture_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    return {"window": window, "screen": initial_screen}


def _dismiss_tashuo_liked_you_modal_if_present(
    session: Any,
    payload: dict[str, Any],
    planned_steps: list[dict[str, Any]],
    *,
    window: Any,
    screen: dict[str, Any],
    output_dir: Path | None,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if not (screen.get("liked_you_modal_present") or screen.get("visual_state") == "tashuo_liked_you_modal"):
        return {"window": window, "screen": screen}

    dismiss_result = _dismiss_tashuo_liked_you_modal(session, window)
    executed_steps.append({**planned_steps[3], "result": dismiss_result})
    if dismiss_result.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": dismiss_result.get("reason") or "tashuo_liked_you_modal_dismiss_failed",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "dismiss_tashuo_recoverable_modal_manually",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(float(planned_steps[3]["wait_after_seconds"]))
    refresh_result, refreshed_window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_liked_you_modal",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or refreshed_window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "restore_tashuo_window_focus",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    window = refreshed_window
    after_modal_output = (
        output_dir / "mac_ios_app.tashuo.prepare_message_page.after_liked_you_modal.png"
        if output_dir is not None
        else None
    )
    after_modal_screen = _capture_tashuo_visual_screen(session, window, output=after_modal_output)
    payload["after_liked_you_modal_screen"] = platform._redacted_screen(after_modal_screen)
    payload["liked_you_modal_dismissed"] = True
    if after_modal_screen.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": after_modal_screen.get("reason") or "tashuo_visual_capture_failed",
            "screen_state": after_modal_screen.get("state", "unknown"),
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    if after_modal_screen.get("liked_you_modal_present") or after_modal_screen.get("visual_state") == "tashuo_liked_you_modal":
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_liked_you_modal_not_dismissed",
            "screen_state": after_modal_screen.get("state", "unknown"),
            "next_host_action": "dismiss_tashuo_recoverable_modal_manually",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    payload["post_liked_you_modal_visual_state"] = after_modal_screen.get("visual_state", "unknown")
    payload["post_liked_you_modal_active_tab"] = after_modal_screen.get("visual_active_tab", "unknown")
    return {"window": window, "screen": after_modal_screen}


def _return_tashuo_conversation_to_message_list_if_needed(
    session: Any,
    payload: dict[str, Any],
    planned_steps: list[dict[str, Any]],
    *,
    window: Any,
    screen: dict[str, Any],
    output_dir: Path | None,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if screen.get("visual_state") != "tashuo_conversation":
        return {"window": window, "screen": screen}

    navback_result = _click_tashuo_conversation_navback_button(session)
    executed_steps.append({**planned_steps[4], "result": navback_result})
    if navback_result.get("status") != "ok":
        fallback_result = session._click_ratio(window, planned_steps[5]["tap_ratio"])
        executed_steps.append({
            **planned_steps[5],
            "accessibility_result": navback_result,
            "result": fallback_result,
        })
        if fallback_result.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": fallback_result.get("reason") or navback_result.get("reason") or "tashuo_conversation_navback_failed",
                "screen_state": screen.get("state", "unknown"),
                "next_host_action": "inspect_tashuo_conversation_navback",
                "executed_steps": executed_steps,
            })
            return {"return_payload": payload}
        time.sleep(float(planned_steps[5]["wait_after_seconds"]))
    else:
        time.sleep(float(planned_steps[4]["wait_after_seconds"]))

    refresh_result, refreshed_window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_conversation_navback",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or refreshed_window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "restore_tashuo_window_focus",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    window = refreshed_window
    returned_output = (
        output_dir / "mac_ios_app.tashuo.prepare_message_page.after_navback.png"
        if output_dir is not None
        else None
    )
    returned_screen = _capture_tashuo_visual_screen(session, window, output=returned_output)
    payload["after_navback_screen"] = platform._redacted_screen(returned_screen)
    if returned_screen.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": returned_screen.get("reason") or "tashuo_visual_capture_failed",
            "screen_state": returned_screen.get("state", "unknown"),
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    payload["post_navback_visual_state"] = returned_screen.get("visual_state", "unknown")
    payload["post_navback_active_tab"] = returned_screen.get("visual_active_tab", "unknown")
    return {"window": window, "screen": returned_screen}


def _return_tashuo_secondary_page_if_needed(
    session: Any,
    payload: dict[str, Any],
    planned_steps: list[dict[str, Any]],
    *,
    window: Any,
    screen: dict[str, Any],
    output_dir: Path | None,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if not _tashuo_secondary_page_without_bottom_nav(screen):
        return {"window": window, "screen": screen}

    back_result = session._click_ratio(window, planned_steps[6]["tap_ratio"])
    executed_steps.append({**planned_steps[6], "result": back_result})
    if back_result.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": back_result.get("reason") or "tashuo_secondary_page_navback_failed",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "inspect_tashuo_secondary_page_navback",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(float(planned_steps[6]["wait_after_seconds"]))
    refresh_result, refreshed_window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_secondary_navback",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or refreshed_window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "restore_tashuo_window_focus",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    window = refreshed_window
    returned_output = (
        output_dir / "mac_ios_app.tashuo.prepare_message_page.after_secondary_navback.png"
        if output_dir is not None
        else None
    )
    returned_screen = _capture_tashuo_visual_screen(session, window, output=returned_output)
    payload["after_secondary_navback_screen"] = platform._redacted_screen(returned_screen)
    if returned_screen.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": returned_screen.get("reason") or "tashuo_visual_capture_failed",
            "screen_state": returned_screen.get("state", "unknown"),
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    payload["post_secondary_navback_visual_state"] = returned_screen.get("visual_state", "unknown")
    payload["post_secondary_navback_active_tab"] = returned_screen.get("visual_active_tab", "unknown")
    return {"window": window, "screen": returned_screen}


def _settle_or_open_tashuo_messages_page(
    session: Any,
    payload: dict[str, Any],
    planned_steps: list[dict[str, Any]],
    *,
    window: Any,
    screen: dict[str, Any],
    output_dir: Path | None,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if not screen.get("visual_bottom_nav_present"):
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_top_level_tab_bar_not_verified",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "visual_analyze_current_screen",
            "executed_steps": executed_steps,
        })
        return payload
    if screen.get("visual_active_tab") == "messages":
        settled_screen, settle_result = _wait_for_tashuo_message_page_ready(
            session,
            window,
            output_dir=output_dir,
            output_stem="mac_ios_app.tashuo.prepare_message_page.messages",
            initial_screen=screen,
        )
        payload["message_page_settle"] = settle_result
        executed_steps.append({**planned_steps[9], "result": settle_result})
        payload.update({
            "screen": platform._redacted_screen(settled_screen),
            "screen_state": settled_screen.get("state", "unknown"),
            "executed_steps": executed_steps,
        })
        if settle_result.get("status") != "ok":
            payload.update({
                "status": "needs_verification",
                "reason": "tashuo_message_page_content_not_settled",
                "next_host_action": "visual_analyze_current_screen",
            })
        else:
            executed_steps.append({**planned_steps[10], "result": {"status": "ok"}})
        return payload

    ax_result = _click_tashuo_messages_radio_button(session)
    executed_steps.append({**planned_steps[7], "result": ax_result})
    if ax_result["status"] != "ok":
        tap_result = session._click_ratio(window, planned_steps[8]["tap_ratio"])
        executed_steps.append({**planned_steps[8], "result": tap_result})
        if tap_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": tap_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(float(planned_steps[8]["wait_after_seconds"]))
    else:
        time.sleep(float(planned_steps[7]["wait_after_seconds"]))
    refresh_result, refreshed_window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_messages_tab",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or refreshed_window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "screen_state": screen.get("state", "unknown"),
            "next_host_action": "restore_tashuo_window_focus",
            "executed_steps": executed_steps,
        })
        return payload
    window = refreshed_window

    final_screen, settle_result = _wait_for_tashuo_message_page_ready(
        session,
        window,
        output_dir=output_dir,
        output_stem="mac_ios_app.tashuo.prepare_message_page.messages",
    )
    payload["message_page_settle"] = settle_result
    payload["screen"] = platform._redacted_screen(final_screen)
    payload["screen_state"] = final_screen.get("state", "unknown")
    executed_steps.append({**planned_steps[9], "result": settle_result})
    payload["executed_steps"] = executed_steps
    if final_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": final_screen.get("reason") or "tashuo_visual_capture_failed"})
    elif settle_result.get("status") != "ok":
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_message_page_content_not_settled",
            "next_host_action": "visual_analyze_current_screen",
        })
    elif final_screen.get("visual_active_tab") != "messages":
        payload.update({"status": "needs_verification", "reason": "tashuo_messages_tab_not_verified"})
    else:
        executed_steps.append({**planned_steps[10], "result": {"status": "ok"}})
    return payload


def _tashuo_secondary_page_without_bottom_nav(screen: dict[str, Any]) -> bool:
    if screen.get("visual_bottom_nav_present"):
        return False
    return str(screen.get("state") or screen.get("visual_state") or "") in {
        "tashuo_profile",
        "tashuo_self_profile",
        "tashuo_recommend",
        "tashuo_pending_question_list",
    }

def _refresh_tashuo_mac_ios_window(session: Any) -> tuple[dict[str, Any], Any | None]:
    activate = session._activate_window()
    payload: dict[str, Any] = {
        "status": "ok" if activate.get("status") == "ok" else "blocked",
        "activation": activate,
    }
    if activate.get("status") != "ok":
        payload["reason"] = activate.get("reason") or "tashuo_activation_failed"
        return payload, None

    doctor = session.doctor(capture=False)
    payload["doctor"] = {
        "status": doctor.get("status"),
        "reason": doctor.get("reason"),
        "harness_backend": doctor.get("harness_backend"),
    }
    if doctor.get("status") != "ok":
        payload.update({"status": "blocked", "reason": doctor.get("reason") or "tashuo_doctor_failed"})
        return payload, None

    window_payload = doctor.get("window") if isinstance(doctor.get("window"), dict) else None
    if not window_payload:
        payload.update({"status": "blocked", "reason": "tashuo_window_not_found"})
        return payload, None
    try:
        window = platform._window_from_payload(window_payload)
    except (KeyError, TypeError, ValueError) as exc:
        payload.update({
            "status": "blocked",
            "reason": "tashuo_window_payload_invalid",
            "error_type": type(exc).__name__,
        })
        return payload, None
    payload["window"] = {
        "name": window.name,
        "frontmost": window.frontmost,
        "width": window.width,
        "height": window.height,
        "window_id": window.window_id,
    }
    return payload, window

def _capture_tashuo_visual_screen(session: Any, window: Any, *, output: Path | None = None) -> dict[str, Any]:
    output = (output or platform._default_screenshot_path()).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    window_id = getattr(window, "window_id", None)
    if window_id is not None:
        command = ["screencapture", "-x", "-l", str(window_id), str(output)]
    else:
        command = [
            "screencapture",
            "-x",
            "-R",
            f"{window.x},{window.y},{window.width},{window.height}",
            str(output),
        ]
    result = session.runner.run(command)
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "screenshot_failed",
            "stderr": platform._short(result.stderr),
            "state": "unknown",
            "text_state": "not_run",
            "visual_state": "unknown",
            "visual_status": "not_run",
            "visual_active_tab": "unknown",
            "visual_bottom_nav_present": False,
            "chat_list_visual_present": False,
            "recommend_card_visual_present": False,
            "liked_you_modal_present": False,
            "ocr_status": "skipped",
            "text": "",
        }
    visual = classify_tashuo_screen_image(output)
    visual_state = str(visual.get("state") or "unknown")
    return {
        "schema_version": 2,
        "status": "ok" if visual.get("status") == "ok" else "blocked",
        "path": str(output),
        "state": visual_state,
        "text_state": "not_run",
        "visual_state": visual_state,
        "visual_status": visual.get("status", "unknown"),
        "visual_active_tab": visual.get("active_tab", "unknown"),
        "visual_bottom_nav_present": visual.get("bottom_nav_present", False),
        "chat_list_visual_present": visual.get("chat_list_visual_present", False),
        "chat_list_visual_signal": visual.get("chat_list_visual_signal", {}),
        "message_list_top_anchor_present": visual.get("message_list_top_anchor_present", False),
        "message_list_top_anchor_signal": visual.get("message_list_top_anchor_signal", {}),
        "recommend_card_visual_present": visual.get("recommend_card_visual_present", False),
        "recommend_card_visual_signal": visual.get("recommend_card_visual_signal", {}),
        "liked_you_modal_present": visual.get("liked_you_modal_present", False),
        "liked_you_modal_signal": visual.get("liked_you_modal_signal", {}),
        "conversation_toolbar_present": visual.get("conversation_toolbar_present", False),
        "ocr_status": "skipped",
        "text": "",
    }

def _tashuo_message_page_visual_ready(screen: dict[str, Any]) -> bool:
    return (
        screen.get("status") == "ok"
        and screen.get("visual_active_tab") == "messages"
        and bool(screen.get("chat_list_visual_present"))
        and not bool(screen.get("recommend_card_visual_present"))
    )

def _tashuo_message_list_top_anchor_verified(screen: dict[str, Any]) -> bool:
    return (
        screen.get("status") == "ok"
        and screen.get("state") == "tashuo_chat_list"
        and tashuo_message_list_top_anchor_present(screen)
    )

def _tashuo_scroll_top_attempt(
    *,
    attempt: int,
    screen: dict[str, Any],
    scroll_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "attempt": attempt,
        "top_anchor_verified": _tashuo_message_list_top_anchor_verified(screen),
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "message_list_top_anchor_present": bool(screen.get("message_list_top_anchor_present")),
        "message_list_top_anchor_signal": screen.get("message_list_top_anchor_signal") or {},
    }
    if scroll_result is not None:
        payload["scroll_result"] = scroll_result
    return payload

def scroll_tashuo_conversation_list_to_top(
    session: Any,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    max_scrolls: int = 8,
) -> dict[str, Any]:
    scroll_step = _tashuo_action_steps("conversation-list-scroll-up")[0]
    payload = {
        **session._base_payload("ok"),
        "action": "conversation-list-scroll-to-top",
        "target": "tashuo_message_list_top",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": [
            {
                **scroll_step,
                "repeat_until": "message_list_top_anchor_verified",
                "max_scrolls": max(0, max_scrolls),
                "post_action_observation_delay_seconds": platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS,
            }
        ],
        "visual_only_navigation": _is_mac_ios_app_session(session),
        "ocr_used": not _is_mac_ios_app_session(session),
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    doctor = session.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    window = platform._window_from_payload(doctor.get("window") or {})
    use_ocr = not _is_mac_ios_app_session(session)
    initial_output = (
        output_dir / f"{_tashuo_capture_prefix(session)}.message_list_top_check.initial.png"
        if output_dir is not None
        else None
    )
    initial_screen = _capture_tashuo_window(session, output=initial_output, window=window, ocr=use_ocr)
    attempts = [_tashuo_scroll_top_attempt(attempt=0, screen=initial_screen)]
    payload["attempts"] = attempts
    if initial_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": initial_screen.get("reason") or "tashuo_top_check_capture_failed"})
        return payload
    if initial_screen.get("state") != "tashuo_chat_list":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_chat_list_not_verified",
            "screen_state": initial_screen.get("state", "unknown"),
        })
        return payload
    if attempts[-1]["top_anchor_verified"]:
        payload.update({
            "top_anchor_verified": True,
            "screen": platform._redacted_screen(initial_screen),
            "screen_state": initial_screen.get("state", "unknown"),
            "executed_steps": [],
            "next_host_action": "visual_plan_message_list_from_top",
        })
        return payload

    executed_steps: list[dict[str, Any]] = []
    for attempt in range(1, max(0, max_scrolls) + 1):
        scroll_result = session._execute_step(window, scroll_step)
        executed_steps.append({**scroll_step, "result": scroll_result, "attempt": attempt})
        if scroll_result.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": scroll_result.get("reason") or "tashuo_conversation_list_scroll_up_failed",
                "executed_steps": executed_steps,
            })
            return payload
        time.sleep(max(platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(scroll_step.get("wait_after_seconds", 0.0))))
        output = (
            output_dir / f"{_tashuo_capture_prefix(session)}.message_list_top_check.{attempt:02d}.png"
            if output_dir is not None
            else None
        )
        screen = _capture_tashuo_window(session, output=output, window=window, ocr=use_ocr)
        attempt_payload = _tashuo_scroll_top_attempt(attempt=attempt, screen=screen, scroll_result=scroll_result)
        attempts.append(attempt_payload)
        if screen.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": screen.get("reason") or "tashuo_top_check_capture_failed",
                "executed_steps": executed_steps,
            })
            return payload
        if screen.get("state") != "tashuo_chat_list":
            payload.update({
                "status": "blocked",
                "reason": "tashuo_chat_list_not_verified_after_scroll",
                "screen_state": screen.get("state", "unknown"),
                "executed_steps": executed_steps,
            })
            return payload
        if attempt_payload["top_anchor_verified"]:
            payload.update({
                "top_anchor_verified": True,
                "screen": platform._redacted_screen(screen),
                "screen_state": screen.get("state", "unknown"),
                "executed_steps": executed_steps,
                "next_host_action": "visual_plan_message_list_from_top",
            })
            return payload

    payload.update({
        "status": "needs_host_visual_verification",
        "reason": "tashuo_message_list_top_anchor_not_verified",
        "top_anchor_verified": False,
        "executed_steps": executed_steps,
        "next_host_action": "visual_confirm_message_list_top_or_continue_scroll",
    })
    return payload

def _wait_for_tashuo_message_page_ready(
    session: Any,
    window: Any,
    *,
    output_dir: Path | None,
    output_stem: str,
    initial_screen: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    last_screen: dict[str, Any] = initial_screen or {
        "status": "blocked",
        "reason": "tashuo_visual_capture_not_started",
        "state": "unknown",
    }
    start = time.monotonic()
    if initial_screen is not None:
        ready = _tashuo_message_page_visual_ready(initial_screen)
        attempts.append({
            "attempt": 0,
            "source": "initial_screen",
            "ready": ready,
            "screen": platform._redacted_screen(initial_screen),
        })
        if ready:
            return initial_screen, {
                "status": "ok",
                "attempt_count": 0,
                "settled": True,
                "attempts": attempts,
            }

    attempt = 0
    while time.monotonic() - start <= TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS:
        attempt += 1
        output = None
        if output_dir is not None:
            suffix = "" if attempt == 1 else f".wait_{attempt}"
            output = output_dir / f"{output_stem}{suffix}.png"
        screen = _capture_tashuo_visual_screen(session, window, output=output)
        last_screen = screen
        ready = _tashuo_message_page_visual_ready(screen)
        attempts.append({
            "attempt": attempt,
            "ready": ready,
            "screen": platform._redacted_screen(screen),
        })
        if screen.get("status") != "ok":
            return screen, {
                "status": "blocked",
                "reason": screen.get("reason") or "tashuo_visual_capture_failed",
                "attempt_count": attempt,
                "settled": False,
                "attempts": attempts,
            }
        if ready:
            return screen, {
                "status": "ok",
                "attempt_count": attempt,
                "settled": True,
                "attempts": attempts,
            }
        if time.monotonic() - start >= TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS:
            break
        time.sleep(TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS)

    return last_screen, {
        "status": "timeout",
        "reason": "tashuo_message_page_content_not_settled",
        "attempt_count": attempt,
        "settled": False,
        "attempts": attempts,
    }

def _click_tashuo_conversation_navback_button(session: Any) -> dict[str, Any]:
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    process_name = str(runtime_config.get("process_name") or "tashuo")
    script = f'''
tell application "System Events"
  tell process "{process_name}"
    set elems to entire contents of window 1
    repeat with e in elems
      try
        if (class of e as text) is "button" and (description of e as text) is "thin left navback" then
          click e
          return "clicked"
        end if
      end try
    end repeat
    return "not_found"
  end tell
end tell
'''.strip()
    result = session.runner.run(["osascript", "-e", script])
    stdout = (result.stdout or "").strip()
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_conversation_navback_ax_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    if stdout != "clicked":
        return {
            "status": "blocked",
            "reason": "tashuo_conversation_navback_not_found",
            "stdout": platform._short(stdout),
            "input_backend": "macos_accessibility",
        }
    return {
        "status": "ok",
        "input_backend": "macos_accessibility",
        "ax_description": "thin left navback",
    }

def _dismiss_tashuo_liked_you_modal(session: Any, window: Any) -> dict[str, Any]:
    ax_result = _click_tashuo_liked_you_modal_later_button(session)
    if ax_result.get("status") == "ok":
        return {
            "status": "ok",
            "method": "macos_accessibility",
            "does_not_purchase": True,
            "ax_result": ax_result,
        }
    tap_result = session._click_ratio(window, TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO)
    if tap_result.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": tap_result.get("reason") or ax_result.get("reason") or "tashuo_liked_you_modal_dismiss_failed",
            "does_not_purchase": True,
            "ax_result": ax_result,
            "tap_result": tap_result,
        }
    return {
        "status": "ok",
        "method": "visual_cancel_tap",
        "does_not_purchase": True,
        "tap_ratio": _copy_tap_ratio(TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO),
        "ax_result": ax_result,
        "tap_result": tap_result,
    }

def _dismiss_tashuo_notification_prompt(session: Any, window: Any) -> dict[str, Any]:
    ax_result = _click_tashuo_notification_prompt_close_button(session)
    if ax_result.get("status") == "ok":
        return {
            "status": "ok",
            "method": "macos_accessibility",
            "does_not_enable_notifications": True,
            "ax_result": ax_result,
        }
    tap_result = session._click_ratio(window, TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO)
    if tap_result.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": tap_result.get("reason") or ax_result.get("reason") or "tashuo_notification_prompt_dismiss_failed",
            "does_not_enable_notifications": True,
            "ax_result": ax_result,
            "tap_result": tap_result,
        }
    return {
        "status": "ok",
        "method": "visual_close_tap",
        "does_not_enable_notifications": True,
        "tap_ratio": _copy_tap_ratio(TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO),
        "ax_result": ax_result,
        "tap_result": tap_result,
    }

def _click_tashuo_notification_prompt_close_button(session: Any) -> dict[str, Any]:
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    process_name = str(runtime_config.get("process_name") or "tashuo").replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
-- DATING_BOOST_TASHUO_DISMISS_NOTIFICATION_PROMPT
on labelOf(e)
  set labelText to ""
  tell application "System Events"
    try
      set labelText to labelText & (name of e as text) & "\\n"
    end try
    try
      set labelText to labelText & (description of e as text) & "\\n"
    end try
    try
      set labelText to labelText & (value of e as text) & "\\n"
    end try
  end tell
  return labelText
end labelOf

on clickClose(e, depth)
  tell application "System Events"
    try
      set labelText to my labelOf(e)
      if labelText contains "关闭" or labelText contains "Close" or labelText contains "close" or labelText contains "xmark" then
        click e
        return "clicked"
      end if
    end try
    if depth < 24 then
      try
        repeat with child in UI elements of e
          set resultText to my clickClose(child, depth + 1)
          if resultText is "clicked" then return "clicked"
        end repeat
      end try
    end if
  end tell
  return "not_found"
end clickClose

tell application "System Events"
  tell process "{process_name}"
    return my clickClose(window 1, 0)
  end tell
end tell
'''.strip()
    result = session.runner.run(["osascript", "-e", script])
    stdout = (result.stdout or "").strip()
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_notification_prompt_ax_dismiss_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    if stdout != "clicked":
        return {
            "status": "blocked",
            "reason": "tashuo_notification_prompt_close_button_not_found",
            "stdout": platform._short(stdout),
            "input_backend": "macos_accessibility",
        }
    return {
        "status": "ok",
        "input_backend": "macos_accessibility",
        "ax_label": "close",
        "does_not_enable_notifications": True,
    }

def _click_tashuo_liked_you_modal_later_button(session: Any) -> dict[str, Any]:
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    process_name = str(runtime_config.get("process_name") or "tashuo").replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
-- DATING_BOOST_TASHUO_DISMISS_LIKED_YOU_MODAL
on labelOf(e)
  set labelText to ""
  tell application "System Events"
    try
      set labelText to labelText & (name of e as text) & "\\n"
    end try
    try
      set labelText to labelText & (description of e as text) & "\\n"
    end try
    try
      set labelText to labelText & (value of e as text) & "\\n"
    end try
  end tell
  return labelText
end labelOf

on clickDismiss(e, depth)
  tell application "System Events"
    try
      set labelText to my labelOf(e)
      if labelText contains "稍后再说" or labelText contains "以后再说" or labelText contains "暂不" or labelText contains "Not now" or labelText contains "Later" then
        click e
        return "clicked"
      end if
    end try
    if depth < 24 then
      try
        repeat with child in UI elements of e
          set resultText to my clickDismiss(child, depth + 1)
          if resultText is "clicked" then return "clicked"
        end repeat
      end try
    end if
  end tell
  return "not_found"
end clickDismiss

tell application "System Events"
  tell process "{process_name}"
    return my clickDismiss(window 1, 0)
  end tell
end tell
'''.strip()
    result = session.runner.run(["osascript", "-e", script])
    stdout = (result.stdout or "").strip()
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_liked_you_modal_ax_dismiss_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    if stdout != "clicked":
        return {
            "status": "blocked",
            "reason": "tashuo_liked_you_modal_later_button_not_found",
            "stdout": platform._short(stdout),
            "input_backend": "macos_accessibility",
        }
    return {
        "status": "ok",
        "input_backend": "macos_accessibility",
        "ax_label": "later",
        "does_not_purchase": True,
    }

def _click_tashuo_messages_radio_button(session: Any) -> dict[str, Any]:
    process_name = str(getattr(session, "window_title", "") or "她说").replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "System Events" to tell process "{process_name}" '
        'to click radio button 3 of window 1'
    )
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_messages_radio_button_click_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    return {"status": "ok", "input_backend": "macos_accessibility", "radio_button_index": 3}

def _click_tashuo_mine_radio_button(session: Any) -> dict[str, Any]:
    process_name = str(getattr(session, "window_title", "") or "她说").replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "System Events" to tell process "{process_name}" '
        'to click radio button 4 of window 1'
    )
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_mine_radio_button_click_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    return {"status": "ok", "input_backend": "macos_accessibility", "radio_button_index": 4}

def _verify_tashuo_step_precondition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_tashuo_step_precondition(step):
        return {"status": "ok"}
    output = None
    if output_dir is not None:
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_precondition_{step_index:02d}.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=_tashuo_step_ocr_enabled(session, step))
    result = {
        "status": screen.get("status", "blocked"),
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "tashuo_precondition_capture_failed"
    elif step.get("requires_tashuo_top_level_tab_bar") and not tashuo_top_level_bottom_nav_present(screen):
        result.update({"status": "blocked", "reason": "tashuo_top_level_tab_bar_not_verified"})
    else:
        state_check = _verify_tashuo_step_state(screen, step, key="requires_tashuo_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "tashuo_step_precondition_not_verified"
    return result

def _verify_tashuo_step_postcondition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_tashuo_step_postcondition(step):
        return {"status": "ok", "checked": False}
    output = None
    if output_dir is not None:
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_postcondition_{step_index:02d}.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=_tashuo_step_ocr_enabled(session, step))
    result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "tashuo_postcondition_capture_failed"
    else:
        state_check = _verify_tashuo_step_state(screen, step, key="expected_tashuo_states")
        if state_check["status"] != "ok":
            notification_prompt_recovery = _recover_tashuo_notification_prompt_postcondition(
                session,
                window,
                step,
                first_result=result,
                output_dir=output_dir,
                step_index=step_index,
            )
            if notification_prompt_recovery is not None:
                return notification_prompt_recovery
            retry = _retry_tashuo_step_postcondition_after_transition(
                session,
                window,
                step,
                first_result=result,
                output_dir=output_dir,
                step_index=step_index,
            )
            if retry is not None:
                return retry
            result.update(state_check)
            result["reason"] = "tashuo_step_postcondition_not_verified"
    return result

def _recover_tashuo_notification_prompt_postcondition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    first_result: dict[str, Any],
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any] | None:
    if not _tashuo_step_expects_state(step, "tashuo_conversation"):
        return None
    first_screen = first_result.get("screen") if isinstance(first_result.get("screen"), dict) else {}
    prompt_visible = (
        first_result.get("screen_state") == "tashuo_conversation_notification_prompt"
        or first_screen.get("conversation_notification_prompt_present") is True
    )
    if not prompt_visible:
        return None
    dismiss_result = _dismiss_tashuo_notification_prompt(session, window)
    if dismiss_result.get("status") != "ok":
        return {
            **first_result,
            "status": "blocked",
            "reason": dismiss_result.get("reason") or "tashuo_notification_prompt_dismiss_failed",
            "dismiss_tashuo_notification_prompt": dismiss_result,
        }
    time.sleep(0.6)
    output = None
    if output_dir is not None:
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_postcondition_{step_index:02d}.notification_prompt_dismissed.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=_tashuo_step_ocr_enabled(session, step))
    result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "dismissed_tashuo_notification_prompt": True,
        "dismiss_tashuo_notification_prompt": dismiss_result,
        "first_screen_state": first_result.get("screen_state"),
        "first_screen": first_screen,
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "tashuo_postcondition_after_notification_prompt_dismiss_capture_failed"
        return result
    state_check = _verify_tashuo_step_state(screen, step, key="expected_tashuo_states")
    if state_check["status"] != "ok":
        result.update(state_check)
        result["reason"] = "tashuo_step_postcondition_not_verified"
    return result

def _retry_tashuo_step_postcondition_after_transition(
    session: Any,
    window: Any,
    step: dict[str, Any],
    *,
    first_result: dict[str, Any],
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any] | None:
    retry_after = float(step.get("postcondition_retry_after_seconds") or 0)
    if retry_after <= 0:
        return None
    if first_result.get("screen_state") not in {"unknown", "tashuo_unknown"}:
        return None
    time.sleep(retry_after)
    output = None
    if output_dir is not None:
        output = output_dir / f"{_tashuo_capture_prefix(session)}.tashuo_postcondition_{step_index:02d}.retry.png"
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=_tashuo_step_ocr_enabled(session, step))
    retry_result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "retried_after_transition": True,
        "first_screen_state": first_result.get("screen_state"),
        "first_screen": first_result.get("screen"),
    }
    if retry_result["status"] != "ok":
        retry_result["reason"] = screen.get("reason") or "tashuo_postcondition_retry_capture_failed"
        return retry_result
    state_check = _verify_tashuo_step_state(screen, step, key="expected_tashuo_states")
    if state_check["status"] != "ok":
        retry_result.update(state_check)
        retry_result["reason"] = "tashuo_step_postcondition_not_verified"
    return retry_result

def _tashuo_step_ocr_enabled(session: Any, step: dict[str, Any]) -> bool:
    if not _is_mac_ios_app_session(session):
        return True
    return str(step.get("intent") or "") in {
        "wheel_tashuo_profile_read_down",
        "wheel_tashuo_profile_read_up",
    }

__all__ = [
    'annotations', 'copy', 'hashlib', 'json',
    'Path', 're', 'Any', 'uuid4',
    'time', 'TASHUO_FOREGROUND_STATES', 'classify_tashuo_screen_image', 'classify_tashuo_capture',
    'tashuo_layout_hints', 'tashuo_message_list_top_anchor_present', 'tashuo_top_level_bottom_nav_present', 'TASHUO_MESSAGES_TAB_TAP_RATIO',
    'TASHUO_MINE_TAB_TAP_RATIO', '_has_tashuo_step_postcondition', '_has_tashuo_step_precondition', '_tap_ratio_option',
    '_tashuo_action_steps', '_tashuo_profile_field_coverage', '_tashuo_step_expects_state', '_tashuo_workflow_steps',
    '_verify_tashuo_step_state', 'platform', 'target_binding_specific_marker_present', 'target_binding_structural_evidence_present',
    'EvidencePayload', 'PostSendVerification', 'SendAttemptContext', 'StagingResult',
    'RowToThreadBindingSpec', 'finish_row_to_thread_screen_verification', 'row_to_thread_base_result', 'validate_row_to_thread_structural_evidence',
    'SubprocessRunner', '_read_png_pixels', 'normalize_text', 'TASHUO_BLOCKED_GUI_ACTIONS',
    'TASHUO_SEND_BLOCKED_GUI_ACTIONS', 'TASHUO_QUESTION_GATE_POLICY', 'TASHUO_MESSAGE_INPUT_UNFOCUSED_TAP_RATIO', 'TASHUO_MESSAGE_INPUT_FOCUSED_TAP_RATIO',
    'TASHUO_MAC_IOS_APP_MESSAGE_INPUT_FOCUSED_TAP_RATIO', 'TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO', 'TASHUO_CONVERSATION_NAVBACK_TAP_RATIO', 'TASHUO_LIKED_YOU_MODAL_LATER_TAP_RATIO',
    'TASHUO_NOTIFICATION_PROMPT_CLOSE_TAP_RATIO', 'TASHUO_MESSAGE_PAGE_SETTLE_TIMEOUT_SECONDS', 'TASHUO_MESSAGE_PAGE_SETTLE_INTERVAL_SECONDS', 'TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION',
    'TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'TASHUO_MAC_IOS_APP_INPUT_OCR_REGION', 'TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED', 'TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION',
    'TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO', 'TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA', 'TASHUO_MAC_IOS_APP_TARGET_RELOCATION_MAX_ATTEMPTS', 'TASHUO_CHAT_LIST_VISUAL_ANCHOR_SCAN_REGION',
    'TASHUO_CHAT_LIST_VISUAL_ANCHOR_MAX_DISTANCE', 'TASHUO_CHAT_LIST_BOTTOM_NAV_TOP_RATIO', 'TASHUO_CHAT_LIST_BOTTOM_ROW_SAFE_TAP_Y', 'TASHUO_CHAT_LIST_BOTTOM_ROW_TOP_THRESHOLD',
    'TASHUO_CHAT_LIST_BOTTOM_ROW_REGION_THRESHOLD', 'TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MIN', 'TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_MAX', 'TASHUO_CHAT_LIST_ROW_TAP_TOP_INSET_FRACTION',
    'TASHUO_PROFILE_BOTTOM_MAX_SCROLLS', '_capture_tashuo_window', '_tashuo_post_action_observation_delay_seconds', '_sleep_for_tashuo_post_action_observation',
    'tashuo_guardrails_payload', '_is_mac_ios_app_session', '_tashuo_capture_prefix', '_copy_tap_ratio',
    '_applescript_literal', '_tashuo_window_missing_payload', '_tashuo_message_input_tap_ratio', '_tashuo_input_coordinate_model',
    '_force_recover_tashuo_mac_ios_app_window', '_open_tashuo_mac_ios_app_bundle', '_recover_tashuo_mac_ios_app_window', '_tashuo_mac_ios_window_recoverable_reason',
    'prepare_tashuo_message_page', '_tashuo_prepare_message_page_steps', '_open_preflight_capture_tashuo_message_page', '_dismiss_tashuo_liked_you_modal_if_present',
    '_return_tashuo_conversation_to_message_list_if_needed', '_return_tashuo_secondary_page_if_needed', '_settle_or_open_tashuo_messages_page', '_tashuo_secondary_page_without_bottom_nav',
    '_refresh_tashuo_mac_ios_window', '_capture_tashuo_visual_screen', '_tashuo_message_page_visual_ready', '_tashuo_message_list_top_anchor_verified',
    '_tashuo_scroll_top_attempt', 'scroll_tashuo_conversation_list_to_top', '_wait_for_tashuo_message_page_ready', '_click_tashuo_conversation_navback_button',
    '_dismiss_tashuo_liked_you_modal', '_dismiss_tashuo_notification_prompt', '_click_tashuo_notification_prompt_close_button', '_click_tashuo_liked_you_modal_later_button',
    '_click_tashuo_messages_radio_button', '_click_tashuo_mine_radio_button', '_verify_tashuo_step_precondition', '_verify_tashuo_step_postcondition',
    '_recover_tashuo_notification_prompt_postcondition', '_retry_tashuo_step_postcondition_after_transition', '_tashuo_step_ocr_enabled',
]
