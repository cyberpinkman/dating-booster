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

def doctor_wechat(self, *, capture: bool = True, output: Path | None = None) -> dict[str, Any]:
    payload = self._base_payload("ok")
    payload["checks"] = self._command_checks()
    if not self.platform.startswith("darwin"):
        payload.update({"status": "blocked", "reason": "unsupported_platform"})
        return payload
    missing_required = [
        name
        for name in ("osascript", "screencapture")
        if not payload["checks"].get(name, {}).get("available")
    ]
    if missing_required:
        payload.update({"status": "blocked", "reason": "missing_required_macos_tools"})
        return payload

    activate = self._activate_window()
    payload["activation"] = activate
    window = self._window_info()
    if window is None:
        payload.update({"status": "blocked", "reason": "wechat_window_not_found"})
        return payload
    payload["window"] = window.to_dict()
    if not window.frontmost:
        payload.update({"status": "blocked", "reason": "wechat_not_frontmost"})
        return payload

    if capture:
        screen = self.capture_window(output=output, window=window)
        payload["screen"] = _redacted_screen(screen)
        if screen["state"] == "screen_permission_prompt":
            payload.update({"status": "blocked", "reason": screen["state"]})
        elif screen["ocr_status"] == "unavailable":
            payload.update({"status": "degraded", "reason": "ocr_unavailable"})
    return payload


def launch_wechat(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    planned_steps = [
        {
            "intent": "activate_wechat_application",
            "application_name": self.window_title,
            "risk": "navigation_only",
            "wait_after_seconds": 0.6,
        }
    ]
    payload = {
        **self._base_payload("ok"),
        "target": "wechat_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    result = self._activate_window()
    payload["executed_steps"] = [{**planned_steps[0], "result": result}]
    if result["status"] != "ok":
        payload.update({"status": "blocked", "reason": "wechat_activation_failed"})
        return payload
    time.sleep(float(planned_steps[0]["wait_after_seconds"]))
    verification_output = output_dir / "wechat.after_launch.png" if output_dir is not None else None
    verification = self.doctor_wechat(capture=True, output=verification_output)
    payload["verification"] = verification
    if verification["status"] == "blocked":
        payload.update({"status": "blocked", "reason": verification.get("reason")})
    elif verification.get("screen", {}).get("state") not in WECHAT_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "wechat_foreground_not_verified"})
    return payload


def observe_wechat_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
    payload = {
        **self._base_payload("ok"),
        "target": "wechat_screen",
        "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = self.doctor_wechat(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload

    window = _window_from_payload(doctor.get("window") or {})
    output = output_dir / "wechat.observe.png" if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    payload["screen"] = _redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    payload["layout_hints"] = _wechat_layout_hints(screen)
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason")})
    elif screen.get("state") == "screen_permission_prompt":
        payload.update({"status": "blocked", "reason": screen.get("state")})
    elif screen.get("state") not in WECHAT_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "wechat_foreground_not_verified"})
    return payload


def stage_wechat_draft(
    self,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    require_accessibility_verification: bool = False,
) -> dict[str, Any]:
    if not draft_text:
        return {
            **self._base_payload("blocked"),
            "action": "stage_draft",
            "reason": "empty_draft",
            "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
        }
    planned_steps = [
        {
            "intent": "copy_draft_to_clipboard",
            "risk": "draft_staging_only",
        },
        {
            "intent": "paste_clipboard_into_wechat_input",
            "risk": "draft_staging_only",
            "does_not_send": True,
            "requires_verified_wechat_screen": True,
        },
    ]
    payload = {
        **self._base_payload("ok"),
        "action": "stage_draft",
        "target": "wechat_message_input",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
        "draft_character_count": len(draft_text),
        **_text_fingerprint_fields("draft_clipboard", draft_text),
        "blocked_actions": list(WECHAT_BLOCKED_GUI_ACTIONS),
        "requires_user_confirmation_before_send": True,
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    before = output_dir / "wechat.before_stage_draft.png" if output_dir is not None else None
    doctor = self.doctor_wechat(capture=True, output=before)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state != "wechat_chat":
        payload.update({"status": "blocked", "reason": "wechat_chat_input_not_verified", "screen_state": screen_state})
        return payload

    executed_steps: list[dict[str, Any]] = []
    previous_clipboard = self._read_clipboard()
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard["reason"]})
        return payload
    payload.update(_text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))

    copy_result = {"status": "not_run"}
    paste_result = {"status": "not_run"}
    try:
        copy_result = self._copy_to_clipboard(draft_text)
        executed_steps.append({**planned_steps[0], "result": copy_result})
        if copy_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": copy_result["reason"]})
            return payload
        paste_result = self._paste_clipboard_into_frontmost_app()
        executed_steps.append({**planned_steps[1], "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result["reason"]})
            return payload
        if require_accessibility_verification:
            focused_text = self._read_wechat_focused_text()
            observed_text = str(focused_text.get("text") or "") if focused_text.get("status") == "ok" else ""
            text_matches = focused_text.get("status") == "ok" and observed_text == draft_text
            payload["staged_text_verification"] = {
                "status": "ok" if text_matches else "blocked",
                "verification_method": "macos_accessibility_focused_ui_value",
                "expected_payload_hash": payload["draft_fingerprint"],
                "observed_text_hash": hashlib.sha256(observed_text.encode("utf-8")).hexdigest()
                if focused_text.get("status") == "ok"
                else None,
                "observed_character_count": len(observed_text)
                if focused_text.get("status") == "ok"
                else None,
            }
            if focused_text.get("status") != "ok":
                payload["staged_text_verification"]["reason"] = focused_text.get("reason")
                payload.update({"status": "blocked", "reason": "staged_text_accessibility_read_failed"})
                return payload
            if not text_matches:
                payload["staged_text_verification"]["reason"] = "focused_input_text_mismatch"
                payload.update({"status": "blocked", "reason": "staged_text_mismatch"})
                return payload
            payload["staged_text_verified"] = True

        window = _window_from_payload(doctor.get("window") or {})
        after = output_dir / "wechat.after_stage_draft.png" if output_dir is not None else None
        payload["verification"] = _redacted_screen(self.capture_window(output=after, window=window))
        payload["next_host_action"] = "verify_staged_text_before_send"
    finally:
        payload["executed_steps"] = executed_steps
        restore_result = self._copy_to_clipboard(previous_clipboard.get("text", ""))
        payload["clipboard_restored"] = restore_result["status"] == "ok"
        payload["clipboard_restore_status"] = restore_result["status"]
        if restore_result["status"] != "ok":
            payload["clipboard_restore_reason"] = restore_result.get("reason")
        if restore_result["status"] != "ok" and paste_result.get("status") == "ok":
            payload.update({
                "status": "degraded",
                "reason": "clipboard_restore_failed",
                "next_host_action": "verify_staged_text_and_clear_clipboard",
            })
    return payload


def send_wechat_message(
    self,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    planned_steps = [
        {
            "intent": "stage_draft_with_accessibility_verification",
            "risk": "live_send_precondition",
            "requires_exact_text_match": True,
        },
        {
            "intent": "press_return_to_send_wechat_message",
            "risk": "live_send",
            "requires_explicit_authorization": True,
        },
        {
            "intent": "verify_input_cleared_and_capture_post_action_screen",
            "risk": "post_action_verification",
        },
    ]
    payload = SendAttemptContext(
        action="send_message",
        target="wechat_message_input",
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=tuple(planned_steps),
        blocked_actions=("payments", "calls", "contact_exchange_without_user"),
    ).initial_payload(self._base_payload("ok"))
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    if target_binding is not None:
        target_verification = self._verify_wechat_target_binding(target_binding, output_dir=output_dir)
        payload["target_binding_verification"] = target_verification
        if target_verification.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": target_verification.get("reason") or "target_binding_mismatch",
            })
            return payload

    stage_payload = self.stage_wechat_draft(
        draft_text,
        dry_run=False,
        output_dir=output_dir,
        require_accessibility_verification=True,
    )
    payload["stage_status"] = stage_payload.get("status")
    payload["staged_text_verification"] = stage_payload.get("staged_text_verification")
    payload["clipboard_restored"] = stage_payload.get("clipboard_restored")
    for key in (
        "previous_clipboard_fingerprint",
        "previous_clipboard_character_count",
        "previous_clipboard_topic_labels",
    ):
        if key in stage_payload:
            payload[key] = stage_payload[key]
    if stage_payload.get("status") != "ok":
        payload.update({"status": "blocked", "reason": stage_payload.get("reason") or "stage_failed"})
        return payload

    send_result = self._press_return_key()
    payload["executed_steps"] = [
        {"intent": planned_steps[0]["intent"], "result": {"status": "ok"}},
        {"intent": planned_steps[1]["intent"], "result": send_result},
    ]
    if send_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": send_result["reason"]})
        return payload

    time.sleep(0.4)
    focused_after = self._read_wechat_focused_text()
    after_text = str(focused_after.get("text") or "") if focused_after.get("status") == "ok" else ""
    input_cleared = focused_after.get("status") == "ok" and not after_text.strip()
    payload["post_send_verification"] = {
        "status": "ok" if input_cleared else "needs_verification",
        "verification_method": "macos_accessibility_focused_ui_value",
        "input_cleared_after_send": input_cleared,
        "observed_character_count": len(after_text) if focused_after.get("status") == "ok" else None,
        "reason": focused_after.get("reason") if focused_after.get("status") != "ok" else None,
    }
    window_payload = stage_payload.get("preflight", {}).get("window") or {}
    window = _window_from_payload(window_payload)
    after = output_dir / "wechat.after_send_message.png" if output_dir is not None else None
    post_screen = self.capture_window(output=after, window=window)
    payload["post_action_observation"] = _redacted_screen(post_screen)
    post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or _now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    payload["post_action_observation_id"] = post_observation_id
    post_screen_captured = post_screen.get("status") == "ok"
    outbound_verification = _verify_outbound_message(post_screen, draft_text)
    payload["outbound_message_verification"] = outbound_verification
    outbound_verified = outbound_verification.get("status") == "ok"
    payload["evidence"] = EvidencePayload(
        staging=StagingResult.from_verification(
            stage_payload.get("staged_text_verification")
            if isinstance(stage_payload.get("staged_text_verification"), dict)
            else None,
            staged_text_verified=bool(stage_payload.get("staged_text_verified")),
        ),
        post_send=PostSendVerification(
            post_action_observation_id=post_observation_id,
            input_cleared_after_send=input_cleared,
            post_action_screen_captured=post_screen_captured,
            outbound_message_verified=outbound_verified,
        ),
        send_input_backend=send_result.get("input_backend"),
    ).to_dict()
    if not input_cleared:
        payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
    elif not post_screen_captured:
        payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
    elif not outbound_verified:
        payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
    return payload


def _verify_wechat_target_binding(
    self,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    markers = _target_binding_required_markers(target_binding)
    base = {
        "verification_method": "wechat_screen_ocr_required_visible_text",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "required_marker_hashes": [_hash_text(marker) for marker in markers],
    }
    if not markers:
        return {**base, "status": "blocked", "reason": "target_binding_required"}
    window = self._window_info()
    if window is None:
        return {**base, "status": "blocked", "reason": "wechat_window_not_found"}
    output = output_dir / "wechat.target_binding.png" if output_dir is not None else None
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
    if screen.get("state") != "wechat_chat":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    return {**result, "status": "ok"}


def _read_wechat_focused_text(self) -> dict[str, Any]:
    result = self.runner.run(
        [
            "osascript",
            "-e",
            (
                f'tell application "System Events" to tell process "{self.window_title}" '
                'to get value of focused UI element'
            ),
        ]
    )
    if result.returncode != 0:
        return {"status": "blocked", "reason": "focused_input_read_failed", "stderr": _short(result.stderr)}
    return {"status": "ok", "text": result.stdout.rstrip("\r\n")}


__all__ = [
    'annotations', 'hashlib', '_platform', 'copy',
    'csv', 'datetime', 'timezone', 'io',
    're', 'struct', 'sys', 'tempfile',
    'time', 'zlib', 'Path', 'Any',
    'uuid4', 'SubprocessRunner', 'WindowInfo', '_parse_window_info',
    '_short', '_window_from_payload', '_click_iphone_mirroring_view_menu_item_backend', '_core_graphics_click_backend',
    '_core_graphics_command_v_backend', '_core_graphics_drag_backend', '_core_graphics_wheel_backend', 'BUMBLE_FOREGROUND_STATES',
    'TINDER_FOREGROUND_STATES', 'WECHAT_FOREGROUND_STATES', '_bumble_layout_hints', '_bumble_top_level_bottom_nav_present',
    'classify_bumble_screen_text', 'classify_bumble_screen_image', 'classify_screen_image', 'classify_screen_text',
    'classify_wechat_screen_text', '_combine_bumble_screen_states', '_combine_screen_states', '_read_png_pixels_for_send_button',
    '_region_stats_for_send_button', '_redacted_screen', '_tinder_layout_hints', '_tinder_profile_danger_action_visible',
    '_tinder_profile_expand_control_visible', '_tinder_profile_field_coverage', '_wechat_layout_hints', 'bumble_target_binding_specific_marker_present',
    'target_binding_structural_evidence_present', '_expected_text_observation_stats', '_hash_text', '_message_text_comparable',
    '_message_text_matches', '_normalize_text', '_outbound_text_ocr_evidence', '_staged_text_ocr_evidence',
    '_staged_text_visual_verification_request', '_text_fingerprint_fields', '_harness_step_validation_reason', 'GUI_HARNESS_SCHEMA_VERSION',
    'IPHONE_MIRRORING_HARNESS_BACKEND', 'MAC_IOS_APP_HARNESS_BACKEND', 'WECHAT_HARNESS_BACKEND', 'HARNESS_BACKEND',
    '_contains_cjk_text', 'direct_text_entry_block_reason', 'NativeGuiHarness', '_applescript_string_literal',
    '_ensure_ascii_input_source', '_switch_ascii_input_source', '_read_current_input_source', '_input_source_id_is_ascii',
    '_app_search_result_visible', '_default_screenshot_path', '_now_iso', '_parse_mac_ios_process_probe',
    '_parse_core_graphics_window_info', '_parse_mac_ios_active_application_probe', '_swift_string_literal', '_mac_ios_running_application_lookup_script',
    '_mac_ios_core_graphics_window_lookup_script', '_mac_ios_window_failure_reason', 'mac_ios_window_failure_payload', '_contains_host_appleevents_unavailable_error',
    '_host_appleevents_unavailable_diagnostic', '_looks_like_iphone_mirroring_window', '_looks_like_mac_ios_app_window', 'EvidencePayload',
    'PostSendVerification', 'SendAttemptContext', 'StagingResult', 'BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION',
    'IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE', 'TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION', '_bumble_action_steps', '_bumble_profile_field_coverage',
    '_bumble_tap_step', '_bumble_workflow_steps', '_copy_tap_ratio', '_has_bumble_step_postcondition',
    '_has_bumble_step_precondition', '_int_in_range', '_launch_app_steps', '_launch_tinder_steps',
    '_message_list_visual_anchor_evidence_from_options', '_normalized_visual_anchor_region', '_redacted_iphone_prepare_message_page_payload', '_redacted_message_list_visual_anchor_evidence',
    '_redacted_target_binding', '_target_binding_primary_visible_name', '_target_binding_required_markers', '_tap_ratio_option',
    '_tap_step', '_tinder_feedback_survey_dismiss_step', '_tinder_action_steps', '_tinder_subscription_paywall_dismiss_step',
    '_tinder_workflow_steps', '_verify_bumble_step_state', '_visual_anchor_hamming_distance', 'harness_step_validation_reason',
    'RowToThreadBindingSpec', 'finish_row_to_thread_screen_verification', 'row_to_thread_base_result', 'validate_row_to_thread_structural_evidence',
    'target_binding_specific_marker_present', 'BLOCKED_GUI_ACTIONS', 'WECHAT_BLOCKED_GUI_ACTIONS', 'BUMBLE_BLOCKED_GUI_ACTIONS',
    'BUMBLE_SEND_BLOCKED_GUI_ACTIONS', 'BUMBLE_OPENING_MOVE_POLICY', 'TINDER_SUBSCRIPTION_PAYWALL_STATE', 'TINDER_FEEDBACK_SURVEY_STATE',
    'DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS', 'IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO', 'IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y', 'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION',
    'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS', 'capture_window', '_execute_planned_steps',
    '_locate_iphone_message_list_visual_anchor_target', '_verify_open_conversation_target_binding_against_screen', '_visible_text_contains_marker', '_prepare_iphone_message_page',
    '_recover_iphone_prepare_message_page_blocker', '_finish_iphone_message_page_ready', '_select_iphone_prepare_message_page_step', '_execute_iphone_prepare_message_page_step',
    '_open_conversation_by_message_list_visual_anchor', '_preflight_iphone_visual_anchor_open_conversation', '_navigate_iphone_to_visual_anchor_source', '_relocate_and_tap_iphone_visual_anchor_target',
    '_iphone_visual_anchor_tap_step', '_verify_iphone_visual_anchor_open_conversation_target', '_locate_visible_text_y_ratio', '_ocr_tsv',
    '_visible_text_location_from_tsv', '_recover_iphone_current_thread_visual_identity_mismatch', '_iphone_visual_identity_relocation_preflight', '_run_iphone_visual_identity_relocation_attempts',
    '_iphone_visual_identity_relocation_attempt_blocked_payload', '_iphone_visual_identity_relocation_exhausted_payload', '_run_iphone_visual_identity_relocation_attempt', '_locate_iphone_visual_identity_relocation_target',
    '_iphone_relocation_open_target_tap_step', '_verify_iphone_current_thread_visual_identity', '_verify_chat_list_row_target_binding', '_iphone_message_list_visual_anchor_scan_setup',
    '_scan_iphone_message_list_visual_anchor_candidates', '_finish_iphone_message_list_visual_anchor_location', '_safe_iphone_message_list_visual_anchor_tap_ratio', '_iphone_visual_anchor_hash_for_pixels',
    '_iphone_visual_anchor_hash_for_path', '_iphone_current_thread_visual_anchor', '_verify_target_binding_against_screen', '_iphone_already_sent_payload_update',
    '_iphone_already_sent_idempotency_allowed', '_iphone_stage_needs_user_verification', '_iphone_stage_draft_payload_update', '_iphone_pre_stage_input_guard',
    '_verify_outbound_message', '_screen_region_stats', 'doctor_wechat', 'launch_wechat',
    'observe_wechat_screen', 'stage_wechat_draft', 'send_wechat_message', '_verify_wechat_target_binding',
    '_read_wechat_focused_text',
]
