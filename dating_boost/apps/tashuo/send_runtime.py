from __future__ import annotations

from .runtime_common import *
from .targeting import *
from .send_input_ax import *
from .send_verification import *

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


__all__ = [name for name in globals() if not name.startswith("__")]
