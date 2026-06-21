#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-tashuo-mac-ios-smoke"
DEFAULT_WORK_DIR = ROOT / ".local" / "dating-boost-tashuo-mac-ios-smoke-work"
_RECOVERABLE_DOCTOR_REASONS = {
    "mac_ios_app_window_not_found",
    "mac_ios_app_not_running",
    "mac_ios_app_process_has_no_windows",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded TaShuo mac-ios-app managed-session smoke check without sending messages."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--goal", type=Path, required=True)
    parser.add_argument("--availability", type=Path, required=True)
    parser.add_argument("--management-mode", choices=["conservative", "high-throughput"], default="conservative")
    parser.add_argument("--max-threads-per-cycle", type=int)
    parser.add_argument("--max-pages-per-cycle", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--cycle-send-limit", type=int)
    parser.add_argument("--skip-prepare-message-page", action="store_true")
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
        payload = _finish(
            args,
            steps,
            "blocked",
            "message_list_scan_boundary_framework_controlled",
            support_session_id,
        )
        payload["message_list_scan_boundary"] = {"type": "first_historical_row", "history_cutoff_days": 7}
        return payload
    final_status = "ok"
    final_reason = None
    try:
        capabilities = _run_cli(
            steps,
            "capabilities",
            "capabilities",
            "--json",
            "--data-dir",
            str(args.data_dir),
        )
        if "tashuo" not in _supported_app_profiles(capabilities):
            return _finish(args, steps, "blocked", "tashuo_not_supported", support_session_id)

        runtime_select = _run_cli(
            steps,
            "runtime_select_mac_ios_app",
            "runtime",
            "select",
            "--data-dir",
            str(args.data_dir),
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--json",
            allow_failure=True,
        )
        if runtime_select.get("status") != "selected":
            return _finish(
                args,
                steps,
                "blocked",
                str(runtime_select.get("reason") or "runtime_select_failed"),
                support_session_id,
            )
        _run_cli(
            steps,
            "runtime_status_mac_ios_app",
            "runtime",
            "status",
            "--data-dir",
            str(args.data_dir),
            "--json",
        )

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
            "tashuo",
            "--json",
        )
        support_session_id = str(support.get("session_id") or "")

        doctor = _run_cli(
            steps,
            "harness_doctor_mac_ios_app",
            "harness",
            "doctor",
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--data-dir",
            str(args.data_dir),
            "--json",
            allow_failure=True,
        )
        doctor_status = doctor.get("status")
        doctor_reason = str(doctor.get("reason") or "")
        if doctor_status != "ok" and doctor_reason not in _RECOVERABLE_DOCTOR_REASONS:
            final_status = "blocked"
            final_reason = str(doctor.get("reason") or "mac_ios_app_doctor_failed")

        if final_status == "ok" and not args.skip_prepare_message_page:
            prepare = _run_cli(
                steps,
                "prepare_message_page_mac_ios_app",
                "harness",
                "tashuo",
                "action",
                "prepare-message-page",
                "--runtime",
                "mac-ios-app",
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

        managed_started = False
        if final_status == "ok":
            start_args = [
                "managed-session",
                "start",
                "--app-id",
                "tashuo",
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
                "--harness-runtime",
                "mac-ios-app",
                "--management-mode",
                args.management_mode,
                "--json",
            ]
            if args.max_threads_per_cycle is not None:
                start_args.extend(
                    ["--max-threads-per-cycle", str(args.max_threads_per_cycle)]
                )
            if args.cycle_send_limit is not None:
                start_args.extend(["--cycle-send-limit", str(args.cycle_send_limit)])
            managed_start = _run_cli(
                steps,
                "managed_session_start_mac_ios_app",
                *start_args,
                allow_failure=True,
            )
            if managed_start.get("status") not in {"active", "paused"}:
                final_status = "blocked"
                final_reason = str(
                    managed_start.get("reason")
                    or final_reason
                    or "managed_session_not_active"
                )

            if managed_start.get("status") in {"active", "paused"}:
                managed_started = True
            if managed_start.get("status") == "active":
                tick = _run_cli(
                    steps,
                    "managed_session_tick_mac_ios_app",
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
                "tashuo_mac_ios_app_smoke_complete",
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
        "work_item_type",
    ):
        if key in payload:
            summary[key] = payload[key]
    if name == "capabilities":
        summary["supported_app_profiles"] = _supported_app_profiles(payload)
        agent_native = payload.get("agent_native_capabilities")
        if isinstance(agent_native, dict):
            summary["tashuo_mac_ios_app_runtime"] = agent_native.get("tashuo_mac_ios_app_runtime")
            summary["managed_session_harness_runtime_selection"] = agent_native.get(
                "managed_session_harness_runtime_selection"
            )
    if "work_item" in payload and isinstance(payload["work_item"], dict):
        work_item = payload["work_item"]
        summary["work_item"] = {
            key: work_item.get(key)
            for key in ("work_item_id", "work_item_type", "reason")
            if key in work_item
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
        "app_id": "tashuo",
        "harness_runtime": "mac-ios-app",
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
