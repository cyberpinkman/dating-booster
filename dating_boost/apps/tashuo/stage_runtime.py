from __future__ import annotations

from .runtime_common import *
from .targeting import *
from .send_input_ax import *
from .send_verification import *

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
