from __future__ import annotations

from dating_boost.core import gui_harness as _platform


for _name, _value in vars(_platform).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

del _name, _value


BLOCKED_GUI_ACTIONS = ["send", "like", "super_like", "unmatch", "report", "profile_edit"]
WECHAT_BLOCKED_GUI_ACTIONS = ["send", "payments", "calls", "contact_exchange_without_user"]
BUMBLE_BLOCKED_GUI_ACTIONS = [
    "send",
    "like",
    "superswipe",
    "pass",
    "unmatch",
    "report",
    "profile_edit",
    "premium_purchase",
    "opening_move_enable",
    "opening_move_skip",
    "opening_move_decide_reply_satisfaction",
    "opening_move_send",
]
BUMBLE_SEND_BLOCKED_GUI_ACTIONS = [
    "like",
    "superswipe",
    "pass",
    "unmatch",
    "report",
    "profile_edit",
    "premium_purchase",
    "opening_move_enable",
    "opening_move_skip",
    "opening_move_decide_reply_satisfaction",
    "opening_move_autonomous_send",
]
BUMBLE_OPENING_MOVE_POLICY: dict[str, Any] = {
    "scope": "bumble_opening_move",
    "female_user": {
        "agent_decision_authority": "none",
        "user_decision_required": [
            "enable_opening_move",
            "skip_opening_move",
            "accept_male_reply",
            "reject_male_reply",
        ],
        "agent_allowed_actions": [
            "observe_opening_move_prompt",
            "summarize_visible_reply",
            "ask_user_to_decide",
        ],
        "agent_disallowed_actions": [
            "enable_opening_move",
            "skip_opening_move",
            "accept_male_reply",
            "reject_male_reply",
        ],
    },
    "male_user": {
        "agent_may_draft_reply": True,
        "requires_user_confirmation_before_send": True,
        "current_harness_stage_supported": True,
        "current_harness_send_supported": True,
        "autonomous_opening_move_send_supported": False,
        "agent_allowed_actions": ["draft_opening_move_reply"],
        "agent_disallowed_actions": [
            "send_opening_move_reply_without_user_confirmation",
            "autonomous_opening_move_send",
        ],
    },
}
TINDER_SUBSCRIPTION_PAYWALL_STATE = "tinder_subscription_paywall"
TINDER_FEEDBACK_SURVEY_STATE = "tinder_feedback_survey"


def _bumble_guardrails_payload() -> dict[str, Any]:
    return {
        "blocked_actions": list(BUMBLE_BLOCKED_GUI_ACTIONS),
        "opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY),
    }


class AppSpecificNativeGuiSessionMixin:
    def capture_window(self, *, output: Path | None = None, window: WindowInfo | None = None) -> dict[str, Any]:
        if window is None:
            window = self._window_info()
        if window is None:
            return {
                "status": "blocked",
                "reason": "iphone_mirroring_window_not_found",
                "state": "unknown",
                "ocr_status": "not_run",
            }
        output = (output or _default_screenshot_path()).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        result = self.runner.run(
            [
                "screencapture",
                "-x",
                "-R",
                f"{window.x},{window.y},{window.width},{window.height}",
                str(output),
            ]
        )
        if result.returncode != 0:
            return {
                "status": "blocked",
                "reason": "screenshot_failed",
                "stderr": _short(result.stderr),
                "state": "unknown",
                "ocr_status": "not_run",
            }
        ocr = self._ocr(output)
        app_observer = getattr(self, "app_screen_state_observer", None)
        if callable(app_observer):
            text = ocr.get("text", "")
            observed = app_observer(output, text)
            text_state = observed["text_state"]
            visual = {
                "status": observed["visual_status"],
                "state": observed["visual_state"],
                "active_tab": observed.get("visual_active_tab", "unknown"),
                "bottom_nav_present": observed.get("visual_bottom_nav_present", False),
            }
            state = observed["state"]
        elif self.app_id == "wechat":
            text_state = classify_wechat_screen_text(ocr.get("text", ""))
            visual = {"status": "not_applicable", "state": "unknown"}
            state = text_state
        elif self.app_id == "bumble":
            text = ocr.get("text", "")
            text_state = classify_bumble_screen_text(text)
            visual = classify_bumble_screen_image(output)
            state = _combine_bumble_screen_states(
                text_state,
                visual["state"],
                text,
                visual_bottom_nav_present=bool(visual.get("bottom_nav_present")),
            )
        else:
            text = ocr.get("text", "")
            text_state = classify_screen_text(text)
            visual = classify_screen_image(output)
            state = _combine_screen_states(text_state, visual["state"], text)
        return {
            "schema_version": GUI_HARNESS_SCHEMA_VERSION,
            "status": "ok",
            "path": str(output),
            "state": state,
            "text_state": text_state,
            "visual_state": visual["state"],
            "visual_status": visual["status"],
            "visual_active_tab": visual.get("active_tab", "unknown"),
            "visual_bottom_nav_present": visual.get("bottom_nav_present", False),
            "ocr_status": ocr["status"],
            "ocr_error": ocr.get("error"),
            "text": ocr.get("text", ""),
        }

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
        payload = {
            **self._base_payload("ok"),
            "action": "send_message",
            "target": "wechat_message_input",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": planned_steps,
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            **_text_fingerprint_fields("draft_clipboard", draft_text),
            "blocked_actions": ["payments", "calls", "contact_exchange_without_user"],
            "live_send": True,
            "requires_explicit_authorization": True,
        }
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
        payload["evidence"] = {
            "staged_text_verified": bool(stage_payload.get("staged_text_verified")),
            "send_input_backend": send_result.get("input_backend"),
            "input_cleared_after_send": input_cleared,
            "post_action_screen_captured": post_screen_captured,
            "outbound_message_verified": outbound_verified,
            "post_action_observation_id": post_observation_id,
        }
        if not input_cleared:
            payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
        elif not post_screen_captured:
            payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
        elif not outbound_verified:
            payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
        return payload


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
        if action == "open-conversation":
            visible_name = str(options.get("visible_name") or "").strip()
            target_binding = options.get("target_binding")
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


    def send_bumble_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_step = {
            "intent": "tap_bumble_message_input",
            "tap_ratio": {"x": 0.45, "y": 0.92},
            "risk": "live_send_precondition",
            "requires_verified_bumble_thread": True,
        }
        paste_step = {
            "intent": "paste_clipboard_into_bumble_message_input",
            "risk": "live_send_precondition",
            "requires_exact_text_match": True,
        }
        type_fallback_step = {
            "intent": "type_bumble_message_input_if_paste_did_not_stage",
            "risk": "live_send_precondition",
            "fallback_only": True,
            "requires_ascii_draft": True,
            "requires_exact_text_verification_after_direct_type": True,
        }
        ime_commit_step = {
            "intent": "commit_bumble_message_input_ime_candidate_if_needed",
            "risk": "live_send_precondition",
            "fallback_only": True,
            "requires_failed_direct_type_verification": True,
            "requires_exact_text_verification_after_commit": True,
        }
        send_step = {
            "intent": "tap_bumble_send_button",
            "tap_ratio": {"x": 0.94, "y": 0.92},
            "risk": "live_send",
            "requires_explicit_authorization": True,
            "visual_only_exact_verification_allowed": False,
        }
        payload = {
            **self._base_payload("ok"),
            "action": "send_message",
            "target": "bumble_message_input",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": [input_step, paste_step, type_fallback_step, ime_commit_step, send_step],
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            **_text_fingerprint_fields("draft_clipboard", draft_text),
            "blocked_actions": list(BUMBLE_SEND_BLOCKED_GUI_ACTIONS),
            "opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY),
            "live_send": True,
            "requires_explicit_authorization": True,
        }
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
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
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
                payload.update({
                    "status": "blocked",
                    "reason": staged_verification.get("reason") or "staged_text_not_verified",
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
        payload["evidence"] = {
            "staged_text_verified": bool(payload.get("staged_text_verified")),
            "staged_exact_text_ocr_verified": bool(staged_verification.get("exact_text_ocr_verified")),
            "send_input_backend": send_result.get("input_backend"),
            "input_cleared_after_send": input_cleared,
            "post_action_screen_captured": post_screen_captured,
            "outbound_message_verified": outbound_verified,
            "outbound_exact_text_ocr_verified": bool(outbound_verification.get("exact_text_ocr_verified")),
            "visual_only_exact_verification_allowed": False,
            "post_action_observation_id": post_observation_id,
        }
        if not post_screen_captured:
            payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
        elif not input_cleared:
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
    ) -> dict[str, Any]:
        input_step = {
            "intent": "tap_tinder_message_input",
            "tap_ratio": {"x": 0.45, "y": 0.92},
            "risk": "live_send_precondition",
            "requires_verified_tinder_thread": True,
        }
        paste_step = {
            "intent": "paste_clipboard_into_tinder_message_input",
            "risk": "live_send_precondition",
            "requires_exact_text_match": True,
        }
        send_step = {
            "intent": "tap_tinder_send_button",
            "tap_ratio": {"x": 0.90, "y": 0.92},
            "risk": "live_send",
            "requires_explicit_authorization": True,
        }
        payload = {
            **self._base_payload("ok"),
            "action": "send_message",
            "target": "tinder_message_input",
            "mode": "dry_run" if dry_run else "execute",
            "planned_steps": [input_step, paste_step, send_step],
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            **_text_fingerprint_fields("draft_clipboard", draft_text),
            "blocked_actions": ["like", "super_like", "unmatch", "report", "profile_edit"],
            "live_send": True,
            "requires_explicit_authorization": True,
        }
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
                    )
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
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
            )
        if baseline_screen.get("state") != "tinder_conversation":
            payload.update({"status": "blocked", "reason": "tinder_conversation_not_verified"})
            return payload

        executed_steps: list[dict[str, Any]] = []
        stage_ready = False
        staged_screen = baseline_screen
        baseline_staged_verification = _verify_staged_tinder_message(baseline_screen, draft_text)
        if baseline_staged_verification.get("status") == "ok":
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
            baseline_staged_verification["reused_existing_staged_text"] = True
            payload["staged_text_verification"] = baseline_staged_verification
            payload["staged_text_verified"] = True
            payload["previous_clipboard_read"] = False
            payload["draft_clipboard_copy"] = False
            payload["clipboard_restored"] = True
            payload["clipboard_restore_status"] = "not_needed"
            stage_ready = True
        else:
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
                payload["staged_text_verification"] = staged_verification
                payload["staged_text_verified"] = staged_verification.get("status") == "ok"
                if staged_verification.get("status") != "ok":
                    payload.update({
                        "status": "blocked",
                        "reason": staged_verification.get("reason") or "staged_text_not_verified",
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
        post_screen_captured = post_screen.get("status") == "ok"
        outbound_verification = _verify_tinder_outbound_message(
            post_screen,
            draft_text,
            staged_screen=staged_screen,
        )
        payload["outbound_message_verification"] = outbound_verification
        outbound_verified = outbound_verification.get("status") == "ok"
        payload["evidence"] = {
            "staged_text_verified": payload["staged_text_verified"],
            "send_input_backend": send_result.get("input_backend"),
            "input_cleared_after_send": outbound_verification.get("input_cleared_after_send") is True,
            "post_action_screen_captured": post_screen_captured,
            "outbound_message_verified": outbound_verified,
            "post_action_observation_id": post_observation_id,
        }
        if not post_screen_captured:
            payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
        elif not outbound_verified:
            payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
        return payload


    def _execute_planned_steps(self, payload: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        before = output_dir / "iphone_mirroring.before_action.png" if output_dir is not None else None
        doctor = self.doctor(capture=True, output=before)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        screen_state = doctor.get("screen", {}).get("state")
        window = _window_from_payload(doctor.get("window") or {})
        requires_paywall = any(step.get("requires_tinder_subscription_paywall") for step in payload["planned_steps"])
        requires_feedback_survey = any(step.get("requires_tinder_feedback_survey") for step in payload["planned_steps"])
        if requires_paywall:
            if screen_state != TINDER_SUBSCRIPTION_PAYWALL_STATE:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "tinder_subscription_paywall_not_visible",
                        "screen_state": screen_state,
                    }
                )
                return payload
        elif requires_feedback_survey:
            if screen_state != TINDER_FEEDBACK_SURVEY_STATE:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "tinder_feedback_survey_not_visible",
                        "screen_state": screen_state,
                    }
                )
                return payload
        elif screen_state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
            recovery = self._dismiss_tinder_subscription_paywall(
                window,
                output_dir=output_dir,
                label="pre_action",
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
        if any(step.get("requires_verified_tinder_screen") for step in payload["planned_steps"]):
            if screen_state not in TINDER_FOREGROUND_STATES:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "tinder_foreground_not_verified",
                        "screen_state": screen_state,
                    }
                )
                return payload
        if any(step.get("requires_verified_bumble_screen") for step in payload["planned_steps"]):
            if screen_state not in BUMBLE_FOREGROUND_STATES:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "bumble_foreground_not_verified",
                        "screen_state": screen_state,
                    }
                )
                return payload
        app_verified_screen_key = getattr(self, "app_verified_screen_key", None)
        app_foreground_states = getattr(self, "app_foreground_states", None)
        if app_verified_screen_key and any(step.get(app_verified_screen_key) for step in payload["planned_steps"]):
            if screen_state not in set(app_foreground_states or ()):
                payload.update(
                    {
                        "status": "blocked",
                        "reason": getattr(self, "app_foreground_not_verified_reason", "app_foreground_not_verified"),
                        "screen_state": screen_state,
                    }
                )
                return payload
        executed_steps: list[dict[str, Any]] = []
        profile_read_captures: list[dict[str, Any]] = []
        profile_read_texts: list[str] = []
        for step in payload["planned_steps"]:
            precondition = self._verify_bumble_step_precondition(
                window,
                step,
                output_dir=output_dir,
                step_index=len(executed_steps) + 1,
            )
            if precondition["status"] == "ok":
                app_precondition_verifier = getattr(self, "app_step_precondition_verifier", None)
                if callable(app_precondition_verifier):
                    precondition = app_precondition_verifier(
                        self,
                        window,
                        step,
                        output_dir=output_dir,
                        step_index=len(executed_steps) + 1,
                    )
            if precondition["status"] != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": precondition["reason"],
                        "screen_state": precondition.get("screen_state"),
                        "precondition": precondition,
                    }
                )
                return payload
            if step["intent"] == "capture_profile_read_step":
                output = None
                if output_dir is not None:
                    output = output_dir / f"iphone_mirroring.profile_read_step_{len(profile_read_captures) + 1:02d}.png"
                screen = self.capture_window(output=output, window=window)
                result = {
                    "status": screen.get("status", "blocked"),
                    "screen": _redacted_screen(screen),
                }
                profile_read_captures.append(result["screen"])
                profile_read_texts.append(str(screen.get("text") or ""))
            elif step["intent"] == "safe_expand_visible_profile_section":
                output = None
                if output_dir is not None:
                    output = output_dir / f"iphone_mirroring.profile_expand_check_{len(profile_read_captures) + 1:02d}.png"
                screen = self.capture_window(output=output, window=window)
                observed_text = str(screen.get("text") or "")
                result = {
                    "status": screen.get("status", "blocked"),
                    "screen": _redacted_screen(screen),
                    "skipped": False,
                }
                if result["status"] != "ok":
                    result["reason"] = screen.get("reason") or "profile_expand_check_failed"
                elif _tinder_profile_danger_action_visible(observed_text):
                    result.update({"status": "ok", "skipped": True, "reason": "dangerous_profile_action_visible"})
                elif not _tinder_profile_expand_control_visible(observed_text):
                    result.update({"status": "ok", "skipped": True, "reason": "profile_expand_control_not_visible"})
                else:
                    click_result = self._click_ratio(window, step["tap_ratio"])
                    result.update({"click_result": click_result, "status": click_result["status"]})
                    if click_result["status"] != "ok":
                        result["reason"] = click_result.get("reason") or "profile_expand_click_failed"
                profile_read_captures.append(result["screen"])
                profile_read_texts.append(observed_text)
            else:
                result = self._execute_step(window, step)
            executed_step = {**step, "result": result}
            if result["status"] != "ok":
                executed_steps.append(executed_step)
                payload.update({"status": "blocked", "reason": result.get("reason", "tinder_action_step_failed"), "executed_steps": executed_steps})
                return payload
            time.sleep(float(step.get("wait_after_seconds", 0.2)))
            postcondition = self._verify_bumble_step_postcondition(
                window,
                step,
                output_dir=output_dir,
                step_index=len(executed_steps) + 1,
            )
            if postcondition.get("status") == "ok" and postcondition.get("checked") is False:
                app_postcondition_verifier = getattr(self, "app_step_postcondition_verifier", None)
                if callable(app_postcondition_verifier):
                    postcondition = app_postcondition_verifier(
                        self,
                        window,
                        step,
                        output_dir=output_dir,
                        step_index=len(executed_steps) + 1,
                    )
            if postcondition["status"] != "ok":
                executed_step["postcondition"] = postcondition
                executed_steps.append(executed_step)
                payload.update(
                    {
                        "status": "blocked",
                        "reason": postcondition["reason"],
                        "screen_state": postcondition.get("screen_state"),
                        "postcondition": postcondition,
                        "executed_steps": executed_steps,
                    }
                )
                return payload
            if postcondition.get("status") == "ok" and postcondition.get("checked"):
                executed_step["postcondition"] = postcondition
            executed_steps.append(executed_step)
        payload["executed_steps"] = executed_steps
        if profile_read_captures:
            payload["profile_read_captures"] = profile_read_captures
            app_profile_field_coverage = getattr(self, "app_profile_field_coverage", None)
            if callable(app_profile_field_coverage):
                payload["field_coverage"] = app_profile_field_coverage("\n".join(profile_read_texts))
            elif self.app_id == "bumble":
                payload["field_coverage"] = _bumble_profile_field_coverage("\n".join(profile_read_texts))
            else:
                payload["field_coverage"] = _tinder_profile_field_coverage("\n".join(profile_read_texts))
        after = output_dir / "iphone_mirroring.after_action.png" if output_dir is not None else None
        verification_screen = self.capture_window(output=after, window=window)
        payload["verification"] = _redacted_screen(verification_screen)
        if verification_screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
            recovery = self._dismiss_tinder_subscription_paywall(
                window,
                output_dir=output_dir,
                label="after_action",
            )
            _apply_tinder_paywall_recovery_result(payload, recovery)
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


    def _locate_visible_text_y_ratio(self, screen: dict[str, Any], marker: str) -> dict[str, Any]:
        marker_hash = _hash_text(marker)
        path = screen.get("path")
        if screen.get("status") != "ok":
            return {"status": "blocked", "reason": screen.get("reason") or "screen_not_captured", "target_marker_hash": marker_hash}
        if not isinstance(path, str) or not path:
            return {"status": "blocked", "reason": "screen_path_required", "target_marker_hash": marker_hash}
        tsv = self._ocr_tsv(Path(path))
        if tsv.get("status") != "ok":
            return {
                "status": "blocked",
                "reason": tsv.get("reason") or "visible_text_ocr_tsv_failed",
                "target_marker_hash": marker_hash,
            }
        return _visible_text_location_from_tsv(str(tsv.get("text") or ""), marker, Path(path))


    def _ocr_tsv(self, image_path: Path) -> dict[str, str]:
        if not self._command_available("tesseract"):
            return {"status": "unavailable", "text": "", "reason": "ocr_unavailable"}
        result = self.runner.run(
            [
                "tesseract",
                str(image_path),
                "stdout",
                "-l",
                "eng+chi_sim",
                "--psm",
                "6",
                "tsv",
            ]
        )
        if result.returncode != 0:
            fallback = self.runner.run(["tesseract", str(image_path), "stdout", "--psm", "6", "tsv"])
            if fallback.returncode != 0:
                return {"status": "failed", "text": "", "error": _short(fallback.stderr or result.stderr)}
            return {"status": "ok", "text": fallback.stdout}
        return {"status": "ok", "text": result.stdout}


    def _recover_tinder_subscription_paywall_for_send(
        self,
        payload: dict[str, Any],
        recovery: dict[str, Any],
        *,
        draft_text: str,
        output_dir: Path | None,
        target_binding: dict[str, Any] | None,
        retry_attempted: bool,
    ) -> dict[str, Any]:
        payload["subscription_paywall_recovery"] = recovery
        payload["next_host_action"] = "navigate_to_verified_tinder_conversation_and_retry_send"
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
        }
        if not markers:
            return {**base, "status": "blocked", "reason": "target_binding_required"}
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


    def _verify_bumble_target_binding(
        self,
        target_binding: dict[str, Any],
        *,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
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
        selection_evidence = (
            target_binding.get("selection_evidence")
            if isinstance(target_binding.get("selection_evidence"), dict)
            else {}
        )
        row_index = selection_evidence.get("row_index")
        base = {
            "verification_method": verification_method,
            "binding_type": target_binding.get("binding_type"),
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "row_index": row_index,
            "source_state": selection_evidence.get("source_state"),
            "opened_state": selection_evidence.get("opened_state"),
            "target_scope": selection_evidence.get("target_scope"),
            "open_action": selection_evidence.get("open_action"),
            "requires_target_specific_marker": True,
            "requires_header_marker": False,
            "emoji_nickname_supported": True,
            "visual_only_exact_verification_allowed": False,
        }
        if not target_binding_structural_evidence_present(app_id, target_binding):
            return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
        if selection_evidence.get("source_state") not in source_states:
            return {**base, "status": "blocked", "reason": "target_binding_source_state_mismatch"}
        if selection_evidence.get("opened_state") != conversation_state:
            return {**base, "status": "blocked", "reason": "target_binding_opened_state_mismatch"}
        if selection_evidence.get("open_action") != "open-conversation":
            return {**base, "status": "blocked", "reason": "target_binding_open_action_mismatch"}
        target_scope = selection_evidence.get("target_scope")
        if target_scope not in {None, "ordinary_conversation", "existing_conversation"}:
            return {**base, "status": "blocked", "reason": "target_binding_scope_not_ordinary_conversation"}
        window = self._window_info()
        if window is None:
            return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
        output = output_dir / output_name if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        observed_text = str(screen.get("text") or "")
        result = {
            **base,
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
            "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        }
        if screen.get("status") != "ok":
            return {**result, "status": "blocked", "reason": "target_binding_screen_capture_failed"}
        if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
            return {**result, "status": "blocked", "reason": screen.get("state")}
        blocked_reason = blocked_state_reasons.get(str(screen.get("state") or ""))
        if blocked_reason:
            return {**result, "status": "blocked", "reason": blocked_reason}
        if screen.get("state") != conversation_state:
            return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
        return {**result, "status": "ok"}


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

def _target_binding_required_markers(target_binding: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    value = target_binding.get("required_visible_text")
    if isinstance(value, list):
        markers.extend(str(item).strip() for item in value if str(item).strip())
    visible_name = target_binding.get("visible_name")
    if isinstance(visible_name, str) and visible_name.strip():
        markers.append(visible_name.strip())
    unique: list[str] = []
    for marker in markers:
        if marker not in unique:
            unique.append(marker)
    return unique



def _target_binding_primary_visible_name(target_binding: dict[str, Any]) -> str | None:
    markers = _target_binding_required_markers(target_binding)
    if markers:
        return markers[0]
    return None



def _redacted_target_binding(target_binding: dict[str, Any] | None) -> dict[str, Any] | None:
    if target_binding is None:
        return None
    return {
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "required_marker_hashes": [_hash_text(marker) for marker in _target_binding_required_markers(target_binding)],
    }



def _verify_target_binding_against_screen(
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
) -> dict[str, Any]:
    markers = _target_binding_required_markers(target_binding or {})
    if not markers and fallback_marker.strip():
        markers = [fallback_marker.strip()]
    observed_text = str(screen.get("text") or "")
    matched = [marker for marker in markers if _visible_text_contains_marker(observed_text, marker)]
    result = {
        "verification_method": verification_method,
        "target_match_id": target_binding.get("target_match_id") if isinstance(target_binding, dict) else None,
        "candidate_key": target_binding.get("candidate_key") if isinstance(target_binding, dict) else None,
        "required_marker_hashes": [_hash_text(marker) for marker in markers],
        "matched_marker_hashes": [_hash_text(marker) for marker in matched],
        "screen": _redacted_screen(screen),
        "screen_state": screen.get("state", "unknown"),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "target_binding_screen_capture_failed"}
    if screen.get("state") != "tinder_conversation":
        return {**result, "status": "blocked", "reason": "target_binding_chat_not_verified"}
    if not markers:
        return {**result, "status": "blocked", "reason": "target_binding_required"}
    if len(matched) != len(markers):
        return {**result, "status": "blocked", "reason": "target_binding_mismatch"}
    return {**result, "status": "ok"}



def _visible_text_location_from_tsv(tsv_text: str, marker: str, image_path: Path) -> dict[str, Any]:
    marker_hash = _hash_text(marker)
    try:
        image_height = int(_read_png_pixels_for_send_button(image_path)["height"])
    except (OSError, ValueError, zlib.error, struct.error):
        image_height = 0
    if image_height <= 0:
        return {"status": "blocked", "reason": "locator_image_dimensions_unavailable", "target_marker_hash": marker_hash}
    lines: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        key = (
            str(row.get("block_num") or ""),
            str(row.get("par_num") or ""),
            str(row.get("line_num") or ""),
        )
        lines.setdefault(key, []).append(row)
    for rows in lines.values():
        line_text = " ".join(str(row.get("text") or "").strip() for row in rows if str(row.get("text") or "").strip())
        if not _visible_text_contains_marker(line_text, marker):
            continue
        bounds: list[tuple[int, int]] = []
        for row in rows:
            try:
                top = int(float(str(row.get("top") or "0")))
                height = int(float(str(row.get("height") or "0")))
            except ValueError:
                continue
            bounds.append((top, top + height))
        if not bounds:
            continue
        y_ratio = (min(top for top, _bottom in bounds) + max(bottom for _top, bottom in bounds)) / 2 / image_height
        return {
            "status": "ok",
            "target_marker_hash": marker_hash,
            "line_hash": _hash_text(line_text),
            "line_character_count": len(line_text),
            "y_ratio": round(y_ratio, 4),
        }
    return {"status": "not_found", "reason": "visible_text_marker_not_found", "target_marker_hash": marker_hash}



def _visible_text_contains_marker(observed_text: str, marker: str) -> bool:
    marker = marker.strip()
    if not marker:
        return False
    return _normalize_text(marker) in _normalize_text(observed_text) or _message_text_comparable(marker) in _message_text_comparable(observed_text)



def _verify_staged_tinder_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    text_matches = _message_text_matches(observed_text, expected_text)
    observed_stats = _expected_text_observation_stats(observed_text, expected_text)
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    baseline_stats = _expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    result = {
        "verification_method": "tinder_staged_message_ocr_payload_text",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": observed_stats["text_hash"],
        "observed_character_count": observed_stats["text_character_count"],
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "baseline_expected_text_occurrences": baseline_stats["expected_text_occurrences"] if baseline_stats else None,
        "baseline_text_hash": baseline_stats["text_hash"] if baseline_stats else None,
        "screen": _redacted_screen(screen),
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if not text_matches:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
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
    }
    if extra["input_cleared_after_send"] is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    if staged_stats and observed_stats["normalized_text_hash"] == staged_stats["normalized_text_hash"]:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}



def _verify_staged_bumble_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    observed_stats = _expected_text_observation_stats(observed_text, expected_text)
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    baseline_stats = _expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    active_send_button_visible = _bumble_active_send_button_visual_visible(screen)
    result = {
        "verification_method": "bumble_staged_message_ocr_payload_text",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": observed_stats["text_hash"],
        "observed_character_count": observed_stats["text_character_count"],
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "baseline_expected_text_occurrences": baseline_stats["expected_text_occurrences"] if baseline_stats else None,
        "baseline_text_hash": baseline_stats["text_hash"] if baseline_stats else None,
        "active_send_button_visual_visible": active_send_button_visible,
        "exact_text_ocr_verified": _message_text_matches(observed_text, expected_text),
        "visual_only_exact_verification_allowed": False,
        "screen": _redacted_screen(screen),
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "bumble_opening_move":
        return {**result, "status": "blocked", "reason": "bumble_opening_move_requires_user_confirmation"}
    baseline_state = baseline_screen.get("state") if isinstance(baseline_screen, dict) else None
    if screen.get("state") != "bumble_conversation" and baseline_state != "bumble_conversation":
        return {**result, "status": "blocked", "reason": "bumble_conversation_not_verified"}
    if not _message_text_matches(observed_text, expected_text):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    if not _bumble_send_marker_visible(observed_text) and not active_send_button_visible:
        return {**result, "status": "needs_verification", "reason": "bumble_send_button_not_verified_after_staging"}
    return {**result, "status": "ok"}



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


def _verify_outbound_message(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    text_matches = _message_text_matches(observed_text, expected_text)
    result = {
        "verification_method": "wechat_post_send_ocr_payload_text",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        "observed_character_count": len(observed_text) if observed_text else None,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "post_action_screen_not_captured"}
    if not text_matches:
        return {**result, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, "status": "ok"}



def _expected_text_observation_stats(text: str, expected_text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    normalized_expected = _normalize_text(expected_text)
    comparable_text = _message_text_comparable(text)
    comparable_expected = _message_text_comparable(expected_text)
    return {
        "text_hash": _hash_text(text) if text else None,
        "normalized_text_hash": _hash_text(normalized_text) if normalized_text else None,
        "text_character_count": len(text) if text else None,
        "expected_text_occurrences": comparable_text.count(comparable_expected) if comparable_expected else 0,
    }



def _message_text_matches(observed_text: str, expected_text: str) -> bool:
    if not expected_text:
        return False
    if expected_text in observed_text or _normalize_text(expected_text) in _normalize_text(observed_text):
        return True
    comparable_expected = _message_text_comparable(expected_text)
    return bool(comparable_expected and comparable_expected in _message_text_comparable(observed_text))



def _message_text_comparable(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())



def _tinder_send_marker_visible(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped in {"send", "发送"}:
            return True
    return False



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



def _screen_region_stats(screen: dict[str, Any], x1: float, y1: float, x2: float, y2: float) -> dict[str, float] | None:
    path = screen.get("path")
    if not isinstance(path, str) or not path:
        return None
    try:
        pixels = _read_png_pixels_for_send_button(Path(path))
    except (OSError, ValueError, zlib.error, struct.error):
        return None
    return _region_stats_for_send_button(pixels, x1, y1, x2, y2)



def _direct_type_fallback_allowed(text: str) -> bool:
    return bool(text) and "\n" not in text



def _bumble_direct_type_fallback_allowed(text: str) -> bool:
    return bool(text) and "\n" not in text and all(32 <= ord(char) <= 126 for char in text)



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



def _has_bumble_step_precondition(step: dict[str, Any]) -> bool:
    return bool(step.get("requires_bumble_top_level_tab_bar") or step.get("requires_bumble_states"))



def _has_bumble_step_postcondition(step: dict[str, Any]) -> bool:
    return bool(step.get("expected_bumble_states"))



def _verify_bumble_step_state(screen: dict[str, Any], step: dict[str, Any], *, key: str) -> dict[str, Any]:
    expected = step.get(key)
    if not expected:
        return {"status": "ok"}
    expected_states = [str(expected)] if isinstance(expected, str) else [str(state) for state in expected]
    actual = str(screen.get("state") or "unknown")
    if actual in expected_states:
        return {"status": "ok"}
    return {
        "status": "blocked",
        "expected_bumble_states": expected_states,
        "actual_bumble_state": actual,
    }



def _tap_step(intent: str, *, x: float, y: float) -> dict[str, Any]:
    return {
        "intent": intent,
        "tap_ratio": {"x": x, "y": y},
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }



def _tinder_subscription_paywall_dismiss_step() -> dict[str, Any]:
    return {
        "intent": "tap_tinder_subscription_paywall_close",
        "tap_ratio": {"x": 0.09, "y": 0.14},
        "requires_tinder_subscription_paywall": True,
        "risk": "subscription_paywall_recovery",
        "subscription_purchase_executed": False,
    }



def _tinder_feedback_survey_dismiss_step() -> dict[str, Any]:
    return {
        "intent": "tap_tinder_feedback_survey_ignore",
        "tap_ratio": {"x": 0.50, "y": 0.64},
        "requires_tinder_feedback_survey": True,
        "risk": "feedback_survey_recovery",
        "rating_submitted": False,
    }



def _swipe_step(intent: str, *, from_x: float, from_y: float, to_x: float, to_y: float, duration_ms: int = 350) -> dict[str, Any]:
    return {
        "intent": intent,
        "swipe": {
            "from": {"x": from_x, "y": from_y},
            "to": {"x": to_x, "y": to_y},
            "duration_ms": duration_ms,
        },
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }



def _wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "wheel": {
            "x": x,
            "y": y,
            "delta_y": delta_y,
            "delta_x": delta_x,
            "repeats": repeats,
            "interval_us": 18000,
        },
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }



def _capture_profile_read_step(*, app_id: str = "tinder") -> dict[str, Any]:
    if app_id == "bumble":
        requires_key = "requires_verified_bumble_screen"
    else:
        requires_key = "requires_verified_tinder_screen"
    step = {
        "intent": "capture_profile_read_step",
        requires_key: True,
        "risk": "navigation_only",
        "wait_after_seconds": 0.0,
    }
    if app_id == "bumble":
        step["requires_bumble_states"] = ["bumble_browse", "bumble_profile", "bumble_self_profile"]
    return step



def _safe_expand_step() -> dict[str, Any]:
    return {
        "intent": "safe_expand_visible_profile_section",
        "tap_ratio": {"x": 0.50, "y": 0.76},
        "requires_verified_tinder_screen": True,
        "risk": "navigation_only",
    }



def _tinder_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    match_index = int(options.get("match_index") or 1)
    row_y = min(0.86, 0.30 + (max(row_index, 1) - 1) * 0.12)
    if options.get("y_ratio") is not None:
        row_y = max(0.12, min(0.88, float(options["y_ratio"])))
    match_x = min(0.86, 0.42 + (max(match_index, 1) - 1) * 0.24)
    target = str(options.get("target") or "row")
    conversation_x = 0.14 if target == "avatar" else 0.50
    visible_name = str(options.get("visible_name") or "").strip()
    target_binding = options.get("target_binding")
    if not visible_name and isinstance(target_binding, dict):
        visible_name = _target_binding_primary_visible_name(target_binding) or ""
    if action == "open-conversation" and visible_name:
        marker_hash = _hash_text(visible_name)
        return [
            {
                "intent": "locate_visible_conversation_name",
                "target_marker_hash": marker_hash,
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
            {
                "intent": "tap_visible_conversation_row",
                "target_marker_hash": marker_hash,
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
        ]
    actions: dict[str, list[dict[str, Any]]] = {
        "open-chats": [_tap_step("tap_chats_tab", x=0.66, y=0.94)],
        "matches-carousel-next": [_wheel_step("wheel_new_matches_left", x=0.56, y=0.30, delta_x=-20, repeats=18)],
        "matches-carousel-previous": [_wheel_step("wheel_new_matches_right", x=0.56, y=0.30, delta_x=20, repeats=18)],
        "conversation-list-scroll-down": [
            _wheel_step("wheel_conversation_list_down", x=0.50, y=0.78, delta_y=-20, repeats=14)
        ],
        "conversation-list-scroll-up": [
            _wheel_step("wheel_conversation_list_up", x=0.50, y=0.46, delta_y=20, repeats=14)
        ],
        "open-new-match": [{**_tap_step("tap_new_match_card", x=match_x, y=0.30), "match_index": match_index}],
        "open-conversation": [
            {**_tap_step("tap_conversation_row", x=conversation_x, y=row_y), "row_index": row_index, "target": target}
        ],
        "open-thread-profile": [_tap_step("tap_thread_profile_avatar", x=0.50, y=0.14)],
        "open-self-profile-preview": [_tap_step("tap_self_profile_avatar", x=0.14, y=0.13)],
        "profile-photo-next": [_tap_step("tap_photo_next", x=0.86, y=0.45)],
        "profile-photo-previous": [_tap_step("tap_photo_previous", x=0.14, y=0.45)],
        "open-full-profile": [_tap_step("tap_profile_up_arrow", x=0.90, y=0.82)],
        "profile-scroll-down": [_wheel_step("wheel_profile_read_down", x=0.50, y=0.86, delta_y=-20, repeats=18)],
        "profile-scroll-up": [_wheel_step("wheel_profile_read_up", x=0.50, y=0.46, delta_y=20, repeats=18)],
        "expand-visible-profile-section": [_safe_expand_step()],
        "close-full-profile": [_tap_step("tap_profile_down_arrow", x=0.90, y=0.08)],
        "close-preview": [_tap_step("tap_preview_done", x=0.90, y=0.08)],
        "return-to-chats": [_tap_step("tap_thread_back_to_chats", x=0.09, y=0.13)],
        "dismiss-subscription-paywall": [_tinder_subscription_paywall_dismiss_step()],
        "dismiss-feedback-survey": [_tinder_feedback_survey_dismiss_step()],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]



def _tinder_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "self-profile-read":
        photo_steps = max(0, int(options.get("photo_steps", 1)))
        scroll_steps = max(0, int(options.get("scroll_steps", 1)))
        steps: list[dict[str, Any]] = []
        steps.extend(_tinder_action_steps("open-self-profile-preview"))
        for _ in range(photo_steps):
            steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("profile-photo-previous"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        steps.extend(_tinder_action_steps("close-preview"))
        return steps
    if workflow == "chat-read-match-profile":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps", 1)))
        conversation_row = int(options.get("conversation_row", 1))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        steps.extend(_tinder_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_tinder_action_steps("open-thread-profile"))
        steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        return steps
    if workflow == "new-match-open":
        carousel_swipes = max(0, int(options.get("carousel_swipes", 0)))
        match_index = int(options.get("match_index", 1))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        for _ in range(carousel_swipes):
            steps.extend(_tinder_action_steps("matches-carousel-next"))
        steps.extend(_tinder_action_steps("open-new-match", match_index=match_index))
        return steps
    if workflow == "new-match-read-profile":
        carousel_swipes = max(0, int(options.get("carousel_swipes", 0)))
        match_index = int(options.get("match_index", 1))
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps", 1)))
        steps = []
        steps.extend(_tinder_action_steps("open-chats"))
        for _ in range(carousel_swipes):
            steps.extend(_tinder_action_steps("matches-carousel-next"))
        steps.extend(_tinder_action_steps("open-new-match", match_index=match_index))
        steps.extend(_tinder_action_steps("open-thread-profile"))
        steps.extend(_tinder_action_steps("profile-photo-next"))
        steps.extend(_tinder_action_steps("open-full-profile"))
        steps.append(_capture_profile_read_step())
        for _ in range(profile_scroll_steps):
            steps.extend(_tinder_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("expand-visible-profile-section"))
        steps.append(_capture_profile_read_step())
        steps.extend(_tinder_action_steps("close-full-profile"))
        return steps
    raise KeyError(workflow)



def _bumble_tap_step(
    intent: str,
    *,
    x: float,
    y: float,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = {
        "intent": intent,
        "tap_ratio": {"x": x, "y": y},
        "requires_verified_bumble_screen": True,
        "risk": "navigation_only",
    }
    if requires_states is not None:
        step["requires_bumble_states"] = requires_states
    if expected_states is not None:
        step["expected_bumble_states"] = expected_states
    return step



def _bumble_bottom_tab_step(intent: str, *, x: float, y: float, expected_state: str) -> dict[str, Any]:
    return {
        "intent": intent,
        "tap_ratio": {"x": x, "y": y},
        "requires_verified_bumble_screen": True,
        "requires_bumble_top_level_tab_bar": True,
        "expected_bumble_states": [expected_state],
        "risk": "navigation_only",
    }



def _bumble_wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
    requires_states: list[str] | str | None = None,
    expected_states: list[str] | str | None = None,
) -> dict[str, Any]:
    step = {
        "intent": intent,
        "wheel": {
            "x": x,
            "y": y,
            "delta_y": delta_y,
            "delta_x": delta_x,
            "repeats": repeats,
            "interval_us": 18000,
        },
        "requires_verified_bumble_screen": True,
        "risk": "navigation_only",
    }
    if requires_states is not None:
        step["requires_bumble_states"] = requires_states
    if expected_states is not None:
        step["expected_bumble_states"] = expected_states
    return step



def _bumble_action_steps(action: str, **options: Any) -> list[dict[str, Any]]:
    row_index = int(options.get("row_index") or options.get("conversation_row") or 1)
    match_index = int(options.get("match_index") or 1)
    row_y = min(0.86, 0.53 + (max(row_index, 1) - 1) * 0.12)
    if options.get("y_ratio") is not None:
        row_y = max(0.16, min(0.88, float(options["y_ratio"])))
    match_x = min(0.84, 0.34 + (max(match_index, 1) - 1) * 0.21)
    profile_read_states = ["bumble_browse", "bumble_profile", "bumble_self_profile"]
    actions: dict[str, list[dict[str, Any]]] = {
        "open-profile-tab": [_bumble_bottom_tab_step("tap_bumble_profile_tab", x=0.11, y=0.93, expected_state="bumble_self_profile")],
        "open-discover": [_bumble_bottom_tab_step("tap_bumble_discover_tab", x=0.31, y=0.93, expected_state="bumble_discover")],
        "open-browse": [_bumble_bottom_tab_step("tap_bumble_browse_tab", x=0.50, y=0.93, expected_state="bumble_browse")],
        "open-liked-you": [_bumble_bottom_tab_step("tap_bumble_liked_you_tab", x=0.70, y=0.93, expected_state="bumble_liked_you")],
        "open-chats": [_bumble_bottom_tab_step("tap_bumble_chats_tab", x=0.89, y=0.93, expected_state="bumble_chat_list")],
        "conversation-list-scroll-down": [
            _bumble_wheel_step(
                "wheel_bumble_conversation_list_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=14,
                requires_states="bumble_chat_list",
                expected_states="bumble_chat_list",
            )
        ],
        "conversation-list-scroll-up": [
            _bumble_wheel_step(
                "wheel_bumble_conversation_list_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=14,
                requires_states="bumble_chat_list",
                expected_states="bumble_chat_list",
            )
        ],
        "open-conversation": [
            {
                **_bumble_tap_step(
                    "tap_bumble_conversation_row",
                    x=0.43,
                    y=row_y,
                    requires_states="bumble_chat_list",
                    expected_states="bumble_conversation",
                ),
                "row_index": row_index,
            }
        ],
        "open-match": [
            {
                **_bumble_tap_step(
                    "tap_bumble_match_circle",
                    x=match_x,
                    y=0.245,
                    requires_states="bumble_chat_list",
                    expected_states=["bumble_opening_move", "bumble_conversation"],
                ),
                "match_index": match_index,
            }
        ],
        "open-thread-profile": [
            _bumble_tap_step(
                "tap_bumble_thread_name",
                x=0.32,
                y=0.13,
                requires_states="bumble_conversation",
                expected_states="bumble_profile",
            )
        ],
        "open-opening-move-reply": [
            _bumble_tap_step(
                "tap_bumble_opening_move_reply",
                x=0.24,
                y=0.735,
                requires_states="bumble_opening_move",
                expected_states="bumble_conversation",
            )
        ],
        "profile-scroll-down": [
            _bumble_wheel_step(
                "wheel_bumble_profile_read_down",
                x=0.50,
                y=0.78,
                delta_y=-18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "profile-scroll-up": [
            _bumble_wheel_step(
                "wheel_bumble_profile_read_up",
                x=0.50,
                y=0.46,
                delta_y=18,
                repeats=18,
                requires_states=profile_read_states,
                expected_states=profile_read_states,
            )
        ],
        "close-profile": [
            _bumble_tap_step(
                "tap_bumble_profile_close",
                x=0.09,
                y=0.13,
                requires_states="bumble_profile",
                expected_states="bumble_conversation",
            )
        ],
        "return-to-chats": [
            _bumble_tap_step(
                "tap_bumble_back_to_chats",
                x=0.09,
                y=0.13,
                requires_states=["bumble_conversation", "bumble_opening_move"],
                expected_states="bumble_chat_list",
            )
        ],
    }
    if action not in actions:
        raise KeyError(action)
    return actions[action]



def _bumble_workflow_steps(workflow: str, **options: Any) -> list[dict[str, Any]]:
    if workflow == "browse-profile-read":
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or options.get("scroll_steps") or 2))
        steps = []
        steps.extend(_bumble_action_steps("open-browse"))
        steps.append(_capture_profile_read_step(app_id="bumble"))
        for _ in range(profile_scroll_steps):
            steps.extend(_bumble_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step(app_id="bumble"))
        return steps
    if workflow == "chat-read-match-profile":
        conversation_row = int(options.get("conversation_row") or 1)
        profile_scroll_steps = max(0, int(options.get("profile_scroll_steps") or 2))
        steps = []
        steps.extend(_bumble_action_steps("open-chats"))
        steps.extend(_bumble_action_steps("open-conversation", row_index=conversation_row))
        steps.extend(_bumble_action_steps("open-thread-profile"))
        steps.append(_capture_profile_read_step(app_id="bumble"))
        for _ in range(profile_scroll_steps):
            steps.extend(_bumble_action_steps("profile-scroll-down"))
            steps.append(_capture_profile_read_step(app_id="bumble"))
        steps.extend(_bumble_action_steps("close-profile"))
        return steps
    if workflow == "opening-move-open":
        match_index = int(options.get("match_index") or 1)
        steps = []
        steps.extend(_bumble_action_steps("open-chats"))
        steps.extend(_bumble_action_steps("open-match", match_index=match_index))
        return steps
    if workflow == "opening-move-reply-composer":
        match_index = int(options.get("match_index") or 1)
        steps = []
        steps.extend(_bumble_action_steps("open-chats"))
        steps.extend(_bumble_action_steps("open-match", match_index=match_index))
        steps.extend(_bumble_action_steps("open-opening-move-reply"))
        return steps
    raise KeyError(workflow)


def _launch_tinder_steps() -> list[dict[str, Any]]:
    return _launch_app_steps(app_name="Tinder", search_result_intent="tap_tinder_search_result_icon")



def _launch_app_steps(
    *,
    app_name: str,
    search_result_intent: str,
    expected_app_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    type_step: dict[str, Any] = {
        "intent": "type_app_name_verified",
        "text": app_name,
        "risk": "navigation_only",
        "wait_after_seconds": 0.2,
    }
    if expected_app_labels is not None:
        type_step["expected_app_labels"] = list(expected_app_labels)
    return [
        {
            "intent": "open_iphone_home_screen",
            "risk": "navigation_only",
            "wait_after_seconds": 0.8,
        },
        {
            "intent": "open_ios_spotlight",
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
        type_step,
        {
            "intent": search_result_intent,
            "tap_ratio": {"x": 0.18, "y": 0.20},
            "risk": "navigation_only",
            "wait_after_seconds": 2.5,
        },
    ]



def _bumble_profile_field_coverage(text: str) -> dict[str, bool]:
    normalized = _normalize_text(text)
    return {
        "about_me": any(marker in normalized for marker in ("我的简介", "about me")),
        "basic_info": any(marker in normalized for marker in ("关于我", "cm", "身高")),
        "looking_for": any(marker in normalized for marker in ("我在寻找", "长期恋爱关系", "终身伴侣")),
        "interests": any(marker in normalized for marker in ("我的兴趣爱好", "兴趣")),
        "opening_move": "opening move" in normalized,
        "reply_deadline": any(marker in normalized for marker in ("回复时间", "小时后失效", "失效")),
    }
