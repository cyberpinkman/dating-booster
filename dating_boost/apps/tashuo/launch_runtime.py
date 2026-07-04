from __future__ import annotations

from .runtime_common import *

def observe_tashuo_screen(session: Any, *, output_dir: Path | None = None) -> dict[str, Any]:
    payload = {
        **session._base_payload("ok"),
        "target": "tashuo_screen",
        **tashuo_guardrails_payload(),
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    doctor = session.doctor(capture=False)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    observe_name = "mac_ios_app.tashuo.observe.png" if _is_mac_ios_app_session(session) else "iphone_mirroring.tashuo.observe.png"
    output = output_dir / observe_name if output_dir is not None else None
    screen = _capture_tashuo_window(session, output=output, window=window)
    payload["screen"] = platform._redacted_screen(screen)
    payload["screen_state"] = screen.get("state", "unknown")
    payload["layout_hints"] = tashuo_layout_hints(screen)
    if screen.get("status") != "ok":
        payload.update({"status": "blocked", "reason": screen.get("reason")})
    elif screen.get("state") in {"iphone_mirroring_locked", "screen_permission_prompt"}:
        payload.update({"status": "blocked", "reason": screen.get("state")})
    elif screen.get("state") not in TASHUO_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tashuo_foreground_not_verified"})
    return payload

def launch_tashuo(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    if _is_mac_ios_app_session(session):
        return launch_tashuo_mac_ios_app(session, dry_run=dry_run, output_dir=output_dir)
    planned_steps = platform._launch_app_steps(
        app_name="tashu",
        expected_app_labels=["tashu", "她说", "TaShuo"],
        search_result_intent="tap_tashuo_search_result_icon",
    )
    payload = {
        **session._base_payload("ok"),
        "target": "tashuo_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "bundle_id": "com.intelcupid.tashuo",
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    doctor_output = None
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        doctor_output = output_dir / "iphone_mirroring.tashuo.before_launch.png"
    doctor = session.doctor(capture=True, output=doctor_output)
    payload["preflight"] = doctor
    if doctor["status"] == "blocked":
        payload.update({"status": "blocked", "reason": doctor.get("reason")})
        return payload
    state = doctor.get("screen", {}).get("state")
    if state in TASHUO_FOREGROUND_STATES:
        payload["reason"] = "tashuo_already_foreground"
        return payload

    window = platform._window_from_payload(doctor.get("window") or {})
    executed_steps: list[dict[str, Any]] = []
    for step in planned_steps:
        result = session._execute_step(window, step)
        executed_steps.append({**step, "result": result})
        if result["status"] != "ok":
            payload.update({"status": "blocked", "reason": result["reason"], "executed_steps": executed_steps})
            return payload
        time.sleep(float(step.get("wait_after_seconds", 0.2)))
    payload["executed_steps"] = executed_steps
    verification_output = output_dir / "iphone_mirroring.tashuo.after_launch.png" if output_dir is not None else None
    verification = _capture_tashuo_window(session, output=verification_output, window=window)
    payload["verification"] = platform._redacted_screen(verification)
    if verification["state"] not in TASHUO_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tashuo_launch_not_verified"})
    return payload

def launch_tashuo_mac_ios_app(session: Any, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
    runtime_config = getattr(session, "runtime_config", {}) if isinstance(getattr(session, "runtime_config", {}), dict) else {}
    bundle_id = str(runtime_config.get("bundle_id") or "com.intelcupid.tashuo")
    process_name = str(runtime_config.get("process_name") or "tashuo")
    planned_steps = [
        {
            "intent": "open_tashuo_mac_ios_app_bundle",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "wait_after_seconds": 0.8,
        },
        {
            "intent": "activate_tashuo_mac_ios_process",
            "process_name": process_name,
            "risk": "navigation_only",
            "wait_after_seconds": 0.4,
        },
    ]
    payload = {
        **session._base_payload("ok"),
        "target": "tashuo_mac_ios_app",
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        "bundle_id": bundle_id,
        "process_name": process_name,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    executed_steps: list[dict[str, Any]] = []
    open_payload = _open_tashuo_mac_ios_app_bundle(session, bundle_id)
    executed_steps.append({**planned_steps[0], "result": open_payload})
    if open_payload["status"] != "ok":
        payload.update({"status": "blocked", "reason": "mac_ios_app_open_failed", "executed_steps": executed_steps})
        return payload
    time.sleep(float(planned_steps[0]["wait_after_seconds"]))

    activate_payload = session._activate_window()
    executed_steps.append({**planned_steps[1], "result": activate_payload})
    if activate_payload["status"] != "ok":
        payload.update({
            "status": "blocked",
            "reason": activate_payload.get("reason") or "mac_ios_app_activation_failed",
            "executed_steps": executed_steps,
        })
        return payload
    time.sleep(float(planned_steps[1]["wait_after_seconds"]))

    verification_output = output_dir / "mac_ios_app.tashuo.after_launch.png" if output_dir is not None else None
    verification = session.doctor(capture=True, output=verification_output)
    payload["executed_steps"] = executed_steps
    payload["verification"] = verification
    if verification["status"] == "blocked":
        if _tashuo_mac_ios_window_recoverable_reason(verification.get("reason")):
            recovery_steps = _recover_tashuo_mac_ios_app_window(
                session,
                bundle_id=bundle_id,
                process_name=process_name,
            )
            payload["recovery_steps"] = recovery_steps
            recovery_output = output_dir / "mac_ios_app.tashuo.after_launch_recovered.png" if output_dir is not None else None
            verification = session.doctor(capture=True, output=recovery_output)
            if verification["status"] == "blocked" and _tashuo_mac_ios_window_recoverable_reason(verification.get("reason")):
                force_recovery_steps = _force_recover_tashuo_mac_ios_app_window(
                    session,
                    bundle_id=bundle_id,
                    process_name=process_name,
                )
                payload["force_recovery_steps"] = force_recovery_steps
                force_recovery_output = (
                    output_dir / "mac_ios_app.tashuo.after_launch_force_recovered.png"
                    if output_dir is not None
                    else None
                )
                verification = session.doctor(capture=True, output=force_recovery_output)
            payload["verification"] = verification
            if verification["status"] == "blocked":
                payload.update({"status": "blocked", "reason": verification.get("reason")})
            elif verification.get("screen", {}).get("state") not in TASHUO_FOREGROUND_STATES:
                payload.update({"status": "needs_verification", "reason": "tashuo_mac_ios_app_launch_not_verified"})
        else:
            payload.update({"status": "blocked", "reason": verification.get("reason")})
    elif verification.get("screen", {}).get("state") not in TASHUO_FOREGROUND_STATES:
        payload.update({"status": "needs_verification", "reason": "tashuo_mac_ios_app_launch_not_verified"})
    return payload

def _open_tashuo_mac_ios_app_bundle(session: Any, bundle_id: str) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt_number in range(1, 3):
        open_result = session.runner.run(["open", "-b", bundle_id])
        payload: dict[str, Any] = {
            "attempt": attempt_number,
            "status": "ok" if open_result.returncode == 0 else "blocked",
            "stderr": platform._short(open_result.stderr),
        }
        if payload["status"] == "ok":
            attempts.append(dict(payload))
            payload["attempts"] = attempts
            return payload
        active_probe = session._mac_ios_active_application_probe()
        payload["active_probe_after_failed_open"] = active_probe
        if active_probe.get("status") == "ok":
            payload["status"] = "ok"
            payload["recovered_by"] = "active_probe_after_failed_open"
            attempts.append(dict(payload))
            payload["attempts"] = attempts
            return payload
        attempts.append(dict(payload))
        time.sleep(0.25)
    final = dict(attempts[-1]) if attempts else {"status": "blocked"}
    final["attempts"] = attempts
    return final

def _tashuo_mac_ios_window_recoverable_reason(reason: Any) -> bool:
    return str(reason or "") in {"mac_ios_app_process_has_no_windows", "mac_ios_app_window_not_found"}

def _recover_tashuo_mac_ios_app_window(session: Any, *, bundle_id: str, process_name: str) -> list[dict[str, Any]]:
    recovery_steps: list[dict[str, Any]] = []
    quit_result = session.runner.run(
        ["osascript", "-e", f"tell application id {_applescript_literal(bundle_id)} to quit"]
    )
    recovery_steps.append(
        {
            "intent": "quit_tashuo_mac_ios_app_without_windows",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if quit_result.returncode == 0 else "blocked",
                "stderr": platform._short(quit_result.stderr),
            },
        }
    )
    if quit_result.returncode != 0:
        fallback_script = "\n".join(
            [
                'tell application "System Events"',
                f"if exists process {_applescript_literal(process_name)} then",
                f"tell process {_applescript_literal(process_name)} to quit",
                "end if",
                "end tell",
            ]
        )
        fallback_result = session.runner.run(["osascript", "-e", fallback_script])
        recovery_steps.append(
            {
                "intent": "quit_tashuo_mac_ios_process_without_windows",
                "process_name": process_name,
                "risk": "navigation_only",
                "result": {
                    "status": "ok" if fallback_result.returncode == 0 else "blocked",
                    "stderr": platform._short(fallback_result.stderr),
                },
            }
        )
    time.sleep(0.8)
    reopen_result = session.runner.run(["open", "-b", bundle_id])
    recovery_steps.append(
        {
            "intent": "reopen_tashuo_mac_ios_app_after_no_window",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if reopen_result.returncode == 0 else "blocked",
                "stderr": platform._short(reopen_result.stderr),
            },
        }
    )
    time.sleep(0.8)
    activate_payload = session._activate_window()
    recovery_steps.append(
        {
            "intent": "reactivate_tashuo_mac_ios_app_after_no_window",
            "process_name": process_name,
            "risk": "navigation_only",
            "result": activate_payload,
        }
    )
    time.sleep(0.4)
    return recovery_steps

def _force_recover_tashuo_mac_ios_app_window(session: Any, *, bundle_id: str, process_name: str) -> list[dict[str, Any]]:
    recovery_steps: list[dict[str, Any]] = []
    kill_result = session.runner.run(["pkill", "-x", process_name])
    recovery_steps.append(
        {
            "intent": "force_quit_tashuo_mac_ios_process_without_windows",
            "process_name": process_name,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if kill_result.returncode in {0, 1} else "blocked",
                "stderr": platform._short(kill_result.stderr),
                "returncode": kill_result.returncode,
            },
        }
    )
    time.sleep(1.0)
    reopen_result = session.runner.run(["open", "-b", bundle_id])
    recovery_steps.append(
        {
            "intent": "reopen_tashuo_mac_ios_app_after_force_quit",
            "bundle_id": bundle_id,
            "risk": "navigation_only",
            "result": {
                "status": "ok" if reopen_result.returncode == 0 else "blocked",
                "stderr": platform._short(reopen_result.stderr),
            },
        }
    )
    time.sleep(1.2)
    activate_payload = session._activate_window()
    recovery_steps.append(
        {
            "intent": "reactivate_tashuo_mac_ios_app_after_force_quit",
            "process_name": process_name,
            "risk": "navigation_only",
            "result": activate_payload,
        }
    )
    time.sleep(0.5)
    return recovery_steps

__all__ = [name for name in globals() if not name.startswith("__")]
