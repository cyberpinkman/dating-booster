from __future__ import annotations

from .runtime_common import *
from .targeting import *
from .send_input_ax import *
from .send_verification import *

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
