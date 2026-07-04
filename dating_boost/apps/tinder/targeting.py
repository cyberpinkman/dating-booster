from __future__ import annotations

from dating_boost.apps.iphone_targeting import *

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
