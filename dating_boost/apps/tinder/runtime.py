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
from .send_runtime import (
    stage_tinder_draft, send_tinder_message, _recover_tinder_subscription_paywall_for_send, _tinder_message_input_placeholder_visible,
    _verify_staged_tinder_message, _verify_tinder_outbound_message, _tinder_staged_text_requires_host_visual_verification, _tinder_visual_staged_verification_request,
    _tinder_send_marker_visible, _tinder_direct_type_fallback_allowed, _tinder_send_button_visual_visible, _apply_tinder_paywall_recovery_result,
)
from .targeting import (
    _open_tinder_conversation_by_visible_name, _open_tinder_conversation_by_visual_anchor, _dismiss_tinder_subscription_paywall, _dismiss_tinder_feedback_survey,
    _verify_tinder_target_binding, _recover_tinder_current_thread_visual_identity_mismatch,
)

def observe_tinder_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
    payload = {
        **self._base_payload("ok"),
        "target": "tinder_screen",
        "blocked_actions": list(BLOCKED_GUI_ACTIONS),
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = self.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload

    window = _window_from_payload(doctor.get("window") or {})
    output = output_dir / "iphone_mirroring.observe.png" if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    payload["screen"] = _redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    payload["layout_hints"] = _tinder_layout_hints(screen)
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason")})
    elif screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        payload.update({"status": "blocked", "reason": screen.get("state")})
    elif screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        payload["next_host_action"] = "dismiss_subscription_paywall_and_renavigate"
    elif screen.get("state") == TINDER_FEEDBACK_SURVEY_STATE:
        payload["next_host_action"] = "dismiss_feedback_survey_and_reobserve"
    elif screen.get("state") not in TINDER_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tinder_foreground_not_verified"})
    return payload

def launch_tinder(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    planned_steps = _launch_tinder_steps()
    payload = {
        **self._base_payload("ok"),
        "target": "tinder_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "blocked_actions": list(BLOCKED_GUI_ACTIONS),
    }
    if dry_run:
        return payload
    doctor_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        doctor_output = output_dir / "iphone_mirroring.before_launch.png"
    doctor = self.doctor(capture=True, output=doctor_output)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    state = doctor.get("screen", {}).get("state")
    if state in TINDER_FOREGROUND_STATES:
        payload["reason"] = "tinder_already_foreground"
        return payload

    window_payload = doctor.get("window") or {}
    window = _window_from_payload(window_payload)
    executed_steps: list[dict[str, Any]] = []
    for step in planned_steps:
        result = self._execute_step(window, step)
        executed_steps.append({**step, "result": result})
        if result["status"] != "ok":
            payload.update({"status": "blocked", "reason": result["reason"], "executed_steps": executed_steps})
            return payload
        time.sleep(float(step.get("wait_after_seconds", 0.2)))
    payload["executed_steps"] = executed_steps
    verification_output = output_dir / "iphone_mirroring.after_launch.png" if output_dir is not None else None
    verification = self.capture_window(output=verification_output, window=window)
    payload["verification"] = _redacted_screen(verification)
    if verification["state"] not in TINDER_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tinder_launch_not_verified"})
    return payload

def open_tinder_profile(
    self,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    launch_if_needed: bool = False,
) -> dict[str, Any]:
    profile_step = _tap_step("tap_tinder_profile_tab", x=0.88, y=0.94)
    planned_steps = [profile_step]
    payload = {
        **self._base_payload("ok"),
        "target": "self_profile",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "blocked_actions": list(BLOCKED_GUI_ACTIONS),
    }

    doctor_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        doctor_output = output_dir / "iphone_mirroring.before.png"
    doctor = self.doctor(capture=True, output=doctor_output)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    state = doctor.get("screen", {}).get("state")
    if state not in TINDER_FOREGROUND_STATES and launch_if_needed:
        planned_steps = [*_launch_tinder_steps(), profile_step]
        payload["planned_steps"] = planned_steps
        if dry_run:
            return payload
        launch = self.launch_tinder(dry_run=False, output_dir=output_dir)
        payload["launch"] = launch
        if launch["status"] != "ok":
            payload.update({"status": "blocked", "reason": launch.get("reason")})
            return payload
        doctor = self.doctor(capture=True, output=doctor_output)
        payload["preflight_after_launch"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        state = doctor.get("screen", {}).get("state")
    if state not in TINDER_FOREGROUND_STATES:
        payload.update({"status": "blocked", "reason": "tinder_foreground_not_verified"})
        return payload
    if dry_run:
        return payload

    window_payload = doctor.get("window") or {}
    window = _window_from_payload(window_payload)
    click_result = self._click_ratio(window, profile_step["tap_ratio"])
    payload["executed_steps"] = [{**profile_step, "result": click_result}]
    if click_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": click_result["reason"]})
        return payload

    time.sleep(0.8)
    verify_output = None
    if output_dir is not None:
        verify_output = output_dir / "iphone_mirroring.after_open_profile.png"
    verification = self.capture_window(output=verify_output, window=window)
    payload["verification"] = _redacted_screen(verification)
    if verification["state"] != "tinder_self_profile":
        payload.update({"status": "needs_verification", "reason": "profile_screen_not_verified"})
    return payload

def run_tinder_action(
    self,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _tinder_action_steps(action, **options)
    except KeyError:
        return {
            **self._base_payload("blocked"),
            "action": action,
            "reason": "unknown_tinder_harness_action",
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }
    payload = {
        **self._base_payload("ok"),
        "action": action,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "blocked_actions": list(BLOCKED_GUI_ACTIONS),
    }
    if dry_run:
        return payload
    if action == "prepare-message-page":
        return self._prepare_iphone_message_page(
            payload,
            app_id="tinder",
            output_dir=output_dir,
            output_prefix="iphone_mirroring.tinder",
            chat_list_state="tinder_messages",
            returnable_states={"tinder_conversation"},
            foreground_states=TINDER_FOREGROUND_STATES,
            open_chats_step=_tinder_action_steps("open-chats")[0],
            return_to_chats_step=_tinder_action_steps("return-to-chats")[0],
            secondary_close_steps={"tinder_profile": _tinder_action_steps("close-preview")[0]},
            guardrails={"blocked_actions": list(BLOCKED_GUI_ACTIONS)},
            layout_hints_fn=_tinder_layout_hints,
            message_list_visual_anchor_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        )
    if action == "open-conversation":
        target_binding = options.get("target_binding")
        visual_evidence = _message_list_visual_anchor_evidence_from_options(
            options,
            target_binding=target_binding if isinstance(target_binding, dict) else None,
            default_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
            default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
        )
        if visual_evidence.get("status") == "ok":
            return self._open_tinder_conversation_by_visual_anchor(
                visual_evidence=visual_evidence,
                target_binding=target_binding if isinstance(target_binding, dict) else None,
                output_dir=output_dir,
            )
        if visual_evidence.get("status") == "blocked":
            payload.update(
                {
                    "status": "blocked",
                    "reason": visual_evidence.get("reason") or "message_list_visual_anchor_evidence_invalid",
                    "message_list_visual_anchor": visual_evidence,
                }
            )
            return payload
        visible_name = str(options.get("visible_name") or "").strip()
        if not visible_name and isinstance(target_binding, dict):
            visible_name = _target_binding_primary_visible_name(target_binding) or ""
        if visible_name:
            return self._open_tinder_conversation_by_visible_name(
                visible_name=visible_name,
                target_binding=target_binding if isinstance(target_binding, dict) else None,
                output_dir=output_dir,
            )
    return self._execute_planned_steps(payload, output_dir=output_dir)

def run_tinder_workflow(
    self,
    workflow: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _tinder_workflow_steps(workflow, **options)
    except KeyError:
        return {
            **self._base_payload("blocked"),
            "workflow": workflow,
            "reason": "unknown_tinder_harness_workflow",
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
        }
    payload = {
        **self._base_payload("ok"),
        "workflow": workflow,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "blocked_actions": list(BLOCKED_GUI_ACTIONS),
    }
    if dry_run:
        return payload
    return self._execute_planned_steps(payload, output_dir=output_dir)

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
    '_verify_outbound_message', '_screen_region_stats', 'stage_tinder_draft', 'send_tinder_message',
    '_recover_tinder_subscription_paywall_for_send', '_tinder_message_input_placeholder_visible', '_verify_staged_tinder_message', '_verify_tinder_outbound_message',
    '_tinder_staged_text_requires_host_visual_verification', '_tinder_visual_staged_verification_request', '_tinder_send_marker_visible', '_tinder_direct_type_fallback_allowed',
    '_tinder_send_button_visual_visible', '_apply_tinder_paywall_recovery_result', '_open_tinder_conversation_by_visible_name', '_open_tinder_conversation_by_visual_anchor',
    '_dismiss_tinder_subscription_paywall', '_dismiss_tinder_feedback_survey', '_verify_tinder_target_binding', '_recover_tinder_current_thread_visual_identity_mismatch',
    'observe_tinder_screen', 'launch_tinder', 'open_tinder_profile', 'run_tinder_action',
    'run_tinder_workflow',
]
