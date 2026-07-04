from __future__ import annotations

from dating_boost.apps.iphone_targeting import *

def observe_bumble_screen(self, *, output_dir: Path | None = None) -> dict[str, Any]:
    payload = {
        **self._base_payload("ok"),
        "target": "bumble_screen",
        **_bumble_guardrails_payload(),
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = self.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload

    window = _window_from_payload(doctor.get("window") or {})
    output = output_dir / "iphone_mirroring.bumble.observe.png" if output_dir is not None else None
    screen = self.capture_window(output=output, window=window)
    payload["screen"] = _redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    payload["layout_hints"] = _bumble_layout_hints(screen)
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason")})
    elif screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        payload.update({"status": "blocked", "reason": screen.get("state")})
    elif screen.get("state") not in BUMBLE_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "bumble_foreground_not_verified"})
    return payload


def launch_bumble(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    planned_steps = _launch_app_steps(app_name="Bumble", search_result_intent="tap_bumble_search_result_icon")
    payload = {
        **self._base_payload("ok"),
        "target": "bumble_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **_bumble_guardrails_payload(),
    }
    if dry_run:
        return payload
    doctor_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        doctor_output = output_dir / "iphone_mirroring.bumble.before_launch.png"
    doctor = self.doctor(capture=True, output=doctor_output)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    state = doctor.get("screen", {}).get("state")
    if state in BUMBLE_FOREGROUND_STATES:
        payload["reason"] = "bumble_already_foreground"
        return payload

    window = _window_from_payload(doctor.get("window") or {})
    executed_steps: list[dict[str, Any]] = []
    for step in planned_steps:
        result = self._execute_step(window, step)
        executed_steps.append({**step, "result": result})
        if result["status"] != "ok":
            payload.update({"status": "blocked", "reason": result["reason"], "executed_steps": executed_steps})
            return payload
        time.sleep(float(step.get("wait_after_seconds", 0.2)))
    payload["executed_steps"] = executed_steps
    verification_output = output_dir / "iphone_mirroring.bumble.after_launch.png" if output_dir is not None else None
    verification = self.capture_window(output=verification_output, window=window)
    payload["verification"] = _redacted_screen(verification)
    if verification["state"] not in BUMBLE_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "bumble_launch_not_verified"})
    return payload


def run_bumble_action(
    self,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _bumble_action_steps(action, **options)
    except KeyError:
        return {
            **self._base_payload("blocked"),
            "action": action,
            "reason": "unknown_bumble_harness_action",
            **_bumble_guardrails_payload(),
        }
    payload = {
        **self._base_payload("ok"),
        "action": action,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **_bumble_guardrails_payload(),
    }
    if dry_run:
        return payload
    if action == "prepare-message-page":
        return self._prepare_iphone_message_page(
            payload,
            app_id="bumble",
            output_dir=output_dir,
            output_prefix="iphone_mirroring.bumble",
            chat_list_state="bumble_chat_list",
            returnable_states={"bumble_conversation", "bumble_opening_move"},
            foreground_states=BUMBLE_FOREGROUND_STATES,
            open_chats_step=_bumble_action_steps("open-chats")[0],
            return_to_chats_step=_bumble_action_steps("return-to-chats")[0],
            secondary_close_steps={"bumble_profile": _bumble_action_steps("close-profile")[0]},
            guardrails=_bumble_guardrails_payload(),
            layout_hints_fn=_bumble_layout_hints,
            message_list_visual_anchor_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        )
    if action == "open-conversation":
        target_binding = options.get("target_binding")
        visual_evidence = _message_list_visual_anchor_evidence_from_options(
            options,
            target_binding=target_binding if isinstance(target_binding, dict) else None,
            default_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
            default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
        )
        if visual_evidence.get("status") == "ok":
            return self._open_bumble_conversation_by_visual_anchor(
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
            return self._open_bumble_conversation_by_visible_name(
                visible_name=visible_name,
                target_binding=target_binding if isinstance(target_binding, dict) else None,
                output_dir=output_dir,
            )
    return self._execute_planned_steps(payload, output_dir=output_dir)


def run_bumble_workflow(
    self,
    workflow: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _bumble_workflow_steps(workflow, **options)
    except KeyError:
        return {
            **self._base_payload("blocked"),
            "workflow": workflow,
            "reason": "unknown_bumble_harness_workflow",
            **_bumble_guardrails_payload(),
        }
    payload = {
        **self._base_payload("ok"),
        "workflow": workflow,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **_bumble_guardrails_payload(),
    }
    if dry_run:
        return payload
    return self._execute_planned_steps(payload, output_dir=output_dir)


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


def send_bumble_message(
    self,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
    stage_only: bool = False,
) -> dict[str, Any]:
    input_step = {
        "intent": "tap_bumble_message_input",
        "tap_ratio": {"x": 0.45, "y": 0.92},
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "requires_verified_bumble_thread": True,
        "does_not_send": stage_only,
    }
    paste_step = {
        "intent": "paste_clipboard_into_bumble_message_input",
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "requires_exact_text_match": True,
        "does_not_send": stage_only,
    }
    type_fallback_step = {
        "intent": "type_bumble_message_input_if_paste_did_not_stage",
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
        "fallback_only": True,
        "requires_ascii_draft": True,
        "requires_exact_text_verification_after_direct_type": True,
        "does_not_send": stage_only,
    }
    ime_commit_step = {
        "intent": "commit_bumble_message_input_ime_candidate_if_needed",
        "risk": "draft_staging_only" if stage_only else "live_send_precondition",
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
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    preflight_output = output_dir / "iphone_mirroring.bumble.before_send_message.png" if output_dir is not None else None
    preflight = self.doctor(capture=True, output=preflight_output)
    payload["preflight"] = preflight
    if preflight.get("status") != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "bumble_preflight_not_verified"})
        return payload
    window = _window_from_payload(preflight.get("window") or {})
    preflight_screen = preflight.get("screen") if isinstance(preflight.get("screen"), dict) else {}
    if preflight_screen.get("state") == "bumble_opening_move":
        payload.update({
            "status": "blocked",
            "reason": "bumble_opening_move_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_opening_move_reply",
        })
        return payload
    if preflight_screen.get("state") != "bumble_conversation":
        payload.update({"status": "blocked", "reason": "bumble_conversation_not_verified"})
        return payload

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
                return payload

    baseline_output = output_dir / "iphone_mirroring.bumble.before_stage_message.png" if output_dir is not None else None
    baseline_screen = self.capture_window(output=baseline_output, window=window)
    payload["pre_stage_observation"] = _redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return payload
    if baseline_screen.get("state") == "bumble_opening_move":
        payload.update({
            "status": "blocked",
            "reason": "bumble_opening_move_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_opening_move_reply",
        })
        return payload
    if baseline_screen.get("state") != "bumble_conversation":
        payload.update({"status": "blocked", "reason": "bumble_conversation_not_verified"})
        return payload

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
        return payload

    pre_stage_input_guard = _iphone_pre_stage_input_guard(
        app_id="bumble",
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
            "executed_steps": [],
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

    executed_steps: list[dict[str, Any]] = []
    staged_screen = baseline_screen
    try:
        input_result = self._click_ratio(window, input_step["tap_ratio"])
        executed_steps.append({**input_step, "result": input_result})
        if input_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(0.45)

        paste_result = self._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
        executed_steps.append({**paste_step, "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(0.3)

        staged_output = output_dir / "iphone_mirroring.bumble.after_stage_message.png" if output_dir is not None else None
        staged_screen = self.capture_window(output=staged_output, window=window)
        staged_verification = _verify_staged_bumble_message(
            staged_screen,
            draft_text,
            baseline_screen=baseline_screen,
        )
        if (
            staged_verification.get("status") != "ok"
            and _bumble_direct_type_fallback_allowed(draft_text)
            and not _bumble_active_send_button_visual_visible(staged_screen)
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
                staged_output = output_dir / "iphone_mirroring.bumble.after_ime_commit_message.png" if output_dir is not None else None
                staged_screen = self.capture_window(output=staged_output, window=window)
                staged_verification = _verify_staged_bumble_message(
                    staged_screen,
                    draft_text,
                    baseline_screen=baseline_screen,
                    trusted_direct_input=True,
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
                        conversation_state="bumble_conversation",
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
                return payload
            payload.update({
                "status": "needs_host_visual_verification",
                "reason": "staged_text_requires_visual_verification",
                "next_host_action": "visually_verify_staged_text_before_live_send",
                "executed_steps": executed_steps,
            })
            return payload
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
        return payload

    if stage_only:
        payload.update(
            _iphone_stage_draft_payload_update(
                staged_screen=staged_screen,
                staged_verification=staged_verification,
                executed_steps=executed_steps,
                conversation_state="bumble_conversation",
                send_input_backend=payload.get("staging_input_backend") or paste_result.get("input_backend"),
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


def _verify_bumble_step_precondition(
    self,
    window: WindowInfo,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_bumble_step_precondition(step):
        return {"status": "ok"}
    output = None
    if output_dir is not None:
        output = output_dir / f"iphone_mirroring.bumble_precondition_{step_index:02d}.png"
    screen = self.capture_window(output=output, window=window)
    result = {
        "status": screen.get("status", "blocked"),
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "bumble_precondition_capture_failed"
    elif step.get("requires_bumble_top_level_tab_bar") and not _bumble_top_level_bottom_nav_present(screen):
        result.update({"status": "blocked", "reason": "bumble_top_level_tab_bar_not_verified"})
    else:
        state_check = _verify_bumble_step_state(screen, step, key="requires_bumble_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "bumble_step_precondition_not_verified"
    return result


def _verify_bumble_step_postcondition(
    self,
    window: WindowInfo,
    step: dict[str, Any],
    *,
    output_dir: Path | None,
    step_index: int,
) -> dict[str, Any]:
    if not _has_bumble_step_postcondition(step):
        return {"status": "ok", "checked": False}
    output = None
    if output_dir is not None:
        output = output_dir / f"iphone_mirroring.bumble_postcondition_{step_index:02d}.png"
    screen = self.capture_window(output=output, window=window)
    result = {
        "status": screen.get("status", "blocked"),
        "checked": True,
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
    }
    if result["status"] != "ok":
        result["reason"] = screen.get("reason") or "bumble_postcondition_capture_failed"
    else:
        state_check = _verify_bumble_step_state(screen, step, key="expected_bumble_states")
        if state_check["status"] != "ok":
            result.update(state_check)
            result["reason"] = "bumble_step_postcondition_not_verified"
    return result


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


__all__ = [name for name in globals() if not name.startswith("__")]
