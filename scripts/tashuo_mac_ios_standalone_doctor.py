#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost"
MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M3"
MINIMAX_DEFAULT_API_KEY_ENV = "MINIMAX_API_KEY"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose TaShuo mac-ios-app standalone stage prerequisites.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--backend", choices=["openai", "minimax"], default="minimax")
    parser.add_argument("--vision-backend", choices=["openai", "minimax"], default="minimax")
    parser.add_argument("--model", default=MINIMAX_DEFAULT_MODEL)
    parser.add_argument("--vision-model", default=MINIMAX_DEFAULT_MODEL)
    parser.add_argument("--minimax-base-url", default=MINIMAX_DEFAULT_BASE_URL)
    parser.add_argument("--minimax-api-key-env", default=MINIMAX_DEFAULT_API_KEY_ENV)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = run_doctor(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['reason']}")
        for step in payload["steps"]:
            suffix = f" ({step['reason']})" if step.get("reason") else ""
            print(f"- {step['name']}: {step['status']}{suffix}")
    return 0 if payload["status"] == "ok" else 2


def run_doctor(args: argparse.Namespace) -> dict[str, Any]:
    args.data_dir.mkdir(parents=True, exist_ok=True)
    env = _doctor_env(args.env_file)
    steps: list[dict[str, Any]] = []
    support_session_id: str | None = None
    final_status = "ok"
    final_reason = "standalone_doctor_ok"

    try:
        capabilities = _run_cli(
            steps,
            "capabilities",
            "capabilities",
            "--json",
            "--data-dir",
            str(args.data_dir),
            env=env,
            allow_failure=True,
        )
        if "tashuo" not in _supported_app_profiles(capabilities):
            final_status = "blocked"
            final_reason = "tashuo_not_supported"

        if final_status == "ok":
            data_doctor = _run_cli(
                steps,
                "data_doctor",
                "data",
                "doctor",
                "--data-dir",
                str(args.data_dir),
                "--json",
                env=env,
                allow_failure=True,
            )
            if data_doctor.get("status") != "ok":
                final_status = "blocked"
                final_reason = str(data_doctor.get("reason") or "data_doctor_failed")

        if final_status == "ok":
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
                env=env,
                allow_failure=True,
            )
            if runtime_select.get("status") != "selected":
                final_status = "blocked"
                final_reason = str(runtime_select.get("reason") or "runtime_select_failed")

        if final_status == "ok":
            runtime_status = _run_cli(
                steps,
                "runtime_status_mac_ios_app",
                "runtime",
                "status",
                "--data-dir",
                str(args.data_dir),
                "--json",
                env=env,
                allow_failure=True,
            )
            if runtime_status.get("status") != "selected":
                final_status = "blocked"
                final_reason = str(runtime_status.get("reason") or "runtime_scope_not_selected")

        if final_status == "ok":
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
                env=env,
                allow_failure=True,
            )
            support_session_id = str(support.get("session_id") or "") or None
            if support.get("status") != "active" or support_session_id is None:
                final_status = "blocked"
                final_reason = str(support.get("reason") or "support_session_start_failed")

        if final_status == "ok":
            harness = _run_cli(
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
                env=env,
                allow_failure=True,
            )
            if harness.get("status") != "ok":
                final_status = "blocked"
                final_reason = str(harness.get("reason") or "harness_doctor_failed")

        if final_status == "ok" and (args.backend == "minimax" or args.vision_backend == "minimax"):
            probe = _probe_minimax(
                env=env,
                api_key_env=args.minimax_api_key_env,
                base_url=args.minimax_base_url,
                model=args.vision_model if args.vision_backend == "minimax" else args.model,
            )
            steps.append(_probe_step("minimax_probe", probe))
            if probe.get("status") != "ok":
                final_status = "blocked"
                final_reason = str(probe.get("reason") or "minimax_probe_failed")
    except DoctorCommandError as exc:
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
                    env=env,
                    allow_failure=True,
                )
            except DoctorCommandError:
                pass

    return _finish(args, steps, final_status, final_reason, support_session_id)


def _run_cli(
    steps: list[dict[str, Any]],
    name: str,
    *command: str,
    allow_failure: bool = False,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "dating_boost.cli", *command],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
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
        raise DoctorCommandError(str(step["reason"] or f"{name}_failed"))
    return payload


def _probe_minimax(*, env: dict[str, str], api_key_env: str, base_url: str, model: str) -> dict[str, Any]:
    api_key = env.get(api_key_env) or ""
    if not api_key and api_key_env == MINIMAX_DEFAULT_API_KEY_ENV:
        api_key = env.get("MINIMAX_CN_API_KEY") or ""
    if not api_key and api_key_env == MINIMAX_DEFAULT_API_KEY_ENV:
        api_key = env.get("MINIMAX_SUBSCRIPTION_KEY") or ""
    payload: dict[str, Any] = {
        "status": "blocked",
        "reason": None,
        "base_url": base_url,
        "model": model,
        "api_key_env": api_key_env,
        "env_present": bool(api_key),
        "key_length": len(api_key),
    }
    if not api_key:
        payload["reason"] = f"{api_key_env}_missing"
        return payload
    try:
        from openai import OpenAI
    except ImportError:
        payload["reason"] = "openai_sdk_missing"
        payload["error_type"] = "ImportError"
        payload["error_message"] = "Install with `pip install 'dating-booster[models]'` or run through `uv run --extra models`."
        return payload
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Return only OK."}],
            max_tokens=8,
            extra_body={"thinking": {"type": "disabled"}, "reasoning_split": True},
        )
    except Exception as exc:  # noqa: BLE001 - doctor should report external provider failures.
        payload["reason"] = "minimax_probe_failed"
        payload["error_type"] = type(exc).__name__
        payload["error_message"] = _truncate(str(exc))
        return payload
    payload["status"] = "ok"
    payload["reason"] = None
    payload["choices"] = len(getattr(response, "choices", []) or [])
    return payload


def _doctor_env(env_file: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if env_file is None:
        return env
    path = env_file.expanduser()
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            env[key] = value.strip().strip('"').strip("'")
    return env


def _parse_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "reason": "non_json_command_output", "stdout": _truncate(text)}
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
        "schema_version",
        "session_id",
        "app_id",
        "selected_app_id",
        "selected_runtime",
        "storage_backend",
        "next_host_action",
    ):
        if key in payload:
            summary[key] = payload[key]
    if name == "capabilities":
        summary["supported_app_profiles"] = _supported_app_profiles(payload)
        agent_native = payload.get("agent_native_capabilities")
        if isinstance(agent_native, dict):
            summary["tashuo_mac_ios_app_runtime"] = agent_native.get("tashuo_mac_ios_app_runtime")
            summary["standalone_agent_runtime"] = agent_native.get("standalone_agent_runtime")
    window_probe = _payload_window_probe(payload)
    if window_probe is not None:
        summary["window_probe"] = window_probe
    diagnostic = payload.get("diagnostic")
    if isinstance(diagnostic, dict):
        summary["diagnostic"] = {
            key: diagnostic.get(key)
            for key in ("category", "reason", "next_action")
            if key in diagnostic
        }
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


def _probe_step(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "error_type": payload.get("error_type"),
        "error_message": payload.get("error_message"),
        "payload": {
            key: payload.get(key)
            for key in ("base_url", "model", "api_key_env", "env_present", "key_length", "choices")
            if key in payload
        },
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
        "backend": args.backend,
        "vision_backend": args.vision_backend,
        "support_session_id": support_session_id,
        "steps": steps,
    }


def _truncate(value: Any, *, limit: int = 500) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


class DoctorCommandError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


if __name__ == "__main__":
    raise SystemExit(main())
