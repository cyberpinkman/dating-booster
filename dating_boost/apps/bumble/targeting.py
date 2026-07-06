from __future__ import annotations

from dating_boost.apps.iphone_targeting import (
    annotations, hashlib, _platform, copy,
    csv, datetime, timezone, io,
    re, struct, sys, tempfile,
    time, zlib, Path, Any,
    uuid4, SubprocessRunner, WindowInfo, _parse_window_info,
    _short, _window_from_payload, _click_iphone_mirroring_view_menu_item_backend, _core_graphics_click_backend,
    _core_graphics_command_v_backend, _core_graphics_drag_backend, _core_graphics_wheel_backend, BUMBLE_FOREGROUND_STATES,
    TINDER_FOREGROUND_STATES, WECHAT_FOREGROUND_STATES, _bumble_layout_hints, _bumble_top_level_bottom_nav_present,
    classify_bumble_screen_text, classify_bumble_screen_image, classify_screen_image, classify_screen_text,
    classify_wechat_screen_text, _combine_bumble_screen_states, _combine_screen_states, _read_png_pixels_for_send_button,
    _region_stats_for_send_button, _redacted_screen, _tinder_layout_hints, _tinder_profile_danger_action_visible,
    _tinder_profile_expand_control_visible, _tinder_profile_field_coverage, _wechat_layout_hints, bumble_target_binding_specific_marker_present,
    target_binding_structural_evidence_present, _expected_text_observation_stats, _hash_text, _message_text_comparable,
    _message_text_matches, _normalize_text, _outbound_text_ocr_evidence, _staged_text_ocr_evidence,
    _staged_text_visual_verification_request, _text_fingerprint_fields, _harness_step_validation_reason, GUI_HARNESS_SCHEMA_VERSION,
    IPHONE_MIRRORING_HARNESS_BACKEND, MAC_IOS_APP_HARNESS_BACKEND, WECHAT_HARNESS_BACKEND, HARNESS_BACKEND,
    _contains_cjk_text, direct_text_entry_block_reason, NativeGuiHarness, _applescript_string_literal,
    _ensure_ascii_input_source, _switch_ascii_input_source, _read_current_input_source, _input_source_id_is_ascii,
    _app_search_result_visible, _default_screenshot_path, _now_iso, _parse_mac_ios_process_probe,
    _parse_core_graphics_window_info, _parse_mac_ios_active_application_probe, _swift_string_literal, _mac_ios_running_application_lookup_script,
    _mac_ios_core_graphics_window_lookup_script, _mac_ios_window_failure_reason, mac_ios_window_failure_payload, _contains_host_appleevents_unavailable_error,
    _host_appleevents_unavailable_diagnostic, _looks_like_iphone_mirroring_window, _looks_like_mac_ios_app_window, EvidencePayload,
    PostSendVerification, SendAttemptContext, StagingResult, BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
    IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE, TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION, _bumble_action_steps, _bumble_profile_field_coverage,
    _bumble_tap_step, _bumble_workflow_steps, _copy_tap_ratio, _has_bumble_step_postcondition,
    _has_bumble_step_precondition, _int_in_range, _launch_app_steps, _launch_tinder_steps,
    _message_list_visual_anchor_evidence_from_options, _normalized_visual_anchor_region, _redacted_iphone_prepare_message_page_payload, _redacted_message_list_visual_anchor_evidence,
    _redacted_target_binding, _target_binding_primary_visible_name, _target_binding_required_markers, _tap_ratio_option,
    _tap_step, _tinder_feedback_survey_dismiss_step, _tinder_action_steps, _tinder_subscription_paywall_dismiss_step,
    _tinder_workflow_steps, _verify_bumble_step_state, _visual_anchor_hamming_distance, harness_step_validation_reason,
    RowToThreadBindingSpec, finish_row_to_thread_screen_verification, row_to_thread_base_result, validate_row_to_thread_structural_evidence,
    target_binding_specific_marker_present, BLOCKED_GUI_ACTIONS, WECHAT_BLOCKED_GUI_ACTIONS, BUMBLE_BLOCKED_GUI_ACTIONS,
    BUMBLE_SEND_BLOCKED_GUI_ACTIONS, BUMBLE_OPENING_MOVE_POLICY, TINDER_SUBSCRIPTION_PAYWALL_STATE, TINDER_FEEDBACK_SURVEY_STATE,
    DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y, IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
    IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE, IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS, capture_window, _execute_planned_steps,
    _locate_iphone_message_list_visual_anchor_target, _verify_open_conversation_target_binding_against_screen, _visible_text_contains_marker, _prepare_iphone_message_page,
    _recover_iphone_prepare_message_page_blocker, _finish_iphone_message_page_ready, _select_iphone_prepare_message_page_step, _execute_iphone_prepare_message_page_step,
    _open_conversation_by_message_list_visual_anchor, _preflight_iphone_visual_anchor_open_conversation, _navigate_iphone_to_visual_anchor_source, _relocate_and_tap_iphone_visual_anchor_target,
    _iphone_visual_anchor_tap_step, _verify_iphone_visual_anchor_open_conversation_target, _locate_visible_text_y_ratio, _ocr_tsv,
    _visible_text_location_from_tsv, _recover_iphone_current_thread_visual_identity_mismatch, _iphone_visual_identity_relocation_preflight, _run_iphone_visual_identity_relocation_attempts,
    _iphone_visual_identity_relocation_attempt_blocked_payload, _iphone_visual_identity_relocation_exhausted_payload, _run_iphone_visual_identity_relocation_attempt, _locate_iphone_visual_identity_relocation_target,
    _iphone_relocation_open_target_tap_step, _verify_iphone_current_thread_visual_identity, _verify_chat_list_row_target_binding, _iphone_message_list_visual_anchor_scan_setup,
    _scan_iphone_message_list_visual_anchor_candidates, _finish_iphone_message_list_visual_anchor_location, _safe_iphone_message_list_visual_anchor_tap_ratio, _iphone_visual_anchor_hash_for_pixels,
    _iphone_visual_anchor_hash_for_path, _iphone_current_thread_visual_anchor, _verify_target_binding_against_screen, _iphone_already_sent_payload_update,
    _iphone_already_sent_idempotency_allowed, _iphone_stage_needs_user_verification, _iphone_stage_draft_payload_update, _iphone_pre_stage_input_guard,
    _verify_outbound_message, _screen_region_stats,
)


def _bumble_guardrails_payload() -> dict[str, Any]:
    return {
        "blocked_actions": list(BUMBLE_BLOCKED_GUI_ACTIONS),
        "opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY),
    }

def _open_bumble_conversation_by_visible_name(
    self,
    *,
    visible_name: str,
    target_binding: dict[str, Any] | None = None,
    output_dir: Path | None = None,
    max_scrolls: int = 3,
) -> dict[str, Any]:
    marker = visible_name.strip()
    if not marker:
        return {
            **self._base_payload("blocked"),
            "action": "open-conversation",
            "reason": "visible_conversation_marker_required",
            **_bumble_guardrails_payload(),
        }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    marker_hash = _hash_text(marker)
    payload: dict[str, Any] = {
        **self._base_payload("ok"),
        "action": "open-conversation",
        "mode": "execute",
        "open_mode": "visible_name",
        "target_marker_hash": marker_hash,
        "target_binding": _redacted_target_binding(target_binding) if target_binding is not None else None,
        "planned_steps": _bumble_action_steps("open-conversation", visible_name=marker),
        **_bumble_guardrails_payload(),
    }
    before = output_dir / "iphone_mirroring.bumble.open_conversation.before.png" if output_dir is not None else None
    doctor = self.doctor(capture=True, output=before)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    window = _window_from_payload(doctor.get("window") or {})
    screen_state = doctor.get("screen", {}).get("state")

    executed_steps: list[dict[str, Any]] = []
    if screen_state != "bumble_chat_list":
        if screen_state not in BUMBLE_FOREGROUND_STATES:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "bumble_foreground_not_verified",
                    "screen_state": screen_state,
                }
            )
            return payload
        open_chats_step = _bumble_action_steps("open-chats")[0]
        open_chats_result = self._execute_step(window, open_chats_step)
        executed_steps.append({**open_chats_step, "result": open_chats_result})
        if open_chats_result.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": open_chats_result.get("reason") or "open_chats_failed",
                    "executed_steps": executed_steps,
                }
            )
            return payload
        time.sleep(float(open_chats_step.get("wait_after_seconds", 0.2)))

    search_attempts: list[dict[str, Any]] = []
    for attempt in range(max_scrolls + 1):
        search_output = (
            output_dir / f"iphone_mirroring.bumble.conversation_search_{attempt + 1:02d}.png"
            if output_dir is not None
            else None
        )
        screen = self.capture_window(output=search_output, window=window)
        locator = self._locate_visible_text_y_ratio(screen, marker)
        search_attempts.append(
            {
                "attempt": attempt + 1,
                "screen": _redacted_screen(screen),
                "locator": locator,
            }
        )
        if screen.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": screen.get("reason") or "conversation_list_screen_capture_failed",
                    "executed_steps": executed_steps,
                    "search_attempts": search_attempts,
                }
            )
            return payload
        if screen.get("state") != "bumble_chat_list":
            payload.update(
                {
                    "status": "blocked",
                    "reason": "bumble_chat_list_not_verified",
                    "screen_state": screen.get("state"),
                    "executed_steps": executed_steps,
                    "search_attempts": search_attempts,
                }
            )
            return payload
        if locator.get("status") == "ok":
            y_ratio = float(locator["y_ratio"])
            if not 0.38 <= y_ratio <= 0.88:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "visible_conversation_marker_outside_message_list",
                        "executed_steps": executed_steps,
                        "search_attempts": search_attempts,
                    }
                )
                return payload
            tap_step = {
                **_bumble_tap_step(
                    "tap_bumble_visible_conversation_row",
                    x=0.43,
                    y=y_ratio,
                    requires_states="bumble_chat_list",
                    expected_states="bumble_conversation",
                ),
                "target_marker_hash": marker_hash,
                "location_method": "ocr_tsv_visible_text",
            }
            tap_result = self._execute_step(window, tap_step)
            executed_steps.append({**tap_step, "result": tap_result})
            if tap_result.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": tap_result.get("reason") or "tap_visible_conversation_row_failed",
                        "executed_steps": executed_steps,
                        "search_attempts": search_attempts,
                    }
                )
                return payload
            time.sleep(float(tap_step.get("wait_after_seconds", 0.2)))
            verification_output = (
                output_dir / "iphone_mirroring.bumble.open_conversation.after_tap.png"
                if output_dir is not None
                else None
            )
            verification_screen = self.capture_window(output=verification_output, window=window)
            payload["verification"] = _redacted_screen(verification_screen)
            payload["executed_steps"] = executed_steps
            payload["search_attempts"] = search_attempts
            if verification_screen.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": verification_screen.get("reason") or "open_conversation_verification_failed",
                    }
                )
                return payload
            if verification_screen.get("state") == "bumble_opening_move":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "bumble_opening_move_requires_user_confirmation",
                        "next_host_action": "ask_user_to_confirm_opening_move_reply",
                    }
                )
                return payload
            if verification_screen.get("state") != "bumble_conversation":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "target_conversation_not_verified",
                        "screen_state": verification_screen.get("state"),
                    }
                )
                return payload
            target_result = _verify_target_binding_against_screen(
                target_binding,
                verification_screen,
                fallback_marker=marker,
                verification_method="bumble_open_conversation_visible_name",
                conversation_state="bumble_conversation",
                blocked_state_reasons={"bumble_opening_move": "bumble_opening_move_requires_user_confirmation"},
            )
            payload["target_binding_verification"] = target_result
            if target_result.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": target_result.get("reason") or "target_binding_mismatch",
                    }
                )
                return payload
            return payload
        if attempt >= max_scrolls:
            break
        scroll_step = _bumble_action_steps("conversation-list-scroll-down")[0]
        scroll_result = self._execute_step(window, scroll_step)
        executed_steps.append({**scroll_step, "result": scroll_result})
        if scroll_result.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": scroll_result.get("reason") or "conversation_list_scroll_failed",
                    "executed_steps": executed_steps,
                    "search_attempts": search_attempts,
                }
            )
            return payload
        time.sleep(float(scroll_step.get("wait_after_seconds", 0.2)))
    payload.update(
        {
            "status": "blocked",
            "reason": "visible_conversation_marker_not_found",
            "next_host_action": "open_chats_and_search_visible_conversation",
            "executed_steps": executed_steps,
            "search_attempts": search_attempts,
        }
    )
    return payload

def _open_bumble_conversation_by_visual_anchor(
    self,
    *,
    visual_evidence: dict[str, Any],
    target_binding: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    return self._open_conversation_by_message_list_visual_anchor(
        app_id="bumble",
        visual_evidence=visual_evidence,
        target_binding=target_binding,
        output_dir=output_dir,
        chat_list_state="bumble_chat_list",
        conversation_state="bumble_conversation",
        foreground_states=BUMBLE_FOREGROUND_STATES,
        open_chats_step=_bumble_action_steps("open-chats")[0],
        return_to_chats_step=_bumble_action_steps("return-to-chats")[0],
        planned_steps=_bumble_action_steps(
            "open-conversation",
            message_list_evidence=visual_evidence,
            target_binding=target_binding,
        ),
        tap_intent="tap_bumble_visible_conversation_row",
        tap_x=0.43,
        tap_y_min=0.38,
        tap_y_max=0.88,
        output_prefix="iphone_mirroring.bumble",
        verification_method="bumble_open_conversation_visual_anchor",
        source_states={"bumble_chat_list"},
        blocked_state_reasons={"bumble_opening_move": "bumble_opening_move_requires_user_confirmation"},
        guardrails=_bumble_guardrails_payload(),
    )

def _verify_bumble_target_binding(
    self,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if target_binding.get("binding_type") == "current_thread_visual_identity":
        return self._verify_iphone_current_thread_visual_identity(
            app_id="bumble",
            target_binding=target_binding,
            output_dir=output_dir,
            conversation_state="bumble_conversation",
            blocked_state_reasons={"bumble_opening_move": "bumble_opening_move_requires_user_confirmation"},
            output_name="iphone_mirroring.bumble.target_binding.png",
            verification_method="bumble_current_thread_visual_identity",
        )
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        return self._verify_chat_list_row_target_binding(
            app_id="bumble",
            target_binding=target_binding,
            output_dir=output_dir,
            source_states={"bumble_chat_list"},
            conversation_state="bumble_conversation",
            blocked_state_reasons={"bumble_opening_move": "bumble_opening_move_requires_user_confirmation"},
            output_name="iphone_mirroring.bumble.target_binding.png",
            verification_method="bumble_chat_list_row_to_thread_structural_binding",
        )

    markers = _target_binding_required_markers(target_binding)
    base = {
        "verification_method": "bumble_screen_ocr_required_visible_text",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "required_marker_hashes": [_hash_text(marker) for marker in markers],
        "requires_target_specific_marker": True,
    }
    if not markers:
        return {**base, "status": "blocked", "reason": "target_binding_required"}
    if not bumble_target_binding_specific_marker_present(target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_not_target_specific"}
    window = self._window_info()
    if window is None:
        return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
    output = output_dir / "iphone_mirroring.bumble.target_binding.png" if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    observed_text = str(screen.get("text") or "")
    normalized = _normalize_text(observed_text)
    matched = [marker for marker in markers if _normalize_text(marker) in normalized]
    result = {
        **base,
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        "matched_marker_hashes": [_hash_text(marker) for marker in matched],
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "bumble_opening_move":
        return {**result, "status": "blocked", "reason": "bumble_opening_move_requires_user_confirmation"}
    if screen.get("state") != "bumble_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    return {**result, "status": "ok"}

def _recover_bumble_current_thread_visual_identity_mismatch(
    self,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
    target_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return self._recover_iphone_current_thread_visual_identity_mismatch(
        app_id="bumble",
        target_binding=target_binding,
        target_verification=target_verification,
        output_dir=output_dir,
        chat_list_state="bumble_chat_list",
        conversation_state="bumble_conversation",
        foreground_states=BUMBLE_FOREGROUND_STATES,
        open_chats_step=_bumble_action_steps("open-chats")[0],
        return_to_chats_step=_bumble_action_steps("return-to-chats")[0],
        secondary_close_steps={"bumble_profile": _bumble_action_steps("close-profile")[0]},
        guardrails=_bumble_guardrails_payload(),
        layout_hints_fn=_bumble_layout_hints,
        message_list_visual_anchor_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        blocked_state_reasons={"bumble_opening_move": "bumble_opening_move_requires_user_confirmation"},
        tap_intent="tap_bumble_relocated_visual_conversation_target",
        tap_x=0.43,
        tap_y_min=0.38,
        tap_y_max=0.88,
        output_prefix="iphone_mirroring.bumble",
        verify_target_binding=self._verify_bumble_target_binding,
    )
