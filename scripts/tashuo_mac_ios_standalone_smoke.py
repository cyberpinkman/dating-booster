#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from dating_boost.core.tashuo_standalone_alpha_gate import evaluate_alpha_gate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-tashuo-standalone-smoke"
DEFAULT_OUTPUT_DIR = ROOT / ".local" / "dating-boost-tashuo-standalone-harness"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"


class SmokeCommandError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded TaShuo mac-ios-app standalone stage smoke.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--vision-backend", choices=["scripted", "openai", "minimax"], default="minimax")
    parser.add_argument("--vision-model")
    parser.add_argument("--scripted-vision-output", type=Path)
    parser.add_argument("--backend", choices=["scripted", "openai", "minimax"], default="minimax")
    parser.add_argument("--model")
    parser.add_argument("--scripted-backend-output", type=Path)
    parser.add_argument("--minimax-base-url", default="https://api.minimaxi.com/v1")
    parser.add_argument("--minimax-api-key-env", default="MINIMAX_API_KEY")
    parser.add_argument("--max-ticks", type=int, default=5)
    parser.add_argument("--step-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = run_smoke(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['reason']}")
    return 0 if payload["status"] == "ok" else 2


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    status = "blocked"
    reason = "standalone_stage_not_recorded"
    env = _smoke_env(args.env_file)
    try:
        _run_step(
            steps,
            ["runtime", "select", "--data-dir", str(args.data_dir), "--app-id", "tashuo", "--runtime", "mac-ios-app", "--json"],
            env=env,
            timeout_seconds=args.step_timeout_seconds,
        )
        start_cmd = [
            "standalone-session",
            "start",
            "--data-dir",
            str(args.data_dir),
            "--authorization",
            str(args.authorization),
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--send-mode",
            "stage",
            "--observation-source",
            "live-gui",
            "--output-dir",
            str(args.output_dir),
            "--vision-backend",
            args.vision_backend,
            "--backend",
            args.backend,
            "--json",
        ]
        if args.vision_model is not None:
            start_cmd.extend(["--vision-model", args.vision_model])
        elif args.vision_backend == "minimax":
            start_cmd.extend(["--vision-model", DEFAULT_MINIMAX_MODEL])
        if args.model is not None:
            start_cmd.extend(["--model", args.model])
        elif args.backend == "minimax":
            start_cmd.extend(["--model", DEFAULT_MINIMAX_MODEL])
        if args.vision_backend == "minimax" or args.backend == "minimax":
            start_cmd.extend(["--minimax-base-url", args.minimax_base_url])
            start_cmd.extend(["--minimax-api-key-env", args.minimax_api_key_env])
        if args.scripted_vision_output is not None:
            start_cmd.extend(["--scripted-vision-output", str(args.scripted_vision_output)])
        if args.scripted_backend_output is not None:
            start_cmd.extend(["--scripted-backend-output", str(args.scripted_backend_output)])
        start_payload = _run_step(steps, start_cmd, allow_failure=True, env=env, timeout_seconds=args.step_timeout_seconds)
        if start_payload.get("reason") == "managed_session_config_confirmation_required":
            confirm_token = str(start_payload.get("required_confirm_token") or "").strip()
            if not confirm_token:
                raise SmokeCommandError("managed_session_config_confirmation_token_missing")
            _run_step(steps, [*start_cmd, "--config-confirm", confirm_token], env=env, timeout_seconds=args.step_timeout_seconds)
        elif int(start_payload.get("_returncode") or 0) != 0:
            raise SmokeCommandError(f"command_failed:{start_payload.get('_returncode')}")

        max_ticks = max(1, int(args.max_ticks))
        for _ in range(max_ticks):
            tick = _run_step(
                steps,
                ["standalone-session", "tick", "--data-dir", str(args.data_dir), "--json"],
                allow_failure=True,
                env=env,
                timeout_seconds=args.step_timeout_seconds,
            )
            tick_status = str(tick.get("status") or "unknown")
            if tick_status == "stage_recorded":
                status = "ok"
                reason = "tashuo_standalone_stage_smoke_complete"
                break
            if tick_status in {"blocked", "error"}:
                reason = str(tick.get("reason") or tick_status)
                break
            if int(tick.get("_returncode") or 0) != 0:
                reason = str(tick.get("reason") or f"command_failed:{tick.get('_returncode')}")
                break
            if tick_status == "no_work":
                reason = "standalone_tick_no_work"
                break
            reason = f"standalone_tick_incomplete:{tick_status}"
    except SmokeCommandError as exc:
        reason = exc.reason
    finally:
        try:
            _run_step(
                steps,
                ["standalone-session", "stop", "--data-dir", str(args.data_dir), "--reason", "smoke_complete", "--json"],
                allow_failure=True,
                env=env,
                timeout_seconds=args.step_timeout_seconds,
            )
        except SmokeCommandError:
            pass

    payload: dict[str, Any] = {"schema_version": 1, "status": status, "reason": reason, "steps": steps}
    if status == "ok" and reason == "tashuo_standalone_stage_smoke_complete":
        gate = evaluate_alpha_gate(payload, data_dir=args.data_dir)
        payload["alpha_release_gate"] = gate
        if gate.get("status") != "ok":
            payload["status"] = "blocked"
            payload["reason"] = str(gate.get("reason") or "alpha_gate_failed")
    return payload


def _run_step(
    steps: list[dict[str, Any]],
    dating_boost_args: list[str],
    *,
    allow_failure: bool = False,
    env: dict[str, str] | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "dating_boost.cli", *dating_boost_args]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        reason = _command_timeout_reason(dating_boost_args)
        steps.append(
            {
                "cmd": dating_boost_args,
                "returncode": None,
                "status": "error",
                "reason": reason,
                "error_type": "TimeoutExpired",
                "error_message": _truncate(str(exc)),
                "work_item_type": None,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not allow_failure:
            raise SmokeCommandError(reason) from exc
        return {
            "schema_version": 1,
            "status": "error",
            "reason": reason,
            "error_type": "TimeoutExpired",
            "_returncode": 124,
        }
    payload = _json_or_empty(result.stdout)
    steps.append(
        {
            "cmd": dating_boost_args,
            "returncode": result.returncode,
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "error_type": payload.get("error_type"),
            "error_message": _truncate(payload.get("error_message")),
            "work_item_type": payload.get("work_item_type"),
            "recorded": _recorded_stage_binding(payload.get("recorded")),
        }
    )
    if result.returncode != 0 and not allow_failure:
        raise SmokeCommandError(f"command_failed:{result.returncode}")
    return {**payload, "_returncode": result.returncode}


def _recorded_stage_binding(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    binding = {
        key: value[key]
        for key in ("event_id", "action_request_id", "target_match_id", "payload_hash")
        if isinstance(value.get(key), str) and value.get(key)
    }
    return binding or None


def _command_timeout_reason(dating_boost_args: list[str]) -> str:
    label = " ".join(dating_boost_args[:2] if len(dating_boost_args) >= 2 else dating_boost_args)
    return f"command_timeout:{label or 'dating_boost'}"


def _smoke_env(env_file: Path | None) -> dict[str, str]:
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
        if not key:
            continue
        env[key] = value.strip().strip('"').strip("'")
    return env


def _json_or_empty(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _truncate(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


if __name__ == "__main__":
    raise SystemExit(main())
