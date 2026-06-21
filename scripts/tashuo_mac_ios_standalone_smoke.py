#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-tashuo-standalone-smoke"
DEFAULT_OUTPUT_DIR = ROOT / ".local" / "dating-boost-tashuo-standalone-harness"


class SmokeCommandError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded TaShuo mac-ios-app standalone stage smoke.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--vision-backend", choices=["scripted", "openai"], default="openai")
    parser.add_argument("--scripted-vision-output", type=Path)
    parser.add_argument("--backend", choices=["scripted", "openai"], default="openai")
    parser.add_argument("--scripted-backend-output", type=Path)
    parser.add_argument("--max-ticks", type=int, default=5)
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
    try:
        _run_step(
            steps,
            ["runtime", "select", "--data-dir", str(args.data_dir), "--app-id", "tashuo", "--runtime", "mac-ios-app", "--json"],
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
        if args.scripted_vision_output is not None:
            start_cmd.extend(["--scripted-vision-output", str(args.scripted_vision_output)])
        if args.scripted_backend_output is not None:
            start_cmd.extend(["--scripted-backend-output", str(args.scripted_backend_output)])
        start_payload = _run_step(steps, start_cmd, allow_failure=True)
        if start_payload.get("reason") == "managed_session_config_confirmation_required":
            confirm_token = str(start_payload.get("required_confirm_token") or "").strip()
            if not confirm_token:
                raise SmokeCommandError("managed_session_config_confirmation_token_missing")
            _run_step(steps, [*start_cmd[:-1], "--config-confirm", confirm_token, "--json"])
        elif int(start_payload.get("_returncode") or 0) != 0:
            raise SmokeCommandError(f"command_failed:{start_payload.get('_returncode')}")

        max_ticks = max(1, int(args.max_ticks))
        for _ in range(max_ticks):
            tick = _run_step(steps, ["standalone-session", "tick", "--data-dir", str(args.data_dir), "--json"])
            tick_status = str(tick.get("status") or "unknown")
            if tick_status == "stage_recorded":
                status = "ok"
                reason = "tashuo_standalone_stage_smoke_complete"
                break
            if tick_status in {"blocked", "error"}:
                reason = str(tick.get("reason") or tick_status)
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
            )
        except SmokeCommandError:
            pass

    return {"schema_version": 1, "status": status, "reason": reason, "steps": steps}


def _run_step(steps: list[dict[str, Any]], dating_boost_args: list[str], *, allow_failure: bool = False) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "dating_boost.cli", *dating_boost_args]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=ROOT)
    payload = _json_or_empty(result.stdout)
    steps.append(
        {
            "cmd": dating_boost_args,
            "returncode": result.returncode,
            "status": payload.get("status"),
            "reason": payload.get("reason"),
        }
    )
    if result.returncode != 0 and not allow_failure:
        raise SmokeCommandError(f"command_failed:{result.returncode}")
    return {**payload, "_returncode": result.returncode}


def _json_or_empty(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
