from __future__ import annotations

from dating_boost.apps.iphone_targeting import *

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


def _tinder_send_steps(stage_only: bool) -> dict[str, Any]:
    risk = "draft_staging_only" if stage_only else "live_send_precondition"
    input_step = {
        "intent": "tap_tinder_message_input",
        "tap_ratio": {"x": 0.45, "y": 0.92},
        "risk": risk,
        "requires_verified_tinder_thread": True,
        "does_not_send": stage_only,
    }
    paste_step = {
        "intent": "paste_clipboard_into_tinder_message_input",
        "risk": risk,
        "requires_exact_text_match": True,
        "does_not_send": stage_only,
    }
    type_fallback_step = {
        "intent": "type_tinder_message_input_if_paste_did_not_stage",
        "risk": risk,
        "fallback_only": True,
        "requires_ascii_draft": True,
        "requires_exact_text_verification_after_direct_type": True,
        "does_not_send": stage_only,
    }
    ime_commit_step = {
        "intent": "commit_tinder_message_input_ime_candidate_if_needed",
        "risk": risk,
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
    return {
        "input": input_step,
        "paste": paste_step,
        "type_fallback": type_fallback_step,
        "ime_commit": ime_commit_step,
        "send": send_step,
        "planned": planned_steps,
    }


def _initial_tinder_send_payload(
    self: Any,
    *,
    draft_text: str,
    dry_run: bool,
    stage_only: bool,
    planned_steps: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
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
    return payload


def _prepare_tinder_send_context(
    self,
    payload: dict[str, Any],
    draft_text: str,
    *,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
    _paywall_retry_attempted: bool = False,
    stage_only: bool = False,
) -> dict[str, Any]:
    preflight_output = output_dir / "iphone_mirroring.tinder.before_send_message.png" if output_dir is not None else None
    preflight = self.doctor(capture=True, output=preflight_output)
    payload["preflight"] = preflight
    if preflight["status"] != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "tinder_preflight_not_verified"})
        return {"return_payload": payload}
    window = _window_from_payload(preflight.get("window") or {})
    if preflight.get("screen", {}).get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="before_send_message",
        )
        return {
            "return_payload": self._recover_tinder_subscription_paywall_for_send(
                payload,
                recovery,
                draft_text=draft_text,
                output_dir=output_dir,
                target_binding=target_binding,
                retry_attempted=_paywall_retry_attempted,
                stage_only=stage_only,
            )
        }
        return {"return_payload": payload}

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
                return {
                    "return_payload": self._recover_tinder_subscription_paywall_for_send(
                        payload,
                        recovery,
                        draft_text=draft_text,
                        output_dir=output_dir,
                        target_binding=target_binding,
                        retry_attempted=_paywall_retry_attempted,
                        stage_only=stage_only,
                    )
                }
                return {"return_payload": payload}
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
                return {"return_payload": payload}

    baseline_output = output_dir / "iphone_mirroring.tinder.before_stage_message.png" if output_dir is not None else None
    baseline_screen = self.capture_window(output=baseline_output, window=window)
    payload["pre_stage_observation"] = _redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return {"return_payload": payload}
    if baseline_screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
        recovery = self._dismiss_tinder_subscription_paywall(
            window,
            output_dir=output_dir,
            label="before_stage_message",
        )
        return {
            "return_payload": self._recover_tinder_subscription_paywall_for_send(
                payload,
                recovery,
                draft_text=draft_text,
                output_dir=output_dir,
                target_binding=target_binding,
                retry_attempted=_paywall_retry_attempted,
                stage_only=stage_only,
            )
        }
        return {"return_payload": payload}
    if baseline_screen.get("state") != "tinder_conversation":
        payload.update({"status": "blocked", "reason": "tinder_conversation_not_verified"})
        return {"return_payload": payload}

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
        return {"return_payload": payload}

    return {"window": window, "baseline_screen": baseline_screen}


def _stage_tinder_send_input(
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

    executed_steps: list[dict[str, Any]] = []
    baseline_staged_verification = _verify_staged_tinder_message(baseline_screen, draft_text)
    reused = _reuse_existing_tinder_staged_input_if_present(
        payload,
        draft_text,
        baseline_screen=baseline_screen,
        baseline_staged_verification=baseline_staged_verification,
        target_binding=target_binding,
        stage_only=stage_only,
        executed_steps=executed_steps,
    )
    if reused.get("return_payload") is not None:
        return reused
    if reused.get("stage_ready"):
        staged = reused
    else:
        prepared = _prepare_tinder_stage_clipboard(self, payload, draft_text, baseline_screen, executed_steps)
        if prepared.get("return_payload") is not None:
            return prepared
        previous_clipboard = prepared["previous_clipboard"]
        try:
            staged = _paste_and_verify_tinder_stage_input(
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
    }


def _reuse_existing_tinder_staged_input_if_present(
    payload: dict[str, Any],
    draft_text: str,
    *,
    baseline_screen: dict[str, Any],
    baseline_staged_verification: dict[str, Any],
    target_binding: dict[str, Any] | None,
    stage_only: bool,
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    if baseline_staged_verification.get("status") != "ok":
        return {}
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
        return {"return_payload": payload}
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
            return {"return_payload": payload}
        payload.update({
            "status": "needs_host_visual_verification",
            "reason": "staged_text_requires_visual_verification",
            "next_host_action": "visually_verify_staged_text_before_live_send",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    return {
        "stage_ready": True,
        "staged_screen": baseline_screen,
        "staged_verification": baseline_staged_verification,
    }


def _prepare_tinder_stage_clipboard(
    self,
    payload: dict[str, Any],
    draft_text: str,
    baseline_screen: dict[str, Any],
    executed_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    pre_stage_input_guard = _tinder_pre_stage_input_guard(baseline_screen, draft_text)
    payload["pre_stage_input_guard"] = pre_stage_input_guard
    if pre_stage_input_guard.get("status") == "blocked":
        payload.update({
            "status": "blocked",
            "reason": pre_stage_input_guard.get("reason") or "message_input_not_empty_before_staging",
            "next_host_action": "clear_existing_message_input_before_stage",
            "staged_text_verified": False,
            "executed_steps": executed_steps,
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


def _paste_and_verify_tinder_stage_input(
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
    initial = _paste_tinder_stage_input(
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
    fallback = _tinder_stage_direct_type_fallback_if_needed(
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
    finish = _finish_tinder_stage_verification(
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
    return {"staged_screen": staged_screen, "staged_verification": staged_verification}


def _paste_tinder_stage_input(
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
    time.sleep(0.2)

    paste_result = self._paste_clipboard_into_frontmost_app()
    executed_steps.append({**paste_step, "result": paste_result})
    if paste_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
        return {"return_payload": payload}
    time.sleep(0.3)

    staged_output = output_dir / "iphone_mirroring.tinder.after_stage_message.png" if output_dir is not None else None
    staged_screen = self.capture_window(output=staged_output, window=window)
    staged_verification = _verify_staged_tinder_message(
        staged_screen,
        draft_text,
        baseline_screen=baseline_screen,
    )
    return {"staged_screen": staged_screen, "staged_verification": staged_verification, "paste_result": paste_result}


def _tinder_stage_direct_type_fallback_if_needed(
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
        and _tinder_direct_type_fallback_allowed(draft_text)
        and not _tinder_send_button_visual_visible(staged_screen)
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
        committed = _tinder_commit_ime_after_direct_type(
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


def _tinder_commit_ime_after_direct_type(
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
    return {"staged_screen": staged_screen, "staged_verification": staged_verification}


def _finish_tinder_stage_verification(
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
                    conversation_state="tinder_conversation",
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
            return {"return_payload": payload}
        payload.update({
            "status": "needs_host_visual_verification",
            "reason": "staged_text_requires_visual_verification",
            "next_host_action": "visually_verify_staged_text_before_live_send",
            "executed_steps": executed_steps,
        })
        return {"return_payload": payload}
    return {}


def _complete_tinder_send(
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
) -> dict[str, Any]:
    send_step = steps["send"]
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
    steps = _tinder_send_steps(stage_only)
    payload = _initial_tinder_send_payload(
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

    prepared = _prepare_tinder_send_context(
        self,
        payload,
        draft_text,
        output_dir=output_dir,
        target_binding=target_binding,
        _paywall_retry_attempted=_paywall_retry_attempted,
        stage_only=stage_only,
    )
    if prepared.get("return_payload") is not None:
        return prepared["return_payload"]

    staged = _stage_tinder_send_input(
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

    return _complete_tinder_send(
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

def _tinder_pre_stage_input_guard(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    guard = _iphone_pre_stage_input_guard(
        app_id="tinder",
        screen=screen,
        expected_text=expected_text,
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
