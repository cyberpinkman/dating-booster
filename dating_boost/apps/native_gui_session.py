from __future__ import annotations

import hashlib

from dating_boost.core import gui_harness as _platform


for _name, _value in vars(_platform).items():
    if not _name.startswith("__"):
        globals()[_name] = _value

del _name, _value

from dating_boost.core.send_pipeline import (  # noqa: E402
    EvidencePayload,
    PostSendVerification,
    SendAttemptContext,
    StagingResult,
)
from dating_boost.core.harness_steps import (  # noqa: E402
    harness_step_validation_reason,
    marker_step as _harness_marker_step,
    swipe_step as _harness_swipe_step,
    tap_step as _harness_tap_step,
    wheel_step as _harness_wheel_step,
)
from dating_boost.core.target_binding import (  # noqa: E402
    RowToThreadBindingSpec,
    finish_row_to_thread_screen_verification,
    row_to_thread_base_result,
    validate_row_to_thread_structural_evidence,
)
from dating_boost.core.live_send_contract import (  # noqa: E402
    target_binding_specific_marker_present,
    target_binding_structural_evidence_present,
)


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
DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS = 2.0
TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION = {"x1": 0.0, "y1": 0.32, "x2": 1.0, "y2": 0.89}
BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION = {"x1": 0.0, "y1": 0.34, "x2": 1.0, "y2": 0.89}
IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE = 8
IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO = 0.90
IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y = 0.86
IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION = {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65}
IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE = 12
IPHONE_TARGET_RELOCATION_MAX_ATTEMPTS = 3


def _bumble_guardrails_payload() -> dict[str, Any]:
    return {
        "blocked_actions": list(BUMBLE_BLOCKED_GUI_ACTIONS),
        "opening_move_policy": copy.deepcopy(BUMBLE_OPENING_MOVE_POLICY),
    }


class AppSpecificNativeGuiSessionMixin:
    def capture_window(
        self,
        *,
        output: Path | None = None,
        window: WindowInfo | None = None,
        ocr: bool = True,
    ) -> dict[str, Any]:
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
        window_id = getattr(window, "window_id", None)
        if window_id is not None:
            command = ["screencapture", "-x", "-l", str(window_id), str(output)]
        else:
            command = [
                "screencapture",
                "-x",
                "-R",
                f"{window.x},{window.y},{window.width},{window.height}",
                str(output),
            ]
        result = self.runner.run(command)
        if result.returncode != 0:
            return {
                "status": "blocked",
                "reason": "screenshot_failed",
                "stderr": _short(result.stderr),
                "state": "unknown",
                "ocr_status": "not_run",
            }
        ocr_payload = self._ocr(output) if ocr else {"status": "skipped", "text": "", "error": None}
        app_observer = getattr(self, "app_screen_state_observer", None)
        if callable(app_observer):
            text = ocr_payload.get("text", "")
            observed = app_observer(output, text)
            text_state = observed["text_state"]
            visual = {
                "status": observed["visual_status"],
                "state": observed["visual_state"],
                "active_tab": observed.get("visual_active_tab", "unknown"),
                "bottom_nav_present": observed.get("visual_bottom_nav_present", False),
            }
            for key in (
                "chat_list_visual_present",
                "chat_list_visual_signal",
                "message_list_top_anchor_present",
                "message_list_top_anchor_signal",
                "recommend_card_visual_present",
                "recommend_card_visual_signal",
                "conversation_toolbar_present",
            ):
                if key in observed:
                    visual[key] = observed[key]
            state = observed["state"]
        elif self.app_id == "wechat":
            text_state = classify_wechat_screen_text(ocr_payload.get("text", ""))
            visual = {"status": "not_applicable", "state": "unknown"}
            state = text_state
        elif self.app_id == "bumble":
            text = ocr_payload.get("text", "")
            text_state = classify_bumble_screen_text(text)
            visual = classify_bumble_screen_image(output)
            state = _combine_bumble_screen_states(
                text_state,
                visual["state"],
                text,
                visual_bottom_nav_present=bool(visual.get("bottom_nav_present")),
            )
        else:
            text = ocr_payload.get("text", "")
            text_state = classify_screen_text(text)
            visual = classify_screen_image(output)
            state = _combine_screen_states(text_state, visual["state"], text)
        payload = {
            "schema_version": GUI_HARNESS_SCHEMA_VERSION,
            "status": "ok",
            "path": str(output),
            "state": state,
            "text_state": text_state,
            "visual_state": visual["state"],
            "visual_status": visual["status"],
            "visual_active_tab": visual.get("active_tab", "unknown"),
            "visual_bottom_nav_present": visual.get("bottom_nav_present", False),
            "ocr_status": ocr_payload["status"],
            "ocr_error": ocr_payload.get("error"),
            "text": ocr_payload.get("text", ""),
        }
        for key in (
            "chat_list_visual_present",
            "chat_list_visual_signal",
            "message_list_top_anchor_present",
            "message_list_top_anchor_signal",
            "recommend_card_visual_present",
            "recommend_card_visual_signal",
            "conversation_toolbar_present",
        ):
            if key in visual:
                payload[key] = visual[key]
        return payload

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


    def _execute_planned_steps(self, payload: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        capture_prefix = "mac_ios_app" if self.harness_backend == MAC_IOS_APP_HARNESS_BACKEND else "iphone_mirroring"
        use_ocr = self.harness_backend != MAC_IOS_APP_HARNESS_BACKEND
        before = output_dir / f"{capture_prefix}.before_action.png" if output_dir is not None else None
        doctor = self.doctor(capture=True, output=before, ocr=use_ocr)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        screen_state = doctor.get("screen", {}).get("state")
        window = _window_from_payload(doctor.get("window") or {})
        planned_steps = payload.get("planned_steps")
        if not isinstance(planned_steps, list):
            payload.update({"status": "blocked", "reason": "gui_planned_steps_not_list"})
            return payload
        for step_index, step in enumerate(planned_steps, start=1):
            validation_reason = harness_step_validation_reason(step)
            if validation_reason is not None:
                payload.update({"status": "blocked", "reason": validation_reason, "step_index": step_index, "step": step})
                return payload
        requires_paywall = any(step.get("requires_tinder_subscription_paywall") for step in planned_steps)
        requires_feedback_survey = any(step.get("requires_tinder_feedback_survey") for step in planned_steps)
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
        if any(step.get("requires_verified_tinder_screen") for step in planned_steps):
            if screen_state not in TINDER_FOREGROUND_STATES:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": "tinder_foreground_not_verified",
                        "screen_state": screen_state,
                    }
                )
                return payload
        if any(step.get("requires_verified_bumble_screen") for step in planned_steps):
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
        if app_verified_screen_key and any(step.get(app_verified_screen_key) for step in planned_steps):
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
        for step in planned_steps:
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
                    output = output_dir / f"{capture_prefix}.profile_read_step_{len(profile_read_captures) + 1:02d}.png"
                screen = self.capture_window(output=output, window=window, ocr=use_ocr)
                result = {
                    "status": screen.get("status", "blocked"),
                    "screen": _redacted_screen(screen),
                }
                profile_read_captures.append(result["screen"])
                profile_read_texts.append(str(screen.get("text") or ""))
            elif step["intent"] == "safe_expand_visible_profile_section":
                output = None
                if output_dir is not None:
                    output = output_dir / f"{capture_prefix}.profile_expand_check_{len(profile_read_captures) + 1:02d}.png"
                screen = self.capture_window(output=output, window=window, ocr=use_ocr)
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
            time.sleep(max(DEFAULT_POST_ACTION_OBSERVATION_DELAY_SECONDS, float(step.get("wait_after_seconds", 0.0))))
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
        after = output_dir / f"{capture_prefix}.after_action.png" if output_dir is not None else None
        verification_screen = self.capture_window(output=after, window=window, ocr=use_ocr)
        payload["verification"] = _redacted_screen(verification_screen)
        if verification_screen.get("state") == TINDER_SUBSCRIPTION_PAYWALL_STATE:
            recovery = self._dismiss_tinder_subscription_paywall(
                window,
                output_dir=output_dir,
                label="after_action",
            )
            _apply_tinder_paywall_recovery_result(payload, recovery)
        return payload


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
        payload.update(guardrails)
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        doctor = self.doctor(capture=False)
        payload["preflight"] = doctor
        if doctor.get("status") == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        window = _window_from_payload(doctor.get("window") or {})
        initial_output = output_dir / f"{output_prefix}.prepare_message_page.initial.png" if output_dir is not None else None
        screen = self.capture_window(output=initial_output, window=window)
        payload["initial_observation"] = _redacted_screen(screen)
        if screen.get("status") != "ok":
            payload.update({"status": "blocked", "reason": screen.get("reason") or "prepare_message_page_initial_capture_failed"})
            return payload
        if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
            payload.update({"status": "blocked", "reason": screen.get("state")})
            return payload

        executed_steps: list[dict[str, Any]] = []
        recoveries: list[dict[str, Any]] = []
        for attempt in range(4):
            state = str(screen.get("state") or "unknown")
            if app_id == "tinder" and state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
                recovery = self._dismiss_tinder_subscription_paywall(
                    window,
                    output_dir=output_dir,
                    label=f"prepare_message_page_{attempt + 1:02d}",
                )
                recoveries.append({"kind": "subscription_paywall", "result": recovery})
                if recovery.get("status") != "ok":
                    payload.update(
                        {
                            "status": "blocked",
                            "reason": recovery.get("reason") or "tinder_subscription_paywall_recovery_failed",
                            "recoveries": recoveries,
                            "executed_steps": executed_steps,
                        }
                    )
                    return payload
                recovery_output = (
                    output_dir / f"{output_prefix}.prepare_message_page.after_paywall_recovery_{attempt + 1:02d}.png"
                    if output_dir is not None
                    else None
                )
                screen = self.capture_window(output=recovery_output, window=window)
                continue
            if app_id == "tinder" and state == TINDER_FEEDBACK_SURVEY_STATE:
                recovery = self._dismiss_tinder_feedback_survey(
                    window,
                    output_dir=output_dir,
                    label=f"prepare_message_page_{attempt + 1:02d}",
                )
                recoveries.append({"kind": "feedback_survey", "result": recovery})
                if recovery.get("status") != "ok":
                    payload.update(
                        {
                            "status": "blocked",
                            "reason": recovery.get("reason") or "tinder_feedback_survey_recovery_failed",
                            "recoveries": recoveries,
                            "executed_steps": executed_steps,
                        }
                    )
                    return payload
                recovery_output = (
                    output_dir / f"{output_prefix}.prepare_message_page.after_feedback_recovery_{attempt + 1:02d}.png"
                    if output_dir is not None
                    else None
                )
                screen = self.capture_window(output=recovery_output, window=window)
                continue
            if state == chat_list_state:
                payload["prepared_message_page_observation"] = _redacted_screen(screen)
                payload["screen_state"] = state
                payload["layout_hints"] = layout_hints_fn(screen)
                payload["next_host_action"] = "visual_plan_message_list"
                payload["message_list_planning_contract"] = {
                    "source": "fresh_message_list_observation",
                    "use_visual_row_anchor_for_non_ocr_rows": True,
                    "message_list_visual_anchor_scan_region": dict(message_list_visual_anchor_scan_region),
                    "record_tap_ratio_from_visual_plan": True,
                    "allowed_target_bindings": ["chat_list_row_to_thread", "current_thread_visual_identity"],
                    "visible_name_navigation_allowed": True,
                    "generic_ui_markers_are_not_target_binding": True,
                    "fixed_row_index_only_compatibility_fallback": True,
                }
                if executed_steps:
                    payload["executed_steps"] = executed_steps
                if recoveries:
                    payload["recoveries"] = recoveries
                return payload
            if state in secondary_close_steps:
                step = secondary_close_steps[state]
            elif state in returnable_states:
                step = return_to_chats_step
            elif state in foreground_states:
                if app_id == "bumble" and not _bumble_top_level_bottom_nav_present(screen):
                    payload.update(
                        {
                            "status": "blocked",
                            "reason": "bumble_top_level_tab_bar_not_verified",
                            "screen_state": state,
                            "executed_steps": executed_steps,
                        }
                    )
                    return payload
                step = open_chats_step
            else:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": f"{app_id}_foreground_not_verified",
                        "screen_state": state,
                        "executed_steps": executed_steps,
                    }
                )
                return payload

            result = self._execute_step(window, step)
            executed_steps.append({**step, "result": result})
            if result.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": result.get("reason") or "prepare_message_page_step_failed",
                        "executed_steps": executed_steps,
                    }
                )
                return payload
            time.sleep(float(step.get("wait_after_seconds", 0.2)))
            output = output_dir / f"{output_prefix}.prepare_message_page.after_step_{attempt + 1:02d}.png" if output_dir is not None else None
            screen = self.capture_window(output=output, window=window)
            if screen.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": screen.get("reason") or "prepare_message_page_step_capture_failed",
                        "executed_steps": executed_steps,
                    }
                )
                return payload

        payload.update(
            {
                "status": "blocked",
                "reason": f"{chat_list_state}_not_verified",
                "screen_state": screen.get("state", "unknown"),
                "executed_steps": executed_steps,
            }
        )
        if recoveries:
            payload["recoveries"] = recoveries
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
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            **self._base_payload("ok"),
            "action": "open-conversation",
            "mode": "execute",
            "open_mode": "message_list_visual_anchor",
            "message_list_visual_anchor": _redacted_message_list_visual_anchor_evidence(visual_evidence),
            "target_binding": _redacted_target_binding(target_binding) if target_binding is not None else None,
            "planned_steps": planned_steps,
            **guardrails,
        }
        before = output_dir / f"{output_prefix}.open_conversation.before.png" if output_dir is not None else None
        doctor = self.doctor(capture=True, output=before)
        payload["preflight"] = doctor
        if doctor["status"] == "blocked":
            payload.update({"status": "blocked", "reason": doctor.get("reason")})
            return payload
        window = _window_from_payload(doctor.get("window") or {})
        screen_state = doctor.get("screen", {}).get("state")
        if app_id == "tinder" and screen_state == TINDER_SUBSCRIPTION_PAYWALL_STATE:
            recovery = self._dismiss_tinder_subscription_paywall(
                window,
                output_dir=output_dir,
                label="open_conversation_visual_anchor",
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
        if app_id == "tinder" and screen_state == TINDER_FEEDBACK_SURVEY_STATE:
            recovery = self._dismiss_tinder_feedback_survey(
                window,
                output_dir=output_dir,
                label="open_conversation_visual_anchor",
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
        if screen_state == conversation_state:
            back_result = self._execute_step(window, return_to_chats_step)
            executed_steps.append({**return_to_chats_step, "result": back_result})
            if back_result.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": back_result.get("reason") or "return_to_chats_failed",
                        "executed_steps": executed_steps,
                    }
                )
                return payload
            time.sleep(float(return_to_chats_step.get("wait_after_seconds", 0.2)))
        elif screen_state != chat_list_state:
            if screen_state not in foreground_states:
                payload.update(
                    {
                        "status": "blocked",
                        "reason": f"{app_id}_foreground_not_verified",
                        "screen_state": screen_state,
                    }
                )
                return payload
            open_result = self._execute_step(window, open_chats_step)
            executed_steps.append({**open_chats_step, "result": open_result})
            if open_result.get("status") != "ok":
                payload.update(
                    {
                        "status": "blocked",
                        "reason": open_result.get("reason") or "open_chats_failed",
                        "executed_steps": executed_steps,
                    }
                )
                return payload
            time.sleep(float(open_chats_step.get("wait_after_seconds", 0.2)))

        list_output = output_dir / f"{output_prefix}.conversation_visual_anchor_list.png" if output_dir is not None else None
        list_screen = self.capture_window(output=list_output, window=window)
        location = _locate_iphone_message_list_visual_anchor_target(
            list_screen,
            visual_evidence,
            chat_list_state=chat_list_state,
            tap_x=tap_x,
            tap_y_min=tap_y_min,
            tap_y_max=tap_y_max,
        )
        relocation = {
            "status": location.get("status"),
            "message_list_screen": _redacted_screen(list_screen),
            "message_list_location": location,
        }
        payload["message_list_relocation"] = relocation
        if location.get("status") != "ok":
            relocation["reason"] = location.get("reason") or "target_relocation_visual_anchor_not_found"
            payload.update(
                {
                    "status": "blocked",
                    "reason": relocation["reason"],
                    "executed_steps": executed_steps,
                }
            )
            return payload
        tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
        if tap_ratio is None:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "target_relocation_tap_ratio_unavailable",
                    "executed_steps": executed_steps,
                }
            )
            return payload
        if app_id == "bumble":
            tap_step = {
                **_bumble_tap_step(
                    tap_intent,
                    x=float(tap_ratio["x"]),
                    y=float(tap_ratio["y"]),
                    requires_states=chat_list_state,
                    expected_states=conversation_state,
                ),
                "location_method": location.get("location_method"),
                "message_list_location": location,
            }
        else:
            tap_step = {
                **_tap_step(tap_intent, x=float(tap_ratio["x"]), y=float(tap_ratio["y"])),
                "location_method": location.get("location_method"),
                "message_list_location": location,
            }
        tap_result = self._execute_step(window, tap_step)
        executed_steps.append({**tap_step, "result": tap_result})
        payload["executed_steps"] = executed_steps
        if tap_result.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": tap_result.get("reason") or "tap_visual_anchor_conversation_row_failed",
                }
            )
            return payload
        time.sleep(float(tap_step.get("wait_after_seconds", 0.2)))
        verification_output = output_dir / f"{output_prefix}.open_conversation.after_visual_anchor_tap.png" if output_dir is not None else None
        verification_screen = self.capture_window(output=verification_output, window=window)
        payload["verification"] = _redacted_screen(verification_screen)
        if verification_screen.get("status") != "ok":
            payload.update(
                {
                    "status": "blocked",
                    "reason": verification_screen.get("reason") or "open_conversation_verification_failed",
                }
            )
            return payload
        blocked_reason = blocked_state_reasons.get(str(verification_screen.get("state") or ""))
        if blocked_reason:
            payload.update(
                {
                    "status": "blocked",
                    "reason": blocked_reason,
                    "next_host_action": "ask_user_to_confirm_opening_move_reply"
                    if blocked_reason == "bumble_opening_move_requires_user_confirmation"
                    else None,
                }
            )
            return payload
        if verification_screen.get("state") != conversation_state:
            payload.update(
                {
                    "status": "blocked",
                    "reason": "target_conversation_not_verified",
                    "screen_state": verification_screen.get("state"),
                }
            )
            return payload
        target_result = _verify_open_conversation_target_binding_against_screen(
            app_id,
            target_binding,
            verification_screen,
            fallback_marker="",
            verification_method=verification_method,
            conversation_state=conversation_state,
            source_states=source_states,
            blocked_state_reasons=blocked_state_reasons,
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
        base = {
            "recovery_method": f"{app_id}_iphone_mirroring_message_list_visual_relocation",
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "attempt_limit": max_attempts,
            "requires_message_list_visual_evidence": True,
            "uses_fixed_row_index": False,
            "uses_header_ocr": False,
        }
        if target_binding.get("binding_type") != "current_thread_visual_identity":
            return {
                **base,
                "status": "blocked",
                "reason": (target_verification or {}).get("reason") or "target_binding_visual_identity_required",
                "recovery_skipped": True,
            }
        if (target_verification or {}).get("reason") != "target_binding_visual_anchor_mismatch":
            return {
                **base,
                "status": "blocked",
                "reason": (target_verification or {}).get("reason") or "target_binding_mismatch",
                "recovery_skipped": True,
            }

        evidence = _message_list_visual_anchor_evidence_from_options(
            {},
            target_binding=target_binding,
            default_scan_region=message_list_visual_anchor_scan_region,
            default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
        )
        if evidence.get("status") != "ok":
            return {
                **base,
                **evidence,
                "status": "blocked",
                "reason": evidence.get("reason") or "target_relocation_visual_evidence_required",
            }

        attempts: list[dict[str, Any]] = []
        for attempt_index in range(1, max_attempts + 1):
            prepare_payload = self._prepare_iphone_message_page(
                {
                    **self._base_payload("ok"),
                    "action": "recover-target-binding",
                    "mode": "execute",
                    "attempt_index": attempt_index,
                    **guardrails,
                },
                app_id=app_id,
                output_dir=output_dir,
                output_prefix=output_prefix,
                chat_list_state=chat_list_state,
                returnable_states={conversation_state},
                foreground_states=foreground_states,
                open_chats_step=open_chats_step,
                return_to_chats_step=return_to_chats_step,
                secondary_close_steps=secondary_close_steps,
                guardrails=guardrails,
                layout_hints_fn=layout_hints_fn,
                message_list_visual_anchor_scan_region=message_list_visual_anchor_scan_region,
            )
            attempt: dict[str, Any] = {
                "attempt_index": attempt_index,
                "message_list_recovery": _redacted_iphone_prepare_message_page_payload(prepare_payload),
            }
            if prepare_payload.get("status") != "ok":
                attempts.append(attempt)
                return {
                    **base,
                    "status": "blocked",
                    "reason": prepare_payload.get("reason") or "target_relocation_message_list_not_verified",
                    "attempts": attempts,
                }

            window = self._window_info()
            if window is None:
                attempts.append(attempt)
                return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found", "attempts": attempts}
            list_output = output_dir / f"{output_prefix}.target_relocation_{attempt_index:02d}.message_list.png" if output_dir is not None else None
            list_screen = self.capture_window(output=list_output, window=window)
            location = _locate_iphone_message_list_visual_anchor_target(
                list_screen,
                evidence,
                chat_list_state=chat_list_state,
                tap_x=tap_x,
                tap_y_min=tap_y_min,
                tap_y_max=tap_y_max,
            )
            attempt["message_list_location"] = location
            if location.get("status") != "ok":
                attempts.append(attempt)
                if attempt_index < max_attempts:
                    time.sleep(0.25)
                    continue
                break

            tap_ratio = location.get("tap_ratio") if isinstance(location.get("tap_ratio"), dict) else None
            if tap_ratio is None:
                attempts.append(attempt)
                return {
                    **base,
                    "status": "blocked",
                    "reason": "target_relocation_tap_ratio_unavailable",
                    "attempts": attempts,
                }
            if app_id == "bumble":
                tap_step = {
                    **_bumble_tap_step(
                        tap_intent,
                        x=float(tap_ratio["x"]),
                        y=float(tap_ratio["y"]),
                        requires_states=chat_list_state,
                        expected_states=conversation_state,
                    ),
                    "location_method": location.get("location_method"),
                    "message_list_location": location,
                }
            else:
                tap_step = {
                    **_tap_step(tap_intent, x=float(tap_ratio["x"]), y=float(tap_ratio["y"])),
                    "location_method": location.get("location_method"),
                    "message_list_location": location,
                }
            click_result = self._execute_step(window, tap_step)
            attempt["open_target_click"] = {**tap_step, "result": click_result}
            if click_result.get("status") != "ok":
                attempts.append(attempt)
                return {
                    **base,
                    "status": "blocked",
                    "reason": click_result.get("reason") or "target_relocation_open_click_failed",
                    "attempts": attempts,
                }
            time.sleep(float(tap_step.get("wait_after_seconds", 0.2)))

            verification = verify_target_binding(target_binding, output_dir=output_dir)
            attempt["target_binding_verification"] = verification
            attempts.append(attempt)
            if verification.get("status") == "ok":
                return {
                    **base,
                    "status": "ok",
                    "attempt_count": attempt_index,
                    "attempts": attempts,
                    "target_binding_verification": {
                        **verification,
                        "recovered_by": "message_list_visual_relocation",
                        "relocation_attempt_count": attempt_index,
                    },
                }
            if verification.get("reason") != "target_binding_visual_anchor_mismatch":
                return {
                    **base,
                    "status": "blocked",
                    "reason": verification.get("reason") or "target_relocation_target_verification_failed",
                    "attempts": attempts,
                }

        return {
            **base,
            "status": "blocked",
            "reason": "target_binding_visual_relocation_exhausted",
            "last_reason": (
                attempts[-1].get("target_binding_verification", {}).get("reason")
                if attempts and isinstance(attempts[-1].get("target_binding_verification"), dict)
                else attempts[-1].get("message_list_location", {}).get("reason")
                if attempts and isinstance(attempts[-1].get("message_list_location"), dict)
                else None
            ),
            "attempts": attempts,
        }


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
        thread_evidence = (
            target_binding.get("thread_evidence")
            if isinstance(target_binding.get("thread_evidence"), dict)
            else {}
        )
        expected_visual_hash = str(thread_evidence.get("visual_anchor_hash") or "").strip()
        visual_region = _normalized_visual_anchor_region(
            thread_evidence.get("visual_anchor_region"),
            fallback=IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
        ) or dict(IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
        max_distance = _int_in_range(
            thread_evidence.get("visual_anchor_max_hamming_distance"),
            default=IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_MAX_DISTANCE,
            minimum=0,
            maximum=32,
        )
        base = {
            "verification_method": verification_method,
            "binding_type": target_binding.get("binding_type"),
            "target_match_id": target_binding.get("target_match_id"),
            "candidate_key": target_binding.get("candidate_key"),
            "conversation_fingerprint_hash": _hash_text(str(target_binding.get("conversation_fingerprint") or "")),
            "pre_action_observation_id": thread_evidence.get("observation_id"),
            "latest_inbound_fingerprint_hash": _hash_text(str(thread_evidence.get("latest_inbound_fingerprint") or "")),
            "expected_visual_anchor_hash": expected_visual_hash or None,
            "visual_anchor_region": visual_region,
            "visual_anchor_max_hamming_distance": max_distance,
            "requires_visual_anchor": True,
            "requires_header_marker": False,
            "requires_fresh_conversation_screen": True,
            "uses_header_ocr": False,
            "visual_only_exact_verification_allowed": False,
        }
        if not target_binding_structural_evidence_present(app_id, target_binding):
            return {**base, "status": "blocked", "reason": "target_binding_structural_evidence_required"}
        window = self._window_info()
        if window is None:
            return {**base, "status": "blocked", "reason": "iphone_mirroring_window_not_found"}
        output = output_dir / output_name if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        screen_path = str(screen.get("path") or "")
        if screen_path:
            try:
                visual_hash_result = _iphone_visual_anchor_hash_for_pixels(
                    _read_png_pixels_for_send_button(Path(screen_path)),
                    region=visual_region,
                )
            except Exception as exc:
                visual_hash_result = {
                    "status": "blocked",
                    "reason": "target_binding_visual_anchor_read_failed",
                    "error": str(exc)[:80],
                }
        else:
            visual_hash_result = {"status": "blocked", "reason": "target_binding_screen_path_missing"}
        observed_visual_hash = str(visual_hash_result.get("visual_anchor_hash") or "")
        visual_distance = (
            _visual_anchor_hamming_distance(expected_visual_hash, observed_visual_hash)
            if expected_visual_hash and observed_visual_hash
            else None
        )
        result = {
            **base,
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
            "visual_state": screen.get("visual_state", "unknown"),
            "visual_anchor_hash_status": visual_hash_result.get("status"),
            "observed_visual_anchor_hash": observed_visual_hash or None,
            "visual_anchor_hamming_distance": visual_distance,
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
        if visual_hash_result.get("status") != "ok":
            return {
                **result,
                "status": "blocked",
                "reason": visual_hash_result.get("reason") or "target_binding_visual_anchor_unavailable",
            }
        if visual_distance is None or visual_distance > max_distance:
            return {**result, "status": "blocked", "reason": "target_binding_visual_anchor_mismatch"}
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
        spec = RowToThreadBindingSpec(
            app_id=app_id,
            verification_method=verification_method,
            source_states=frozenset(source_states),
            conversation_state=conversation_state,
            window_missing_reason="iphone_mirroring_window_not_found",
            blocked_state_reasons=dict(blocked_state_reasons),
        )
        base = row_to_thread_base_result(target_binding, spec=spec)
        structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
        if structural_block is not None:
            return structural_block
        window = self._window_info()
        if window is None:
            return base.with_status("blocked", spec.window_missing_reason)
        output = output_dir / output_name if output_dir is not None else None
        screen = self.capture_window(output=output, window=window)
        observed_text = str(screen.get("text") or "")
        return finish_row_to_thread_screen_verification(
            base,
            screen=screen,
            redacted_screen=_redacted_screen(screen),
            observed_text=observed_text,
            spec=spec,
        )


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
    selection_evidence = (
        target_binding.get("selection_evidence")
        if isinstance(target_binding.get("selection_evidence"), dict)
        else {}
    )
    redacted_selection = None
    if selection_evidence:
        redacted_selection = {
            "row_index": selection_evidence.get("row_index"),
            "source_state": selection_evidence.get("source_state"),
            "opened_state": selection_evidence.get("opened_state"),
            "target_scope": selection_evidence.get("target_scope"),
            "open_action": selection_evidence.get("open_action"),
        }
        visual = _redacted_message_list_visual_anchor_evidence(selection_evidence)
        if visual.get("has_visual_anchor"):
            redacted_selection["message_list_visual_anchor"] = visual
    return {
        "target_match_id": target_binding.get("target_match_id"),
        "candidate_key": target_binding.get("candidate_key"),
        "binding_type": target_binding.get("binding_type"),
        "selection_evidence": redacted_selection,
        "required_marker_hashes": [_hash_text(marker) for marker in _target_binding_required_markers(target_binding)],
    }


def _redacted_iphone_prepare_message_page_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "status",
        "reason",
        "action",
        "mode",
        "screen_state",
        "next_host_action",
        "message_list_planning_contract",
        "layout_hints",
        "executed_steps",
        "recoveries",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _message_list_visual_anchor_evidence_from_options(
    options: dict[str, Any],
    *,
    target_binding: dict[str, Any] | None,
    default_scan_region: dict[str, float],
    default_max_distance: int,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for key in ("message_list_evidence", "selection_evidence", "target_selection_evidence"):
        value = options.get(key)
        if isinstance(value, dict):
            sources.append(value)
    if isinstance(target_binding, dict):
        for key in ("message_list_evidence", "selection_evidence", "target_selection_evidence"):
            value = target_binding.get(key)
            if isinstance(value, dict):
                sources.append(value)
    flat = {
        key: options.get(key)
        for key in (
            "visual_anchor_hash",
            "row_visual_anchor_hash",
            "message_list_visual_anchor_hash",
            "visual_anchor_region",
            "row_visual_anchor_region",
            "message_list_visual_anchor_region",
            "visual_anchor_scan_region",
            "visual_anchor_max_hamming_distance",
            "row_visual_anchor_max_hamming_distance",
            "tap_ratio",
            "visual_tap_ratio",
            "target_tap_ratio",
            "tap_ratio_source",
            "selection_method",
            "source_state",
        )
        if options.get(key) is not None
    }
    if flat:
        sources.append(flat)
    requested = False
    blocked: dict[str, Any] | None = None
    for source in sources:
        if _message_list_visual_anchor_requested(source):
            requested = True
        evidence = _normalize_iphone_message_list_visual_anchor_evidence(
            source,
            default_scan_region=default_scan_region,
            default_max_distance=default_max_distance,
        )
        if evidence.get("status") == "ok":
            return evidence
        if evidence.get("status") == "blocked":
            blocked = evidence
    if requested:
        return blocked or {"status": "blocked", "reason": "target_relocation_visual_evidence_required"}
    return {"status": "not_requested"}


def _message_list_visual_anchor_requested(source: dict[str, Any]) -> bool:
    return any(
        source.get(key) is not None
        for key in (
            "visual_anchor_hash",
            "row_visual_anchor_hash",
            "message_list_visual_anchor_hash",
            "visual_anchor_region",
            "row_visual_anchor_region",
            "message_list_visual_anchor_region",
            "message_list_evidence",
        )
    )


def _normalize_iphone_message_list_visual_anchor_evidence(
    source: dict[str, Any],
    *,
    default_scan_region: dict[str, float],
    default_max_distance: int,
) -> dict[str, Any]:
    visual_hash = str(
        source.get("visual_anchor_hash")
        or source.get("row_visual_anchor_hash")
        or source.get("message_list_visual_anchor_hash")
        or ""
    ).strip()
    region = _normalized_visual_anchor_region(
        source.get("visual_anchor_region")
        or source.get("row_visual_anchor_region")
        or source.get("message_list_visual_anchor_region"),
        fallback=None,
    )
    if not visual_hash and region is None:
        return {"status": "not_requested"}
    if not visual_hash or region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_evidence_incomplete"}
    max_distance = _int_in_range(
        source.get("visual_anchor_max_hamming_distance") or source.get("row_visual_anchor_max_hamming_distance"),
        default=default_max_distance,
        minimum=0,
        maximum=32,
    )
    scan_region = _normalized_visual_anchor_region(
        source.get("visual_anchor_scan_region") or source.get("scan_region"),
        fallback=default_scan_region,
    )
    if scan_region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_scan_region_invalid"}
    return {
        "status": "ok",
        "evidence_type": "message_list_visual_anchor",
        "visual_anchor_hash": visual_hash,
        "visual_anchor_region": region,
        "visual_anchor_scan_region": scan_region,
        "visual_anchor_max_hamming_distance": max_distance,
        "tap_ratio": _tap_ratio_option(
            source.get("tap_ratio") or source.get("visual_tap_ratio") or source.get("target_tap_ratio")
        ),
        "tap_ratio_source": source.get("tap_ratio_source"),
        "source_state": source.get("source_state"),
        "selection_method": source.get("selection_method") or "message_list_visual_anchor_scan",
    }


def _redacted_message_list_visual_anchor_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    visual_hash = str(
        evidence.get("visual_anchor_hash")
        or evidence.get("row_visual_anchor_hash")
        or evidence.get("message_list_visual_anchor_hash")
        or ""
    ).strip()
    raw_region = (
        evidence.get("visual_anchor_region")
        or evidence.get("row_visual_anchor_region")
        or evidence.get("message_list_visual_anchor_region")
    )
    region = raw_region if isinstance(raw_region, dict) else None
    raw_scan_region = evidence.get("visual_anchor_scan_region") or evidence.get("scan_region")
    scan_region = raw_scan_region if isinstance(raw_scan_region, dict) else None
    return {
        "has_visual_anchor": bool(visual_hash and region),
        "visual_anchor_hash": visual_hash or None,
        "visual_anchor_region": dict(region) if region is not None else None,
        "visual_anchor_scan_region": dict(scan_region) if scan_region is not None else None,
        "visual_anchor_max_hamming_distance": evidence.get("visual_anchor_max_hamming_distance")
        or evidence.get("row_visual_anchor_max_hamming_distance"),
        "tap_ratio": _copy_tap_ratio(evidence.get("tap_ratio")) if isinstance(evidence.get("tap_ratio"), dict) else None,
        "selection_method": evidence.get("selection_method"),
        "source_state": evidence.get("source_state"),
    }


def _locate_iphone_message_list_visual_anchor_target(
    list_screen: dict[str, Any],
    evidence: dict[str, Any],
    *,
    chat_list_state: str,
    tap_x: float,
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    if list_screen.get("status") != "ok":
        return {"status": "blocked", "reason": list_screen.get("reason") or "target_relocation_message_list_not_captured"}
    if list_screen.get("state") != chat_list_state:
        return {
            "status": "blocked",
            "reason": "target_relocation_message_list_not_verified",
            "screen_state": list_screen.get("state", "unknown"),
        }
    expected_hash = str(evidence.get("visual_anchor_hash") or "").strip()
    source_region = evidence.get("visual_anchor_region") if isinstance(evidence.get("visual_anchor_region"), dict) else None
    scan_region = evidence.get("visual_anchor_scan_region") if isinstance(evidence.get("visual_anchor_scan_region"), dict) else None
    if not expected_hash or source_region is None or scan_region is None:
        return {"status": "blocked", "reason": "target_relocation_visual_anchor_evidence_incomplete"}
    path = str(list_screen.get("path") or "")
    if not path:
        return {"status": "blocked", "reason": "target_relocation_message_list_screen_path_missing"}
    try:
        screen_pixels = _read_png_pixels_for_send_button(Path(path))
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "target_binding_visual_anchor_read_failed",
            "error": str(exc)[:80],
        }

    row_height = max(0.03, min(0.28, float(source_region["y2"]) - float(source_region["y1"])))
    row_width = max(0.05, min(1.0, float(source_region["x2"]) - float(source_region["x1"])))
    scan_y1 = max(0.0, min(1.0 - row_height, float(scan_region["y1"])))
    scan_y2 = max(scan_y1 + row_height, min(1.0, float(scan_region["y2"])))
    source_x1 = max(0.0, min(1.0 - row_width, float(source_region["x1"])))
    source_x2 = source_x1 + row_width
    tap_ratio = evidence.get("tap_ratio") if isinstance(evidence.get("tap_ratio"), dict) else None
    tap_y_offset = 0.5
    prior_tap_y: float | None = None
    if tap_ratio is not None:
        tap_y_offset = (float(tap_ratio["y"]) - float(source_region["y1"])) / row_height
        prior_tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    tap_y_offset = max(0.05, min(0.95, tap_y_offset))
    max_distance = int(evidence.get("visual_anchor_max_hamming_distance") or IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE)
    step_y = max(0.004, min(0.012, row_height / 12.0))
    best: dict[str, Any] | None = None
    candidate_count = 0
    y = scan_y1
    while y <= scan_y2 - row_height + 0.0001:
        region = {"x1": source_x1, "y1": y, "x2": source_x2, "y2": y + row_height}
        hash_result = _iphone_visual_anchor_hash_for_pixels(screen_pixels, region=region)
        candidate_count += 1
        observed_hash = str(hash_result.get("visual_anchor_hash") or "")
        distance = (
            _visual_anchor_hamming_distance(expected_hash, observed_hash)
            if hash_result.get("status") == "ok" and observed_hash
            else None
        )
        candidate = {
            "status": hash_result.get("status"),
            "visual_anchor_region": region,
            "observed_visual_anchor_hash": observed_hash or None,
            "visual_anchor_hamming_distance": distance,
            "visual_anchor_tap_y_delta": (
                abs(max(0.0, min(1.0, y + row_height * tap_y_offset)) - prior_tap_y)
                if prior_tap_y is not None
                else None
            ),
        }
        if distance is not None and (
            best is None
            or distance < int(best["visual_anchor_hamming_distance"])
            or (
                distance == int(best["visual_anchor_hamming_distance"])
                and candidate["visual_anchor_tap_y_delta"] is not None
                and (
                    best.get("visual_anchor_tap_y_delta") is None
                    or float(candidate["visual_anchor_tap_y_delta"]) < float(best["visual_anchor_tap_y_delta"])
                )
            )
        ):
            best = candidate
        y += step_y
    if best is None:
        return {
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_unavailable",
            "candidate_count": candidate_count,
        }
    if int(best["visual_anchor_hamming_distance"]) > max_distance:
        return {
            **best,
            "status": "blocked",
            "reason": "target_relocation_visual_anchor_not_found",
            "expected_visual_anchor_hash": expected_hash,
            "visual_anchor_max_hamming_distance": max_distance,
            "candidate_count": candidate_count,
        }
    matched_region = best["visual_anchor_region"]
    raw_tap_ratio = {
        "x": max(0.0, min(1.0, float(tap_ratio["x"]) if tap_ratio is not None else tap_x)),
        "y": max(0.0, min(1.0, float(matched_region["y1"]) + row_height * tap_y_offset)),
    }
    safe_tap = _safe_iphone_message_list_visual_anchor_tap_ratio(
        raw_tap_ratio,
        matched_region=matched_region,
        tap_y_min=tap_y_min,
        tap_y_max=tap_y_max,
    )
    return {
        **best,
        "status": "ok",
        "location_method": "message_list_visual_anchor_scan",
        "expected_visual_anchor_hash": expected_hash,
        "visual_anchor_max_hamming_distance": max_distance,
        "candidate_count": candidate_count,
        "tap_ratio": safe_tap["tap_ratio"],
        "raw_tap_ratio": raw_tap_ratio,
        "tap_adjustment": safe_tap["tap_adjustment"],
        "uses_fixed_row_index": False,
        "visual_anchor_scanned": True,
    }


def _safe_iphone_message_list_visual_anchor_tap_ratio(
    tap_ratio: dict[str, float],
    *,
    matched_region: dict[str, Any],
    tap_y_min: float,
    tap_y_max: float,
) -> dict[str, Any]:
    tap_y = max(0.0, min(1.0, float(tap_ratio["y"])))
    try:
        region_y1 = float(matched_region["y1"])
        region_y2 = float(matched_region["y2"])
    except (KeyError, TypeError, ValueError):
        region_y1 = tap_y
        region_y2 = tap_y
    reasons: list[str] = []
    bottom_row = region_y2 >= IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO or tap_y >= tap_y_max
    if bottom_row:
        safe_y = min(tap_y, tap_y_max, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y)
        if safe_y < tap_y:
            tap_y = safe_y
            reasons.append("bottom_row_safe_tap_guard")
    else:
        tap_y = max(tap_y_min, min(tap_y_max, tap_y))
    if tap_y >= IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO:
        safe_y = min(tap_y, IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y)
        if safe_y < tap_y:
            tap_y = safe_y
            reasons.append("bottom_nav_overlap_guard")
    if tap_y < tap_y_min:
        tap_y = tap_y_min
        reasons.append("row_top_safe_tap_guard")
    return {
        "tap_ratio": {
            "x": max(0.0, min(1.0, float(tap_ratio["x"]))),
            "y": round(tap_y, 4),
        },
        "tap_adjustment": {
            "adjusted": bool(reasons),
            "reason": "+".join(reasons) if reasons else None,
            "bottom_nav_top_ratio": IPHONE_MESSAGE_LIST_BOTTOM_NAV_TOP_RATIO,
            "bottom_row_safe_tap_y": IPHONE_MESSAGE_LIST_BOTTOM_ROW_SAFE_TAP_Y,
            "bottom_row_detected": bottom_row,
            "matched_region_y2": region_y2,
        },
    }


def _iphone_visual_anchor_hash_for_pixels(
    pixels: dict[str, Any],
    *,
    region: dict[str, float],
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        width = int(pixels["width"])
        height = int(pixels["height"])
        channels = int(pixels["channels"])
        rows = pixels["rows"]
        x1 = max(0, min(width - 1, int(float(region["x1"]) * width)))
        x2 = max(x1 + 1, min(width, int(float(region["x2"]) * width)))
        y1 = max(0, min(height - 1, int(float(region["y1"]) * height)))
        y2 = max(y1 + 1, min(height, int(float(region["y2"]) * height)))
        values: list[float] = []
        for cell_y in range(grid_size):
            start_y = y1 + int((y2 - y1) * cell_y / grid_size)
            end_y = y1 + int((y2 - y1) * (cell_y + 1) / grid_size)
            for cell_x in range(grid_size):
                start_x = x1 + int((x2 - x1) * cell_x / grid_size)
                end_x = x1 + int((x2 - x1) * (cell_x + 1) / grid_size)
                total = 0.0
                count = 0
                for y in range(start_y, max(start_y + 1, end_y)):
                    row = rows[y]
                    for x in range(start_x, max(start_x + 1, end_x)):
                        offset = x * channels
                        r, g, b = row[offset : offset + 3]
                        total += (0.299 * int(r)) + (0.587 * int(g)) + (0.114 * int(b))
                        count += 1
                values.append(total / max(1, count))
        average = sum(values) / len(values)
        bits = "".join("1" if value >= average else "0" for value in values)
        return {
            "status": "ok",
            "visual_anchor_hash": f"{int(bits, 2):0{grid_size * grid_size // 4}x}",
            "grid_size": grid_size,
        }
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_hash_failed", "error": str(exc)[:80]}


def _iphone_visual_anchor_hash_for_path(
    path: Path,
    *,
    region: dict[str, float],
    grid_size: int = 8,
) -> dict[str, Any]:
    try:
        pixels = _read_png_pixels_for_send_button(path)
    except Exception as exc:
        return {"status": "blocked", "reason": "target_binding_visual_anchor_read_failed", "error": str(exc)[:80]}
    return _iphone_visual_anchor_hash_for_pixels(pixels, region=region, grid_size=grid_size)


def _iphone_current_thread_visual_anchor(
    screen: dict[str, Any],
    *,
    conversation_state: str,
    region: dict[str, float] | None = None,
) -> dict[str, Any]:
    anchor_region = region or dict(IPHONE_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    base = {
        "screen_state": screen.get("state", "unknown"),
        "visual_state": screen.get("visual_state", "unknown"),
        "visual_anchor_region": anchor_region,
        "uses_header_ocr": False,
    }
    if screen.get("status") != "ok":
        return {**base, "status": "blocked", "reason": screen.get("reason") or "screen_not_captured"}
    if screen.get("state") != conversation_state:
        return {**base, "status": "blocked", "reason": f"{conversation_state}_not_verified"}
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {**base, "status": "blocked", "reason": "target_binding_screen_path_missing"}
    return {
        **base,
        **_iphone_visual_anchor_hash_for_path(Path(screen_path), region=anchor_region),
    }


def _iphone_already_sent_payload_update(
    payload: dict[str, Any],
    *,
    screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    conversation_state: str,
) -> dict[str, Any]:
    post_id_source = f"{payload['draft_fingerprint']}:{screen.get('path') or _now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    exact_text_ocr_verified = bool(outbound_verification.get("exact_text_ocr_verified"))
    return {
        "post_action_observation": _redacted_screen(screen),
        "post_action_observation_id": post_observation_id,
        "outbound_message_verification": outbound_verification,
        "current_thread_visual_anchor": _iphone_current_thread_visual_anchor(
            screen,
            conversation_state=conversation_state,
        ),
        "already_sent": True,
        "staged_text_verified": False,
        "executed_steps": [],
        "evidence": {
            "staged_text_verified": False,
            "staged_exact_text_verified": False,
            "staged_exact_text_ocr_verified": False,
            "send_input_backend": "already_sent_idempotent_skip",
            "input_cleared_after_send": bool(outbound_verification.get("input_cleared_after_send")),
            "post_action_screen_captured": screen.get("status") == "ok",
            "outbound_message_verified": True,
            "outbound_exact_text_verified": exact_text_ocr_verified,
            "outbound_exact_text_ocr_verified": exact_text_ocr_verified,
            "visual_only_exact_verification_allowed": False,
            "post_action_observation_id": post_observation_id,
        },
    }


def _iphone_already_sent_idempotency_allowed(target_binding: dict[str, Any] | None) -> bool:
    return (
        isinstance(target_binding, dict)
        and target_binding.get("binding_type") == "current_thread_visual_identity"
    )


def _iphone_stage_needs_user_verification(
    staged_verification: dict[str, Any],
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    verification = copy.deepcopy(staged_verification)
    verification["status"] = "needs_user_verification"
    verification["reason"] = reason or verification.get("reason") or "staged_text_not_verified"
    return verification


def _iphone_stage_draft_payload_update(
    *,
    staged_screen: dict[str, Any],
    staged_verification: dict[str, Any],
    executed_steps: list[dict[str, Any]],
    conversation_state: str,
    send_input_backend: Any,
) -> dict[str, Any]:
    staged_text_verified = staged_verification.get("status") == "ok"
    return {
        "status": "ok",
        "stage_attempt_status": "completed",
        "staged_text_verification": staged_verification,
        "staged_text_verified": staged_text_verified,
        "verification": _redacted_screen(staged_screen),
        "current_thread_visual_anchor": _iphone_current_thread_visual_anchor(
            staged_screen,
            conversation_state=conversation_state,
        ),
        "executed_steps": executed_steps,
        "send_action_executed": False,
        "requires_user_confirmation_before_send": True,
        "next_host_action": "verify_staged_text_before_send",
        "evidence": EvidencePayload(
            staging=StagingResult.from_verification(
                staged_verification,
                staged_text_verified=staged_text_verified,
            ),
            post_send=PostSendVerification(
                post_action_observation_id="stage_only_no_post_action",
                input_cleared_after_send=False,
                post_action_screen_captured=False,
                outbound_message_verified=False,
            ),
            send_input_backend=send_input_backend,
            extra_fields={
                "stage_mode": True,
                "live_send_executed": False,
                "outbound_exact_text_ocr_verified": False,
                "visual_only_exact_verification_allowed": False,
            },
        ).to_dict(),
    }


def _visual_anchor_hamming_distance(left: str, right: str) -> int:
    if len(left) != len(right):
        return max(len(left), len(right)) * 4
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return max(len(left), len(right)) * 4


def _normalized_visual_anchor_region(
    raw: Any,
    *,
    fallback: dict[str, float] | None,
) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return dict(fallback) if fallback is not None else None
    fallback_values = fallback or {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
    region: dict[str, float] = {}
    for key, default in fallback_values.items():
        value = raw.get(key)
        try:
            region[key] = float(value)
        except (TypeError, ValueError):
            if fallback is None:
                return None
            region[key] = default
    if region["x2"] <= region["x1"] or region["y2"] <= region["y1"]:
        return dict(fallback) if fallback is not None else None
    return {
        "x1": max(0.0, min(0.99, region["x1"])),
        "y1": max(0.0, min(0.99, region["y1"])),
        "x2": max(0.01, min(1.0, region["x2"])),
        "y2": max(0.01, min(1.0, region["y2"])),
    }


def _tap_ratio_option(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw["x"])
        y = float(raw["y"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"x": max(0.0, min(1.0, x)), "y": max(0.0, min(1.0, y))}


def _copy_tap_ratio(raw: Any) -> dict[str, float] | None:
    return _tap_ratio_option(raw)


def _int_in_range(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _verify_open_conversation_target_binding_against_screen(
    app_id: str,
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
    conversation_state: str,
    source_states: set[str],
    blocked_state_reasons: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(target_binding, dict):
        return {
            "verification_method": verification_method,
            "status": "blocked",
            "reason": "target_binding_required",
            "screen": _redacted_screen(screen),
            "screen_state": screen.get("state", "unknown"),
        }
    if target_binding.get("binding_type") == "chat_list_row_to_thread":
        spec = RowToThreadBindingSpec(
            app_id=app_id,
            verification_method=f"{verification_method}_structural_binding",
            source_states=frozenset(source_states),
            conversation_state=conversation_state,
            window_missing_reason="iphone_mirroring_window_not_found",
            blocked_state_reasons=dict(blocked_state_reasons),
        )
        base = row_to_thread_base_result(target_binding, spec=spec)
        structural_block = validate_row_to_thread_structural_evidence(target_binding, spec=spec, base=base)
        if structural_block is not None:
            return structural_block
        return finish_row_to_thread_screen_verification(
            base,
            screen=screen,
            redacted_screen=_redacted_screen(screen),
            observed_text=str(screen.get("text") or ""),
            spec=spec,
        )
    return _verify_target_binding_against_screen(
        target_binding,
        screen,
        fallback_marker=fallback_marker,
        verification_method=verification_method,
        conversation_state=conversation_state,
        blocked_state_reasons=blocked_state_reasons,
    )



def _verify_target_binding_against_screen(
    target_binding: dict[str, Any] | None,
    screen: dict[str, Any],
    *,
    fallback_marker: str,
    verification_method: str,
    conversation_state: str = "tinder_conversation",
    blocked_state_reasons: dict[str, str] | None = None,
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
    blocked_reason = (blocked_state_reasons or {}).get(str(screen.get("state") or ""))
    if blocked_reason:
        return {**result, "status": "blocked", "reason": blocked_reason}
    if screen.get("state") != conversation_state:
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


def _iphone_pre_stage_input_guard(
    *,
    app_id: str,
    screen: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    guard: dict[str, Any] = {
        "status": "ok",
        "app_id": app_id,
        "verification_method": f"{app_id}_pre_stage_input_occupied_guard",
        "expected_payload_hash": _hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "observed_text_hash": _hash_text(observed_text) if observed_text else None,
        "observed_character_count": len(observed_text) if observed_text else None,
        "screen": _redacted_screen(screen),
    }
    if app_id == "bumble":
        active_send_button_visible = _bumble_active_send_button_visual_visible(screen)
        guard["active_send_button_visual_visible"] = active_send_button_visible
        if active_send_button_visible:
            guard.update({
                "status": "blocked",
                "reason": "message_input_not_empty_before_staging",
            })
        return guard
    if app_id == "tinder":
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


def _verify_outbound_message(screen: dict[str, Any], expected_text: str) -> dict[str, Any]:
    observed_text = str(screen.get("text") or "")
    result = _outbound_text_ocr_evidence(
        verification_method="wechat_post_send_ocr_payload_text",
        observed_text=observed_text,
        expected_text=expected_text,
    )
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "post_action_screen_not_captured"}
    if not result["exact_text_ocr_verified"]:
        return {**result, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, "status": "ok"}



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
    return direct_text_entry_block_reason(text) is None



def _tinder_direct_type_fallback_allowed(text: str) -> bool:
    return direct_text_entry_block_reason(text) is None



def _bumble_direct_type_fallback_allowed(text: str) -> bool:
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
    return _harness_tap_step(intent, x=x, y=y, requires_verified_tinder_screen=True)



def _tinder_subscription_paywall_dismiss_step() -> dict[str, Any]:
    return _harness_tap_step(
        "tap_tinder_subscription_paywall_close",
        x=0.09,
        y=0.14,
        risk="subscription_paywall_recovery",
        requires_tinder_subscription_paywall=True,
        subscription_purchase_executed=False,
    )



def _tinder_feedback_survey_dismiss_step() -> dict[str, Any]:
    return _harness_tap_step(
        "tap_tinder_feedback_survey_ignore",
        x=0.50,
        y=0.64,
        risk="feedback_survey_recovery",
        requires_tinder_feedback_survey=True,
        rating_submitted=False,
    )



def _swipe_step(intent: str, *, from_x: float, from_y: float, to_x: float, to_y: float, duration_ms: int = 350) -> dict[str, Any]:
    return _harness_swipe_step(
        intent,
        from_x=from_x,
        from_y=from_y,
        to_x=to_x,
        to_y=to_y,
        duration_ms=duration_ms,
        requires_verified_tinder_screen=True,
    )



def _wheel_step(
    intent: str,
    *,
    x: float,
    y: float,
    delta_y: int = 0,
    delta_x: int = 0,
    repeats: int = 18,
) -> dict[str, Any]:
    return _harness_wheel_step(
        intent,
        x=x,
        y=y,
        delta_y=delta_y,
        delta_x=delta_x,
        repeats=repeats,
        requires_verified_tinder_screen=True,
    )



def _capture_profile_read_step(*, app_id: str = "tinder") -> dict[str, Any]:
    if app_id == "bumble":
        requires_key = "requires_verified_bumble_screen"
    else:
        requires_key = "requires_verified_tinder_screen"
    step = _harness_marker_step("capture_profile_read_step", **{requires_key: True}, wait_after_seconds=0.0)
    if app_id == "bumble":
        step["requires_bumble_states"] = ["bumble_browse", "bumble_profile", "bumble_self_profile"]
    return step



def _safe_expand_step() -> dict[str, Any]:
    return _harness_tap_step(
        "safe_expand_visible_profile_section",
        x=0.50,
        y=0.76,
        requires_verified_tinder_screen=True,
    )



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
    visual_evidence = _message_list_visual_anchor_evidence_from_options(
        options,
        target_binding=target_binding if isinstance(target_binding, dict) else None,
        default_scan_region=TINDER_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    )
    if action == "open-conversation" and visual_evidence.get("status") == "ok":
        visual = _redacted_message_list_visual_anchor_evidence(visual_evidence)
        return [
            {
                "intent": "locate_conversation_row_visual_anchor",
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
            {
                "intent": "tap_visible_conversation_row",
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
        ]
    if action == "open-conversation" and visual_evidence.get("status") == "blocked":
        return [
            {
                "intent": "message_list_visual_anchor_evidence_incomplete",
                "requires_verified_tinder_screen": True,
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "evidence_status": "blocked",
                "reason": visual_evidence.get("reason") or "target_relocation_visual_evidence_required",
            }
        ]
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
        "prepare-message-page": [
            {
                **_tap_step("tap_thread_back_to_chats_if_in_thread", x=0.09, y=0.13),
                "conditional": "when_current_state_is_tinder_conversation",
            },
            {
                **_tap_step("tap_chats_tab_if_needed", x=0.66, y=0.94),
                "conditional": "when_current_state_is_tinder_foreground_not_messages",
            },
        ],
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
    step = _harness_tap_step(intent, x=x, y=y, requires_verified_bumble_screen=True)
    if requires_states is not None:
        step["requires_bumble_states"] = requires_states
    if expected_states is not None:
        step["expected_bumble_states"] = expected_states
    return step



def _bumble_bottom_tab_step(intent: str, *, x: float, y: float, expected_state: str) -> dict[str, Any]:
    return _harness_tap_step(
        intent,
        x=x,
        y=y,
        requires_verified_bumble_screen=True,
        requires_bumble_top_level_tab_bar=True,
        expected_bumble_states=[expected_state],
    )



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
    step = _harness_wheel_step(
        intent,
        x=x,
        y=y,
        delta_y=delta_y,
        delta_x=delta_x,
        repeats=repeats,
        requires_verified_bumble_screen=True,
    )
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
    visible_name = str(options.get("visible_name") or "").strip()
    target_binding = options.get("target_binding")
    visual_evidence = _message_list_visual_anchor_evidence_from_options(
        options,
        target_binding=target_binding if isinstance(target_binding, dict) else None,
        default_scan_region=BUMBLE_MESSAGE_LIST_VISUAL_ANCHOR_SCAN_REGION,
        default_max_distance=IPHONE_MESSAGE_LIST_VISUAL_ANCHOR_MAX_DISTANCE,
    )
    if action == "open-conversation" and visual_evidence.get("status") == "ok":
        visual = _redacted_message_list_visual_anchor_evidence(visual_evidence)
        return [
            {
                "intent": "locate_bumble_conversation_row_visual_anchor",
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
            {
                "intent": "tap_bumble_visible_conversation_row",
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "expected_bumble_states": "bumble_conversation",
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "message_list_visual_anchor": visual,
            },
        ]
    if action == "open-conversation" and visual_evidence.get("status") == "blocked":
        return [
            {
                "intent": "message_list_visual_anchor_evidence_incomplete",
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "risk": "navigation_only",
                "location_method": "message_list_visual_anchor_scan",
                "evidence_status": "blocked",
                "reason": visual_evidence.get("reason") or "target_relocation_visual_evidence_required",
            }
        ]
    if not visible_name and isinstance(target_binding, dict):
        visible_name = _target_binding_primary_visible_name(target_binding) or ""
    if action == "open-conversation" and visible_name:
        marker_hash = _hash_text(visible_name)
        return [
            {
                "intent": "locate_bumble_visible_conversation_name",
                "target_marker_hash": marker_hash,
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
            {
                "intent": "tap_bumble_visible_conversation_row",
                "target_marker_hash": marker_hash,
                "requires_verified_bumble_screen": True,
                "requires_bumble_states": "bumble_chat_list",
                "expected_bumble_states": "bumble_conversation",
                "risk": "navigation_only",
                "location_method": "ocr_tsv_visible_text",
            },
        ]
    actions: dict[str, list[dict[str, Any]]] = {
        "prepare-message-page": [
            {
                **_bumble_tap_step(
                    "tap_bumble_back_to_chats_if_in_thread",
                    x=0.09,
                    y=0.13,
                    requires_states=["bumble_conversation", "bumble_opening_move"],
                    expected_states="bumble_chat_list",
                ),
                "conditional": "when_current_state_is_bumble_thread_or_opening_move",
            },
            {
                **_bumble_bottom_tab_step("tap_bumble_chats_tab_if_needed", x=0.89, y=0.93, expected_state="bumble_chat_list"),
                "conditional": "when_current_state_is_bumble_top_level_not_chat_list",
            },
        ],
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
    type_step = _harness_marker_step("type_app_name_verified", text=app_name, wait_after_seconds=0.2)
    if expected_app_labels is not None:
        type_step["expected_app_labels"] = list(expected_app_labels)
    return [
        _harness_marker_step("open_iphone_home_screen", wait_after_seconds=0.8),
        _harness_marker_step("open_ios_spotlight", wait_after_seconds=0.4),
        type_step,
        _harness_tap_step(search_result_intent, x=0.18, y=0.20, wait_after_seconds=2.5),
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
