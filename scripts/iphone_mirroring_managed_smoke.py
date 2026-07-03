#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SKILL_PACKAGE_PATH = ROOT / "skills" / "dating-booster-codex" / "skill-package.json"
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-iphone-mirroring-smoke"
DEFAULT_WORK_DIR = ROOT / ".local" / "dating-boost-iphone-mirroring-smoke-work"
SUPPORTED_APPS = ("tinder", "bumble")
IPHONE_MIRRORING_BLOCK_REASONS = {
    "iphone_mirroring_locked",
    "iphone_mirroring_window_not_found",
    "iphone_mirroring_not_frontmost",
    "screen_permission_prompt",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded Tinder/Bumble iPhone Mirroring managed-session stage smoke check."
    )
    parser.add_argument("--app-id", choices=SUPPORTED_APPS, required=True)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--goal", type=Path, required=True)
    parser.add_argument("--availability", type=Path, required=True)
    parser.add_argument("--management-mode", choices=["conservative", "high-throughput"], default="conservative")
    parser.add_argument("--max-threads-per-cycle", type=int)
    parser.add_argument("--max-pages-per-cycle", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--cycle-send-limit", type=int)
    parser.add_argument(
        "--accept-managed-session-config",
        action="store_true",
        help="Explicitly accept the managed-session proposed config returned by the first start attempt.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = run_smoke(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(payload["status"])
        for step in payload["steps"]:
            print(f"- {step['name']}: {step['status']}")
    return 0 if payload["status"] == "ok" else 2


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    support_session_id: str | None = None
    if getattr(args, "max_pages_per_cycle", None) is not None:
        payload = _finish(args, steps, "blocked", "message_list_scan_boundary_framework_controlled", support_session_id)
        payload["message_list_scan_boundary"] = {"type": "first_historical_row", "history_cutoff_days": 7}
        return payload

    final_status = "ok"
    final_reason: str | None = None
    managed_started = False
    try:
        skill_doctor = _run_cli(
            steps,
            "skill_doctor",
            "skill",
            "doctor",
            "--package",
            str(SKILL_PACKAGE_PATH),
            "--data-dir",
            str(args.data_dir),
            "--json",
            allow_failure=True,
        )
        if skill_doctor.get("status") != "ok":
            return _finish(
                args,
                steps,
                "blocked",
                str(skill_doctor.get("reason") or skill_doctor.get("status") or "skill_doctor_failed"),
                support_session_id,
            )

        release_doctor = _run_cli(
            steps,
            "release_doctor",
            "release",
            "doctor",
            "--json",
            allow_failure=True,
        )
        if release_doctor.get("status") != "ok":
            return _finish(
                args,
                steps,
                "blocked",
                str(release_doctor.get("reason") or "release_doctor_failed"),
                support_session_id,
            )

        data_doctor = _run_cli(
            steps,
            "data_doctor",
            "data",
            "doctor",
            "--data-dir",
            str(args.data_dir),
            "--json",
            allow_failure=True,
        )
        if data_doctor.get("status") == "needs_migration":
            data_migrate = _run_cli(
                steps,
                "data_migrate",
                "data",
                "migrate",
                "--data-dir",
                str(args.data_dir),
                "--json",
                allow_failure=True,
            )
            if data_migrate.get("status") != "ok":
                return _finish(
                    args,
                    steps,
                    "blocked",
                    str(data_migrate.get("reason") or "data_migrate_failed"),
                    support_session_id,
                )
            data_doctor = _run_cli(
                steps,
                "data_doctor_after_migrate",
                "data",
                "doctor",
                "--data-dir",
                str(args.data_dir),
                "--json",
                allow_failure=True,
            )
        if data_doctor.get("status") != "ok":
            return _finish(
                args,
                steps,
                "blocked",
                str(data_doctor.get("reason") or data_doctor.get("status") or "data_doctor_failed"),
                support_session_id,
            )

        capabilities = _run_cli(
            steps,
            "capabilities",
            "capabilities",
            "--json",
            "--data-dir",
            str(args.data_dir),
        )
        if args.app_id not in _supported_app_profiles(capabilities):
            return _finish(args, steps, "blocked", f"{args.app_id}_not_supported", support_session_id)
        if _direct_harness_scope(capabilities) != "executor_internal_only":
            return _finish(args, steps, "blocked", "direct_harness_scope_not_executor_internal_only", support_session_id)

        runtime_select = _run_cli(
            steps,
            "runtime_select_default",
            "runtime",
            "select",
            "--data-dir",
            str(args.data_dir),
            "--app-id",
            args.app_id,
            "--runtime",
            "default",
            "--json",
            allow_failure=True,
        )
        if runtime_select.get("status") != "selected":
            return _finish(args, steps, "blocked", str(runtime_select.get("reason") or "runtime_select_failed"), support_session_id)

        _run_cli(steps, "runtime_status_default", "runtime", "status", "--data-dir", str(args.data_dir), "--json")

        support = _run_cli(
            steps,
            "support_session_start",
            "support",
            "session",
            "start",
            "--data-dir",
            str(args.data_dir),
            "--host",
            "codex",
            "--app-id",
            args.app_id,
            "--json",
        )
        support_session_id = str(support.get("session_id") or "")

        doctor = _run_cli(
            steps,
            "harness_doctor_iphone_mirroring",
            "harness",
            "doctor",
            "--app-id",
            args.app_id,
            "--data-dir",
            str(args.data_dir),
            "--json",
            allow_failure=True,
        )
        if doctor.get("status") == "blocked":
            reason = str(doctor.get("reason") or "iphone_mirroring_doctor_failed")
            if reason in IPHONE_MIRRORING_BLOCK_REASONS:
                return _finish(args, steps, "blocked", reason, support_session_id)
            final_status = "blocked"
            final_reason = reason

        if final_status == "ok":
            _run_cli(
                steps,
                "harness_launch_dry_run",
                "harness",
                args.app_id,
                "launch",
                "--dry-run",
                "--data-dir",
                str(args.data_dir),
                "--json",
                allow_failure=True,
            )
            observe = _run_cli(
                steps,
                "harness_observe",
                "harness",
                args.app_id,
                "observe",
                "--data-dir",
                str(args.data_dir),
                "--output-dir",
                str(args.work_dir),
                "--json",
                allow_failure=True,
            )
            if observe.get("status") not in {"ok", "needs_verification"}:
                final_status = "blocked"
                final_reason = str(observe.get("reason") or "iphone_mirroring_observe_failed")
            else:
                prepare = _run_cli(
                    steps,
                    "prepare_message_page_iphone_mirroring",
                    "harness",
                    args.app_id,
                    "action",
                    "prepare-message-page",
                    "--data-dir",
                    str(args.data_dir),
                    "--output-dir",
                    str(args.work_dir),
                    "--json",
                    allow_failure=True,
                )
                if prepare.get("status") not in {"ok", "needs_verification"}:
                    final_status = "blocked"
                    final_reason = str(prepare.get("reason") or "prepare_message_page_failed")

        if final_status == "ok":
            managed_start = _managed_session_start(args, steps)
            if (
                managed_start.get("status") == "blocked"
                and managed_start.get("reason") == "managed_session_config_confirmation_required"
                and args.accept_managed_session_config
            ):
                token = str(managed_start.get("required_confirm_token") or "")
                if token:
                    managed_start = _managed_session_start(args, steps, config_confirm=token)
            if managed_start.get("status") not in {"active", "paused"}:
                final_status = "blocked"
                final_reason = str(managed_start.get("reason") or "managed_session_not_active")
            else:
                managed_started = True
            if managed_start.get("status") == "active":
                tick = _run_cli(
                    steps,
                    "managed_session_tick",
                    "managed-session",
                    "tick",
                    "--data-dir",
                    str(args.data_dir),
                    "--json",
                    allow_failure=True,
                )
                if tick.get("status") not in {"host_work_required", "no_work", "paused", "stopped"}:
                    final_status = "blocked"
                    final_reason = str(tick.get("reason") or "managed_session_tick_failed")

        if managed_started:
            _run_cli(
                steps,
                "managed_session_stop",
                "managed-session",
                "stop",
                "--data-dir",
                str(args.data_dir),
                "--reason",
                f"{args.app_id}_iphone_mirroring_smoke_complete",
                "--json",
                allow_failure=True,
            )
    except SmokeCommandError as exc:
        final_status = "blocked"
        final_reason = exc.reason
    finally:
        if support_session_id:
            try:
                _run_cli(
                    steps,
                    "support_session_stop",
                    "support",
                    "session",
                    "stop",
                    "--data-dir",
                    str(args.data_dir),
                    "--session-id",
                    support_session_id,
                    "--json",
                    allow_failure=True,
                )
            except SmokeCommandError:
                pass
    return _finish(args, steps, final_status, final_reason, support_session_id)


def _managed_session_start(
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    *,
    config_confirm: str | None = None,
) -> dict[str, Any]:
    start_args = [
        "managed-session",
        "start",
        "--app-id",
        args.app_id,
        "--data-dir",
        str(args.data_dir),
        "--authorization",
        str(args.authorization),
        "--goal",
        str(args.goal),
        "--availability",
        str(args.availability),
        "--send-mode",
        "stage",
        "--management-mode",
        args.management_mode,
    ]
    if args.max_threads_per_cycle is not None:
        start_args.extend(["--max-threads-per-cycle", str(args.max_threads_per_cycle)])
    if args.cycle_send_limit is not None:
        start_args.extend(["--cycle-send-limit", str(args.cycle_send_limit)])
    if config_confirm:
        start_args.extend(["--config-confirm", config_confirm])
    start_args.append("--json")
    return _run_cli(
        steps,
        "managed_session_start" if config_confirm is None else "managed_session_start_confirmed",
        *start_args,
        allow_failure=True,
    )


def _run_cli(
    steps: list[dict[str, Any]],
    name: str,
    *command: str,
    allow_failure: bool = False,
) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "dating_boost.cli", *command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = _parse_json(result.stdout)
    step = {
        "name": name,
        "status": payload.get("status") or ("ok" if result.returncode == 0 else "error"),
        "returncode": result.returncode,
        "reason": payload.get("reason"),
        "cmd": list(command),
        "payload": _summarize_payload(name, payload),
    }
    steps.append(step)
    if result.returncode != 0 and not allow_failure:
        raise SmokeCommandError(str(step["reason"] or f"{name}_failed"))
    return payload


def _parse_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "reason": "non_json_command_output", "stdout": text}
    return parsed if isinstance(parsed, dict) else {"status": "error", "reason": "non_object_json_output"}


def _supported_app_profiles(payload: dict[str, Any]) -> list[str]:
    direct = payload.get("supported_app_profiles")
    if isinstance(direct, list):
        return [str(item) for item in direct]
    agent_native = payload.get("agent_native_capabilities")
    if isinstance(agent_native, dict):
        nested = agent_native.get("supported_app_profiles")
        if isinstance(nested, list):
            return [str(item) for item in nested]
    return []


def _direct_harness_scope(payload: dict[str, Any]) -> str | None:
    guidance = payload.get("managed_live_send_guidance")
    if isinstance(guidance, dict):
        scope = guidance.get("direct_harness_scope")
        if isinstance(scope, str):
            return scope
    agent_native = payload.get("agent_native_capabilities")
    if isinstance(agent_native, dict):
        guidance = agent_native.get("managed_live_send_guidance")
        if isinstance(guidance, dict):
            scope = guidance.get("direct_harness_scope")
            if isinstance(scope, str):
                return scope
    return None


def _summarize_payload(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
    }
    for key in (
        "session_id",
        "support_session_id",
        "app_id",
        "harness_runtime",
        "send_mode",
        "next_host_action",
        "required_confirm_token",
    ):
        if key in payload:
            summary[key] = payload[key]
    if name == "capabilities":
        summary["supported_app_profiles"] = _supported_app_profiles(payload)
        summary["direct_harness_scope"] = _direct_harness_scope(payload)
        agent_native = payload.get("agent_native_capabilities")
        if isinstance(agent_native, dict):
            summary["managed_session_harness_runtime_selection"] = agent_native.get(
                "managed_session_harness_runtime_selection"
            )
    if name == "skill_doctor":
        summary["capabilities_ok"] = payload.get("capabilities_ok")
        summary["missing_commands"] = list(payload.get("missing_commands") or [])[:5]
        summary["schema_mismatches"] = list(payload.get("schema_mismatches") or [])[:5]
        summary["next_action"] = payload.get("next_action")
        summary["cli_version"] = payload.get("cli_version")
    if name == "release_doctor":
        summary["issues"] = list(payload.get("issues") or [])[:5]
    if name in {"data_doctor", "data_doctor_after_migrate", "data_migrate"}:
        for key in ("storage_backend", "migration_schema_version", "encrypted_default"):
            if key in payload:
                summary[key] = payload[key]
    if isinstance(payload.get("proposed_config"), dict):
        proposed = payload["proposed_config"]
        summary["proposed_config"] = {
            key: proposed.get(key)
            for key in (
                "app_id",
                "send_mode",
                "managed_gui_send",
                "management_mode",
                "max_threads_per_cycle",
                "cycle_send_limit",
                "harness_runtime",
                "message_list_scan_boundary",
            )
            if key in proposed
        }
    window_probe = _payload_window_probe(payload)
    if window_probe is not None:
        summary["window_probe"] = window_probe
    return {key: value for key, value in summary.items() if value is not None}


def _payload_window_probe(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_probe = payload.get("window_probe")
    if not isinstance(raw_probe, dict):
        preflight = payload.get("preflight")
        if isinstance(preflight, dict):
            raw_probe = preflight.get("window_probe")
    if not isinstance(raw_probe, dict):
        app_precheck = payload.get("app_precheck")
        if isinstance(app_precheck, dict):
            raw_probe = app_precheck.get("window_probe")
    if not isinstance(raw_probe, dict):
        return None
    processes = raw_probe.get("processes")
    summarized_processes = []
    if isinstance(processes, list):
        for process in processes:
            if isinstance(process, dict):
                summarized_processes.append(
                    {
                        key: process.get(key)
                        for key in ("process_name", "process_exists", "frontmost", "visible", "window_count", "status")
                        if key in process
                    }
                )
    return {
        "frontmost_process": raw_probe.get("frontmost_process"),
        "processes": summarized_processes,
    }


def _finish(
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    status: str,
    reason: str | None,
    support_session_id: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "app_id": args.app_id,
        "harness_runtime": "default",
        "send_mode": "stage",
        "data_dir": str(args.data_dir),
        "work_dir": str(args.work_dir),
        "support_session_id": support_session_id,
        "steps": steps,
    }


class SmokeCommandError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


if __name__ == "__main__":
    raise SystemExit(main())
