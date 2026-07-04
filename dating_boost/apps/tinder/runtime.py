from __future__ import annotations

from dating_boost.apps.iphone_targeting import *

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


def stage_tinder_draft(
    self,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    return self.send_tinder_message(
        draft_text,
        dry_run=dry_run,
        output_dir=output_dir,
        stage_only=True,
    )


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
    input_step = {
        "intent": "tap_tinder_message_input",
        "tap_ratio": {"x": 0.45, "y": 0.92},
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "requires_verified_tinder_thread": True,
        "does_not_send": stage_only,
    }
    paste_step = {
        "intent": "paste_clipboard_into_tinder_message_input",
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "requires_exact_text_match": True,
        "does_not_send": stage_only,
    }
    type_fallback_step = {
        "intent": "type_tinder_message_input_if_paste_did_not_stage",
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "fallback_only": True,
        "requires_ascii_draft": True,
        "requires_exact_text_verification_after_direct_type": True,
        "does_not_send": stage_only,
    }
    ime_commit_step = {
        "intent": "commit_tinder_message_input_ime_candidate_if_needed",
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "fallback_only": True,
        "requires_failed_direct_type_verification": True,
        "requires_exact_text_verification_after_commit": True,
        "does_not_send": stage_only,
    }
    send_step = {
        "intent": "tap_tinder_send_button",
        "tap_ratio": {"x": 0.90, "y": 0.92},
        "risk": "live_send",
        "requires_explicit_authorization": True,
    }
    planned_steps = (input_step, paste_step, type_fallback_step, ime_commit_step)
    if not stage_only:
        planned_steps = (*planned_steps, send_step)
    payload = SendAttemptContext(
        action="stage_draft" if stage_only else "send_message",
        target="tinder_message_input",
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=planned_steps,
        blocked_actions=("like", "super_like", "unmatch", "report", "profile_edit"),
    ).initial_payload(self._base_payload("ok"))
    if stage_only:
        payload["requires_user_confirmation_before_send"] = True
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    preflight_output = output_dir / "iphone_mirroring.tinder.before_send_message.png" if output_dir is not None else None
    preflight = self.doctor(capture=True, output=preflight_output)
    payload["preflight"] = preflight
    if preflight["status"] != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "tinder_preflight_not_verified"})
        return payload
    window = _window_from_payload(preflight.get("window") or {})
    if preflight.get("screen", {}).get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="before_send_message",
        )
        return self._recover_tinder_subscription_paywall_for_send(
            payload,
            recovery,
            draft_text=draft_text,
            output_dir=output_dir,
            target_binding=target_binding,
            retry_attempted=_paywall_retry_attempted,
            stage_only=stage_only,
        )

    if target_binding is not None:
        target_verification = self._verify_tinder_target_binding(target_binding, output_dir=output_dir)
        payload["target_binding_verification"] = target_verification
        if target_verification.get("status") != "ok":
            if target_verification.get("reason") == "tinder_subscription_paywall_visible":
                recovery = self._dismiss_tinder_subscription_paywall(
                    window,
                    output_dir=output_dir,
                    label="target_binding",
                )
                return self._recover_tinder_subscription_paywall_for_send(
                    payload,
                    recovery,
                    draft_text=draft_text,
                    output_dir=output_dir,
                    target_binding=target_binding,
                    retry_attempted=_paywall_retry_attempted,
                    stage_only=stage_only,
                )
            relocation = self._recover_tinder_current_thread_visual_identity_mismatch(
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
                return payload

    baseline_output = output_dir / "iphone_mirroring.tinder.before_stage_message.png" if output_dir is not None else None
    baseline_screen = self.capture_window(output=baseline_output, window=window)
    payload["pre_stage_observation"] = _redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return payload
    if baseline_screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="before_stage_message",
        )
        return self._recover_tinder_subscription_paywall_for_send(
            payload,
            recovery,
            draft_text=draft_text,
            output_dir=output_dir,
            target_binding=target_binding,
            retry_attempted=_paywall_retry_attempted,
            stage_only=stage_only,
        )
    if baseline_screen.get("state") != "tinder_conversation":
        payload.update({"status": "blocked", "reason": "tinder_conversation_not_verified"})
        return payload

    already_sent_verification = (
        _verify_tinder_outbound_message(baseline_screen, draft_text)
        if _iphone_already_sent_idempotency_allowed(target_binding)
        else {"status": "not_run", "reason": "current_thread_visual_identity_required"}
    )
    if already_sent_verification.get("status") == "ok":
        payload.update(
            _iphone_already_sent_payload_update(
                payload,
                screen=baseline_screen,
                outbound_verification=already_sent_verification,
                conversation_state="tinder_conversation",
            )
        )
        return payload

    executed_steps: list[dict[str, Any]] = []
    stage_ready = False
    staged_screen = baseline_screen
    baseline_staged_verification = _verify_staged_tinder_message(baseline_screen, draft_text)
    staged_verification = baseline_staged_verification
    if baseline_staged_verification.get("status") == "ok":
        baseline_staged_verification["reused_existing_staged_text"] = True
        if not _tinder_send_button_visual_visible(baseline_screen):
            payload["staged_text_verification"] = baseline_staged_verification
            payload["staged_text_verified"] = True
            payload.update({
                "status": "blocked",
                "reason": "payload_already_visible_before_staging",
                "next_host_action": "verify_no_duplicate_send_request",
                "executed_steps": executed_steps,
            })
            return payload
        payload["staged_text_verification"] = baseline_staged_verification
        payload["staged_text_verified"] = True
        payload["previous_clipboard_read"] = False
        payload["draft_clipboard_copy"] = False
        payload["clipboard_restored"] = True
        payload["clipboard_restore_status"] = "not_needed"
        if _tinder_staged_text_requires_host_visual_verification(
            baseline_staged_verification,
            draft_text,
            target_binding=target_binding,
            screen=baseline_screen,
            reused_existing_staged_text=True,
        ):
            payload["visual_verification_request"] = _tinder_visual_staged_verification_request(
                baseline_screen,
                baseline_staged_verification,
                draft_text,
                reused_existing_staged_text=True,
            )
            if stage_only:
                payload.update(
                    _iphone_stage_draft_payload_update(
                        staged_screen=baseline_screen,
                        staged_verification=_iphone_stage_needs_user_verification(
                            baseline_staged_verification,
                            reason="staged_text_requires_visual_verification",
                        ),
                        executed_steps=executed_steps,
                        conversation_state="tinder_conversation",
                        send_input_backend="already_staged",
                    )
                )
                return payload
            payload.update({
                "status": "needs_host_visual_verification",
                "reason": "staged_text_requires_visual_verification",
                "next_host_action": "visually_verify_staged_text_before_live_send",
                "executed_steps": executed_steps,
            })
            return payload
        stage_ready = True
    else:
        pre_stage_input_guard = _iphone_pre_stage_input_guard(
            app_id="tinder",
            screen=baseline_screen,
            expected_text=draft_text,
        )
        payload["pre_stage_input_guard"] = pre_stage_input_guard
        if pre_stage_input_guard.get("status") == "blocked":
            payload.update({
                "status": "blocked",
                "reason": pre_stage_input_guard.get("reason") or "message_input_not_empty_before_staging",
                "next_host_action": "clear_existing_message_input_before_stage",
                "staged_text_verified": False,
                "executed_steps": executed_steps,
            })
            return payload

        previous_clipboard = self._read_clipboard()
        payload["previous_clipboard_read"] = previous_clipboard["status"] == "ok"
        if previous_clipboard["status"] != "ok":
            payload.update({"status": "blocked", "reason": previous_clipboard.get("reason")})
            return payload
        payload.update(_text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))
        copy_result = self._copy_to_clipboard(draft_text)
        payload["draft_clipboard_copy"] = copy_result["status"] == "ok"
        if copy_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": copy_result.get("reason")})
            return payload

        try:
            input_result = self._click_ratio(window, input_step["tap_ratio"])
            executed_steps.append({**input_step, "result": input_result})
            if input_result["status"] != "ok":
                payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
                return payload
            time.sleep(0.2)

            paste_result = self._paste_clipboard_into_frontmost_app()
            executed_steps.append({**paste_step, "result": paste_result})
            if paste_result["status"] != "ok":
                payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
                return payload
            time.sleep(0.3)

            staged_output = output_dir / "iphone_mirroring.tinder.after_stage_message.png" if output_dir is not None else None
            staged_screen = self.capture_window(output=staged_output, window=window)
            staged_verification = _verify_staged_tinder_message(
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
            )
            if (
                staged_verification.get("status") != "ok"
                and _tinder_direct_type_fallback_allowed(draft_text)
                and not _tinder_send_button_visual_visible(staged_screen)
            ):
                type_result = self._type_text_into_frontmost_app(draft_text)
                executed_steps.append({**type_fallback_step, "result": type_result})
                if type_result["status"] != "ok":
                    payload.update({
                        "status": "blocked",
                        "reason": type_result.get("reason") or "direct_text_entry_failed",
                        "executed_steps": executed_steps,
                    })
                    return payload
                time.sleep(0.3)
                staged_output = output_dir / "iphone_mirroring.tinder.after_type_message.png" if output_dir is not None else None
                staged_screen = self.capture_window(output=staged_output, window=window)
                staged_verification = _verify_staged_tinder_message(
                    staged_screen,
                    draft_text,
                    baseline_screen=baseline_screen,
                )
                if (
                    staged_verification.get("status") != "ok"
                    and not _tinder_send_button_visual_visible(staged_screen)
                ):
                    ime_commit_result = self._press_space_key()
                    executed_steps.append({**ime_commit_step, "result": ime_commit_result})
                    if ime_commit_result["status"] != "ok":
                        payload.update({
                            "status": "blocked",
                            "reason": ime_commit_result.get("reason") or "ime_commit_space_failed",
                            "executed_steps": executed_steps,
                        })
                        return payload
                    time.sleep(0.3)
                    staged_output = (
                        output_dir / "iphone_mirroring.tinder.after_ime_commit_message.png"
                        if output_dir is not None
                        else None
                    )
                    staged_screen = self.capture_window(output=staged_output, window=window)
                    staged_verification = _verify_staged_tinder_message(
                        staged_screen,
                        draft_text,
                        baseline_screen=baseline_screen,
                    )
                payload["staging_input_backend"] = type_result.get("input_backend")
            payload["staged_text_verification"] = staged_verification
            payload["staged_text_verified"] = staged_verification.get("status") == "ok"
            if staged_verification.get("status") != "ok":
                if stage_only and staged_verification.get("status") == "needs_verification":
                    payload.update(
                        _iphone_stage_draft_payload_update(
                            staged_screen=staged_screen,
                            staged_verification=_iphone_stage_needs_user_verification(staged_verification),
                            executed_steps=executed_steps,
                            conversation_state="tinder_conversation",
                            send_input_backend=payload.get("staging_input_backend") or paste_result.get("input_backend"),
                        )
                    )
                    return payload
                payload.update({
                    "status": "blocked",
                    "reason": staged_verification.get("reason") or "staged_text_not_verified",
                    "executed_steps": executed_steps,
                })
                return payload
            if _tinder_staged_text_requires_host_visual_verification(
                staged_verification,
                draft_text,
                target_binding=target_binding,
                screen=staged_screen,
            ):
                payload["visual_verification_request"] = _tinder_visual_staged_verification_request(
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
                            conversation_state="tinder_conversation",
                            send_input_backend=payload.get("staging_input_backend") or paste_result.get("input_backend"),
                        )
                    )
                    return payload
                payload.update({
                    "status": "needs_host_visual_verification",
                    "reason": "staged_text_requires_visual_verification",
                    "next_host_action": "visually_verify_staged_text_before_live_send",
                    "executed_steps": executed_steps,
                })
                return payload
            stage_ready = True
        finally:
            restore_result = self._copy_to_clipboard(previous_clipboard.get("text", ""))
            payload["clipboard_restored"] = restore_result["status"] == "ok"
            payload["clipboard_restore_status"] = restore_result["status"]
            if restore_result["status"] != "ok":
                payload["clipboard_restore_reason"] = restore_result.get("reason")

    if not stage_ready:
        return payload
    if payload["clipboard_restored"] is not True:
        payload.update({
            "status": "blocked",
            "reason": "clipboard_restore_failed",
            "executed_steps": executed_steps,
        })
        return payload

    if stage_only:
        payload.update(
            _iphone_stage_draft_payload_update(
                staged_screen=staged_screen,
                staged_verification=staged_verification,
                executed_steps=executed_steps,
                conversation_state="tinder_conversation",
                send_input_backend=payload.get("staging_input_backend") or "stage_draft_existing_input",
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
    post_output = output_dir / "iphone_mirroring.tinder.after_send_message.png" if output_dir is not None else None
    post_screen = self.capture_window(output=post_output, window=window)
    payload["post_action_observation"] = _redacted_screen(post_screen)
    if post_screen.get("state") == TINDER_FEEDBACK_SURVEY_STATE:
        recovery = self._dismiss_tinder_feedback_survey(
            window,
            output_dir=output_dir,
            label="after_send_message",
        )
        payload["feedback_survey_recovery"] = recovery
        if recovery.get("status") == "ok":
            post_recovery_output = (
                output_dir / "iphone_mirroring.tinder.after_send_message.after_feedback_survey.png"
                if output_dir is not None
                else None
            )
            post_screen = self.capture_window(output=post_recovery_output, window=window)
            payload["post_action_observation_after_feedback_survey"] = _redacted_screen(post_screen)
        else:
            payload.update(
                {
                    "status": "needs_verification",
                    "reason": recovery.get("reason") or "feedback_survey_recovery_failed",
                    "executed_steps": executed_steps,
                }
            )
            return payload
    post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or _now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    payload["post_action_observation_id"] = post_observation_id
    payload["current_thread_visual_anchor"] = _iphone_current_thread_visual_anchor(
        post_screen,
        conversation_state="tinder_conversation",
    )
    post_screen_captured = post_screen.get("status") == "ok"
    outbound_verification = _verify_tinder_outbound_message(
        post_screen,
        draft_text,
        staged_screen=staged_screen,
    )
    payload["outbound_message_verification"] = outbound_verification
    outbound_verified = outbound_verification.get("status") == "ok"
    payload["evidence"] = EvidencePayload(
        staging=StagingResult.from_verification(
            staged_verification,
            staged_text_verified=bool(payload["staged_text_verified"]),
        ),
        post_send=PostSendVerification(
            post_action_observation_id=post_observation_id,
            input_cleared_after_send=outbound_verification.get("input_cleared_after_send") is True,
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
    elif outbound_verification.get("input_cleared_after_send") is not True:
        payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
    elif not outbound_verified:
        payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
    return payload


def _open_tinder_conversation_by_visible_name(
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
            "blocked_actions": list(BLOCKED_GUI_ACTIONS),
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
        "planned_steps": _tinder_action_steps("open-conversation", visible_name=marker),
        "blocked_actions": list(BLOCKED_GUI_ACTIONS),
    }
    before = output_dir / "iphone_mirroring.tinder.open_conversation.before.png" if output_dir is not None else None
    doctor = self.doctor(capture=True, output=before)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    window = _window_from_payload(doctor.get("window") or {})
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="open_conversation",
        )
        payload["subscription_paywall_recovery"] = recovery
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
                }
            )
            return payload
        screen_state = recovery.get("verification", {}).get("state")
    if screen_state == TINDER_FEEDBACK_SURVEY_STATE:
        recovery = self._dismiss_tinder_feedback_survey(
            window,
            output_dir=output_dir,
            label="open_conversation",
        )
        payload["feedback_survey_recovery"] = recovery
        if recovery.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": recovery.get("reason") or "tinder_feedback_survey_recovery_failed",
                }
            )
            return payload
        screen_state = recovery.get("verification", {}).get("state")

    executed_steps: list[dict[str, Any]] = []
    if screen_state != "tinder_messages":
        if screen_state not in TINDER_FOREGROUND_STATES:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "tinder_foreground_not_verified",
                    "screen_state": screen_state,
                }
            )
            return payload
        open_chats_step = _tinder_action_steps("open-chats")[0]
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
            output_dir / f"iphone_mirroring.tinder.conversation_search_{attempt + 1:02d}.png"
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
        if screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
            recovery = self._dismiss_tinder_subscription_paywall(
                window,
                output_dir=output_dir,
                label=f"open_conversation_search_{attempt + 1:02d}",
            )
            payload["subscription_paywall_recovery"] = recovery
            if recovery.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
                        "executed_steps": executed_steps,
                        "search_attempts": search_attempts,
                    }
                )
                return payload
            continue
        if screen.get("state") != "tinder_messages":
            payload.update(
                {
                    "status": "blocked",
                    "reason": "tinder_messages_not_verified",
                    "screen_state": screen.get("state"),
                    "executed_steps": executed_steps,
                    "search_attempts": search_attempts,
                }
            )
            return payload
        if locator.get("status") == "ok":
            y_ratio = float(locator["y_ratio"])
            if not 0.36 <= y_ratio <= 0.88:
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
                **_tap_step("tap_visible_conversation_row", x=0.50, y=y_ratio),
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
                output_dir / "iphone_mirroring.tinder.open_conversation.after_tap.png"
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
            if verification_screen.get("state") != "tinder_conversation":
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
                verification_method="tinder_open_conversation_visible_name",
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
        scroll_step = _tinder_action_steps("conversation-list-scroll-down")[0]
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


def _open_tinder_conversation_by_visual_anchor(
    self,
    *,
    visual_evidence: dict[str, Any],
    target_binding: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    return self._open_conversation_by_message_list_visual_anchor(
        app_id="tinder",
        visual_evidence=visual_evidence,
        target_binding=target_binding,
        output_dir=output_dir,
        chat_list_state="tinder_messages",
        conversation_state="tinder_conversation",
        foreground_states=TINDER_FOREGROUND_STATES,
        open_chats_step=_tinder_action_steps("open-chats")[0],
        return_to_chats_step=_tinder_action_steps("return-to-chats")[0],
        planned_steps=_tinder_action_steps(
            "open-conversation",
            message_list_evidence=visual_evidence,
            target_binding=target_binding,
        ),
        tap_intent="tap_visible_conversation_row",
        tap_x=0.50,
        tap_y_min=0.36,
        tap_y_max=0.88,
        output_prefix="iphone_mirroring.tinder",
        verification_method="tinder_open_conversation_visual_anchor",
        source_states={"tinder_messages"},
        blocked_state_reasons={TINDER_SUBSCRIPTION_PAYWALL_STATE: "tinder_subscription_paywall_visible"},
        guardrails={"blocked_actions": list(BLOCKED_GUI_ACTIONS)},
    )


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
    payload["subscription_paywall_recovery"] = recovery
    payload["next_host_action"] = (
        "navigate_to_verified_tinder_conversation_and_retry_stage"
        if stage_only
        else "navigate_to_verified_tinder_conversation_and_retry_send"
    )
    if recovery.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
            }
        )
        return payload
    if retry_attempted:
        payload.update(
            {
                "status": "blocked",
                "reason": "tinder_subscription_paywall_retry_already_attempted",
            }
        )
        return payload
    marker = _target_binding_primary_visible_name(target_binding or {})
    if not marker:
        payload.update({"status": "blocked", "reason": "tinder_subscription_paywall_dismissed"})
        return payload
    navigation = self._open_tinder_conversation_by_visible_name(
        visible_name=marker,
        target_binding=target_binding,
        output_dir=output_dir,
    )
    payload["post_paywall_navigation"] = navigation
    if navigation.get("status") != "ok":
        payload.update(
            {
                "status": "blocked",
                "reason": "post_paywall_target_navigation_failed",
                "post_paywall_navigation_reason": navigation.get("reason"),
            }
        )
        return payload
    retry_payload = self.send_tinder_message(
        draft_text,
        dry_run=False,
        output_dir=output_dir,
        target_binding=target_binding,
        _paywall_retry_attempted=True,
        stage_only=stage_only,
    )
    retry_payload["paywall_recovered_and_retried"] = True
    retry_payload["subscription_paywall_recovery"] = recovery
    retry_payload["post_paywall_navigation"] = navigation
    return retry_payload


def _dismiss_tinder_subscription_paywall(
    self,
    window: WindowInfo,
    *,
    output_dir: Path | None = None,
    label: str,
) -> dict[str, Any]:
    step = _tinder_subscription_paywall_dismiss_step()
    click_result = self._execute_step(window, step)
    verification_screen: dict[str, Any] = {"status": "not_run", "state": "unknown"}
    if click_result.get("status") == "ok":
        time.sleep(0.4)
        output = (
            output_dir / f"iphone_mirroring.tinder.subscription_paywall.{label}.after_dismiss.png"
            if output_dir is not None
            else None
        )
        verification_screen = self.capture_window(output=output, window=window)
    verification = _redacted_screen(verification_screen)
    if click_result.get("status") != "ok":
        status = "blocked"
        reason = click_result.get("reason") or "tinder_subscription_paywall_dismiss_failed"
    elif verification_screen.get("status") != "ok":
        status = "needs_verification"
        reason = verification_screen.get("reason") or "subscription_paywall_dismiss_verification_failed"
    elif verification_screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        status = "needs_verification"
        reason = "subscription_paywall_still_visible"
    else:
        status = "ok"
        reason = "subscription_paywall_dismissed"
    return {
        "schema_version": GUI_HARNESS_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "action": "dismiss_subscription_paywall",
        "executed_step": {**step, "result": click_result},
        "verification": verification,
        "subscription_purchase_executed": False,
    }


def _dismiss_tinder_feedback_survey(
    self,
    window: WindowInfo,
    *,
    output_dir: Path | None = None,
    label: str,
) -> dict[str, Any]:
    step = _tinder_feedback_survey_dismiss_step()
    click_result = self._execute_step(window, step)
    verification_screen: dict[str, Any] = {"status": "not_run", "state": "unknown"}
    if click_result.get("status") == "ok":
        time.sleep(0.4)
        output = (
            output_dir / f"iphone_mirroring.tinder.feedback_survey.{label}.after_dismiss.png"
            if output_dir is not None
            else None
        )
        verification_screen = self.capture_window(output=output, window=window)
    verification = _redacted_screen(verification_screen)
    if click_result.get("status") != "ok":
        status = "blocked"
        reason = click_result.get("reason") or "tinder_feedback_survey_dismiss_failed"
    elif verification_screen.get("status") != "ok":
        status = "needs_verification"
        reason = verification_screen.get("reason") or "feedback_survey_dismiss_verification_failed"
    elif verification_screen.get("state") == TINDER_FEEDBACK_SURVEY_STATE:
        status = "needs_verification"
        reason = "feedback_survey_still_visible"
    else:
        status = "ok"
        reason = "feedback_survey_dismissed"
    return {
        "schema_version": GUI_HARNESS_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "action": "dismiss_feedback_survey",
        "executed_step": {**step, "result": click_result},
        "verification": verification,
        "rating_submitted": False,
    }


def _verify_tinder_target_binding(
    self,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if target_binding.get("binding_type") == "current_thread_visual_identity":
        return self._verify_iphone_current_thread_visual_identity(
            app_id="tinder",
            target_binding=target_binding,
            output_dir=output_dir,
            conversation_state="tinder_conversation",
            blocked_state_reasons={TINDER_SUBSCRIPTION_PAYWALL_STATE: "tinder_subscription_paywall_visible"},
            output_name="iphone_mirroring.tinder.target_binding.png",
            verification_method="tinder_current_thread_visual_identity",
        )
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        return self._verify_chat_list_row_target_binding(
            app_id="tinder",
            target_binding=target_binding,
            output_dir=output_dir,
            source_states={"tinder_messages"},
            conversation_state="tinder_conversation",
            blocked_state_reasons={TINDER_SUBSCRIPTION_PAYWALL_STATE: "tinder_subscription_paywall_visible"},
            output_name="iphone_mirroring.tinder.target_binding.png",
            verification_method="tinder_chat_list_row_to_thread_structural_binding",
        )

    markers = _target_binding_required_markers(target_binding)
    base = {
        "verification_method": "tinder_screen_ocr_required_visible_text",
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "required_marker_hashes": [_hash_text(marker) for marker in markers],
        "requires_target_specific_marker": True,
    }
    if not markers:
        return {**base, "status": "blocked", "reason": "target_binding_required"}
    if not target_binding_specific_marker_present("tinder", target_binding):
        return {**base, "status": "blocked", "reason": "target_binding_not_target_specific"}
    window = self._window_info()
    if window is None:
        return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
    output = output_dir / "iphone_mirroring.tinder.target_binding.png" if output_dir is not None else None
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
    if screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        return {**result, "status": "blocked", "reason": "tinder_subscription_paywall_visible"}
    if screen.get("state") != "tinder_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    return {**result, "status": "ok"}


def _recover_tinder_current_thread_visual_identity_mismatch(
    self,
    target_binding: dict[str, Any],
    *,
    output_dir: Path | None = None,
    target_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return self._recover_iphone_current_thread_visual_identity_mismatch(
        app_id="tinder",
        target_binding=target_binding,
        target_verification=target_verification,
        output_dir=output_dir,
        chat_list_state="tinder_messages",
        conversation_state="tinder_conversation",
        foreground_states=TINDER_FOREGROUND_STATES,
        open_chats_step=_tinder_action_steps("open-chats")[0],
        return_to_chats_step=_tinder_action_steps("return-to-chats")[0],
        secondary_close_steps={"tinder_profile": _tinder_action_steps("close-preview")[0]},
        guardrails={"blocked_actions": list(BLOCKED_GUI_ACTIONS)},
        layout_hints_fn=_tinder_layout_hints,
        message_list_visual_anchor_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        blocked_state_reasons={TINDER_SUBSCRIPTION_PAYWALL_STATE: "tinder_subscription_paywall_visible"},
        tap_intent="tap_tinder_relocated_visual_conversation_target",
        tap_x=0.50,
        tap_y_min=0.30,
        tap_y_max=0.88,
        output_prefix="iphone_mirroring.tinder",
        verify_target_binding=self._verify_tinder_target_binding,
    )


def _tinder_message_input_placeholder_visible(text: str) -> bool:
    placeholder_markers = {
        "message",
        "消息",
        "发消息",
        "发送消息",
        "输入消息",
        "输入信息",
        "发一条消息",
    }
    for line in text.splitlines():
        normalized = _normalize_text(line.strip())
        comparable = _message_text_comparable(line)
        if normalized in placeholder_markers or comparable in placeholder_markers:
            return True
    return False


def _verify_staged_tinder_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    result = _staged_text_ocr_evidence(
        verification_method="tinder_staged_message_ocr_payload_text",
        observed_text=observed_text,
        expected_text=expected_text,
        baseline_text=baseline_text,
        screen=screen,
        redact_screen=_redacted_screen,
    )
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if not result["exact_text_ocr_verified"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if (
        result["baseline_expected_text_occurrences"] is not None
        and result["observed_expected_text_occurrences"] <= result["baseline_expected_text_occurrences"]
    ):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    return {**result, "status": "ok"}


def _verify_tinder_outbound_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    staged_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _verify_outbound_message(screen, expected_text)
    if result.get("status") != "ok":
        return result
    observed_text = str(screen.get("text") or "")
    staged_text = str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    observed_stats = _expected_text_observation_stats(observed_text, expected_text)
    staged_stats = _expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    extra = {
        "verification_method": "tinder_post_send_ocr_payload_text_delta",
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
        "input_cleared_after_send": not _tinder_send_marker_visible(observed_text),
        "exact_text_ocr_verified": result.get("status") == "ok",
        "visual_only_exact_verification_allowed": False,
    }
    if extra["input_cleared_after_send"] is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    if staged_stats and observed_stats["normalized_text_hash"] == staged_stats["normalized_text_hash"]:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}


def _tinder_staged_text_requires_host_visual_verification(
    staged_verification: dict[str, Any],
    expected_text: str,
    *,
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    reused_existing_staged_text: bool = False,
) -> bool:
    if staged_verification.get("status") != "ok":
        return False
    if screen.get("status") != "ok" or not screen.get("path"):
        return False
    if reused_existing_staged_text:
        return True
    if not isinstance(target_binding, dict) or target_binding.get("binding_type") != "chat_list_row_to_thread":
        return False
    comparable_expected = _message_text_comparable(expected_text)
    if len(comparable_expected) > 3:
        return False
    baseline_occurrences = int(staged_verification.get("baseline_expected_text_occurrences") or 0)
    observed_occurrences = int(staged_verification.get("observed_expected_text_occurrences") or 0)
    return baseline_occurrences > 0 and observed_occurrences > baseline_occurrences


def _tinder_visual_staged_verification_request(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
    *,
    reused_existing_staged_text: bool = False,
) -> dict[str, Any]:
    return _staged_text_visual_verification_request(
        screen=screen,
        staged_verification=staged_verification,
        expected_text=expected_text,
        extra={"reused_existing_staged_text": reused_existing_staged_text},
        instructions="Visually inspect the focused Tinder input and confirm it exactly matches the current payload before any live send. Do not treat OCR text elsewhere in the thread as proof that the input box contains the payload.",
    )


def _tinder_send_marker_visible(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped in {"send", "发送"}:
            return True
    return False


def _tinder_direct_type_fallback_allowed(text: str) -> bool:
    return direct_text_entry_block_reason(text) is None


def _tinder_send_button_visual_visible(screen: dict[str, Any]) -> bool:
    path = screen.get("path")
    if not isinstance(path, str) or not path:
        return False
    try:
        pixels = _read_png_pixels_for_send_button(Path(path))
    except (OSError, ValueError, zlib.error, struct.error):
        return False
    stats = _region_stats_for_send_button(pixels, 0.87, 0.90, 0.96, 0.98)
    return stats["color_ratio"] > 0.08 and stats["mid_ratio"] > 0.08


def _apply_tinder_paywall_recovery_result(payload: dict[str, Any], recovery: dict[str, Any]) -> None:
    payload["subscription_paywall_recovery"] = recovery
    payload["next_host_action"] = "navigate_to_verified_tinder_conversation_and_retry_send"
    if recovery.get("status") == "ok":
        payload.update({"status": "blocked", "reason": "tinder_subscription_paywall_dismissed"})
    else:
        payload.update(
            {
                "status": "blocked",
                "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
            }
        )


__all__ = [name for name in globals() if not name.startswith("__")]
