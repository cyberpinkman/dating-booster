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
from .message_page_runtime import (
    _capture_tashuo_visual_screen,
    _click_tashuo_mine_radio_button,
    _refresh_tashuo_mac_ios_window,
    prepare_tashuo_message_page,
)

def prepare_tashuo_self_profile_page(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "prepare-self-profile-page",
            "target": "tashuo_self_profile_page",
            "reason": "tashuo_prepare_self_profile_page_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    planned_steps = [
        {
            "intent": "prepare_tashuo_message_page_as_safe_top_level_anchor",
            "risk": "navigation_only",
            "does_not_open_conversation": True,
            "ocr_used": False,
        },
        {
            "intent": "click_tashuo_mine_tab_accessibility",
            "radio_button_index": 4,
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "tap_tashuo_mine_tab_fallback",
            "tap_ratio": _copy_tap_ratio(TASHUO_MINE_TAB_TAP_RATIO),
            "risk": "navigation_only",
            "fallback_for": "click_tashuo_mine_tab_accessibility",
            "wait_after_seconds": 0.4,
        },
        {
            "intent": "handoff_to_visible_self_profile_fact_extraction",
            "risk": "visual_observation_only",
            "does_not_edit_profile": True,
            "ocr_used": False,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "action": "prepare-self-profile-page",
        "target": "tashuo_self_profile_page",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "visual_only_navigation": True,
        "ocr_used": False,
        "self_profile_followup": "visible_fact_extraction_only",
        "next_host_action": "extract_visible_self_profile_facts",
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    message_page = prepare_tashuo_message_page(session, dry_run=False, output_dir=output_dir)
    payload["message_page_preparation"] = {
        "status": message_page.get("status"),
        "reason": message_page.get("reason"),
        "screen_state": message_page.get("screen_state"),
        "next_host_action": message_page.get("next_host_action"),
    }
    executed_steps: list[dict[str, Any]] = [
        {
            **planned_steps[0],
            "result": {
                "status": message_page.get("status"),
                "reason": message_page.get("reason"),
                "screen_state": message_page.get("screen_state"),
            },
        }
    ]
    if message_page.get("status") != "ok":
        payload.update({
            "status": "blocked" if message_page.get("status") == "blocked" else "needs_verification",
            "reason": message_page.get("reason") or "tashuo_message_page_anchor_not_verified",
            "executed_steps": executed_steps,
            "next_host_action": message_page.get("next_host_action") or "visual_analyze_current_screen",
        })
        return payload

    refresh_result, window = _refresh_tashuo_mac_ios_window(session)
    payload["profile_page_window_refresh"] = refresh_result
    if refresh_result.get("status") != "ok" or window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "executed_steps": executed_steps,
            "next_host_action": "restore_tashuo_window_focus",
        })
        return payload

    ax_result = _click_tashuo_mine_radio_button(session)
    executed_steps.append({**planned_steps[1], "result": ax_result})
    if ax_result.get("status") != "ok":
        tap_result = session._click_ratio(window, planned_steps[2]["tap_ratio"])
        executed_steps.append({**planned_steps[2], "result": tap_result})
        if tap_result.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": tap_result.get("reason") or "tashuo_mine_tab_click_failed",
                "executed_steps": executed_steps,
            })
            return payload
        time.sleep(float(planned_steps[2]["wait_after_seconds"]))
    else:
        time.sleep(float(planned_steps[1]["wait_after_seconds"]))

    refresh_result, window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_mine_tab",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "executed_steps": executed_steps,
            "next_host_action": "restore_tashuo_window_focus",
        })
        return payload

    final_output = output_dir / "mac_ios_app.tashuo.prepare_self_profile_page.profile.png" if output_dir is not None else None
    final_screen = _capture_tashuo_visual_screen(session, window, output=final_output)
    payload["screen"] = platform._redacted_screen(final_screen)
    payload["screen_state"] = final_screen.get("state", "unknown")
    executed_steps.append({
        **planned_steps[3],
        "result": {"status": "ok" if final_screen.get("status") == "ok" else "blocked"},
    })
    payload["executed_steps"] = executed_steps
    if final_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": final_screen.get("reason") or "tashuo_visual_capture_failed"})
    elif final_screen.get("visual_active_tab") != "mine" or final_screen.get("state") != "tashuo_self_profile":
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_self_profile_tab_not_verified",
            "next_host_action": "visual_analyze_current_screen",
        })
    return payload

def open_tashuo_self_profile_detail(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "open-self-profile-detail",
            "target": "tashuo_self_profile_detail",
            "reason": "tashuo_open_self_profile_detail_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    planned_steps = [
        {
            "intent": "prepare_tashuo_self_profile_page_top",
            "risk": "navigation_only",
            "does_not_edit_profile": True,
            "ocr_used": False,
        },
        {
            **_tashuo_action_steps("profile-scroll-up")[0],
            "intent": "wheel_tashuo_self_profile_to_avatar_top",
            "risk": "navigation_only",
            "does_not_edit_profile": True,
            "wait_after_seconds": 0.45,
        },
        {
            "intent": "tap_tashuo_self_profile_avatar",
            "tap_ratio": _copy_tap_ratio(TASHUO_SELF_PROFILE_AVATAR_TAP_RATIO),
            "risk": "read_only_profile_navigation",
            "does_not_tap_edit_profile": True,
            "wait_after_seconds": 0.6,
        },
        {
            "intent": "capture_tashuo_self_profile_detail",
            "risk": "visual_observation_only",
            "does_not_edit_profile": True,
            "ocr_used": False,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "action": "open-self-profile-detail",
        "target": "tashuo_self_profile_detail",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "visual_only_navigation": True,
        "ocr_used": False,
        "next_host_action": "extract_visible_self_profile_detail_facts",
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    prepare = prepare_tashuo_self_profile_page(session, dry_run=False, output_dir=output_dir)
    payload["self_profile_page_preparation"] = {
        "status": prepare.get("status"),
        "reason": prepare.get("reason"),
        "screen_state": prepare.get("screen_state"),
        "next_host_action": prepare.get("next_host_action"),
    }
    executed_steps: list[dict[str, Any]] = [
        {
            **planned_steps[0],
            "result": {
                "status": prepare.get("status"),
                "reason": prepare.get("reason"),
                "screen_state": prepare.get("screen_state"),
            },
        }
    ]
    if prepare.get("status") != "ok":
        payload.update({
            "status": "blocked" if prepare.get("status") == "blocked" else "needs_verification",
            "reason": prepare.get("reason") or "tashuo_self_profile_page_not_verified",
            "executed_steps": executed_steps,
            "next_host_action": prepare.get("next_host_action") or "visual_analyze_current_screen",
        })
        return payload

    refresh_result, window = _refresh_tashuo_mac_ios_window(session)
    payload["detail_page_window_refresh"] = refresh_result
    if refresh_result.get("status") != "ok" or window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "executed_steps": executed_steps,
            "next_host_action": "restore_tashuo_window_focus",
        })
        return payload

    scroll_result = session._execute_step(window, planned_steps[1])
    executed_steps.append({**planned_steps[1], "result": scroll_result})
    if scroll_result.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": scroll_result.get("reason") or "tashuo_self_profile_scroll_to_avatar_failed",
            "executed_steps": executed_steps,
        })
        return payload
    time.sleep(float(planned_steps[1]["wait_after_seconds"]))

    refresh_result, window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_profile_top_scroll",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "executed_steps": executed_steps,
            "next_host_action": "restore_tashuo_window_focus",
        })
        return payload

    tap_result = session._click_ratio(window, planned_steps[2]["tap_ratio"])
    executed_steps.append({**planned_steps[2], "result": tap_result})
    if tap_result.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": tap_result.get("reason") or "tashuo_self_profile_avatar_tap_failed",
            "executed_steps": executed_steps,
        })
        return payload
    time.sleep(float(planned_steps[2]["wait_after_seconds"]))

    refresh_result, window = _refresh_tashuo_mac_ios_window(session)
    executed_steps.append({
        "intent": "refresh_tashuo_mac_ios_window_after_avatar_tap",
        "risk": "navigation_only",
        "result": refresh_result,
    })
    if refresh_result.get("status") != "ok" or window is None:
        payload.update({
            "status": "blocked",
            "reason": refresh_result.get("reason") or "tashuo_window_refresh_failed",
            "executed_steps": executed_steps,
            "next_host_action": "restore_tashuo_window_focus",
        })
        return payload

    detail_output = output_dir / "mac_ios_app.tashuo.self_profile_detail.png" if output_dir is not None else None
    detail_screen = _capture_tashuo_window(session, output=detail_output, window=window, ocr=True)
    payload["screen"] = platform._redacted_screen(detail_screen)
    payload["screen_state"] = detail_screen.get("state", "unknown")
    executed_steps.append({
        **planned_steps[3],
        "result": {"status": "ok" if detail_screen.get("status") == "ok" else "blocked"},
    })
    payload["executed_steps"] = executed_steps
    if detail_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": detail_screen.get("reason") or "tashuo_visual_capture_failed"})
    elif detail_screen.get("state") != "tashuo_profile":
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_self_profile_detail_not_verified",
            "next_host_action": "visual_analyze_current_screen",
        })
    return payload

def scroll_tashuo_profile_read_mac_ios_app(
    session: Any,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    canonical_action = "profile-scroll-up" if action in {"profile-scroll-up", "profile_scroll_up"} else "profile-scroll-down"
    step = _tashuo_action_steps(canonical_action)[0]
    payload = {
        **session._base_payload("ok"),
        "action": canonical_action,
        "target": "tashuo_profile_read",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": [step],
        "visual_only_navigation": False,
        "ocr_used": True,
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
    before_output = output_dir / "mac_ios_app.tashuo.profile_scroll.before.png" if output_dir is not None else None
    before_screen = _capture_tashuo_window(session, output=before_output, window=window, ocr=True)
    payload["before_screen"] = platform._redacted_screen(before_screen)
    if before_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": before_screen.get("reason") or "tashuo_profile_scroll_preflight_capture_failed"})
        return payload
    if not _tashuo_profile_read_screen_verified(before_screen):
        payload.update({
            "status": "blocked",
            "reason": "tashuo_profile_scroll_precondition_not_verified",
            "screen_state": before_screen.get("state", "unknown"),
        })
        return payload

    result = session._execute_step(window, step)
    executed_steps = [{**step, "result": result}]
    payload["executed_steps"] = executed_steps
    if result.get("status") != "ok":
        payload.update({"status": "blocked", "reason": result.get("reason") or "tashuo_profile_scroll_failed"})
        return payload
    time.sleep(max(platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(step.get("wait_after_seconds", 0.0))))
    after_output = output_dir / "mac_ios_app.tashuo.profile_scroll.after.png" if output_dir is not None else None
    after_screen = _capture_tashuo_window(session, output=after_output, window=window, ocr=True)
    payload["verification"] = platform._redacted_screen(after_screen)
    payload["screen_state"] = after_screen.get("state", "unknown")
    if after_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": after_screen.get("reason") or "tashuo_profile_scroll_postcondition_capture_failed"})
    elif not _tashuo_profile_read_screen_verified(after_screen):
        payload.update({
            "status": "needs_verification",
            "reason": "tashuo_profile_scroll_postcondition_not_verified",
            "next_host_action": "visual_analyze_current_screen",
        })
    return payload

def scroll_tashuo_profile_to_bottom_mac_ios_app(
    session: Any,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    max_scrolls: int = TASHUO_PROFILE_BOTTOM_MAX_SCROLLS,
) -> dict[str, Any]:
    step = _tashuo_action_steps("profile-scroll-down")[0]
    max_scrolls = max(0, int(max_scrolls))
    payload = {
        **session._base_payload("ok"),
        "action": "profile-scroll-to-bottom",
        "target": "tashuo_profile_bottom",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": [
            {
                **step,
                "repeat_until": "tashuo_profile_bottom_anchor_verified",
                "max_scrolls": max_scrolls,
            }
        ],
        "ocr_used": True,
        "bottom_anchor": "分享给好友",
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
    attempts: list[dict[str, Any]] = []
    executed_steps: list[dict[str, Any]] = []

    initial_output = output_dir / "mac_ios_app.tashuo.profile_scroll_to_bottom.00.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=initial_output, window=window, ocr=True)
    attempts.append(_tashuo_profile_bottom_attempt(attempt=0, screen=screen))
    payload["attempts"] = attempts
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason") or "tashuo_profile_bottom_capture_failed"})
        return payload
    if not _tashuo_profile_read_screen_verified(screen):
        payload.update({
            "status": "blocked",
            "reason": "tashuo_profile_bottom_precondition_not_verified",
            "screen_state": screen.get("state", "unknown"),
        })
        return payload
    if _tashuo_profile_bottom_anchor_present(screen):
        payload.update(_tashuo_profile_bottom_success(screen=screen, attempts=attempts, executed_steps=executed_steps))
        return payload

    previous_fingerprints = {str(screen.get("text_fingerprint") or "")}
    for attempt in range(1, max_scrolls + 1):
        scroll_result = session._execute_step(window, step)
        executed_steps.append({**step, "result": scroll_result, "attempt": attempt})
        payload["executed_steps"] = executed_steps
        if scroll_result.get("status") != "ok":
            payload.update({"status": "blocked", "reason": scroll_result.get("reason") or "tashuo_profile_bottom_scroll_failed"})
            return payload
        time.sleep(max(platform.DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(step.get("wait_after_seconds", 0.0))))
        output = (
            output_dir / f"mac_ios_app.tashuo.profile_scroll_to_bottom.{attempt:02d}.png"
            if output_dir is not None
            else None
        )
        screen = _capture_tashuo_window(session, output=output, window=window, ocr=True)
        attempt_payload = _tashuo_profile_bottom_attempt(attempt=attempt, screen=screen, scroll_result=scroll_result)
        attempts.append(attempt_payload)
        if screen.get("status") != "ok":
            payload.update({"status": "blocked", "reason": screen.get("reason") or "tashuo_profile_bottom_capture_failed"})
            return payload
        if not _tashuo_profile_read_screen_verified(screen):
            payload.update({
                "status": "needs_verification",
                "reason": "tashuo_profile_bottom_postcondition_not_verified",
                "screen_state": screen.get("state", "unknown"),
                "next_host_action": "visual_analyze_current_screen",
            })
            return payload
        if _tashuo_profile_bottom_anchor_present(screen):
            payload.update(_tashuo_profile_bottom_success(screen=screen, attempts=attempts, executed_steps=executed_steps))
            return payload
        fingerprint = str(screen.get("text_fingerprint") or "")
        if fingerprint and fingerprint in previous_fingerprints:
            payload.update({
                "status": "needs_verification",
                "reason": "tashuo_profile_bottom_anchor_not_found_after_no_progress",
                "screen": platform._redacted_screen(screen),
                "screen_state": screen.get("state", "unknown"),
                "bottom_anchor_verified": False,
                "attempt_count": len(attempts),
                "next_host_action": "visual_analyze_current_screen",
            })
            return payload
        if fingerprint:
            previous_fingerprints.add(fingerprint)

    payload.update({
        "status": "needs_verification",
        "reason": "tashuo_profile_bottom_anchor_not_found",
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "bottom_anchor_verified": False,
        "attempt_count": len(attempts),
        "next_host_action": "visual_analyze_current_screen",
    })
    return payload

def _tashuo_profile_read_screen_verified(screen: dict[str, Any]) -> bool:
    if screen.get("status") != "ok":
        return False
    if screen.get("state") in {"tashuo_profile", "tashuo_self_profile", "tashuo_recommend"}:
        return True
    return _tashuo_profile_read_text_anchor_present(screen) or _tashuo_profile_bottom_anchor_present(screen)

def _tashuo_profile_read_text_anchor_present(screen: dict[str, Any]) -> bool:
    normalized = normalize_text(str(screen.get("text") or ""))
    compact = re.sub(r"\s+", "", normalized)
    if "我的资料" in compact:
        return True
    profile_mid_markers = (
        "更多信息",
        "有健身习惯",
        "不饮酒",
        "不吸烟",
        "我的恋爱三观",
        "查看详细解析",
        "我的心灵测试",
        "关于人生阶段",
        "当前人生阶段",
        "我的MBTI",
        "近期动态",
        "我在哪里",
    )
    return sum(1 for marker in profile_mid_markers if marker in compact) >= 2

def _tashuo_profile_bottom_anchor_present(screen: dict[str, Any]) -> bool:
    normalized = normalize_text(str(screen.get("text") or ""))
    compact = re.sub(r"\s+", "", normalized)
    return "分享给好友" in compact or ("分享" in compact and "好友" in compact)

def _tashuo_profile_bottom_attempt(
    *,
    attempt: int,
    screen: dict[str, Any],
    scroll_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "attempt": attempt,
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "bottom_anchor_verified": _tashuo_profile_bottom_anchor_present(screen),
    }
    if scroll_result is not None:
        payload["scroll_result"] = scroll_result
    return payload

def _tashuo_profile_bottom_success(
    *,
    screen: dict[str, Any],
    attempts: list[dict[str, Any]],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": "tashuo_profile_bottom_anchor_verified",
        "screen": platform._redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "bottom_anchor_verified": True,
        "attempt_count": len(attempts),
        "executed_steps": executed_steps,
        "next_host_action": "extract_visible_self_profile_detail_facts",
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
    '_capture_tashuo_visual_screen', '_click_tashuo_mine_radio_button', '_refresh_tashuo_mac_ios_window', 'prepare_tashuo_message_page',
    'prepare_tashuo_self_profile_page', 'open_tashuo_self_profile_detail', 'scroll_tashuo_profile_read_mac_ios_app', 'scroll_tashuo_profile_to_bottom_mac_ios_app',
    '_tashuo_profile_read_screen_verified', '_tashuo_profile_read_text_anchor_present', '_tashuo_profile_bottom_anchor_present', '_tashuo_profile_bottom_attempt',
    '_tashuo_profile_bottom_success',
]
