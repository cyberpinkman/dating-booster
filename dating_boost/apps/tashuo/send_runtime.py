from __future__ import annotations

from .runtime_common import *
from .targeting import *

def run_tashuo_workflow(
    session: Any,
    workflow: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _tashuo_workflow_steps(workflow, **options)
    except KeyError:
        return {
            **session._base_payload("blocked"),
            "workflow": workflow,
            "reason": "unknown_tashuo_harness_workflow",
            **tashuo_guardrails_payload(),
        }
    payload = {
        **session._base_payload("ok"),
        "workflow": workflow,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    return session._execute_planned_steps(payload, output_dir=output_dir)

def stage_tashuo_draft(
    session: Any,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "stage_draft",
            "target": "tashuo_message_input",
            "reason": "tashuo_stage_draft_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    if not draft_text:
        return {
            **session._base_payload("blocked"),
            "action": "stage_draft",
            "target": "tashuo_message_input",
            "reason": "empty_draft",
            **tashuo_guardrails_payload(),
        }
    planned_steps = [
        {
            "intent": "tap_tashuo_message_input",
            "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
            "focus_state": "unfocused",
            "post_focus_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
            "risk": "draft_staging_only",
            "does_not_send": True,
            "requires_verified_tashuo_thread": True,
        },
        {
            "intent": "clear_existing_tashuo_message_input_if_present",
            "risk": "draft_staging_only",
            "does_not_send": True,
            "fallback_ok": True,
        },
        {
            "intent": "tap_tashuo_message_input_after_clear",
            "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
            "focus_state": "focused",
            "risk": "draft_staging_only",
            "does_not_send": True,
        },
        {
            "intent": "copy_draft_to_clipboard",
            "risk": "draft_staging_only",
            "does_not_send": True,
        },
        {
            "intent": "paste_clipboard_into_tashuo_message_input",
            "risk": "draft_staging_only",
            "does_not_send": True,
        },
        {
            "intent": "set_tashuo_message_input_with_accessibility_if_paste_did_not_stage",
            "risk": "draft_staging_only",
            "does_not_send": True,
            "fallback_only": True,
            "requires_exact_text_verification_after_ax_set": True,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "action": "stage_draft",
        "target": "tashuo_message_input",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
        "draft_character_count": len(draft_text),
        **platform._text_fingerprint_fields("draft_clipboard", draft_text),
        "input_coordinate_model": _tashuo_input_coordinate_model(session),
        **tashuo_guardrails_payload(),
        "requires_user_confirmation_before_send": True,
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    before = output_dir / "mac_ios_app.tashuo.before_stage_draft.png" if output_dir is not None else None
    doctor = session.doctor(capture=True, output=before, ocr=not _is_mac_ios_app_session(session))
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state == "tashuo_question_gate":
        payload.update({"status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"})
        return payload
    if screen_state != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified", "screen_state": screen_state})
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    previous_clipboard = session._read_clipboard()
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard["reason"]})
        return payload
    payload.update(platform._text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))
    baseline = output_dir / "mac_ios_app.tashuo.before_stage_draft.baseline.png" if output_dir is not None else None
    baseline_screen = _capture_tashuo_window(session, output=baseline, window=window, ocr=not _is_mac_ios_app_session(session))
    payload["pre_stage_observation"] = platform._redacted_screen(baseline_screen)

    executed_steps: list[dict[str, Any]] = []
    copy_result = {"status": "not_run"}
    paste_result = {"status": "not_run"}
    clear_result = {"status": "not_run"}
    try:
        click_result = session._click_ratio(window, planned_steps[0]["tap_ratio"])
        executed_steps.append({**planned_steps[0], "result": click_result})
        if click_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": click_result["reason"]})
            return payload
        clear_result = _clear_tashuo_ax_text_area(session)
        payload["pre_stage_clear_result"] = clear_result
        executed_steps.append({**planned_steps[1], "result": clear_result})
        if clear_result.get("status") == "ok":
            time.sleep(0.1)
        refocus_result = session._click_ratio(window, planned_steps[2]["tap_ratio"])
        executed_steps.append({**planned_steps[2], "result": refocus_result})
        if refocus_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": refocus_result["reason"]})
            return payload
        time.sleep(0.15)
        copy_result = session._copy_to_clipboard(draft_text)
        executed_steps.append({**planned_steps[3], "result": copy_result})
        if copy_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": copy_result["reason"]})
            return payload
        paste_result = session._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
        executed_steps.append({**planned_steps[4], "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result["reason"]})
            return payload
        time.sleep(0.35)
        after = output_dir / "mac_ios_app.tashuo.after_stage_draft.png" if output_dir is not None else None
        after_screen = _capture_tashuo_window(session, output=after, window=window, ocr=not _is_mac_ios_app_session(session))
        time.sleep(0.45)
        delayed_after = output_dir / "mac_ios_app.tashuo.after_stage_draft.delayed.png" if output_dir is not None else None
        delayed_screen = _capture_tashuo_window(session, output=delayed_after, window=window, ocr=not _is_mac_ios_app_session(session))
        payload["verification"] = platform._redacted_screen(delayed_screen)
        payload["stage_attempt_status"] = "completed"
        stage_ax_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
        payload["staged_text_verification"] = _stage_only_tashuo_verification(
            delayed_screen,
            draft_text,
            baseline_screen=baseline_screen if isinstance(baseline_screen, dict) else None,
            first_screen=after_screen,
            trusted_direct_input=clear_result.get("status") == "ok",
            ax_text_area_value=stage_ax_value,
        )
        if payload["staged_text_verification"].get("status") != "verified":
            ax_set_result = _set_tashuo_ax_text_area_value(session, draft_text)
            payload["ax_set_text_area_result"] = ax_set_result
            executed_steps.append({**planned_steps[5], "result": ax_set_result})
            if ax_set_result.get("status") == "ok":
                time.sleep(0.25)
                ax_after = output_dir / "mac_ios_app.tashuo.after_ax_set_stage_draft.png" if output_dir is not None else None
                ax_after_screen = _capture_tashuo_window(
                    session,
                    output=ax_after,
                    window=window,
                    ocr=not _is_mac_ios_app_session(session),
                )
                ax_stage_value = _tashuo_ax_text_area_value(session)
                ax_verification = _stage_only_tashuo_verification(
                    ax_after_screen,
                    draft_text,
                    baseline_screen=baseline_screen if isinstance(baseline_screen, dict) else None,
                    first_screen=after_screen,
                    trusted_direct_input=True,
                    ax_text_area_value=ax_stage_value,
                )
                payload["ax_set_text_verification"] = ax_verification
                payload["staging_input_backend"] = ax_set_result.get("input_backend")
                if ax_verification.get("status") == "verified":
                    payload["verification"] = platform._redacted_screen(ax_after_screen)
                    payload["staged_text_verification"] = ax_verification
        payload["staged_text_verified"] = payload["staged_text_verification"]["status"] == "verified"
        payload["next_host_action"] = "verify_staged_text_before_send"
    finally:
        payload["executed_steps"] = executed_steps
        restore_result = session._copy_to_clipboard(previous_clipboard.get("text", ""))
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

def clear_tashuo_message_input(
    session: Any,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not _is_mac_ios_app_session(session):
        return {
            **session._base_payload("blocked"),
            "action": "clear-message-input",
            "target": "tashuo_message_input",
            "reason": "tashuo_clear_message_input_requires_mac_ios_app_runtime",
            **tashuo_guardrails_payload(),
        }
    planned_steps = [
        {
            "intent": "verify_tashuo_conversation_before_input_cleanup",
            "risk": "visual_observation_only",
            "does_not_send": True,
        },
        {
            "intent": "tap_tashuo_message_input_before_cleanup",
            "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
            "risk": "draft_staging_cleanup_only",
            "does_not_send": True,
        },
        {
            "intent": "clear_tashuo_ax_text_area",
            "risk": "draft_staging_cleanup_only",
            "does_not_send": True,
            "input_backend": "macos_accessibility",
        },
        {
            "intent": "verify_tashuo_input_is_empty",
            "risk": "visual_observation_only",
            "does_not_send": True,
            "verification": "accessibility_text_area_value",
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "action": "clear-message-input",
        "target": "tashuo_message_input",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "send_action_executed": False,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    before = output_dir / "mac_ios_app.tashuo.before_clear_message_input.png" if output_dir is not None else None
    doctor = session.doctor(capture=True, output=before, ocr=False)
    payload["preflight"] = doctor
    if doctor.get("status") == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason") or "tashuo_preflight_not_verified"})
        return payload
    screen_state = doctor.get("screen", {}).get("state")
    if screen_state != "tashuo_conversation":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_conversation_not_verified_for_input_cleanup",
            "screen_state": screen_state,
        })
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    executed_steps: list[dict[str, Any]] = [{**planned_steps[0], "result": {"status": "ok", "screen_state": screen_state}}]
    click_result = session._click_ratio(window, planned_steps[1]["tap_ratio"])
    executed_steps.append({**planned_steps[1], "result": click_result})
    if click_result.get("status") != "ok":
        payload.update({
            "status": "blocked",
            "reason": click_result.get("reason") or "tashuo_input_cleanup_focus_failed",
            "executed_steps": executed_steps,
        })
        return payload

    clear_result = _clear_tashuo_ax_text_area(session)
    executed_steps.append({**planned_steps[2], "result": clear_result})
    if clear_result.get("status") == "ok":
        time.sleep(0.2)
    ax_value = _tashuo_ax_text_area_value(session)
    final_text = str(ax_value.get("value") or "") if isinstance(ax_value, dict) and ax_value.get("status") == "ok" else ""
    final_count = len(final_text)
    after = output_dir / "mac_ios_app.tashuo.after_clear_message_input.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=after, window=window, ocr=False)
    verification = {
        "schema_version": 1,
        "status": "ok" if clear_result.get("status") == "ok" and ax_value.get("status") == "ok" and final_count == 0 else "blocked",
        "verification_method": "tashuo_ax_text_area_value_after_clear",
        "input_cleared": final_count == 0,
        "final_input_character_count": final_count,
        "ax_text_area_status": ax_value.get("status") if isinstance(ax_value, dict) else "blocked",
        "final_input_hash": platform._hash_text(final_text) if final_text else None,
        "screen": platform._redacted_screen(screen),
    }
    if clear_result.get("status") != "ok":
        verification["reason"] = clear_result.get("reason") or "tashuo_ax_text_area_clear_failed"
    elif ax_value.get("status") != "ok":
        verification["reason"] = ax_value.get("reason") or "tashuo_ax_text_area_read_failed"
    elif final_count != 0:
        verification["reason"] = "tashuo_final_input_not_empty"
    executed_steps.append({**planned_steps[3], "result": verification})
    payload.update({
        "executed_steps": executed_steps,
        "clear_result": clear_result,
        "final_input_verification": verification,
        "input_cleared": verification["input_cleared"],
        "final_input_character_count": final_count,
    })
    if verification["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": verification.get("reason") or "tashuo_input_cleanup_not_verified",
        })
    return payload

def send_tashuo_message(
    session: Any,
    draft_text: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    target_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_step = {
        "intent": "tap_tashuo_message_input",
        "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=False),
        "focus_state": "unfocused",
        "post_focus_input_tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
        "risk": "live_send_precondition",
        "requires_verified_tashuo_thread": True,
    }
    focused_input_step = {
        "intent": "tap_tashuo_message_input_after_focus",
        "tap_ratio": _tashuo_message_input_tap_ratio(session, focused=True),
        "focus_state": "focused",
        "risk": "live_send_precondition",
        "requires_verified_tashuo_thread": True,
    }
    paste_step = {
        "intent": "paste_clipboard_into_tashuo_message_input",
        "risk": "live_send_precondition",
        "requires_exact_text_match": True,
    }
    ax_set_text_step = {
        "intent": "set_tashuo_message_input_with_accessibility_if_paste_did_not_stage",
        "risk": "live_send_precondition",
        "fallback_only": True,
        "requires_exact_text_verification_after_ax_set": True,
    }
    type_fallback_step = {
        "intent": "type_tashuo_message_input_if_paste_did_not_stage",
        "risk": "live_send_precondition",
        "fallback_only": True,
        "requires_printable_ascii_draft": True,
        "requires_exact_text_verification_after_direct_type": True,
    }
    ime_commit_step = {
        "intent": "commit_tashuo_message_input_ime_candidate_if_needed",
        "risk": "live_send_precondition",
        "fallback_only": True,
        "commits_direct_type_candidate": True,
        "requires_exact_text_verification_after_commit": True,
    }
    send_step = {
        "intent": "press_return_to_send_tashuo_message",
        "focus_state": "focused",
        "risk": "live_send",
        "requires_explicit_authorization": True,
        "visual_only_exact_verification_allowed": _is_mac_ios_app_session(session),
        "requires_exact_text_verification_before_return": True,
    }
    payload = SendAttemptContext(
        action="send_message",
        target="tashuo_message_input",
        draft_text=draft_text,
        dry_run=dry_run,
        planned_steps=(input_step, paste_step, ax_set_text_step, type_fallback_step, ime_commit_step, send_step),
        blocked_actions=tuple(TASHUO_SEND_BLOCKED_GUI_ACTIONS),
        extra_fields={
            "question_gate_policy": copy.deepcopy(TASHUO_QUESTION_GATE_POLICY),
            "input_coordinate_model": _tashuo_input_coordinate_model(session),
        },
    ).initial_payload(session._base_payload("ok"))
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    if (
        target_binding is not None
        and _is_mac_ios_app_session(session)
        and not target_binding_structural_evidence_present("tashuo", target_binding)
    ):
        payload.update({
            "status": "blocked",
            "reason": "target_binding_structural_evidence_required",
            "target_binding_verification": {
                "verification_method": "tashuo_mac_ios_app_structural_binding_required",
                "status": "blocked",
                "reason": "target_binding_structural_evidence_required",
                "requires_header_marker": False,
                "requires_structural_binding": True,
            },
        })
        return payload

    capture_prefix = _tashuo_capture_prefix(session)
    preflight_output = output_dir / f"{capture_prefix}.before_send_message.png" if output_dir is not None else None
    preflight = session.doctor(capture=True, output=preflight_output, ocr=not _is_mac_ios_app_session(session))
    payload["preflight"] = preflight
    if preflight.get("status") != "ok":
        payload.update({"status": "blocked", "reason": preflight.get("reason") or "tashuo_preflight_not_verified"})
        return payload
    window = platform._window_from_payload(preflight.get("window") or {})
    preflight_screen = preflight.get("screen") if isinstance(preflight.get("screen"), dict) else {}
    if preflight_screen.get("state") == "tashuo_question_gate":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_question_gate_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_question_gate_reply",
        })
        return payload
    if preflight_screen.get("state") != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified"})
        return payload

    if target_binding is not None:
        target_verification = _verify_tashuo_target_binding(session, target_binding, output_dir=output_dir)
        payload["target_binding_verification"] = target_verification
        if target_verification.get("status") != "ok":
            can_relocate_anchor_mismatch = (
                _is_mac_ios_app_session(session)
                and target_binding.get("binding_type") == "current_thread_visual_identity"
                and target_verification.get("reason") == "target_binding_visual_anchor_mismatch"
                and target_verification.get("screen_state") == "tashuo_conversation"
            )
            if can_relocate_anchor_mismatch:
                relocation = _recover_tashuo_current_thread_visual_identity_mismatch(
                    session,
                    target_binding,
                    output_dir=output_dir,
                )
                payload["target_binding_relocation"] = relocation
                if relocation.get("status") == "ok":
                    payload["target_binding_verification"] = relocation.get("target_binding_verification") or {
                        **target_verification,
                        "status": "ok",
                        "recovered_by": "message_list_visual_relocation",
                    }
                else:
                    payload.update({
                        "status": "blocked",
                        "reason": relocation.get("reason") or target_verification.get("reason") or "target_binding_mismatch",
                    })
                    return payload
            else:
                payload.update({
                    "status": "blocked",
                    "reason": target_verification.get("reason") or "target_binding_mismatch",
                })
                return payload

    baseline_output = output_dir / f"{capture_prefix}.before_stage_message.png" if output_dir is not None else None
    baseline_screen = _capture_tashuo_window(session, output=baseline_output, window=window, ocr=not _is_mac_ios_app_session(session))
    payload["pre_stage_observation"] = platform._redacted_screen(baseline_screen)
    if baseline_screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": baseline_screen.get("reason") or "pre_stage_screen_not_captured"})
        return payload
    if baseline_screen.get("state") == "tashuo_question_gate":
        payload.update({
            "status": "blocked",
            "reason": "tashuo_question_gate_requires_user_confirmation",
            "next_host_action": "ask_user_to_confirm_question_gate_reply",
        })
        return payload
    if baseline_screen.get("state") != "tashuo_conversation":
        payload.update({"status": "blocked", "reason": "tashuo_conversation_not_verified"})
        return payload

    already_sent_ax_static_text_values = _tashuo_ax_static_text_values(session) if _is_mac_ios_app_session(session) else None
    already_sent_ax_text_area_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    already_sent_verification = _verify_tashuo_outbound_message(
        baseline_screen,
        draft_text,
        ax_static_text_values=already_sent_ax_static_text_values,
        ax_text_area_value=already_sent_ax_text_area_value,
        visual_commit_allowed=False,
        ocr_disabled_after_message_page=_is_mac_ios_app_session(session),
    )
    if already_sent_verification.get("status") == "ok":
        post_id_source = f"{payload['draft_fingerprint']}:{baseline_screen.get('path') or platform._now_iso()}:{uuid4().hex}"
        post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
        current_thread_anchor = _tashuo_current_thread_visual_anchor(baseline_screen)
        payload["post_action_observation"] = platform._redacted_screen(baseline_screen)
        payload["post_action_observation_id"] = post_observation_id
        payload["outbound_message_verification"] = already_sent_verification
        payload["current_thread_visual_anchor"] = current_thread_anchor
        payload["already_sent"] = True
        payload["staged_text_verified"] = False
        payload["executed_steps"] = []
        payload["evidence"] = {
            "staged_text_verified": False,
            "staged_exact_text_verified": False,
            "staged_exact_text_ax_verified": False,
            "staged_exact_text_ocr_verified": False,
            "send_input_backend": "already_sent_idempotent_skip",
            "input_cleared_after_send": bool(already_sent_verification.get("input_cleared_after_send")),
            "post_action_screen_captured": baseline_screen.get("status") == "ok",
            "outbound_message_verified": True,
            "outbound_exact_text_verified": bool(already_sent_verification.get("exact_text_verified")),
            "outbound_exact_text_ax_verified": bool(already_sent_verification.get("exact_text_ax_verified")),
            "outbound_exact_text_ocr_verified": bool(already_sent_verification.get("exact_text_ocr_verified")),
            "outbound_exact_text_visual_verified": bool(already_sent_verification.get("exact_text_visual_verified")),
            "outbound_visual_commit_verified": bool(already_sent_verification.get("visual_commit_verified")),
            "visual_only_exact_verification_allowed": bool(already_sent_verification.get("visual_only_exact_verification_allowed")),
            "post_action_observation_id": post_observation_id,
        }
        return payload

    previous_clipboard = session._read_clipboard()
    payload["previous_clipboard_read"] = previous_clipboard["status"] == "ok"
    if previous_clipboard["status"] != "ok":
        payload.update({"status": "blocked", "reason": previous_clipboard.get("reason")})
        return payload
    payload.update(platform._text_fingerprint_fields("previous_clipboard", previous_clipboard.get("text", "")))
    copy_result = session._copy_to_clipboard(draft_text)
    payload["draft_clipboard_copy"] = copy_result["status"] == "ok"
    if copy_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": copy_result.get("reason")})
        return payload

    executed_steps: list[dict[str, Any]] = []
    staged_screen = baseline_screen
    try:
        input_result = session._click_ratio(window, input_step["tap_ratio"])
        executed_steps.append({**input_step, "result": input_result})
        if input_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": input_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(0.45)

        paste_result = session._paste_clipboard_into_frontmost_app(prefer_core_graphics_keyboard=True)
        executed_steps.append({**paste_step, "result": paste_result})
        if paste_result["status"] != "ok":
            payload.update({"status": "blocked", "reason": paste_result.get("reason"), "executed_steps": executed_steps})
            return payload
        time.sleep(0.3)

        staged_output = output_dir / f"{capture_prefix}.after_stage_message.png" if output_dir is not None else None
        staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
        staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
            session,
            staged_screen,
            draft_text,
            baseline_screen=baseline_screen,
            output_dir=output_dir,
            label=f"{capture_prefix}.after_stage_message.input_crop",
        )
        staged_text = str(staged_screen.get("text") or "")
        staged_input_placeholder_visible = _tashuo_input_placeholder_visible(staged_text)
        if staged_verification.get("status") != "ok" and _is_mac_ios_app_session(session):
            ax_set_result = _set_tashuo_ax_text_area_value(session, draft_text)
            executed_steps.append({**ax_set_text_step, "result": ax_set_result})
            payload["ax_set_text_area_result"] = ax_set_result
            if ax_set_result.get("status") == "ok":
                time.sleep(0.25)
                staged_output = output_dir / f"{capture_prefix}.after_ax_set_message.png" if output_dir is not None else None
                staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
                staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
                    session,
                    staged_screen,
                    draft_text,
                    baseline_screen=baseline_screen,
                    output_dir=output_dir,
                    label=f"{capture_prefix}.after_ax_set_message.input_crop",
                )
                payload["ax_set_text_verification"] = staged_verification
                payload["staging_input_backend"] = ax_set_result.get("input_backend")
                staged_text = str(staged_screen.get("text") or "")
                staged_input_placeholder_visible = _tashuo_input_placeholder_visible(staged_text)
        direct_type_input_candidate = (
            staged_verification.get("status") != "ok"
            and staged_input_placeholder_visible
        )
        direct_type_block_reason = platform.direct_text_entry_block_reason(draft_text)
        if direct_type_input_candidate and direct_type_block_reason is not None:
            cleanup_result = _cleanup_failed_tashuo_stage(
                session,
                window,
                focused_input_step,
                expected_text=draft_text,
                output_dir=output_dir,
            )
            payload["failed_stage_cleanup"] = cleanup_result
            payload["staged_text_verification"] = staged_verification
            payload["staged_text_verified"] = False
            payload.update({
                "status": "blocked",
                "reason": direct_type_block_reason,
                "executed_steps": executed_steps,
            })
            return payload
        direct_type_fallback_candidate = (
            direct_type_input_candidate
            and platform._direct_type_fallback_allowed(draft_text)
        )
        if direct_type_fallback_candidate:
            type_result = session._type_text_into_frontmost_app(draft_text)
            executed_steps.append({**type_fallback_step, "result": type_result})
            if type_result["status"] != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": type_result.get("reason") or "direct_text_entry_failed",
                    "executed_steps": executed_steps,
                })
                return payload
            time.sleep(0.3)
            staged_output = output_dir / f"{capture_prefix}.after_type_message.png" if output_dir is not None else None
            staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
            staged_verification = _verify_staged_tashuo_message_with_crop_ocr(
                session,
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
                trusted_direct_input=True,
                output_dir=output_dir,
                label=f"{capture_prefix}.after_type_message.input_crop",
            )
            direct_type_verification = staged_verification
            ime_commit_result = session._press_space_key()
            executed_steps.append({**ime_commit_step, "result": ime_commit_result})
            if ime_commit_result["status"] != "ok":
                payload.update({
                    "status": "blocked",
                    "reason": ime_commit_result.get("reason") or "ime_commit_space_failed",
                    "executed_steps": executed_steps,
                })
                return payload
            time.sleep(0.3)
            staged_output = output_dir / f"{capture_prefix}.after_ime_commit_message.png" if output_dir is not None else None
            staged_screen = _capture_tashuo_window(session, output=staged_output, window=window, ocr=not _is_mac_ios_app_session(session))
            committed_verification = _verify_staged_tashuo_message_with_crop_ocr(
                session,
                staged_screen,
                draft_text,
                baseline_screen=baseline_screen,
                trusted_direct_input=True,
                output_dir=output_dir,
                label=f"{capture_prefix}.after_ime_commit_message.input_crop",
            )
            payload["direct_type_text_verification"] = direct_type_verification
            payload["ime_commit_text_verification"] = committed_verification
            if committed_verification.get("status") == "ok" or direct_type_verification.get("status") != "ok":
                staged_verification = committed_verification
            payload["staging_input_backend"] = type_result.get("input_backend")
        payload["staged_text_verification"] = staged_verification
        payload["staged_text_verified"] = staged_verification.get("status") == "ok"
        if staged_verification.get("status") != "ok":
            if _tashuo_host_visual_staged_verification_available(staged_screen, staged_verification, draft_text):
                payload["visual_verification_request"] = _tashuo_visual_staged_verification_request(
                    staged_screen,
                    staged_verification,
                    draft_text,
                )
                payload.update({
                    "status": "needs_host_visual_verification",
                    "reason": "staged_text_requires_visual_verification",
                    "next_host_action": "visually_verify_staged_text_before_live_send",
                    "executed_steps": executed_steps,
                })
                return payload
            cleanup_result = _cleanup_failed_tashuo_stage(
                session,
                window,
                focused_input_step,
                expected_text=draft_text,
                output_dir=output_dir,
            )
            payload["failed_stage_cleanup"] = cleanup_result
            payload.update({
                "status": "blocked",
                "reason": staged_verification.get("reason") or "staged_text_not_verified",
                "executed_steps": executed_steps,
            })
            return payload
    finally:
        restore_result = session._copy_to_clipboard(previous_clipboard.get("text", ""))
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

    if payload.get("staging_input_backend") == "macos_accessibility":
        refocus_step = {
            **focused_input_step,
            "intent": "focus_tashuo_message_input_after_accessibility_set",
        }
        refocus_result = session._click_ratio(window, refocus_step["tap_ratio"])
        executed_steps.append({**refocus_step, "result": refocus_result})
        payload["ax_set_refocus_result"] = refocus_result
        if refocus_result.get("status") != "ok":
            payload.update({
                "status": "blocked",
                "reason": refocus_result.get("reason") or "tashuo_input_refocus_after_ax_set_failed",
                "executed_steps": executed_steps,
            })
            return payload
        time.sleep(0.2)

    send_result = session._press_return_key()
    executed_steps.append({**send_step, "result": send_result})
    payload["executed_steps"] = executed_steps
    if send_result["status"] != "ok":
        payload.update({"status": "blocked", "reason": send_result.get("reason")})
        return payload

    _sleep_for_tashuo_post_action_observation(session, fallback=0.5)
    post_output = output_dir / f"{capture_prefix}.after_send_message.png" if output_dir is not None else None
    post_screen = _capture_tashuo_window(session, output=post_output, window=window, ocr=not _is_mac_ios_app_session(session))
    payload["post_action_observation"] = platform._redacted_screen(post_screen)
    payload["current_thread_visual_anchor"] = _tashuo_current_thread_visual_anchor(post_screen)
    post_id_source = f"{payload['draft_fingerprint']}:{post_screen.get('path') or platform._now_iso()}:{uuid4().hex}"
    post_observation_id = "gui_post_send_" + hashlib.sha256(post_id_source.encode("utf-8")).hexdigest()[:16]
    payload["post_action_observation_id"] = post_observation_id
    post_screen_captured = post_screen.get("status") == "ok"
    post_ax_static_text_values = _tashuo_ax_static_text_values(session) if _is_mac_ios_app_session(session) else None
    post_ax_text_area_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    staged_exact_text_verified = bool(
        staged_verification.get("exact_text_ax_verified")
        or (not _is_mac_ios_app_session(session) and staged_verification.get("exact_text_ocr_verified"))
    )
    outbound_verification = _verify_tashuo_outbound_message(
        post_screen,
        draft_text,
        staged_screen=staged_screen,
        ax_static_text_values=post_ax_static_text_values,
        ax_text_area_value=post_ax_text_area_value,
        trusted_direct_input=payload.get("staging_input_backend") == "applescript_direct_keystroke",
        staged_exact_text_verified=staged_exact_text_verified,
        visual_commit_allowed=False,
        ocr_disabled_after_message_page=_is_mac_ios_app_session(session),
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
            "staged_exact_text_verified": staged_exact_text_verified,
            "outbound_exact_text_verified": bool(outbound_verification.get("exact_text_verified")),
            "outbound_exact_text_ax_verified": bool(outbound_verification.get("exact_text_ax_verified")),
            "outbound_exact_text_ocr_verified": bool(outbound_verification.get("exact_text_ocr_verified")),
            "outbound_exact_text_visual_verified": bool(outbound_verification.get("exact_text_visual_verified")),
            "outbound_visual_commit_verified": bool(outbound_verification.get("visual_commit_verified")),
            "visual_only_exact_verification_allowed": bool(outbound_verification.get("visual_only_exact_verification_allowed")),
        },
    ).to_dict()
    if not post_screen_captured:
        payload.update({"status": "needs_verification", "reason": "post_action_screen_not_captured"})
    elif not input_cleared:
        payload.update({"status": "needs_verification", "reason": "post_send_input_not_verified_clear"})
    elif _is_mac_ios_app_session(session) and not outbound_verified and _tashuo_host_visual_outbound_verification_available(
        post_screen,
        outbound_verification,
        draft_text,
        staged_exact_text_verified=staged_exact_text_verified,
        input_cleared=input_cleared,
    ):
        payload["visual_verification_request"] = _tashuo_visual_outbound_verification_request(
            staged_screen,
            post_screen,
            outbound_verification,
            draft_text,
            post_action_observation_id=post_observation_id,
        )
        payload.update({
            "status": "needs_host_visual_verification",
            "reason": "outbound_message_requires_visual_verification",
            "next_host_action": "visually_verify_outbound_message_after_live_send",
        })
    elif not outbound_verified:
        payload.update({"status": "needs_verification", "reason": "outbound_message_not_verified"})
    return payload

def _verify_staged_tashuo_message_with_crop_ocr(
    session: Any,
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    output_dir: Path | None = None,
    label: str = "tashuo.input_crop",
) -> dict[str, Any]:
    ax_value = _tashuo_ax_text_area_value(session) if _is_mac_ios_app_session(session) else None
    ocr_disabled_after_message_page = _is_mac_ios_app_session(session)
    result = _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        ax_text_area_value=ax_value,
        ocr_disabled_after_message_page=ocr_disabled_after_message_page,
    )
    if result.get("status") == "ok" or screen.get("status") != "ok":
        return result
    if ocr_disabled_after_message_page:
        return {
            **result,
            "ocr_fallback_skipped": True,
            "ocr_fallback_skip_reason": "mac_ios_app_visual_first_after_message_page",
        }
    crop_ocr = _tashuo_input_crop_ocr(
        session,
        screen,
        expected_text=expected_text,
        output_dir=output_dir,
        label=label,
    )
    return _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        input_crop_ocr=crop_ocr,
        ax_text_area_value=ax_value,
        ocr_disabled_after_message_page=False,
    )

def _verify_staged_tashuo_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    input_crop_ocr: dict[str, Any] | None = None,
    ax_text_area_value: dict[str, Any] | None = None,
    ocr_disabled_after_message_page: bool = False,
) -> dict[str, Any]:
    observed_text = "" if ocr_disabled_after_message_page else str(screen.get("text") or "")
    crop_text = (
        str(input_crop_ocr.get("text") or "")
        if not ocr_disabled_after_message_page
        and isinstance(input_crop_ocr, dict)
        and input_crop_ocr.get("status") == "ok"
        else ""
    )
    combined_text = "\n".join(item for item in (observed_text, crop_text) if item)
    observed_stats = platform._expected_text_observation_stats(combined_text or observed_text, expected_text)
    baseline_text = (
        ""
        if ocr_disabled_after_message_page
        else str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    )
    baseline_stats = platform._expected_text_observation_stats(baseline_text, expected_text) if baseline_text else None
    screen_exact = platform._message_text_matches(observed_text, expected_text)
    crop_exact = bool(crop_text) and platform._message_text_matches(crop_text, expected_text)
    ax_text = (
        str(ax_text_area_value.get("value") or "")
        if isinstance(ax_text_area_value, dict) and ax_text_area_value.get("status") == "ok"
        else ""
    )
    ax_exact = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
    result = platform._staged_text_ocr_evidence(
        verification_method=(
            "tashuo_staged_message_ax_then_host_visual_payload_text"
            if ocr_disabled_after_message_page
            else "tashuo_staged_message_ax_then_ocr_payload_text"
        ),
        observed_text=combined_text or observed_text,
        expected_text=expected_text,
        baseline_text=baseline_text,
        screen=screen,
        redact_screen=platform._redacted_screen,
        exact_text_ocr_verified=screen_exact or crop_exact,
        extra={
            "ocr_disabled_after_message_page": ocr_disabled_after_message_page,
            "send_action": "press_return",
            "exact_text_ax_verified": ax_exact,
            "ax_text_area_value_hash": platform._hash_text(ax_text) if ax_text else None,
            "ax_text_area_character_count": len(ax_text) if ax_text else 0,
            "screen_exact_text_ocr_verified": screen_exact,
            "input_crop_exact_text_ocr_verified": crop_exact,
        },
    )
    possible_append_to_existing = (
        bool(baseline_stats)
        and int(baseline_stats.get("expected_text_occurrences") or 0) > 0
        and int(observed_stats.get("text_character_count") or 0)
        > int(baseline_stats.get("text_character_count") or 0) + max(4, len(expected_text) // 3)
    )
    result["possible_append_to_existing_staged_text"] = possible_append_to_existing
    if ax_text_area_value is not None and ax_text_area_value.get("status") != "ok":
        result["ax_text_area_status"] = ax_text_area_value.get("status")
        result["ax_text_area_reason"] = ax_text_area_value.get("reason")
    if input_crop_ocr is not None and not ocr_disabled_after_message_page:
        result["input_crop_ocr"] = _redacted_tashuo_input_crop_ocr(input_crop_ocr, expected_text)
    if screen.get("status") != "ok":
        return {**result, "status": "blocked", "reason": screen.get("reason") or "stage_screen_not_captured"}
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        return {**result, "status": "blocked", "reason": screen.get("state")}
    if screen.get("state") == "tashuo_question_gate":
        return {**result, "status": "blocked", "reason": "tashuo_question_gate_requires_user_confirmation"}
    baseline_state = baseline_screen.get("state") if isinstance(baseline_screen, dict) else None
    if screen.get("state") != "tashuo_conversation" and baseline_state != "tashuo_conversation":
        return {**result, "status": "blocked", "reason": "tashuo_conversation_not_verified"}
    if not (result["exact_text_ocr_verified"] or result["exact_text_ax_verified"]):
        return {**result, "status": "needs_verification", "reason": "staged_text_not_verified"}
    if possible_append_to_existing and not trusted_direct_input and not result["exact_text_ax_verified"]:
        return {**result, "status": "needs_verification", "reason": "staged_text_may_have_been_appended"}
    if not result["exact_text_ax_verified"] and baseline_stats and observed_stats["expected_text_occurrences"] <= baseline_stats["expected_text_occurrences"]:
        if trusted_direct_input:
            return {**result, "status": "ok"}
        return {**result, "status": "needs_verification", "reason": "staged_text_not_newly_visible"}
    return {**result, "status": "ok"}

def _tashuo_input_crop_ocr(
    session: Any,
    screen: dict[str, Any],
    *,
    expected_text: str,
    output_dir: Path | None,
    label: str,
) -> dict[str, Any]:
    screen_path = str(screen.get("path") or "")
    if not screen_path:
        return {"status": "blocked", "reason": "input_crop_screen_path_missing"}
    source = Path(screen_path)
    try:
        pixels = _read_png_pixels(source)
        width = int(pixels["width"])
        height = int(pixels["height"])
    except Exception as exc:
        return {"status": "blocked", "reason": "input_crop_dimensions_unavailable", "error": str(exc)[:80]}
    region = dict(TASHUO_MAC_IOS_APP_INPUT_OCR_REGION)
    x = max(0, min(width - 1, int(region["x1"] * width)))
    y = max(0, min(height - 1, int(region["y1"] * height)))
    crop_width = max(1, min(width - x, int((region["x2"] - region["x1"]) * width)))
    crop_height = max(1, min(height - y, int((region["y2"] - region["y1"]) * height)))
    base_dir = output_dir if output_dir is not None else source.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    crop_path = base_dir / f"{label}.png"
    resized_path = base_dir / f"{label}.2x.png"
    crop = session.runner.run(
        [
            "sips",
            "--cropToHeightWidth",
            str(crop_height),
            str(crop_width),
            "--cropOffset",
            str(y),
            str(x),
            str(source),
            "--out",
            str(crop_path),
        ]
    )
    if crop.returncode != 0:
        return {"status": "blocked", "reason": "input_crop_failed", "stderr": platform._short(crop.stderr)}
    resize = session.runner.run(
        [
            "sips",
            "--resampleWidth",
            str(crop_width * 2),
            str(crop_path),
            "--out",
            str(resized_path),
        ]
    )
    if resize.returncode != 0:
        return {"status": "blocked", "reason": "input_crop_resize_failed", "stderr": platform._short(resize.stderr)}
    best: dict[str, Any] | None = None
    for psm in ("6", "11"):
        ocr = session.runner.run(
            [
                "tesseract",
                str(resized_path),
                "stdout",
                "-l",
                "chi_sim+eng",
                "--psm",
                psm,
            ]
        )
        item = {
            "status": "ok" if ocr.returncode == 0 else "blocked",
            "reason": None if ocr.returncode == 0 else "input_crop_ocr_failed",
            "text": ocr.stdout if ocr.returncode == 0 else "",
            "stderr": platform._short(ocr.stderr) if ocr.returncode != 0 else None,
            "psm": psm,
            "path": str(crop_path),
            "resized_path": str(resized_path),
            "region": region,
        }
        best = item
        if item["status"] == "ok" and platform._message_text_matches(str(item.get("text") or ""), expected_text):
            return item
    return best or {"status": "blocked", "reason": "input_crop_ocr_not_run"}

def _redacted_tashuo_input_crop_ocr(payload: dict[str, Any], expected_text: str) -> dict[str, Any]:
    text = str(payload.get("text") or "")
    stats = platform._expected_text_observation_stats(text, expected_text) if text else {}
    return {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "psm": payload.get("psm"),
        "path": payload.get("path"),
        "resized_path": payload.get("resized_path"),
        "region": payload.get("region"),
        "text_hash": stats.get("text_hash"),
        "text_character_count": stats.get("text_character_count"),
        "expected_text_occurrences": stats.get("expected_text_occurrences", 0),
        "exact_text_ocr_verified": bool(text) and platform._message_text_matches(text, expected_text),
        "stderr": payload.get("stderr"),
    }

def _tashuo_ax_text_area_value(session: Any) -> dict[str, Any]:
    script = r'''
-- DATING_BOOST_AX_TEXT_AREA_VALUE
on findTextAreaValue(e, depth)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then
        return value of e as text
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set found to my findTextAreaValue(child, depth + 1)
          if found is not missing value then return found
        end repeat
      end if
    end try
  end tell
  return missing value
end findTextAreaValue

tell application "System Events"
  tell process "她说"
    set found to my findTextAreaValue(window 1, 0)
    if found is missing value then
      return "__DATING_BOOST_TEXT_AREA_NOT_FOUND__"
    end if
    return found
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_read_failed",
            "stderr": platform._short(result.stderr),
        }
    value = str(result.stdout or "").rstrip("\n")
    if value == "__DATING_BOOST_TEXT_AREA_NOT_FOUND__":
        return {"status": "blocked", "reason": "tashuo_ax_text_area_not_found"}
    if value == "missing value":
        value = ""
    return {"status": "ok", "value": value, "input_backend": "macos_accessibility"}

def _tashuo_ax_static_text_values(session: Any) -> dict[str, Any]:
    script = r'''
-- DATING_BOOST_AX_STATIC_TEXT_VALUES
on collectStaticTexts(e, depth)
  set foundValues to {}
  tell application "System Events"
    try
      if role of e is "AXStaticText" then
        try
          set v to value of e as text
          if v is not "" then set end of foundValues to v
        end try
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set childValues to my collectStaticTexts(child, depth + 1)
          repeat with itemValue in childValues
            set end of foundValues to itemValue as text
          end repeat
        end repeat
      end if
    end try
  end tell
  return foundValues
end collectStaticTexts

tell application "System Events"
  tell process "她说"
    set valuesList to my collectStaticTexts(window 1, 0)
    set AppleScript's text item delimiters to linefeed
    return valuesList as text
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_static_text_read_failed",
            "stderr": platform._short(result.stderr),
        }
    raw = str(result.stdout or "").strip()
    values: list[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            values = [str(item).strip() for item in parsed if _tashuo_ax_text_value_is_useful(str(item))]
        else:
            values = [line.strip() for line in raw.splitlines() if _tashuo_ax_text_value_is_useful(line)]
    return {
        "status": "ok",
        "value_count": len(values),
        "values": values,
        "input_backend": "macos_accessibility",
    }

def _tashuo_ax_text_value_is_useful(value: str) -> bool:
    stripped = str(value).strip()
    return bool(stripped) and stripped != "missing value"

def _set_tashuo_ax_text_area_value(session: Any, text: str) -> dict[str, Any]:
    escaped_text = json.dumps(text, ensure_ascii=False)
    script = f'''
-- DATING_BOOST_AX_SET_TEXT_AREA_VALUE
on setTextAreaValue(e, depth, newValue)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then
        set value of e to newValue
        return true
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set changed to my setTextAreaValue(child, depth + 1, newValue)
          if changed is true then return true
        end repeat
      end if
    end try
  end tell
  return false
end setTextAreaValue

tell application "System Events"
  tell process "她说"
    set changed to my setTextAreaValue(window 1, 0, {escaped_text})
    if changed is true then
      return "set"
    end if
    return "not_found"
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_set_failed",
            "stderr": platform._short(result.stderr),
            "input_backend": "macos_accessibility",
        }
    if str(result.stdout or "").strip() != "set":
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_not_found",
            "input_backend": "macos_accessibility",
        }
    return {
        "status": "ok",
        "input_backend": "macos_accessibility",
        "expected_payload_hash": platform._hash_text(text),
        "expected_character_count": len(text),
    }

def _clear_tashuo_ax_text_area(session: Any) -> dict[str, Any]:
    script = r'''
-- DATING_BOOST_AX_CLEAR_TEXT_AREA
on clearTextAreas(e, depth)
  tell application "System Events"
    try
      if role of e is "AXTextArea" then
        set value of e to ""
        return true
      end if
      if depth < 24 then
        repeat with child in UI elements of e
          set cleared to my clearTextAreas(child, depth + 1)
          if cleared is true then return true
        end repeat
      end if
    end try
  end tell
  return false
end clearTextAreas

tell application "System Events"
  tell process "她说"
    set cleared to my clearTextAreas(window 1, 0)
    if cleared is true then
      return "cleared"
    end if
    return "not_found"
  end tell
end tell
'''
    result = session.runner.run(["osascript", "-e", script])
    if result.returncode != 0:
        return {
            "status": "blocked",
            "reason": "tashuo_ax_text_area_clear_failed",
            "stderr": platform._short(result.stderr),
        }
    if str(result.stdout or "").strip() != "cleared":
        return {"status": "blocked", "reason": "tashuo_ax_text_area_not_found"}
    return {"status": "ok", "input_backend": "macos_accessibility"}

def _tashuo_host_visual_staged_verification_available(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> bool:
    if screen.get("status") != "ok" or not screen.get("path"):
        return False
    if screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt", "tashuo_question_gate"}:
        return False
    observed_text = str(screen.get("text") or "")
    if _tashuo_input_placeholder_visible(observed_text):
        return False
    if _tashuo_obvious_wrong_staged_text_visible(observed_text, expected_text):
        return False
    crop_ocr = staged_verification.get("input_crop_ocr")
    return not isinstance(crop_ocr, dict) or crop_ocr.get("status") in {None, "ok", "blocked"}

def _tashuo_obvious_wrong_staged_text_visible(observed_text: str, expected_text: str) -> bool:
    if platform._message_text_matches(observed_text, expected_text):
        return False
    normalized_lines = [line.strip().lower() for line in observed_text.splitlines() if line.strip()]
    if any(line in {"v", "发送v", "v发送"} for line in normalized_lines):
        return True
    comparable = platform._message_text_comparable(observed_text)
    expected = platform._message_text_comparable(expected_text)
    if expected and expected in comparable:
        return False
    return comparable.endswith("v发送") or comparable.endswith("vsend")

def _tashuo_visual_staged_verification_request(
    screen: dict[str, Any],
    staged_verification: dict[str, Any],
    expected_text: str,
) -> dict[str, Any]:
    crop_ocr = staged_verification.get("input_crop_ocr")
    crop = crop_ocr if isinstance(crop_ocr, dict) else {}
    return platform._staged_text_visual_verification_request(
        screen=screen,
        staged_verification=staged_verification,
        expected_text=expected_text,
        extra={
            "input_crop_path": crop.get("path"),
            "input_crop_resized_path": crop.get("resized_path"),
            "input_crop_region": crop.get("region") or TASHUO_MAC_IOS_APP_INPUT_OCR_REGION,
            "ocr_status": "skipped" if staged_verification.get("ocr_disabled_after_message_page") else crop.get("status"),
            "ocr_text_hash": None if staged_verification.get("ocr_disabled_after_message_page") else crop.get("text_hash"),
            "ocr_text_character_count": None
            if staged_verification.get("ocr_disabled_after_message_page")
            else crop.get("text_character_count"),
        },
        instructions="Use visual inspection of the screenshot to compare the staged input with the expected payload held by the current action request. Do not use OCR and do not press Return unless the visual comparison is exact.",
    )

def _tashuo_host_visual_outbound_verification_available(
    post_screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    expected_text: str,
    *,
    staged_exact_text_verified: bool,
    input_cleared: bool,
) -> bool:
    if not expected_text.strip():
        return False
    if staged_exact_text_verified is not True or input_cleared is not True:
        return False
    if post_screen.get("status") != "ok" or not post_screen.get("path"):
        return False
    if post_screen.get("state") != "tashuo_conversation":
        return False
    if outbound_verification.get("exact_text_ax_verified") is True:
        return False
    return True

def _tashuo_visual_outbound_verification_request(
    staged_screen: dict[str, Any] | None,
    post_screen: dict[str, Any],
    outbound_verification: dict[str, Any],
    expected_text: str,
    *,
    post_action_observation_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "verification_type": "outbound_message_visual",
        "status": "needs_host_visual_verification",
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_character_count": len(expected_text),
        "staged_screen_path": staged_screen.get("path") if isinstance(staged_screen, dict) else None,
        "post_screen_path": post_screen.get("path"),
        "screen_state": post_screen.get("state"),
        "post_action_observation_id": post_action_observation_id,
        "input_cleared_after_send": bool(outbound_verification.get("input_cleared_after_send")),
        "staged_exact_text_verified": bool(outbound_verification.get("staged_exact_text_verified")),
        "outbound_visual_region": dict(TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION),
        "ocr_status": "skipped",
        "next_host_action": "visually_verify_outbound_message_after_live_send",
        "instructions": "Use visual inspection of the post-send screenshot to confirm the latest outbound bubble exactly matches the current action request payload. Do not use OCR; if the screenshot does not visibly confirm the sent text, record unknown rather than succeeded.",
    }

def _stage_only_tashuo_verification(
    screen: dict[str, Any],
    expected_text: str,
    *,
    baseline_screen: dict[str, Any] | None = None,
    first_screen: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    ax_text_area_value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    low_level = _verify_staged_tashuo_message(
        screen,
        expected_text,
        baseline_screen=baseline_screen,
        trusted_direct_input=trusted_direct_input,
        ax_text_area_value=ax_text_area_value,
        ocr_disabled_after_message_page=bool(ax_text_area_value is not None),
    )
    observed_text = str(screen.get("text") or "")
    baseline_text = str(baseline_screen.get("text") or "") if isinstance(baseline_screen, dict) else ""
    first_text = str(first_screen.get("text") or "") if isinstance(first_screen, dict) else ""
    placeholder_visible = _tashuo_input_placeholder_visible(observed_text)
    baseline_placeholder_visible = _tashuo_input_placeholder_visible(baseline_text)
    first_placeholder_visible = _tashuo_input_placeholder_visible(first_text)
    evidence = {
        **low_level,
        "placeholder_visible": placeholder_visible,
        "baseline_placeholder_visible": baseline_placeholder_visible,
        "first_capture_placeholder_visible": first_placeholder_visible,
        "screen_text_character_count": len(observed_text),
        "baseline_text_character_count": len(baseline_text),
        "first_screen_text_character_count": len(first_text),
        "trusted_direct_input": trusted_direct_input,
    }
    if low_level.get("status") == "ok":
        return {**evidence, "status": "verified"}
    if low_level.get("status") == "blocked":
        return {**evidence, "status": "failed"}
    if placeholder_visible:
        return {**evidence, "status": "failed", "reason": low_level.get("reason") or "staged_text_not_visible"}
    if len(observed_text) > len(baseline_text) or (baseline_placeholder_visible and not placeholder_visible):
        return {
            **evidence,
            "status": "needs_user_verification",
            "reason": low_level.get("reason") or "cjk_exact_text_not_automatically_verified",
        }
    return {
        **evidence,
        "status": "needs_user_verification",
        "reason": low_level.get("reason") or "stage_result_ambiguous",
    }

def _verify_tashuo_outbound_message(
    screen: dict[str, Any],
    expected_text: str,
    *,
    staged_screen: dict[str, Any] | None = None,
    ax_static_text_values: dict[str, Any] | None = None,
    ax_text_area_value: dict[str, Any] | None = None,
    trusted_direct_input: bool = False,
    staged_exact_text_verified: bool = False,
    visual_commit_allowed: bool = False,
    ocr_disabled_after_message_page: bool = False,
) -> dict[str, Any]:
    result = (
        {
            "verification_method": "tashuo_post_send_ax_then_host_visual_payload_text",
            "expected_payload_hash": platform._hash_text(expected_text),
            "expected_character_count": len(expected_text),
            "observed_text_hash": platform._hash_text(""),
            "observed_character_count": 0,
            "status": "needs_verification",
            "reason": "post_send_requires_visual_verification",
        }
        if ocr_disabled_after_message_page
        else platform._verify_outbound_message(screen, expected_text)
    )
    observed_text = "" if ocr_disabled_after_message_page else str(screen.get("text") or "")
    staged_text = (
        ""
        if ocr_disabled_after_message_page
        else str(staged_screen.get("text") or "") if isinstance(staged_screen, dict) else ""
    )
    observed_stats = platform._expected_text_observation_stats(observed_text, expected_text)
    staged_stats = platform._expected_text_observation_stats(staged_text, expected_text) if staged_text else None
    ax_values = (
        [str(item) for item in ax_static_text_values.get("values", []) if str(item).strip()]
        if isinstance(ax_static_text_values, dict) and isinstance(ax_static_text_values.get("values"), list)
        else []
    )
    ax_text = "\n".join(ax_values)
    ax_stats = platform._expected_text_observation_stats(ax_text, expected_text) if ax_text else None
    ax_text_area = (
        str(ax_text_area_value.get("value") or "")
        if isinstance(ax_text_area_value, dict) and ax_text_area_value.get("status") == "ok"
        else None
    )
    input_cleared = (
        ax_text_area.strip() == ""
        if ax_text_area is not None
        else _tashuo_input_placeholder_visible(observed_text)
    )
    outgoing_bubble_visible = _tashuo_outgoing_bubble_visual_visible(screen)
    staged_outgoing_bubble_visible = (
        _tashuo_outgoing_bubble_visual_visible(staged_screen) if isinstance(staged_screen, dict) else False
    )
    exact_text_ocr_verified = False if ocr_disabled_after_message_page else result.get("status") == "ok"
    exact_text_ax_verified = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
    visual_commit = (
        _tashuo_outbound_visual_commit_verification(
            staged_screen,
            screen,
            input_cleared=input_cleared,
            staged_exact_text_verified=staged_exact_text_verified,
        )
        if visual_commit_allowed
        else {
            "status": "not_applicable",
            "reason": "visual_commit_not_allowed_for_runtime",
            "visual_only_exact_verification_allowed": False,
            "requires_ocr": True,
        }
    )
    exact_text_visual_verified = False
    exact_text_verified = exact_text_ocr_verified or exact_text_ax_verified
    extra = {
        "verification_method": (
            "tashuo_post_send_ax_then_host_visual_payload_text"
            if ocr_disabled_after_message_page
            else "tashuo_post_send_ax_static_text_then_ocr_payload_text"
            if ax_static_text_values is not None
            else "tashuo_post_send_ocr_payload_text_delta"
        ),
        "ocr_disabled_after_message_page": ocr_disabled_after_message_page,
        "observed_expected_text_occurrences": observed_stats["expected_text_occurrences"],
        "staged_expected_text_occurrences": staged_stats["expected_text_occurrences"] if staged_stats else None,
        "staged_text_hash": staged_stats["text_hash"] if staged_stats else None,
        "ax_static_text_status": ax_static_text_values.get("status") if isinstance(ax_static_text_values, dict) else None,
        "ax_static_text_count": ax_static_text_values.get("value_count") if isinstance(ax_static_text_values, dict) else None,
        "ax_expected_text_occurrences": ax_stats["expected_text_occurrences"] if ax_stats else None,
        "ax_text_hash": ax_stats["text_hash"] if ax_stats else None,
        "ax_text_area_status": ax_text_area_value.get("status") if isinstance(ax_text_area_value, dict) else None,
        "ax_text_area_value_hash": platform._hash_text(ax_text_area) if ax_text_area else None,
        "input_cleared_after_send": input_cleared,
        "outgoing_bubble_visual_visible": outgoing_bubble_visible,
        "staged_outgoing_bubble_visual_visible": staged_outgoing_bubble_visible,
        "visual_delta_diagnostics": visual_commit,
        "visual_commit_verification": visual_commit,
        "visual_commit_verified": False,
        "send_action": "press_return",
        "staged_exact_text_verified": staged_exact_text_verified,
        "exact_text_verified": exact_text_verified,
        "exact_text_ax_verified": exact_text_ax_verified,
        "exact_text_ocr_verified": exact_text_ocr_verified,
        "exact_text_visual_verified": exact_text_visual_verified,
        "visual_only_exact_verification_allowed": visual_commit_allowed,
    }
    if screen.get("state") != "tashuo_conversation":
        return {**result, **extra, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if input_cleared is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    if exact_text_verified is not True:
        return {**result, **extra, "status": "needs_verification", "reason": "outbound_message_not_verified"}
    return {**result, **extra, "status": "ok"}

def _tashuo_input_placeholder_visible(text: str) -> bool:
    normalized = platform._normalize_text(text)
    return "点击此处输入文字" in normalized or "输入文字" in normalized

def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)

def _cleanup_failed_tashuo_stage(
    session: Any,
    window: Any,
    input_step: dict[str, Any],
    *,
    expected_text: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    input_tap_ratio = _copy_tap_ratio(input_step["tap_ratio"])
    input_focus_state = str(input_step.get("focus_state") or "unknown")
    click_result = session._click_ratio(window, input_step["tap_ratio"])
    attempts.append({
        "intent": "refocus_tashuo_message_input_for_failed_stage_cleanup",
        "tap_ratio": input_tap_ratio,
        "focus_state": input_focus_state,
        "result": click_result,
    })
    if click_result.get("status") != "ok":
        return {
            "status": "blocked",
            "reason": click_result.get("reason") or "failed_stage_cleanup_refocus_failed",
            "input_tap_ratio": input_tap_ratio,
            "input_focus_state": input_focus_state,
            "attempts": attempts,
        }

    if _is_mac_ios_app_session(session):
        ax_clear_result = _clear_tashuo_ax_text_area(session)
        attempts.append({"intent": "clear_tashuo_text_area_for_failed_stage_cleanup", "result": ax_clear_result})
        if ax_clear_result.get("status") == "ok":
            time.sleep(0.2)
            output = output_dir / f"{_tashuo_capture_prefix(session)}.after_failed_stage_cleanup.png" if output_dir is not None else None
            screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
            ax_value = _tashuo_ax_text_area_value(session)
            ax_text = (
                str(ax_value.get("value") or "")
                if isinstance(ax_value, dict) and ax_value.get("status") == "ok"
                else ""
            )
            expected_still_visible = bool(ax_text) and platform._message_text_matches(ax_text, expected_text)
            input_placeholder_visible = ax_text.strip() == ""
            result = {
                "attempts": attempts,
                "input_tap_ratio": input_tap_ratio,
                "input_focus_state": input_focus_state,
                "screen": platform._redacted_screen(screen),
                "expected_payload_hash": platform._hash_text(expected_text),
                "expected_text_still_visible": expected_still_visible,
                "input_placeholder_visible": input_placeholder_visible,
                "cleanup_backend": "macos_accessibility",
                "ax_text_area_status": ax_value.get("status") if isinstance(ax_value, dict) else None,
                "ax_text_area_value_hash": platform._hash_text(ax_text) if ax_text else None,
            }
            if screen.get("status") != "ok":
                return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_screen_not_captured"}
            if not expected_still_visible and input_placeholder_visible:
                return {**result, "status": "ok"}

    escape_result = session._press_escape_key()
    attempts.append({"intent": "cancel_tashuo_input_candidate_for_failed_stage_cleanup", "result": escape_result})
    backspace_count = min(40, max(4, len(expected_text) + 4))
    for index in range(backspace_count):
        backspace_result = session._press_backspace_key()
        attempts.append({
            "intent": "backspace_tashuo_failed_stage_text",
            "index": index,
            "result": backspace_result,
        })
        if backspace_result.get("status") != "ok":
            return {
                "status": "blocked",
                "reason": backspace_result.get("reason") or "failed_stage_cleanup_backspace_failed",
                "attempts": attempts,
            }
    time.sleep(0.2)
    output = output_dir / f"{_tashuo_capture_prefix(session)}.after_failed_stage_cleanup.png" if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window, ocr=not _is_mac_ios_app_session(session))
    observed_text = str(screen.get("text") or "")
    expected_still_visible = platform._message_text_matches(observed_text, expected_text)
    input_placeholder_visible = _tashuo_input_placeholder_visible(observed_text)
    result = {
        "attempts": attempts,
        "input_tap_ratio": input_tap_ratio,
        "input_focus_state": input_focus_state,
        "screen": platform._redacted_screen(screen),
        "expected_payload_hash": platform._hash_text(expected_text),
        "expected_text_still_visible": expected_still_visible,
        "input_placeholder_visible": input_placeholder_visible,
    }
    if screen.get("status") != "ok":
        return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_screen_not_captured"}
    if expected_still_visible or not input_placeholder_visible:
        return {**result, "status": "needs_verification", "reason": "failed_stage_cleanup_not_verified"}
    return {**result, "status": "ok"}

def _tashuo_outgoing_bubble_visual_visible(screen: dict[str, Any] | None) -> bool:
    if not isinstance(screen, dict):
        return False
    region = TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION
    stats = platform._screen_region_stats(screen, region["x1"], region["y1"], region["x2"], region["y2"])
    if stats is None:
        return False
    return (
        stats["bright_ratio"] > 0.70
        and (
            stats["color_ratio"] > 0.030
            or (stats["color_ratio"] > 0.002 and stats["mid_ratio"] > 0.025)
        )
    )

def _tashuo_outbound_visual_commit_verification(
    staged_screen: dict[str, Any] | None,
    post_screen: dict[str, Any],
    *,
    input_cleared: bool,
    staged_exact_text_verified: bool,
) -> dict[str, Any]:
    base = {
        "verification_method": "tashuo_mac_ios_app_visual_commit_after_exact_stage",
        "staged_exact_text_verified": staged_exact_text_verified,
        "input_cleared_after_send": input_cleared,
        "visual_only_exact_verification_allowed": TASHUO_MAC_IOS_APP_VISUAL_EXACT_VERIFICATION_ALLOWED,
        "visual_region": dict(TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION),
        "requires_ocr": False,
    }
    if not staged_exact_text_verified:
        return {**base, "status": "needs_verification", "reason": "staged_exact_text_not_verified"}
    if input_cleared is not True:
        return {**base, "status": "needs_verification", "reason": "post_send_input_not_clear"}
    if post_screen.get("status") != "ok":
        return {**base, "status": "needs_verification", "reason": post_screen.get("reason") or "post_action_screen_not_captured"}
    if post_screen.get("state") != "tashuo_conversation":
        return {**base, "status": "needs_verification", "reason": "tashuo_conversation_not_verified"}
    if not _tashuo_outgoing_bubble_visual_visible(post_screen):
        return {**base, "status": "needs_verification", "reason": "outgoing_bubble_visual_not_visible"}

    delta = _tashuo_screen_region_visual_delta(
        staged_screen,
        post_screen,
        TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_REGION,
    )
    if delta.get("status") != "ok":
        return {**base, **delta, "status": "needs_verification", "reason": delta.get("reason") or "visual_delta_unavailable"}
    changed_ratio = float(delta.get("changed_pixel_ratio") or 0.0)
    average_delta = float(delta.get("average_channel_delta") or 0.0)
    if (
        changed_ratio < TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO
        or average_delta < TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA
    ):
        return {
            **base,
            **delta,
            "status": "needs_verification",
            "reason": "outgoing_bubble_visual_delta_too_small",
            "min_changed_pixel_ratio": TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_CHANGED_RATIO,
            "min_average_channel_delta": TASHUO_MAC_IOS_APP_OUTBOUND_VISUAL_AVERAGE_DELTA,
        }
    return {**base, **delta, "status": "ok"}

def _tashuo_screen_region_visual_delta(
    before_screen: dict[str, Any] | None,
    after_screen: dict[str, Any],
    region: dict[str, float],
) -> dict[str, Any]:
    if not isinstance(before_screen, dict):
        return {"status": "blocked", "reason": "before_screen_missing"}
    before_path = str(before_screen.get("path") or "")
    after_path = str(after_screen.get("path") or "")
    if not before_path or not after_path:
        return {"status": "blocked", "reason": "visual_delta_screen_path_missing"}
    try:
        before_pixels = _read_png_pixels(Path(before_path))
        after_pixels = _read_png_pixels(Path(after_path))
    except Exception as exc:
        return {"status": "blocked", "reason": "visual_delta_read_failed", "error": str(exc)[:80]}
    try:
        before_width = int(before_pixels["width"])
        before_height = int(before_pixels["height"])
        after_width = int(after_pixels["width"])
        after_height = int(after_pixels["height"])
        before_channels = int(before_pixels["channels"])
        after_channels = int(after_pixels["channels"])
        if before_width != after_width or before_height != after_height:
            return {
                "status": "blocked",
                "reason": "visual_delta_size_mismatch",
                "before_size": [before_width, before_height],
                "after_size": [after_width, after_height],
            }
        x1 = max(0, min(before_width - 1, int(float(region["x1"]) * before_width)))
        x2 = max(x1 + 1, min(before_width, int(float(region["x2"]) * before_width)))
        y1 = max(0, min(before_height - 1, int(float(region["y1"]) * before_height)))
        y2 = max(y1 + 1, min(before_height, int(float(region["y2"]) * before_height)))
        changed_pixels = 0
        total_pixels = 0
        total_delta = 0.0
        for y in range(y1, y2):
            before_row = before_pixels["rows"][y]
            after_row = after_pixels["rows"][y]
            for x in range(x1, x2):
                before_offset = x * before_channels
                after_offset = x * after_channels
                before_rgb = before_row[before_offset : before_offset + 3]
                after_rgb = after_row[after_offset : after_offset + 3]
                delta = sum(abs(int(after_rgb[index]) - int(before_rgb[index])) for index in range(3)) / 3.0
                total_delta += delta
                total_pixels += 1
                if delta >= 10.0:
                    changed_pixels += 1
        return {
            "status": "ok",
            "changed_pixel_ratio": changed_pixels / max(1, total_pixels),
            "average_channel_delta": total_delta / max(1, total_pixels),
            "visual_region": dict(region),
        }
    except Exception as exc:
        return {"status": "blocked", "reason": "visual_delta_failed", "error": str(exc)[:80]}

__all__ = [name for name in globals() if not name.startswith("__")]
