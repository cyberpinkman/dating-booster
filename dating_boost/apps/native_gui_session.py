from __future__ import annotations

import time

from dating_boost.apps import iphone_targeting as _iphone_runtime
from dating_boost.apps.iphone_targeting import *


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


__all__ = [name for name in globals() if not name.startswith("__")]
