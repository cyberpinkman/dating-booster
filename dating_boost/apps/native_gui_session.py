from __future__ import annotations

import time

from dating_boost.apps import iphone_targeting as _iphone_runtime
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


class AppSpecificNativeGuiSessionMixin:
    def capture_window(
        self,
        *,
        output: Path | None = None,
        window: WindowInfo | None = None,
        ocr: bool = True,
    ) -> dict[str, Any]:
        return _iphone_runtime.capture_window(self, output=output, window=window, ocr=ocr)

    def doctor_wechat(self, *, capture: bool = True, output: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime.doctor_wechat(self, capture=capture, output=output)

    def launch_wechat(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime.launch_wechat(self, dry_run=dry_run, output_dir=output_dir)

    def observe_wechat_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime.observe_wechat_screen(self, output_dir=output_dir)

    def stage_wechat_draft(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        require_accessibility_verification: bool = False,
    ) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime.stage_wechat_draft(self, draft_text, dry_run=dry_run, output_dir=output_dir, require_accessibility_verification=require_accessibility_verification)

    def send_wechat_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime.send_wechat_message(self, draft_text, dry_run=dry_run, output_dir=output_dir, target_binding=target_binding)

    def observe_tinder_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.observe_tinder_screen(self, output_dir=output_dir)

    def observe_bumble_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime.observe_bumble_screen(self, output_dir=output_dir)

    def launch_tinder(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.launch_tinder(self, dry_run=dry_run, output_dir=output_dir)

    def launch_bumble(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime.launch_bumble(self, dry_run=dry_run, output_dir=output_dir)

    def open_tinder_profile(
        self,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        launch_if_needed: bool = False,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.open_tinder_profile(self, dry_run=dry_run, output_dir=output_dir, launch_if_needed=launch_if_needed)

    def run_tinder_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.run_tinder_action(self, action, dry_run=dry_run, output_dir=output_dir, **options)

    def run_tinder_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.run_tinder_workflow(self, workflow, dry_run=dry_run, output_dir=output_dir, **options)

    def run_bumble_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime.run_bumble_action(self, action, dry_run=dry_run, output_dir=output_dir, **options)

    def run_bumble_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime.run_bumble_workflow(self, workflow, dry_run=dry_run, output_dir=output_dir, **options)

    def stage_bumble_draft(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime.stage_bumble_draft(self, draft_text, dry_run=dry_run, output_dir=output_dir)

    def send_bumble_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
        stage_only: bool = False,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime.send_bumble_message(self, draft_text, dry_run=dry_run, output_dir=output_dir, target_binding=target_binding, stage_only=stage_only)

    def stage_tinder_draft(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.stage_tinder_draft(self, draft_text, dry_run=dry_run, output_dir=output_dir)

    def send_tinder_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
        _paywall_retry_attempted: bool = False,
        stage_only: bool = False,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime.send_tinder_message(self, draft_text, dry_run=dry_run, output_dir=output_dir, target_binding=target_binding, _paywall_retry_attempted=_paywall_retry_attempted, stage_only=stage_only)

    def _execute_planned_steps(self, payload: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
        return _iphone_runtime._execute_planned_steps(self, payload, output_dir=output_dir)

    def _prepare_iphone_message_page(
        self,
        payload: dict[str, Any],
        *,
        app_id: str,
        output_dir: Path | None,
        output_prefix: str,
        chat_list_state: str,
        returnable_states: set[str],
        foreground_states: set[str],
        open_chats_step: dict[str, Any],
        return_to_chats_step: dict[str, Any],
        secondary_close_steps: dict[str, dict[str, Any]],
        guardrails: dict[str, Any],
        layout_hints_fn: Any,
        message_list_visual_anchor_scan_region: dict[str, float],
    ) -> dict[str, Any]:
        return _iphone_runtime._prepare_iphone_message_page(self, payload, app_id=app_id, output_dir=output_dir, output_prefix=output_prefix, chat_list_state=chat_list_state, returnable_states=returnable_states, foreground_states=foreground_states, open_chats_step=open_chats_step, return_to_chats_step=return_to_chats_step, secondary_close_steps=secondary_close_steps, guardrails=guardrails, layout_hints_fn=layout_hints_fn, message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region)

    def _verify_bumble_step_precondition(
        self,
        window: WindowInfo,
        step: dict[str, Any],
        *,
        output_dir: Path | None,
        step_index: int,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime._verify_bumble_step_precondition(self, window, step, output_dir=output_dir, step_index=step_index)

    def _verify_bumble_step_postcondition(
        self,
        window: WindowInfo,
        step: dict[str, Any],
        *,
        output_dir: Path | None,
        step_index: int,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime._verify_bumble_step_postcondition(self, window, step, output_dir=output_dir, step_index=step_index)

    def _open_tinder_conversation_by_visible_name(
        self,
        *,
        visible_name: str,
        target_binding: dict[str, Any] | None = None,
        output_dir: Path | None = None,
        max_scrolls: int = 3,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._open_tinder_conversation_by_visible_name(self, visible_name=visible_name, target_binding=target_binding, output_dir=output_dir, max_scrolls=max_scrolls)

    def _open_tinder_conversation_by_visual_anchor(
        self,
        *,
        visual_evidence: dict[str, Any],
        target_binding: dict[str, Any] | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._open_tinder_conversation_by_visual_anchor(self, visual_evidence=visual_evidence, target_binding=target_binding, output_dir=output_dir)

    def _open_bumble_conversation_by_visible_name(
        self,
        *,
        visible_name: str,
        target_binding: dict[str, Any] | None = None,
        output_dir: Path | None = None,
        max_scrolls: int = 3,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime._open_bumble_conversation_by_visible_name(self, visible_name=visible_name, target_binding=target_binding, output_dir=output_dir, max_scrolls=max_scrolls)

    def _open_bumble_conversation_by_visual_anchor(
        self,
        *,
        visual_evidence: dict[str, Any],
        target_binding: dict[str, Any] | None = None,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime._open_bumble_conversation_by_visual_anchor(self, visual_evidence=visual_evidence, target_binding=target_binding, output_dir=output_dir)

    def _open_conversation_by_message_list_visual_anchor(
        self,
        *,
        app_id: str,
        visual_evidence: dict[str, Any],
        target_binding: dict[str, Any] | None,
        output_dir: Path | None,
        chat_list_state: str,
        conversation_state: str,
        foreground_states: set[str],
        open_chats_step: dict[str, Any],
        return_to_chats_step: dict[str, Any],
        planned_steps: list[dict[str, Any]],
        tap_intent: str,
        tap_x: float,
        tap_y_min: float,
        tap_y_max: float,
        output_prefix: str,
        verification_method: str,
        source_states: set[str],
        blocked_state_reasons: dict[str, str],
        guardrails: dict[str, Any],
    ) -> dict[str, Any]:
        return _iphone_runtime._open_conversation_by_message_list_visual_anchor(self, app_id=app_id, visual_evidence=visual_evidence, target_binding=target_binding, output_dir=output_dir, chat_list_state=chat_list_state, conversation_state=conversation_state, foreground_states=foreground_states, open_chats_step=open_chats_step, return_to_chats_step=return_to_chats_step, planned_steps=planned_steps, tap_intent=tap_intent, tap_x=tap_x, tap_y_min=tap_y_min, tap_y_max=tap_y_max, output_prefix=output_prefix, verification_method=verification_method, source_states=source_states, blocked_state_reasons=blocked_state_reasons, guardrails=guardrails)

    def _locate_visible_text_y_ratio(self, screen: dict[str, Any], marker: str) -> dict[str, Any]:
        return _iphone_runtime._locate_visible_text_y_ratio(self, screen, marker)

    def _ocr_tsv(self, image_path: Path) -> dict[str, str]:
        return _iphone_runtime._ocr_tsv(self, image_path)

    def _recover_tinder_subscription_paywall_for_send(
        self,
        payload: dict[str, Any],
        recovery: dict[str, Any],
        *,
        draft_text: str,
        output_dir: Path | None,
        target_binding: dict[str, Any] | None,
        retry_attempted: bool,
        stage_only: bool = False,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._recover_tinder_subscription_paywall_for_send(self, payload, recovery, draft_text=draft_text, output_dir=output_dir, target_binding=target_binding, retry_attempted=retry_attempted, stage_only=stage_only)

    def _dismiss_tinder_subscription_paywall(
        self,
        window: WindowInfo,
        *,
        output_dir: Path | None = None,
        label: str,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._dismiss_tinder_subscription_paywall(self, window, output_dir=output_dir, label=label)

    def _dismiss_tinder_feedback_survey(
        self,
        window: WindowInfo,
        *,
        output_dir: Path | None = None,
        label: str,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._dismiss_tinder_feedback_survey(self, window, output_dir=output_dir, label=label)

    def _verify_tinder_target_binding(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._verify_tinder_target_binding(self, target_binding, output_dir=output_dir)

    def _verify_bumble_target_binding(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime._verify_bumble_target_binding(self, target_binding, output_dir=output_dir)

    def _recover_tinder_current_thread_visual_identity_mismatch(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
        target_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.tinder import runtime as _tinder_runtime
        return _tinder_runtime._recover_tinder_current_thread_visual_identity_mismatch(self, target_binding, output_dir=output_dir, target_verification=target_verification)

    def _recover_bumble_current_thread_visual_identity_mismatch(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
        target_verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.bumble import runtime as _bumble_runtime
        return _bumble_runtime._recover_bumble_current_thread_visual_identity_mismatch(self, target_binding, output_dir=output_dir, target_verification=target_verification)

    def _recover_iphone_current_thread_visual_identity_mismatch(
        self,
        *,
        app_id: str,
        target_binding: dict[str, Any],
        target_verification: dict[str, Any] | None,
        output_dir: Path | None,
        chat_list_state: str,
        conversation_state: str,
        foreground_states: set[str],
        open_chats_step: dict[str, Any],
        return_to_chats_step: dict[str, Any],
        secondary_close_steps: dict[str, dict[str, Any]],
        guardrails: dict[str, Any],
        layout_hints_fn: Any,
        message_list_visual_anchor_scan_region: dict[str, float],
        blocked_state_reasons: dict[str, str],
        tap_intent: str,
        tap_x: float,
        tap_y_min: float,
        tap_y_max: float,
        output_prefix: str,
        verify_target_binding: Any,
        max_attempts: int = IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS,
    ) -> dict[str, Any]:
        return _iphone_runtime._recover_iphone_current_thread_visual_identity_mismatch(self, app_id=app_id, target_binding=target_binding, target_verification=target_verification, output_dir=output_dir, chat_list_state=chat_list_state, conversation_state=conversation_state, foreground_states=foreground_states, open_chats_step=open_chats_step, return_to_chats_step=return_to_chats_step, secondary_close_steps=secondary_close_steps, guardrails=guardrails, layout_hints_fn=layout_hints_fn, message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region, blocked_state_reasons=blocked_state_reasons, tap_intent=tap_intent, tap_x=tap_x, tap_y_min=tap_y_min, tap_y_max=tap_y_max, output_prefix=output_prefix, verify_target_binding=verify_target_binding, max_attempts=max_attempts)

    def _verify_iphone_current_thread_visual_identity(
        self,
        *,
        app_id: str,
        target_binding: dict[str, Any],
        output_dir: Path | None,
        conversation_state: str,
        blocked_state_reasons: dict[str, str],
        output_name: str,
        verification_method: str,
    ) -> dict[str, Any]:
        return _iphone_runtime._verify_iphone_current_thread_visual_identity(self, app_id=app_id, target_binding=target_binding, output_dir=output_dir, conversation_state=conversation_state, blocked_state_reasons=blocked_state_reasons, output_name=output_name, verification_method=verification_method)

    def _verify_chat_list_row_target_binding(
        self,
        *,
        app_id: str,
        target_binding: dict[str, Any],
        output_dir: Path | None,
        source_states: set[str],
        conversation_state: str,
        blocked_state_reasons: dict[str, str],
        output_name: str,
        verification_method: str,
    ) -> dict[str, Any]:
        return _iphone_runtime._verify_chat_list_row_target_binding(self, app_id=app_id, target_binding=target_binding, output_dir=output_dir, source_states=source_states, conversation_state=conversation_state, blocked_state_reasons=blocked_state_reasons, output_name=output_name, verification_method=verification_method)

    def _verify_wechat_target_binding(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime._verify_wechat_target_binding(self, target_binding, output_dir=output_dir)

    def _read_wechat_focused_text(self) -> dict[str, Any]:
        from dating_boost.apps.wechat import runtime as _wechat_runtime
        return _wechat_runtime._read_wechat_focused_text(self)


__all__ = [
    'annotations', 'time', '_iphone_runtime', 'hashlib',
    '_platform', 'copy', 'csv', 'datetime',
    'timezone', 'io', 're', 'struct',
    'sys', 'tempfile', 'zlib', 'Path',
    'Any', 'uuid4', 'SubprocessRunner', 'WindowInfo',
    '_parse_window_info', '_short', '_window_from_payload', '_click_iphone_mirroring_view_menu_item_backend',
    '_core_graphics_click_backend', '_core_graphics_command_v_backend', '_core_graphics_drag_backend', '_core_graphics_wheel_backend',
    'BUMBLE_FOREGROUND_STATES', 'TINDER_FOREGROUND_STATES', 'WECHAT_FOREGROUND_STATES', '_bumble_layout_hints',
    '_bumble_top_level_bottom_nav_present', 'classify_bumble_screen_text', 'classify_bumble_screen_image', 'classify_screen_image',
    'classify_screen_text', 'classify_wechat_screen_text', '_combine_bumble_screen_states', '_combine_screen_states',
    '_read_png_pixels_for_send_button', '_region_stats_for_send_button', '_redacted_screen', '_tinder_layout_hints',
    '_tinder_profile_danger_action_visible', '_tinder_profile_expand_control_visible', '_tinder_profile_field_coverage', '_wechat_layout_hints',
    'bumble_target_binding_specific_marker_present', 'target_binding_structural_evidence_present', '_expected_text_observation_stats', '_hash_text',
    '_message_text_comparable', '_message_text_matches', '_normalize_text', '_outbound_text_ocr_evidence',
    '_staged_text_ocr_evidence', '_staged_text_visual_verification_request', '_text_fingerprint_fields', '_harness_step_validation_reason',
    'GUI_HARNESS_SCHEMA_VERSION', 'IPHONE_MIRRORING_HARNESS_BACKEND', 'MAC_IOS_APP_HARNESS_BACKEND', 'WECHAT_HARNESS_BACKEND',
    'HARNESS_BACKEND', '_contains_cjk_text', 'direct_text_entry_block_reason', 'NativeGuiHarness',
    '_applescript_string_literal', '_ensure_ascii_input_source', '_switch_ascii_input_source', '_read_current_input_source',
    '_input_source_id_is_ascii', '_app_search_result_visible', '_default_screenshot_path', '_now_iso',
    '_parse_mac_ios_process_probe', '_parse_core_graphics_window_info', '_parse_mac_ios_active_application_probe', '_swift_string_literal',
    '_mac_ios_running_application_lookup_script', '_mac_ios_core_graphics_window_lookup_script', '_mac_ios_window_failure_reason', 'mac_ios_window_failure_payload',
    '_contains_host_appleevents_unavailable_error', '_host_appleevents_unavailable_diagnostic', '_looks_like_iphone_mirroring_window', '_looks_like_mac_ios_app_window',
    'EvidencePayload', 'PostSendVerification', 'SendAttemptContext', 'StagingResult',
    'BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION', 'IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE', 'TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION', '_bumble_action_steps',
    '_bumble_profile_field_coverage', '_bumble_tap_step', '_bumble_workflow_steps', '_copy_tap_ratio',
    '_has_bumble_step_postcondition', '_has_bumble_step_precondition', '_int_in_range', '_launch_app_steps',
    '_launch_tinder_steps', '_message_list_visual_anchor_evidence_from_options', '_normalized_visual_anchor_region', '_redacted_iphone_prepare_message_page_payload',
    '_redacted_message_list_visual_anchor_evidence', '_redacted_target_binding', '_target_binding_primary_visible_name', '_target_binding_required_markers',
    '_tap_ratio_option', '_tap_step', '_tinder_feedback_survey_dismiss_step', '_tinder_action_steps',
    '_tinder_subscription_paywall_dismiss_step', '_tinder_workflow_steps', '_verify_bumble_step_state', '_visual_anchor_hamming_distance',
    'harness_step_validation_reason', 'RowToThreadBindingSpec', 'finish_row_to_thread_screen_verification', 'row_to_thread_base_result',
    'validate_row_to_thread_structural_evidence', 'target_binding_specific_marker_present', 'BLOCKED_GUI_ACTIONS', 'WECHAT_BLOCKED_GUI_ACTIONS',
    'BUMBLE_BLOCKED_GUI_ACTIONS', 'BUMBLE_SEND_BLOCKED_GUI_ACTIONS', 'BUMBLE_OPENING_MOVE_POLICY', 'TINDER_SUBSCRIPTION_PAYWALL_STATE',
    'TINDER_FEEDBACK_SURVEY_STATE', 'DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS', 'IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO', 'IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y',
    'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION', 'IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE', 'IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS', 'capture_window',
    '_execute_planned_steps', '_locate_iphone_message_list_visual_anchor_target', '_verify_open_conversation_target_binding_against_screen', '_visible_text_contains_marker',
    '_prepare_iphone_message_page', '_recover_iphone_prepare_message_page_blocker', '_finish_iphone_message_page_ready', '_select_iphone_prepare_message_page_step',
    '_execute_iphone_prepare_message_page_step', '_open_conversation_by_message_list_visual_anchor', '_preflight_iphone_visual_anchor_open_conversation', '_navigate_iphone_to_visual_anchor_source',
    '_relocate_and_tap_iphone_visual_anchor_target', '_iphone_visual_anchor_tap_step', '_verify_iphone_visual_anchor_open_conversation_target', '_locate_visible_text_y_ratio',
    '_ocr_tsv', '_visible_text_location_from_tsv', '_recover_iphone_current_thread_visual_identity_mismatch', '_iphone_visual_identity_relocation_preflight',
    '_run_iphone_visual_identity_relocation_attempts', '_iphone_visual_identity_relocation_attempt_blocked_payload', '_iphone_visual_identity_relocation_exhausted_payload', '_run_iphone_visual_identity_relocation_attempt',
    '_locate_iphone_visual_identity_relocation_target', '_iphone_relocation_open_target_tap_step', '_verify_iphone_current_thread_visual_identity', '_verify_chat_list_row_target_binding',
    '_iphone_message_list_visual_anchor_scan_setup', '_scan_iphone_message_list_visual_anchor_candidates', '_finish_iphone_message_list_visual_anchor_location', '_safe_iphone_message_list_visual_anchor_tap_ratio',
    '_iphone_visual_anchor_hash_for_pixels', '_iphone_visual_anchor_hash_for_path', '_iphone_current_thread_visual_anchor', '_verify_target_binding_against_screen',
    '_iphone_already_sent_payload_update', '_iphone_already_sent_idempotency_allowed', '_iphone_stage_needs_user_verification', '_iphone_stage_draft_payload_update',
    '_iphone_pre_stage_input_guard', '_verify_outbound_message', '_screen_region_stats', 'AppSpecificNativeGuiSessionMixin',
]
