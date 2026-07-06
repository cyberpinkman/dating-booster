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

def stage_bumble_draft(
    self,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    return self.send_bumble_message(
        draft_text,
        dry_run=dry_run,
        output_dir=output_dir,
        stage_only=True,
    )


def _bumble_send_steps(stage_only: bool) -> dict[str, Any]:
    risk = "draft_staging_only" if stage_only else "live_send_precondition"
    input_step = {
        "intent": "tap_bumble_message_input",
        "tap_ratio": {"x": 0.45, "y": 0.92},
        "risk": risk,
        "requires_verified_bumble_thread": True,
        "does_not_send": stage_only,
    }
    paste_step = {
        "intent": "paste_clipboard_into_bumble_message_input",
        "risk": risk,
        "requires_exact_text_match": True,
        "does_not_send": stage_only,
    }
    type_fallback_step = {
        "intent": "type_bumble_message_input_if_paste_did_not_stage",
        "risk": risk,
        "fallback_only": True,
        "requires_ascii_draft": True,
        "requires_exact_text_verification_after_direct_type": True,
        "does_not_send": stage_only,
    }
    ime_commit_step = {
        "intent": "commit_bumble_message_input_ime_candidate_if_needed",
        "risk": risk,
        "fallback_only": True,
        "requires_failed_direct_type_verification": True,
        "requires_exact_text_verification_after_commit": True,
        "does_not_send": stage_only,
    }
    send_step = {
        "intent": "tap_bumble_send_button",
        "tap_ratio": {"x": 0.94, "y": 0.92},
        "risk": "live_send",
        "requires_explicit_authorization": True,
        "visual_only_exact_verification_allowed": False,
    }
    planned_steps = (input_step, paste_step, type_fallback_step, ime_commit_step)
    if not stage_only:
        planned_steps = (*planned_steps, send_step)
    return {
        "input": input_step,
        "paste": paste_step,
        "type_fallback": type_fallback_step,
        "ime_commit": ime_commit_step,
        "send": send_step,
        "planned": planned_steps,
    }


def _initial_bumble_send_payload(
    self: Any,
    *,
    draft_text: str,
    dry_run: bool,
    stage_only: bool,
    planned_steps: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    payload = SendAttemptContext(
        action="stage_draft" if stage_only else "send_message",
        target="bumble_message_input",
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=planned_steps,
        blocked_actions=tuple(BUMBLE_SEND_BLOCKED_GUI_ACTIONS),
        extra_fields={"opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY)},
    ).initial_payload(self._base_payload("ok"))
    if stage_only:
        payload["requires_user_confirmation_before_send"] = True
    return payload


def _prepare_bumble_send_context(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preflight_output = output_dir / "iphone_mirroring.bumble.before_send_message.png" if output_dir is not None else None
    preflight = self.doctor(capture=True, output=preflight_output)
    payload["preflight"] = preflight
    if preflight.get("status") != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "bumble_preflight_not_verified"})
        return {"return_payload": payload}
    window = _window_from_payload(preflight.get("window") or {})
    preflight_screen = preflight.get("screen") if isinstance(preflight.get("screen"), dict) else {}
    if preflight_screen.get("state") == "bumble_opening_move":
        payload.update({
            "status": "blocked",
            "reason": "bumble_opening_move_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_opening_move_reply",
        })
        return {"return_payload": payload}
    if preflight_screen.get("state") != "bumble_conversation":
        payload.update({"status": "blocked", "reason": "bumble_conversation_not_verified"})
        return {"return_payload": payload}

    if target_binding is not None:
        target_verification = self._verify_bumble_target_binding(target_binding, output_dir=output_dir)
        payload["target_binding_verification"] = target_verification
        if target_verification.get("status") != "ok":
            relocation = self._recover_bumble_current_thread_visual_identity_mismatch(
                target_binding,
                output_dir=output_dir,
                target_verification=target_verification,
            )
            payload["target_binding_relocation"] = relocation
            if relocation.get("status") == "ok":
                payload["target_binding_verification"] = relocation.get("target_binding_verification", target_verification)
            else:
                payload.update({
                    "status": "blocked",
                    "reason": relocation.get("reason") or target_verification.get("reason") or "target_binding_mismatch",
                })
                return {"return_payload": payload}

    baseline_output = output_dir / "iphone_mirroring.bumble.before_stage_message.png" if output_dir is not None else None
    baseline_screen = self.capture_window(output=baseline_output, window=window)
    payload["pre_stage_observation"] = _redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return {"return_payload": payload}
    if baseline_screen.get("state") == "bumble_opening_move":
        payload.update({
            "status": "blocked",
            "reason": "bumble_opening_move_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_opening_move_reply",
        })
        return {"return_payload": payload}
    if baseline_screen.get("state") != "bumble_conversation":
        payload.update({"status": "blocked", "reason": "bumble_conversation_not_verified"})
        return {"return_payload": payload}

    already_sent_verification = (
        _verify_bumble_outbound_message(baseline_screen, draft_text)
        if _iphone_already_sent_idempotency_allowed(target_binding)
        else {"status": "not_run", "reason": "current_thread_visual_identity_required"}
    )
    if already_sent_verification.get("status") == "ok":
        payload.update(
            _iphone_already_sent_payload_update(
                payload,
                screen=baseline_screen,
                outbound_verification=already_sent_verification,
                conversation_state="bumble_conversation",
            )
        )
        return {"return_payload": payload}

    return {"window": window, "baseline_screen": baseline_screen}


def _stage_bumble_send_input(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    target_binding: dict[str, Any] | None,
    stage_only: bool,
    window: Any,
    baseline_screen: dict[str, Any],
    steps: dict[str, Any],
) -> dict[str, Any]:
    input_step = steps["input"]
    paste_step = steps["paste"]
    type_fallback_step = steps["type_fallback"]
    ime_commit_step = steps["ime_commit"]

    prepared = _prepare_bumble_stage_clipboard(self, payload, draft_text, baseline_screen)
    if prepared.get("return_payload") is not None:
        return prepared
    previous_clipboard = prepared["previous_clipboard"]

    executed_steps: list[dict[str, Any]] = []
    try:
        staged = _paste_and_verify_bumble_stage_input(
            self,
            payload,
            draft_text,
            output_dir=output_dir,
            target_binding=target_binding,
            stage_only=stage_only,
            window=window,
            baseline_screen=baseline_screen,
            input_step=input_step,
            paste_step=paste_step,
            type_fallback_step=type_fallback_step,
            ime_commit_step=ime_commit_step,
            executed_steps=executed_steps,
        )
        if staged.get("return_payload") is not None:
            return staged
    finally:
        restore_result = self._copy_to_clipboard(previous_clipboard.get("text", ""))
        payload["clipboard_restored"] = restore_result["status"] == "ok"
        payload["clipboard_restore_status"] = restore_result["status"]
        if restore_result["status"] != "ok":
            payload["clipboard_restore_reason"] = restore_result.get("reason")

    if payload["clipboard_restored"] is not True:
        payload.update({
            "status": "blocked",
            "reason": "clipboard_restore_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}

    return {
        "executed_steps": executed_steps,
        "staged_screen": staged["staged_screen"],
        "staged_verification": staged["staged_verification"],
        "stage_send_input_backend": payload.get("staging_input_backend") or staged["paste_result"].get("input_backend"),
    }


def _prepare_bumble_stage_clipboard(
    self,
    payload: dict[str, Any],
    draft_text: str,
    baseline_screen: dict[str, Any],
) -> dict[str, Any]:
    pre_stage_input_guard = _bumble_pre_stage_input_guard(baseline_screen, draft_text)
    payload["pre_stage_input_guard"] = pre_stage_input_guard
    if pre_stage_input_guard.get("status") == "blocked":
        payload.update({
            "status": "blocked",
            "reason": pre_stage_input_guard.get("reason") or "message_input_not_empty_before_staging",
            "next_host_action": "clear_existing_message_input_before_stage",
            "staged_text_verified": False,
            "executed_steps": [],
        })
        return {"return_payload": payload}

    previous_clipboard = self._read_clipboard()
    payload["previous_clipboard_read"] = previous_clipboard["status"] == "ok"
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard.get("reason")})
        return {"return_payload": payload}
    payload.update(_text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))
    copy_result = self._copy_to_clipboard(draft_text)
    payload["draft_clipboard_copy"] = copy_result["status"] == "ok"
    if copy_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": copy_result.get("reason")})
        return {"return_payload": payload}
    return {"previous_clipboard": previous_clipboard}


def _paste_and_verify_bumble_stage_input(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    target_binding: dict[str, Any] | None,
    stage_only: bool,
    window: Any,
    baseline_screen: dict[str, Any],
    input_step: dict[str, Any],
    paste_step: dict[str, Any],
    type_fallback_step: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    initial = _paste_bumble_stage_input(
        self,
        payload,
        draft_text,
        output_dir=output_dir,
        window=window,
        baseline_screen=baseline_screen,
        input_step=input_step,
        paste_step=paste_step,
        executed_steps=executed_steps,
    )
    if initial.get("return_payload") is not None:
        return initial
    fallback = _bumble_stage_direct_type_fallback_if_needed(
        self,
        payload,
        draft_text,
        output_dir=output_dir,
        window=window,
        baseline_screen=baseline_screen,
        staged_screen=initial["staged_screen"],
        staged_verification=initial["staged_verification"],
        type_fallback_step=type_fallback_step,
        ime_commit_step=ime_commit_step,
        executed_steps=executed_steps,
    )
    if fallback.get("return_payload") is not None:
        return fallback
    staged_screen = fallback["staged_screen"]
    staged_verification = fallback["staged_verification"]
    finish = _finish_bumble_stage_verification(
        payload,
        draft_text,
        stage_only=stage_only,
        target_binding=target_binding,
        staged_screen=staged_screen,
        staged_verification=staged_verification,
        paste_result=initial["paste_result"],
        executed_steps=executed_steps,
    )
    if finish.get("return_payload") is not None:
        return finish
    return {
        "staged_screen": staged_screen,
        "staged_verification": staged_verification,
        "paste_result": initial["paste_result"],
    }


def _paste_bumble_stage_input(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    window: Any,
    baseline_screen: dict[str, Any],
    input_step: dict[str, Any],
    paste_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    input_result = self._click_ratio(window, input_step["tap_ratio"])
    executed_steps.append({**input_step, "result": input_result})
    if input_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
        return {"return_payload": payload}
    time.sleep(0.45)

    paste_result = self._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
    executed_steps.append({**paste_step, "result": paste_result})
    if paste_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
        return {"return_payload": payload}
    time.sleep(0.3)

    staged_output = output_dir / "iphone_mirroring.bumble.after_stage_message.png" if output_dir is not None else None
    staged_screen = self.capture_window(output=staged_output, window=window)
    staged_verification = _verify_staged_bumble_message(
        staged_screen,
        draft_text,
        baseline_screen=baseline_screen,
    )
    return {"staged_screen": staged_screen, "staged_verification": staged_verification, "paste_result": paste_result}


def _bumble_stage_direct_type_fallback_if_needed(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    window: Any,
    baseline_screen: dict[str, Any],
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    type_fallback_step: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if not (
        staged_verification.get("status") != "ok"
        and _bumble_direct_type_fallback_allowed(draft_text)
        and not _bumble_active_send_button_visual_visible(staged_screen)
    ):
        return {"staged_screen": staged_screen, "staged_verification": staged_verification}

    type_result = self._type_text_into_frontmost_app(draft_text)
    executed_steps.append({**type_fallback_step, "result": type_result})
    if type_result["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": type_result.get("reason") or "direct_text_entry_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(0.3)
    staged_output = output_dir / "iphone_mirroring.bumble.after_type_message.png" if output_dir is not None else None
    staged_screen = self.capture_window(output=staged_output, window=window)
    staged_verification = _verify_staged_bumble_message(
        staged_screen,
        draft_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=True,
    )
    if (
        staged_verification.get("status") != "ok"
        and not _bumble_active_send_button_visual_visible(staged_screen)
    ):
        committed = _bumble_commit_ime_after_direct_type(
            self,
            payload,
            draft_text,
            output_dir=output_dir,
            window=window,
            baseline_screen=baseline_screen,
            ime_commit_step=ime_commit_step,
            executed_steps=executed_steps,
        )
        if committed.get("return_payload") is not None:
            return committed
        staged_screen = committed["staged_screen"]
        staged_verification = committed["staged_verification"]
    payload["staging_input_backend"] = type_result.get("input_backend")
    return {"staged_screen": staged_screen, "staged_verification": staged_verification}


def _bumble_commit_ime_after_direct_type(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    window: Any,
    baseline_screen: dict[str, Any],
    ime_commit_step: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    ime_commit_result = self._press_space_key()
    executed_steps.append({**ime_commit_step, "result": ime_commit_result})
    if ime_commit_result["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": ime_commit_result.get("reason") or "ime_commit_space_failed",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    time.sleep(0.3)
    staged_output = output_dir / "iphone_mirroring.bumble.after_ime_commit_message.png" if output_dir is not None else None
    staged_screen = self.capture_window(output=staged_output, window=window)
    staged_verification = _verify_staged_bumble_message(
        staged_screen,
        draft_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=True,
    )
    return {"staged_screen": staged_screen, "staged_verification": staged_verification}


def _finish_bumble_stage_verification(
    payload: dict[str, Any],
    draft_text: str,
    *,
    stage_only: bool,
    target_binding: dict[str, Any] | None,
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    paste_result: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    payload["staged_text_verification"] = staged_verification
    payload["staged_text_verified"] = staged_verification.get("status") == "ok"
    if staged_verification.get("status") != "ok":
        if stage_only and staged_verification.get("status") == "needs_verification":
            payload.update(
                _iphone_stage_draft_payload_update(
                    staged_screen=staged_screen,
                    staged_verification=_iphone_stage_needs_user_verification(staged_verification),
                    executed_steps=executed_steps,
                    conversation_state="bumble_conversation",
                    send_input_backend=payload.get("staging_input_backend") or paste_result.get("input_backend"),
                )
            )
            return {"return_payload": payload}
        payload.update({
            "status": "blocked",
            "reason": staged_verification.get("reason") or "staged_text_not_verified",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    if _bumble_staged_text_requires_host_visual_verification(
        staged_verification,
        draft_text,
        target_binding=target_binding,
        screen=staged_screen,
    ):
        payload["visual_verification_request"] = _bumble_visual_staged_verification_request(
            staged_screen,
            staged_verification,
            draft_text,
        )
        if stage_only:
            payload.update(
                _iphone_stage_draft_payload_update(
                    staged_screen=staged_screen,
                    staged_verification=_iphone_stage_needs_user_verification(
                        staged_verification,
                        reason="staged_text_requires_visual_verification",
                    ),
                    executed_steps=executed_steps,
                    conversation_state="bumble_conversation",
                    send_input_backend=payload.get("staging_input_backend") or paste_result.get("input_backend"),
                )
            )
            return {"return_payload": payload}
        payload.update({
            "status": "needs_host_visual_verification",
            "reason": "staged_text_requires_visual_verification",
            "next_host_action": "visually_verify_staged_text_before_live_send",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    return {}


def _complete_bumble_send(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None,
    stage_only: bool,
    window: Any,
    steps: dict[str, Any],
    executed_steps: list[dict[str, Any]],
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    stage_send_input_backend: Any,
) -> dict[str, Any]:
    send_step = steps["send"]
    if stage_only:
        payload.update(
            _iphone_stage_draft_payload_update(
                staged_screen=staged_screen,
                staged_verification=staged_verification,
                executed_steps=executed_steps,
                conversation_state="bumble_conversation",
                send_input_backend=stage_send_input_backend,
            )
        )
        return payload

    send_result = self._click_ratio(window, send_step["tap_ratio"])
    executed_steps.append({**send_step, "result": send_result})
    payload["executed_steps"] = executed_steps
    if send_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": send_result.get("reason")})
        return payload

    time.sleep(0.5)
    post_output = output_dir / "iphone_mirroring.bumble.after_send_message.png" if output_dir is not None else None
    post_screen = self.capture_window(output=post_output, window=window)
    payload["post_action_observation"] = _redacted_screen(post_screen)
    payload["current_thread_visual_anchor"] = _iphone_current_thread_visual_anchor(
        post_screen,
        conversation_state="bumble_conversation",
    )
    post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or _now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    payload["post_action_observation_id"] = post_observation_id
    post_screen_captured = post_screen.get("status") == "ok"
    outbound_verification = _verify_bumble_outbound_message(
        post_screen,
        draft_text,
        staged_screen=staged_screen,
        trusted_direct_input=payload.get("staging_input_backend") == "applescript_direct_keystroke",
    )
    payload["outbound_message_verification"] = outbound_verification
    outbound_verified = outbound_verification.get("status") == "ok"
    input_cleared = bool(outbound_verification.get("input_cleared_after_send"))
    payload["evidence"] = EvidencePayload(
        staging=StagingResult.from_verification(
            staged_verification,
            staged_text_verified=bool(payload.get("staged_text_verified")),
        ),
        post_send=PostSendVerification(
            post_action_observation_id=post_observation_id,
            input_cleared_after_send=input_cleared,
            post_action_screen_captured=post_screen_captured,
            outbound_message_verified=outbound_verified,
        ),
        send_input_backend=send_result.get("input_backend"),
        extra_fields={
            "outbound_exact_text_ocr_verified": bool(outbound_verification.get("exact_text_ocr_verified")),
            "visual_only_exact_verification_allowed": False,
        },
    ).to_dict()
    if not post_screen_captured:
        payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
    elif not input_cleared:
        payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
    elif not outbound_verified:
        payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
    return payload


def send_bumble_message(
    self,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
    stage_only: bool = False,
) -> dict[str, Any]:
    steps = _bumble_send_steps(stage_only)
    payload = _initial_bumble_send_payload(
        self,
        draft_text=draft_text,
        dry_run=dry_run,
        stage_only=stage_only,
        planned_steps=steps["planned"],
    )
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    prepared = _prepare_bumble_send_context(
        self,
        payload,
        draft_text,
        output_dir=output_dir,
        target_binding=target_binding,
    )
    if prepared.get("return_payload") is not None:
        return prepared["return_payload"]

    staged = _stage_bumble_send_input(
        self,
        payload,
        draft_text,
        output_dir=output_dir,
        target_binding=target_binding,
        stage_only=stage_only,
        window=prepared["window"],
        baseline_screen=prepared["baseline_screen"],
        steps=steps,
    )
    if staged.get("return_payload") is not None:
        return staged["return_payload"]

    return _complete_bumble_send(
        self,
        payload,
        draft_text,
        output_dir=output_dir,
        stage_only=stage_only,
        window=prepared["window"],
        steps=steps,
        executed_steps=staged["executed_steps"],
        staged_screen=staged["staged_screen"],
        staged_verification=staged["staged_verification"],
        stage_send_input_backend=staged["stage_send_input_backend"],
    )

def _verify_staged_bumble_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    active_send_button_visible = _bumble_active_send_button_visual_visible(screen)
    result = _staged_text_ocr_evidence(
        verification_method="bumble_staged_message_ocr_payload_text",
        observed_text=observed_text,
        expected_text=expected_text,
        baseline_text=baseline_text,
        screen=screen,
        redact_screen=_redacted_screen,
        extra={"active_send_button_visual_visible": active_send_button_visible},
    )
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "bumble_opening_move":
        return {**result, "status": "blocked", "reason": "bumble_opening_move_requires_user_confirmation"}
    baseline_state = baseline_screen.get("state") if isinstance(baseline_screen, dict) else None
    if screen.get("state") != "bumble_conversation" and baseline_state != "bumble_conversation":
        return {**result, "status": "blocked", "reason": "bumble_conversation_not_verified"}
    if not result["exact_text_ocr_verified"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if (
        result["baseline_expected_text_occurrences"] is not None
        and result["observed_expected_text_occurrences"] <= result["baseline_expected_text_occurrences"]
    ):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    if not _bumble_send_marker_visible(observed_text) and not active_send_button_visible:
        return {**result, "status": "needs_verification", "reason": "bumble_send_button_not_verified_after_staging"}
    return {**result, "status": "ok"}

def _bumble_staged_text_requires_host_visual_verification(
    staged_verification: dict[str, Any],
    expected_text: str,
    *,
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
) -> bool:
    if staged_verification.get("status") != "ok":
        return False
    if screen.get("status") != "ok" or not screen.get("path"):
        return False
    if not isinstance(target_binding, dict) or target_binding.get("binding_type") != "chat_list_row_to_thread":
        return False
    comparable_expected = _message_text_comparable(expected_text)
    if len(comparable_expected) > 3:
        return False
    baseline_occurrences = int(staged_verification.get("baseline_expected_text_occurrences") or 0)
    observed_occurrences = int(staged_verification.get("observed_expected_text_occurrences") or 0)
    return baseline_occurrences > 0 and observed_occurrences > baseline_occurrences

def _bumble_visual_staged_verification_request(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    return _staged_text_visual_verification_request(
        screen=screen,
        staged_verification=staged_verification,
        expected_text=expected_text,
        instructions="Visually inspect the focused Bumble input and confirm it exactly matches the current payload before any live send. Do not treat a short repeated OCR token elsewhere in the thread as enough evidence.",
    )

def _verify_bumble_outbound_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    staged_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
) -> dict[str, Any]:
    result = _verify_outbound_message(screen, expected_text)
    observed_text = str(screen.get("text") or "")
    staged_text = str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    observed_stats = _expected_text_observation_stats(observed_text, expected_text)
    staged_stats = _expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    outgoing_bubble_visible = _bumble_outgoing_bubble_visual_visible(screen)
    staged_outgoing_bubble_visible = (
        _bumble_outgoing_bubble_visual_visible(staged_screen) if isinstance(staged_screen, dict) else False
    )
    extra = {
        "verification_method": "bumble_post_send_ocr_payload_text_delta",
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
        "input_cleared_after_send": not _bumble_send_marker_visible(observed_text)
        and not _bumble_active_send_button_visual_visible(screen),
        "outgoing_bubble_visual_visible": outgoing_bubble_visible,
        "staged_outgoing_bubble_visual_visible": staged_outgoing_bubble_visible,
        "exact_text_ocr_verified": result.get("status") == "ok",
        "visual_only_exact_verification_allowed": False,
    }
    if result.get("status") != "ok":
        return {**result, **extra}
    if screen.get("state") != "bumble_conversation":
        return {**result, **extra, "status": "needs_verification", "reason": "bumble_conversation_not_verified"}
    if extra["input_cleared_after_send"] is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}

def _bumble_send_marker_visible(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped in {"send", "发送"}:
            return True
    return False

def _bumble_pre_stage_input_guard(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    guard = _iphone_pre_stage_input_guard(
        app_id="bumble",
        screen=screen,
        expected_text=expected_text,
    )
    active_send_button_visible = _bumble_active_send_button_visual_visible(screen)
    guard["active_send_button_visual_visible"] = active_send_button_visible
    if active_send_button_visible:
        guard.update({
            "status": "blocked",
            "reason": "message_input_not_empty_before_staging",
        })
    return guard

def _bumble_active_send_button_visual_visible(screen: dict[str, Any]) -> bool:
    stats = _screen_region_stats(screen, 0.88, 0.89, 0.98, 0.96)
    if stats is None:
        return False
    return stats["color_ratio"] > 0.08 and stats["bright_ratio"] > 0.45

def _bumble_outgoing_bubble_visual_visible(screen: dict[str, Any] | None) -> bool:
    if not isinstance(screen, dict):
        return False
    stats = _screen_region_stats(screen, 0.78, 0.26, 0.98, 0.62)
    if stats is None:
        return False
    return stats["color_ratio"] > 0.035 and stats["bright_ratio"] > 0.70

def _bumble_direct_type_fallback_allowed(text: str) -> bool:
    return direct_text_entry_block_reason(text) is None
