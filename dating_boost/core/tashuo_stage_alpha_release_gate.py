#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost import __version__


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost"
DEFAULT_WORK_DIR = ROOT / ".local" / "dating-boost-tashuo-stage-alpha-gate"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"
DEFAULT_MINIMAX_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TICKS = 12
FORBIDDEN_COMMAND_TOKENS = {
    "--managed-gui-send",
    "send-message",
    "send_message",
    "like",
    "super-like",
    "super_like",
    "pass",
    "unmatch",
    "report",
    "profile-edit",
    "edit-profile",
    "profile_edit",
    "edit_profile",
    "premium-purchase",
    "premium_purchase",
    "call",
    "payment",
    "flight-start-chat",
    "flight_start_chat",
    "question-gate-send",
    "question_gate_send",
    "question-gate-enable",
    "question_gate_enable",
    "question-gate-skip",
    "question_gate_skip",
    "question-gate-decide-reply-satisfaction",
    "question_gate_decide_reply_satisfaction",
}
LIVE_SEND_COMMAND_TOKENS = {"--managed-gui-send", "send-message", "send_message"}


class GateCommandError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the TaShuo mac-ios-app stage-only private alpha release gate.",
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument(
        "--initial-surface",
        choices=["mixed", "message-list", "current-thread"],
        default="mixed",
        help="mixed covers message-list first, current-thread second, then message-list.",
    )
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--vision-backend", choices=["scripted", "openai", "minimax"], default="minimax")
    parser.add_argument("--vision-model")
    parser.add_argument("--scripted-vision-output", type=Path)
    parser.add_argument("--backend", choices=["scripted", "openai", "minimax"], default="minimax")
    parser.add_argument("--model")
    parser.add_argument("--scripted-backend-output", type=Path)
    parser.add_argument("--minimax-base-url", default="https://api.minimaxi.com/v1")
    parser.add_argument("--minimax-api-key-env", default="MINIMAX_API_KEY")
    parser.add_argument("--minimax-request-timeout-seconds", type=float, default=DEFAULT_MINIMAX_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS)
    parser.add_argument("--step-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--smoke-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--support-session-id",
        help="Reuse an existing active support session. The caller remains responsible for stopping it and exporting the strict bundle.",
    )
    parser.add_argument(
        "--validate-evidence-json",
        type=Path,
        help="Validate an existing alpha_release_evidence.json without opening TaShuo.",
    )
    parser.add_argument(
        "--validate-evidence-bundle",
        type=Path,
        help="Validate an existing alpha_release_evidence_bundle.zip without opening TaShuo.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.validate_evidence_json is not None or args.validate_evidence_bundle is not None:
        payload = validate_release_evidence(
            evidence_json=args.validate_evidence_json,
            evidence_bundle=args.validate_evidence_bundle,
        )
    else:
        if args.authorization is None:
            parser.error("--authorization is required unless validating existing evidence")
        payload = run_gate(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['reason']}")
        print(f"runs: {payload['runs_passed']}/{payload['runs_required']}")
        print(f"evidence: {payload.get('evidence_bundle')}")
    return 0 if payload["status"] == "ok" else 2


def validate_release_evidence(
    *,
    evidence_json: Path | None = None,
    evidence_bundle: Path | None = None,
) -> dict[str, Any]:
    try:
        payload, bundle_smokes, bundle_summary = _load_release_evidence(
            evidence_json=evidence_json,
            evidence_bundle=evidence_bundle,
        )
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "release_evidence_unreadable",
            "error_type": type(exc).__name__,
            "error_message": _truncate(str(exc)),
        }

    checks = _release_evidence_checks(payload, bundle_smokes=bundle_smokes, bundle_summary=bundle_summary)
    status = "ok" if not checks["failures"] else "blocked"
    reason = "tashuo_stage_alpha_release_evidence_validated" if status == "ok" else checks["failures"][0]
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "git_commit": payload.get("git_commit"),
        "tool_version": payload.get("tool_version"),
        "data_schema_version": payload.get("data_schema_version"),
        "runtime_scope": payload.get("runtime_scope") or _runtime_scope_from_payload(payload),
        "run_summary": payload.get("run_summary") or _run_summary_from_payload(payload),
        "source_status": payload.get("status"),
        "source_reason": payload.get("reason"),
        "runs_required": payload.get("runs_required"),
        "runs_completed": payload.get("runs_completed"),
        "runs_passed": payload.get("runs_passed"),
        "checks": checks["checks"],
        "failures": checks["failures"],
        "evidence_json": str(evidence_json) if evidence_json is not None else None,
        "evidence_bundle": str(evidence_bundle) if evidence_bundle is not None else None,
        "bundle_summary": bundle_summary,
    }


def run_gate(args: argparse.Namespace) -> dict[str, Any]:
    if int(args.runs) <= 0:
        raise ValueError("--runs must be positive")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    env = _gate_env(args.env_file)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    steps: list[dict[str, Any]] = []
    smoke_runs: list[dict[str, Any]] = []
    external_support_session = bool(str(getattr(args, "support_session_id", "") or "").strip())
    support_session_id: str | None = str(args.support_session_id).strip() if external_support_session else None
    support_context: dict[str, str] = {}
    support_stop: dict[str, Any] | None = None
    support_bundle: dict[str, Any] | None = None
    final_status = "blocked"
    final_reason = "alpha_release_gate_not_run"
    current_run_number: int | None = None

    try:
        support_session_id = _run_preflight(args, steps=steps, env=env, support_context=support_context)
        for run_number in range(1, int(args.runs) + 1):
            current_run_number = run_number
            run_summary = _run_one_smoke(args, run_number=run_number, steps=steps, env=env)
            smoke_runs.append(run_summary)
            current_run_number = None
            if run_summary["status"] != "ok" and not args.continue_on_failure:
                break
        final_status, final_reason = _release_status(args, smoke_runs, steps)
    except GateCommandError as exc:
        final_status = "blocked"
        final_reason = exc.reason
    except KeyboardInterrupt:
        final_status = "blocked"
        final_reason = "alpha_release_gate_interrupted_by_user"
        if current_run_number is not None and not any(run.get("run_number") == current_run_number for run in smoke_runs):
            smoke_runs.append(_write_interrupted_run_summary(args, run_number=current_run_number))
    finally:
        support_session_id = support_session_id or support_context.get("support_session_id")
        if support_session_id and not external_support_session:
            support_stop = _safe_support_stop(args, steps=steps, env=env, session_id=support_session_id)
            support_bundle = _safe_support_bundle(args, steps=steps, env=env, session_id=support_session_id)

    if final_status == "ok" and not external_support_session and (not support_bundle or support_bundle.get("status") != "ok"):
        final_status = "blocked"
        final_reason = "strict_support_bundle_missing"
    if final_status == "ok" and support_session_id and not external_support_session and (
        not support_stop or support_stop.get("status") not in {"ok", "stopped"}
    ):
        final_status = "blocked"
        final_reason = "support_session_stop_failed"

    payload = _finish(
        args,
        run_id=run_id,
        status=final_status,
        reason=final_reason,
        steps=steps,
        smoke_runs=smoke_runs,
        support_session_id=support_session_id,
        external_support_session=external_support_session,
        support_stop=support_stop,
        support_bundle=support_bundle,
    )
    evidence_json = args.work_dir / "alpha_release_evidence.json"
    evidence_bundle = args.work_dir / "alpha_release_evidence_bundle.zip"
    payload["evidence_json"] = str(evidence_json)
    payload["evidence_bundle"] = str(evidence_bundle)
    payload["evidence_json_path"] = str(evidence_json)
    payload["evidence_bundle_path"] = str(evidence_bundle)
    _write_evidence(payload, evidence_json=evidence_json, evidence_bundle=evidence_bundle)
    return payload


def _run_preflight(
    args: argparse.Namespace,
    *,
    steps: list[dict[str, Any]],
    env: dict[str, str],
    support_context: dict[str, str],
) -> str:
    release = _run_cli(steps, "release_doctor", ["release", "doctor", "--json"], env=env)
    if release.get("status") != "ok":
        raise GateCommandError(str(release.get("reason") or "release_doctor_failed"))

    capabilities = _run_cli(
        steps,
        "capabilities",
        ["capabilities", "--json", "--data-dir", str(args.data_dir)],
        env=env,
    )
    if "tashuo" not in _supported_app_profiles(capabilities):
        raise GateCommandError("tashuo_profile_not_supported")
    agent_native = capabilities.get("agent_native_capabilities")
    if isinstance(agent_native, dict) and agent_native.get("tashuo_mac_ios_app_runtime") is not True:
        raise GateCommandError("tashuo_mac_ios_app_runtime_not_supported")
    if _direct_harness_scope(capabilities) != "executor_internal_only":
        raise GateCommandError("direct_harness_scope_not_executor_internal_only")

    data_doctor = _run_cli(
        steps,
        "data_doctor",
        ["data", "doctor", "--data-dir", str(args.data_dir), "--json"],
        env=env,
    )
    if data_doctor.get("status") == "needs_migration":
        migrate = _run_cli(
            steps,
            "data_migrate",
            ["data", "migrate", "--data-dir", str(args.data_dir), "--json"],
            env=env,
        )
        if migrate.get("status") != "ok":
            raise GateCommandError(str(migrate.get("reason") or "data_migrate_failed"))
        data_doctor = _run_cli(
            steps,
            "data_doctor_after_migrate",
            ["data", "doctor", "--data-dir", str(args.data_dir), "--json"],
            env=env,
        )
    if data_doctor.get("status") != "ok":
        raise GateCommandError(str(data_doctor.get("reason") or "data_doctor_failed"))

    safety = _run_cli(
        steps,
        "safety_status",
        ["safety", "status", "--data-dir", str(args.data_dir), "--json"],
        env=env,
    )
    if safety.get("paused") is True:
        raise GateCommandError("safety_paused")

    readiness = _run_cli(
        steps,
        "user_readiness_autonomous",
        ["user", "readiness", "--data-dir", str(args.data_dir), "--mode", "autonomous", "--json"],
        env=env,
    )
    if readiness.get("ready") is not True:
        raise GateCommandError(str(readiness.get("reason") or readiness.get("status") or "user_readiness_failed"))

    if (args.backend == "minimax" or args.vision_backend == "minimax") and not env.get(args.minimax_api_key_env):
        raise GateCommandError(f"{args.minimax_api_key_env}_missing")
    if _model_backend_requires_openai_sdk(args) and not _openai_sdk_available():
        raise GateCommandError("openai_sdk_missing_for_model_backend")

    runtime_select = _run_cli(
        steps,
        "runtime_select_mac_ios_app",
        [
            "runtime",
            "select",
            "--data-dir",
            str(args.data_dir),
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--json",
        ],
        env=env,
    )
    if runtime_select.get("status") != "selected":
        raise GateCommandError(str(runtime_select.get("reason") or "runtime_select_failed"))

    runtime_status = _run_cli(
        steps,
        "runtime_status_mac_ios_app",
        ["runtime", "status", "--data-dir", str(args.data_dir), "--json"],
        env=env,
    )
    if runtime_status.get("status") != "selected":
        raise GateCommandError(str(runtime_status.get("reason") or "runtime_scope_not_selected"))

    support_session_id = str(getattr(args, "support_session_id", "") or "").strip()
    if support_session_id:
        support_context["support_session_id"] = support_session_id
        steps.append(
            _step(
                "support_session_reuse",
                ["support", "session", "reuse", "--data-dir", str(args.data_dir), "--session-id", support_session_id],
                {
                    "schema_version": 1,
                    "status": "active",
                    "reason": "external_support_session_reused",
                    "session_id": support_session_id,
                    "_returncode": 0,
                },
            )
        )
    else:
        support = _run_cli(
            steps,
            "support_session_start",
            [
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
            ],
            env=env,
        )
        support_session_id = str(support.get("session_id") or "")
        if support.get("status") != "active" or not support_session_id:
            raise GateCommandError(str(support.get("reason") or "support_session_start_failed"))
        support_context["support_session_id"] = support_session_id

    preflight_harness_dir = args.work_dir / "preflight_harness"
    preflight_harness_dir.mkdir(parents=True, exist_ok=True)
    _run_system(
        steps,
        "preflight_force_quit_tashuo_mac_ios_app",
        ["pkill", "-9", "-x", "tashuo"],
        env=env,
        allow_returncodes={0, 1},
    )
    preflight_launch = _run_cli(
        steps,
        "preflight_launch_tashuo_mac_ios_app",
        [
            "harness",
            "tashuo",
            "launch",
            "--data-dir",
            str(args.data_dir),
            "--runtime",
            "mac-ios-app",
            "--output-dir",
            str(preflight_harness_dir),
            "--json",
        ],
        env=env,
        allow_failure=True,
    )
    if preflight_launch.get("status") not in {"ok", "needs_verification"}:
        raise GateCommandError(str(preflight_launch.get("reason") or "preflight_launch_failed"))

    harness = _run_cli(
        steps,
        "harness_doctor_mac_ios_app",
        [
            "harness",
            "doctor",
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--data-dir",
            str(args.data_dir),
            "--json",
        ],
        env=env,
    )
    if harness.get("status") != "ok":
        raise GateCommandError(str(harness.get("reason") or "harness_doctor_failed"))
    return support_session_id


def _model_backend_requires_openai_sdk(args: argparse.Namespace) -> bool:
    return args.backend in {"openai", "minimax"} or args.vision_backend in {"openai", "minimax"}


def _openai_sdk_available() -> bool:
    return importlib.util.find_spec("openai") is not None


def _run_one_smoke(
    args: argparse.Namespace,
    *,
    run_number: int,
    steps: list[dict[str, Any]],
    env: dict[str, str],
) -> dict[str, Any]:
    surface = _surface_for_run(args, run_number)
    run_dir = args.work_dir / f"run_{run_number:02d}_{surface.replace('-', '_')}"
    harness_dir = run_dir / "harness"
    run_dir.mkdir(parents=True, exist_ok=True)
    harness_dir.mkdir(parents=True, exist_ok=True)
    prepare_summary: dict[str, Any] | None = None
    cold_start_summary: dict[str, Any] | None = None
    if surface == "message-list":
        cold_start_summary = _cold_start_tashuo_mac_ios_app(args, run_number=run_number, steps=steps, env=env, harness_dir=harness_dir)
        prepare = _run_prepare_message_page(args, run_number=run_number, steps=steps, env=env, harness_dir=harness_dir)
        if prepare.get("status") != "ok" and _prepare_retry_after_cold_start(prepare):
            cold_start_summary = _cold_start_tashuo_mac_ios_app(
                args,
                run_number=run_number,
                steps=steps,
                env=env,
                harness_dir=harness_dir,
                retry=True,
            )
            time.sleep(0.8)
            prepare = _run_prepare_message_page(
                args,
                run_number=run_number,
                steps=steps,
                env=env,
                harness_dir=harness_dir,
                retry=True,
            )
        prepare_summary = _summarize_prepare(prepare)
        if prepare.get("status") != "ok":
            summary = {
                "schema_version": 1,
                "run_number": run_number,
                "initial_surface": surface,
                "status": "blocked",
                "reason": str(prepare.get("reason") or "prepare_message_page_failed"),
                "cold_start": cold_start_summary,
                "prepare_message_page": prepare_summary,
                "smoke_json": None,
            }
            _write_run_summary(run_dir, summary)
            return summary

    smoke_payload = _run_smoke_script(args, run_number=run_number, run_dir=run_dir, harness_dir=harness_dir, surface=surface, env=env)
    smoke_json = run_dir / "smoke.json"
    smoke_json.write_text(json.dumps(smoke_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    validation = _validate_smoke_payload(smoke_payload)
    summary = {
        "schema_version": 1,
        "run_number": run_number,
        "initial_surface": surface,
        "status": validation["status"],
        "reason": validation["reason"],
        "cold_start": cold_start_summary,
        "prepare_message_page": prepare_summary,
        "smoke_json": str(smoke_json),
        "alpha_release_gate": _summarize_alpha_gate(smoke_payload.get("alpha_release_gate")),
        "final_input_verification": _summarize_final_input(smoke_payload.get("final_input_verification")),
        "stage_binding": _stage_binding(smoke_payload.get("alpha_release_gate")),
    }
    _write_run_summary(run_dir, summary)
    return summary


def _cold_start_tashuo_mac_ios_app(
    args: argparse.Namespace,
    *,
    run_number: int,
    steps: list[dict[str, Any]],
    env: dict[str, str],
    harness_dir: Path,
    retry: bool = False,
) -> dict[str, Any]:
    kill = _run_system(
        steps,
        f"run_{run_number:02d}_{'retry_' if retry else ''}force_quit_tashuo_mac_ios_app",
        ["pkill", "-9", "-x", "tashuo"],
        env=env,
        allow_returncodes={0, 1},
    )
    launch = _run_cli(
        steps,
        f"run_{run_number:02d}_{'retry_' if retry else ''}launch_tashuo_mac_ios_app",
        [
            "harness",
            "tashuo",
            "launch",
            "--data-dir",
            str(args.data_dir),
            "--runtime",
            "mac-ios-app",
            "--output-dir",
            str(harness_dir),
            "--json",
        ],
        env=env,
        allow_failure=True,
    )
    return {
        "status": "ok" if kill.get("status") == "ok" and launch.get("status") in {"ok", "needs_verification"} else "blocked",
        "kill": _summarize_payload(kill),
        "launch": _summarize_payload(launch),
    }


def _run_prepare_message_page(
    args: argparse.Namespace,
    *,
    run_number: int,
    steps: list[dict[str, Any]],
    env: dict[str, str],
    harness_dir: Path,
    retry: bool = False,
) -> dict[str, Any]:
    return _run_cli(
        steps,
        f"run_{run_number:02d}_{'retry_' if retry else ''}prepare_message_page",
        [
            "harness",
            "tashuo",
            "action",
            "prepare-message-page",
            "--data-dir",
            str(args.data_dir),
            "--runtime",
            "mac-ios-app",
            "--output-dir",
            str(harness_dir),
            "--json",
        ],
        env=env,
        allow_failure=True,
    )


def _prepare_retry_after_cold_start(payload: dict[str, Any]) -> bool:
    return str(payload.get("reason") or "") in {
        "tashuo_top_level_tab_bar_not_verified",
        "mac_ios_app_open_failed",
        "mac_ios_app_activation_failed",
        "mac_ios_app_window_not_found",
        "mac_ios_app_process_has_no_windows",
    }


def _run_smoke_script(
    args: argparse.Namespace,
    *,
    run_number: int,
    run_dir: Path,
    harness_dir: Path,
    surface: str,
    env: dict[str, str],
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "tashuo_mac_ios_standalone_smoke.py"),
        "--data-dir",
        str(args.data_dir),
        "--output-dir",
        str(harness_dir),
        "--authorization",
        str(args.authorization),
        "--env-file",
        str(args.env_file),
        "--vision-backend",
        args.vision_backend,
        "--backend",
        args.backend,
        "--initial-surface",
        surface,
        "--max-ticks",
        str(args.max_ticks),
        "--step-timeout-seconds",
        str(args.step_timeout_seconds),
        "--json",
    ]
    if args.vision_model is not None:
        cmd.extend(["--vision-model", args.vision_model])
    elif args.vision_backend == "minimax":
        cmd.extend(["--vision-model", DEFAULT_MINIMAX_MODEL])
    if args.model is not None:
        cmd.extend(["--model", args.model])
    elif args.backend == "minimax":
        cmd.extend(["--model", DEFAULT_MINIMAX_MODEL])
    if args.vision_backend == "minimax" or args.backend == "minimax":
        cmd.extend(["--minimax-base-url", args.minimax_base_url])
        cmd.extend(["--minimax-api-key-env", args.minimax_api_key_env])
        cmd.extend(["--minimax-request-timeout-seconds", str(args.minimax_request_timeout_seconds)])
    if args.scripted_vision_output is not None:
        cmd.extend(["--scripted-vision-output", str(args.scripted_vision_output)])
    if args.scripted_backend_output is not None:
        cmd.extend(["--scripted-backend-output", str(args.scripted_backend_output)])
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=float(args.smoke_timeout_seconds),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "standalone_smoke_timeout",
            "run_number": run_number,
            "error_type": "TimeoutExpired",
            "error_message": _truncate(str(exc)),
            "_returncode": 124,
        }
    payload = _json_or_empty(result.stdout)
    if not payload:
        payload = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "standalone_smoke_non_json_output",
            "stderr": _truncate(result.stderr),
        }
    payload["_returncode"] = result.returncode
    payload["_smoke_command"] = _script_args(cmd)
    payload["_run_dir"] = str(run_dir)
    return payload


def _validate_smoke_payload(smoke_payload: dict[str, Any]) -> dict[str, str]:
    violation = _payload_command_violation(smoke_payload)
    if violation is not None:
        return {"status": "blocked", "reason": violation}
    if smoke_payload.get("status") != "ok":
        return {"status": "blocked", "reason": str(smoke_payload.get("reason") or "standalone_smoke_failed")}
    if smoke_payload.get("reason") != "tashuo_standalone_stage_smoke_complete":
        return {"status": "blocked", "reason": "standalone_smoke_incomplete"}
    final_input = smoke_payload.get("final_input_verification")
    if not isinstance(final_input, dict) or final_input.get("status") != "ok":
        return {"status": "blocked", "reason": "final_input_not_verified_empty"}
    try:
        final_count = int(final_input.get("final_input_character_count"))
    except (TypeError, ValueError):
        final_count = -1
    if final_input.get("input_cleared") is not True or final_count != 0:
        return {"status": "blocked", "reason": "final_input_not_empty"}
    gate = smoke_payload.get("alpha_release_gate")
    if not isinstance(gate, dict) or gate.get("status") != "ok":
        return {"status": "blocked", "reason": str((gate or {}).get("reason") or "alpha_release_gate_failed")}
    checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
    for key in ("stage_only", "live_send_not_executed", "staged_text_verified", "target_verified", "final_input_empty"):
        if checks.get(key) is not True:
            return {"status": "blocked", "reason": f"alpha_gate_check_failed:{key}"}
    stage_result = gate.get("stage_result") if isinstance(gate.get("stage_result"), dict) else {}
    evidence = stage_result.get("evidence") if isinstance(stage_result.get("evidence"), dict) else {}
    if evidence.get("live_send_executed") is not False:
        return {"status": "blocked", "reason": "live_send_execution_not_ruled_out"}
    return {"status": "ok", "reason": "tashuo_stage_alpha_run_passed"}


def _release_status(args: argparse.Namespace, smoke_runs: list[dict[str, Any]], steps: list[dict[str, Any]]) -> tuple[str, str]:
    violation = _steps_command_violation(steps)
    if violation is not None:
        return "blocked", violation
    if len(smoke_runs) != int(args.runs):
        return "blocked", "alpha_release_gate_incomplete"
    for run in smoke_runs:
        if run.get("status") != "ok":
            return "blocked", str(run.get("reason") or "alpha_release_run_failed")
    return "ok", "tashuo_stage_alpha_release_gate_passed"


def _run_cli(
    steps: list[dict[str, Any]],
    name: str,
    dating_boost_args: list[str],
    *,
    env: dict[str, str],
    allow_failure: bool = False,
) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "dating_boost.cli", *dating_boost_args]
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
    except KeyboardInterrupt:
        payload = {
            "schema_version": 1,
            "status": "error",
            "reason": f"command_interrupted:{name}",
            "error_type": "KeyboardInterrupt",
            "error_message": "interrupted by user",
            "_returncode": None,
        }
        steps.append(_step(name, dating_boost_args, payload))
        raise
    except subprocess.TimeoutExpired as exc:
        payload = {
            "schema_version": 1,
            "status": "error",
            "reason": f"command_timeout:{name}",
            "error_type": "TimeoutExpired",
            "error_message": _truncate(str(exc)),
            "_returncode": 124,
        }
        steps.append(_step(name, dating_boost_args, payload))
        if not allow_failure:
            raise GateCommandError(str(payload["reason"])) from exc
        return payload
    payload = _json_or_empty(result.stdout)
    if not payload:
        payload = {"status": "error", "reason": "non_json_command_output", "stderr": _truncate(result.stderr)}
    payload["_returncode"] = result.returncode
    steps.append(_step(name, dating_boost_args, payload))
    if result.returncode != 0 and not allow_failure:
        raise GateCommandError(str(payload.get("reason") or f"{name}_failed"))
    return payload


def _run_system(
    steps: list[dict[str, Any]],
    name: str,
    cmd: list[str],
    *,
    env: dict[str, str],
    allow_returncodes: set[int] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    allowed = allow_returncodes or {0}
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except KeyboardInterrupt:
        payload = {
            "schema_version": 1,
            "status": "blocked",
            "reason": f"command_interrupted:{name}",
            "error_type": "KeyboardInterrupt",
            "error_message": "interrupted by user",
            "_returncode": None,
        }
        steps.append(_step(name, cmd, payload))
        raise
    except subprocess.TimeoutExpired as exc:
        payload = {
            "schema_version": 1,
            "status": "blocked",
            "reason": f"command_timeout:{name}",
            "error_type": "TimeoutExpired",
            "error_message": _truncate(str(exc)),
            "_returncode": 124,
        }
        steps.append(_step(name, cmd, payload))
        return payload
    payload = {
        "schema_version": 1,
        "status": "ok" if result.returncode in allowed else "blocked",
        "reason": None if result.returncode in allowed else f"{name}_failed",
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "_returncode": result.returncode,
    }
    steps.append(_step(name, cmd, payload))
    return payload


def _safe_support_stop(args: argparse.Namespace, *, steps: list[dict[str, Any]], env: dict[str, str], session_id: str) -> dict[str, Any]:
    try:
        return _run_cli(
            steps,
            "support_session_stop",
            [
                "support",
                "session",
                "stop",
                "--data-dir",
                str(args.data_dir),
                "--session-id",
                session_id,
                "--json",
            ],
            env=env,
            allow_failure=True,
        )
    except GateCommandError as exc:
        return {"schema_version": 1, "status": "blocked", "reason": exc.reason}
    except KeyboardInterrupt:
        return {"schema_version": 1, "status": "blocked", "reason": "support_session_stop_interrupted_by_user"}


def _safe_support_bundle(args: argparse.Namespace, *, steps: list[dict[str, Any]], env: dict[str, str], session_id: str) -> dict[str, Any]:
    output = args.work_dir / "dating-boost-support-strict.zip"
    try:
        return _run_cli(
            steps,
            "support_bundle_strict",
            [
                "support",
                "bundle",
                "--data-dir",
                str(args.data_dir),
                "--session-id",
                session_id,
                "--output",
                str(output),
                "--redaction",
                "strict",
                "--json",
            ],
            env=env,
            allow_failure=True,
        )
    except GateCommandError as exc:
        return {"schema_version": 1, "status": "blocked", "reason": exc.reason, "output": str(output)}
    except KeyboardInterrupt:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "support_bundle_interrupted_by_user",
            "output": str(output),
        }


def _finish(
    args: argparse.Namespace,
    *,
    run_id: str,
    status: str,
    reason: str,
    steps: list[dict[str, Any]],
    smoke_runs: list[dict[str, Any]],
    support_session_id: str | None,
    external_support_session: bool,
    support_stop: dict[str, Any] | None,
    support_bundle: dict[str, Any] | None,
) -> dict[str, Any]:
    runs_passed = sum(1 for run in smoke_runs if run.get("status") == "ok")
    command_violation = _any_command_violation(steps, smoke_runs)
    support_bundle_output = support_bundle.get("output") if isinstance(support_bundle, dict) else None
    support_bundle_required = support_session_id is not None and not external_support_session
    strict_support_bundle_ok = (not support_bundle_required) or bool(support_bundle and support_bundle.get("status") == "ok")
    runtime_scope = _runtime_scope_from_steps(steps)
    run_summary = {
        "runs_required": int(args.runs),
        "runs_completed": len(smoke_runs),
        "runs_passed": runs_passed,
        "pass_rate": runs_passed / int(args.runs),
    }
    return {
        "schema_version": 1,
        "status": status,
        "reason": reason,
        "run_id": run_id,
        "git_commit": _git_commit(),
        "tool_version": __version__,
        "data_schema_version": _data_schema_version_from_steps(steps),
        "runtime_scope": runtime_scope,
        "run_summary": run_summary,
        "app_id": "tashuo",
        "harness_runtime": "mac-ios-app",
        "send_mode": "stage",
        "data_dir": str(args.data_dir),
        "work_dir": str(args.work_dir),
        "runs_required": int(args.runs),
        "runs_completed": len(smoke_runs),
        "runs_passed": runs_passed,
        "pass_rate": run_summary["pass_rate"],
        "initial_surface": args.initial_surface,
        "checks": {
            "twenty_of_twenty_passed": int(args.runs) == 20 and runs_passed == 20,
            "required_run_count_passed": len(smoke_runs) == int(args.runs) and runs_passed == int(args.runs),
            "zero_live_send_execution": _zero_live_send_execution(steps, smoke_runs),
            "zero_high_risk_action": command_violation is None,
            "strict_support_bundle": strict_support_bundle_ok,
            "support_bundle_required": support_bundle_required,
            "evidence_bundle_written": True,
        },
        "command_safety_violation": command_violation,
        "support_session_id": support_session_id,
        "external_support_session": external_support_session,
        "support_session_stop": _support_summary(support_stop),
        "support_bundle": _support_summary(support_bundle),
        "support_bundle_path": str(support_bundle_output) if support_bundle_output else None,
        "evidence_bundle_path": str(args.work_dir / "alpha_release_evidence_bundle.zip"),
        "steps": steps,
        "smoke_runs": smoke_runs,
    }


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001 - release metadata should not block evidence generation.
        return "unknown"
    commit = result.stdout.strip()
    return commit or "unknown"


def _data_schema_version_from_steps(steps: list[dict[str, Any]]) -> int | None:
    for step_name in ("data_doctor_after_migrate", "data_doctor"):
        step = next((item for item in reversed(steps) if item.get("name") == step_name), None)
        summary = step.get("summary") if isinstance(step, dict) and isinstance(step.get("summary"), dict) else {}
        try:
            return int(summary.get("schema_version"))
        except (TypeError, ValueError):
            continue
    return None


def _runtime_scope_from_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    for step_name in ("runtime_status_mac_ios_app", "runtime_select_mac_ios_app"):
        step = next((item for item in reversed(steps) if item.get("name") == step_name), None)
        summary = step.get("summary") if isinstance(step, dict) and isinstance(step.get("summary"), dict) else {}
        if summary:
            return {
                "status": summary.get("status"),
                "selected_app_id": summary.get("selected_app_id"),
                "selected_runtime": summary.get("selected_runtime"),
            }
    return {"status": "unknown", "selected_app_id": None, "selected_runtime": None}


def _write_evidence(payload: dict[str, Any], *, evidence_json: Path, evidence_bundle: Path) -> None:
    evidence_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    with zipfile.ZipFile(evidence_bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "alpha_release_evidence.json",
            json.dumps(_redact_for_evidence_bundle(payload), ensure_ascii=False, indent=2, sort_keys=True),
        )
        for run in payload.get("smoke_runs") or []:
            if not isinstance(run, dict):
                continue
            smoke_json = run.get("smoke_json")
            if isinstance(smoke_json, str) and Path(smoke_json).is_file():
                archive.writestr(
                    f"runs/run_{int(run['run_number']):02d}_smoke.json",
                    json.dumps(_redact_for_evidence_bundle(_read_json_file(Path(smoke_json)) or {}), ensure_ascii=False, indent=2, sort_keys=True),
                )
            run_summary = _run_summary_path(payload, run, smoke_json)
            if run_summary is not None and run_summary.is_file():
                archive.writestr(
                    f"runs/run_{int(run['run_number']):02d}_summary.json",
                    json.dumps(_redact_for_evidence_bundle(_read_json_file(run_summary) or {}), ensure_ascii=False, indent=2, sort_keys=True),
                )
        support_bundle = payload.get("support_bundle_path")
        if isinstance(support_bundle, str) and Path(support_bundle).is_file():
            archive.write(support_bundle, "support/dating-boost-support-strict.zip")


EVIDENCE_BUNDLE_REDACT_KEYS = {
    "best_reply",
    "bolder_reply",
    "conversation_observation",
    "draft_text",
    "input_text",
    "latest_match_message",
    "latest_user_message",
    "payload_text",
    "photo_cues",
    "profile_observation",
    "profile_text",
    "raw_chat",
    "raw_conversation",
    "raw_draft",
    "raw_profile",
    "raw_ref",
    "safer_reply",
    "screen",
    "screenshot",
    "text",
    "visible_messages",
    "visible_name",
}


def _run_summary_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "runs_required": payload.get("runs_required"),
        "runs_completed": payload.get("runs_completed"),
        "runs_passed": payload.get("runs_passed"),
        "pass_rate": payload.get("pass_rate"),
    }


def _runtime_scope_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "selected"
        if payload.get("app_id") == "tashuo" and payload.get("harness_runtime") == "mac-ios-app"
        else "unknown",
        "selected_app_id": payload.get("app_id"),
        "selected_runtime": payload.get("harness_runtime"),
        "send_mode": payload.get("send_mode"),
    }


def _redact_for_evidence_bundle(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in EVIDENCE_BUNDLE_REDACT_KEYS:
                redacted[key_text] = _redaction_marker(item)
                continue
            if key_text == "path" and _looks_like_visual_artifact_path(item):
                redacted[key_text] = "[redacted_visual_artifact_path]"
                continue
            redacted[key_text] = _redact_for_evidence_bundle(item)
        return redacted
    if isinstance(value, list):
        return [_redact_for_evidence_bundle(item) for item in value]
    if _looks_like_visual_artifact_path(value):
        return "[redacted_visual_artifact_path]"
    return value


def _redaction_marker(value: Any) -> dict[str, Any]:
    marker = {"redacted": True}
    if isinstance(value, str):
        marker["character_count"] = len(value)
    elif isinstance(value, list):
        marker["item_count"] = len(value)
    elif isinstance(value, dict):
        marker["field_count"] = len(value)
    return marker


def _looks_like_visual_artifact_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return any(ext in lowered for ext in (".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff"))


def _load_release_evidence(
    *,
    evidence_json: Path | None,
    evidence_bundle: Path | None,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]], dict[str, Any]]:
    if evidence_json is None and evidence_bundle is None:
        raise ValueError("one of --validate-evidence-json or --validate-evidence-bundle is required")
    bundle_smokes: dict[int, dict[str, Any]] = {}
    bundle_summary: dict[str, Any] = {"provided": evidence_bundle is not None}
    if evidence_bundle is not None:
        with zipfile.ZipFile(evidence_bundle) as archive:
            names = set(archive.namelist())
            redaction_violations: list[str] = []
            bundle_summary = {
                "provided": True,
                "path": str(evidence_bundle),
                "entry_count": len(names),
                "has_alpha_release_evidence": "alpha_release_evidence.json" in names,
                "has_support_bundle": "support/dating-boost-support-strict.zip" in names,
                "has_visual_artifact_entries": any(_archive_entry_is_visual_artifact(name) for name in names),
            }
            if "alpha_release_evidence.json" not in names:
                raise ValueError("bundle missing alpha_release_evidence.json")
            payload = json.loads(archive.read("alpha_release_evidence.json").decode("utf-8"))
            if isinstance(payload, dict):
                redaction_violations.extend(_redaction_violations(payload, path="alpha_release_evidence.json"))
            for name in sorted(names):
                if name.endswith(".json") and name != "alpha_release_evidence.json":
                    parsed_for_redaction = json.loads(archive.read(name).decode("utf-8"))
                    redaction_violations.extend(_redaction_violations(parsed_for_redaction, path=name))
                if not name.startswith("runs/run_") or not name.endswith("_smoke.json"):
                    continue
                run_number = _bundle_run_number(name)
                if run_number is None:
                    continue
                parsed = json.loads(archive.read(name).decode("utf-8"))
                if isinstance(parsed, dict):
                    bundle_smokes[run_number] = parsed
            bundle_summary["redaction_violations"] = redaction_violations
    else:
        payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("release evidence JSON must be an object")
    if evidence_json is not None and evidence_bundle is not None:
        file_payload = json.loads(evidence_json.read_text(encoding="utf-8"))
        if (
            isinstance(file_payload, dict)
            and payload_digest_for_compare(_redact_for_evidence_bundle(file_payload)) != payload_digest_for_compare(payload)
        ):
            bundle_summary["json_mismatch"] = True
    return payload, bundle_smokes, bundle_summary


def payload_digest_for_compare(payload: dict[str, Any]) -> str:
    comparable = dict(payload)
    comparable.pop("evidence_json", None)
    comparable.pop("evidence_bundle", None)
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _bundle_run_number(name: str) -> int | None:
    stem = Path(name).name
    if not stem.startswith("run_"):
        return None
    try:
        return int(stem.split("_", 2)[1])
    except (IndexError, ValueError):
        return None


def _release_evidence_checks(
    payload: dict[str, Any],
    *,
    bundle_smokes: dict[int, dict[str, Any]],
    bundle_summary: dict[str, Any],
) -> dict[str, Any]:
    failures: list[str] = []
    smoke_runs = payload.get("smoke_runs") if isinstance(payload.get("smoke_runs"), list) else []
    top_checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    support_stop = _dict_or_empty(payload.get("support_session_stop"))
    support_bundle = _dict_or_empty(payload.get("support_bundle"))
    required_top_checks = {
        "twenty_of_twenty_passed",
        "required_run_count_passed",
        "zero_live_send_execution",
        "zero_high_risk_action",
        "strict_support_bundle",
        "support_bundle_required",
        "evidence_bundle_written",
    }
    checks = {
        "source_status_ok": payload.get("status") == "ok",
        "source_reason_ok": payload.get("reason") == "tashuo_stage_alpha_release_gate_passed",
        "app_runtime_stage": payload.get("app_id") == "tashuo"
        and payload.get("harness_runtime") == "mac-ios-app"
        and payload.get("send_mode") == "stage",
        "runs_required_20": payload.get("runs_required") == 20,
        "runs_completed_20": payload.get("runs_completed") == 20,
        "runs_passed_20": payload.get("runs_passed") == 20,
        "smoke_run_count_20": len(smoke_runs) == 20,
        "top_checks_all_true": all(top_checks.get(key) is True for key in required_top_checks),
        "zero_live_send_execution": _zero_live_send_execution(payload.get("steps") if isinstance(payload.get("steps"), list) else [], smoke_runs)
        and _bundle_smokes_zero_live_send_execution(bundle_smokes),
        "zero_high_risk_action": _any_command_violation(
            payload.get("steps") if isinstance(payload.get("steps"), list) else [],
            smoke_runs,
        )
        is None
        and _bundle_smokes_command_violation(bundle_smokes) is None,
        "support_session_stopped": support_stop.get("status") in {"ok", "stopped"},
        "support_bundle_strict": support_bundle.get("status") == "ok"
        and support_bundle.get("redaction") == "strict",
        "bundle_provided": bundle_summary.get("provided") is True,
        "bundle_has_alpha_release_evidence": not bundle_summary.get("provided")
        or bundle_summary.get("has_alpha_release_evidence") is True,
        "bundle_has_support_bundle": not bundle_summary.get("provided")
        or bundle_summary.get("has_support_bundle") is True,
        "bundle_json_matches_file": bundle_summary.get("json_mismatch") is not True,
        "bundle_redacted": bundle_summary.get("provided") is not True
        or (
            bundle_summary.get("has_visual_artifact_entries") is not True
            and not bundle_summary.get("redaction_violations")
        ),
    }
    checks["every_run_summary_ok"] = all(_release_run_summary_ok(run) for run in smoke_runs)
    checks["every_bundle_smoke_ok"] = _bundle_smokes_ok(payload, bundle_smokes, bundle_summary, failures)
    checks["all_release_checks_true"] = all(checks.values())
    for key, value in checks.items():
        if value is not True and key != "all_release_checks_true":
            failures.append(f"release_evidence_check_failed:{key}")
    return {"checks": checks, "failures": failures}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _archive_entry_is_visual_artifact(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith((".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff"))


def _redaction_violations(value: Any, *, path: str) -> list[str]:
    violations: list[str] = []
    _collect_redaction_violations(value, path=path, violations=violations)
    return violations


def _collect_redaction_violations(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            key_text = str(key)
            if key_text in EVIDENCE_BUNDLE_REDACT_KEYS and not _is_redaction_marker(item):
                violations.append(f"unredacted_sensitive_field:{child_path}")
            if key_text == "path" and _looks_like_visual_artifact_path(item):
                violations.append(f"unredacted_visual_path:{child_path}")
            _collect_redaction_violations(item, path=child_path, violations=violations)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _collect_redaction_violations(item, path=f"{path}[{index}]", violations=violations)
        return
    if _looks_like_visual_artifact_path(value):
        violations.append(f"unredacted_visual_path:{path}")


def _is_redaction_marker(value: Any) -> bool:
    return isinstance(value, dict) and value.get("redacted") is True


def _release_run_summary_ok(run: Any) -> bool:
    if not isinstance(run, dict):
        return False
    if run.get("status") != "ok" or run.get("reason") != "tashuo_stage_alpha_run_passed":
        return False
    gate = run.get("alpha_release_gate") if isinstance(run.get("alpha_release_gate"), dict) else {}
    if gate.get("status") != "ok":
        return False
    checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
    for key in ("stage_only", "live_send_not_executed", "staged_text_verified", "target_verified", "final_input_empty"):
        if checks.get(key) is not True:
            return False
    return bool(run.get("stage_binding"))


def _bundle_smokes_ok(
    payload: dict[str, Any],
    bundle_smokes: dict[int, dict[str, Any]],
    bundle_summary: dict[str, Any],
    failures: list[str],
) -> bool:
    if not bundle_summary.get("provided"):
        return True
    try:
        runs_required = int(payload.get("runs_required"))
    except (TypeError, ValueError):
        runs_required = 0
    if runs_required != 20:
        return False
    ok = True
    for run_number in range(1, runs_required + 1):
        smoke = bundle_smokes.get(run_number)
        if not isinstance(smoke, dict):
            failures.append(f"release_evidence_bundle_smoke_missing:run_{run_number:02d}")
            ok = False
            continue
        validation = _validate_smoke_payload(smoke)
        if validation.get("status") != "ok":
            failures.append(f"release_evidence_bundle_smoke_invalid:run_{run_number:02d}:{validation.get('reason')}")
            ok = False
    return ok


def _write_run_summary(run_dir: Path, summary: dict[str, Any]) -> None:
    (run_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_interrupted_run_summary(args: argparse.Namespace, *, run_number: int) -> dict[str, Any]:
    surface = _surface_for_run(args, run_number)
    run_dir = args.work_dir / f"run_{run_number:02d}_{surface.replace('-', '_')}"
    smoke_json = run_dir / "smoke.json"
    existing_summary = _read_json_file(run_dir / "run_summary.json")
    if existing_summary is not None:
        return existing_summary
    summary = {
        "schema_version": 1,
        "run_number": run_number,
        "initial_surface": surface,
        "status": "blocked",
        "reason": "alpha_release_gate_interrupted_by_user",
        "interrupted": True,
        "smoke_json": str(smoke_json) if smoke_json.is_file() else None,
        "partial_artifacts": _partial_run_artifacts(run_dir),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_run_summary(run_dir, summary)
    return summary


def _partial_run_artifacts(run_dir: Path) -> dict[str, Any]:
    if not run_dir.exists():
        return {"run_dir": str(run_dir), "file_count": 0, "files": [], "truncated": False}
    files = sorted(path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file())
    limit = 80
    return {
        "run_dir": str(run_dir),
        "file_count": len(files),
        "files": files[:limit],
        "truncated": len(files) > limit,
    }


def _run_summary_path(payload: dict[str, Any], run: dict[str, Any], smoke_json: Any) -> Path | None:
    if isinstance(smoke_json, str):
        return Path(smoke_json).with_name("run_summary.json")
    work_dir = payload.get("work_dir")
    run_number = run.get("run_number")
    surface = str(run.get("initial_surface") or "").strip()
    if not isinstance(work_dir, str) or not surface:
        return None
    try:
        number = int(run_number)
    except (TypeError, ValueError):
        return None
    return Path(work_dir) / f"run_{number:02d}_{surface.replace('-', '_')}" / "run_summary.json"


def _step(name: str, dating_boost_args: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "cmd": dating_boost_args,
        "returncode": payload.get("_returncode"),
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "error_type": payload.get("error_type"),
        "error_message": _truncate(payload.get("error_message")),
        "summary": _summarize_payload(payload),
    }


def _summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "reason",
        "schema_version",
        "session_id",
        "app_id",
        "selected_app_id",
        "selected_runtime",
        "output",
        "redaction",
        "next_host_action",
        "screen_state",
        "ready",
        "missing",
        "mode",
    )
    return {key: payload[key] for key in keys if key in payload}


def _summarize_prepare(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in ("status", "reason", "screen_state", "next_host_action", "initial_visual_state", "initial_active_tab")
        if key in payload
    }


def _summarize_alpha_gate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "missing"}
    return {
        "status": value.get("status"),
        "reason": value.get("reason"),
        "checks": value.get("checks") if isinstance(value.get("checks"), dict) else None,
        "stage_binding": value.get("stage_binding") if isinstance(value.get("stage_binding"), dict) else None,
    }


def _summarize_final_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "missing"}
    return {
        "status": value.get("status"),
        "input_cleared": value.get("input_cleared"),
        "final_input_character_count": value.get("final_input_character_count"),
        "verification_method": value.get("verification_method"),
        "reason": value.get("reason"),
    }


def _stage_binding(alpha_gate: Any) -> dict[str, Any] | None:
    if not isinstance(alpha_gate, dict):
        return None
    binding = alpha_gate.get("stage_binding")
    return binding if isinstance(binding, dict) else None


def _support_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {key: payload.get(key) for key in ("status", "reason", "output", "redaction") if key in payload}


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


def _direct_harness_scope(payload: dict[str, Any]) -> str:
    guidance = payload.get("managed_live_send_guidance")
    scope = guidance.get("direct_harness_scope") if isinstance(guidance, dict) else None
    return str(scope or "").strip().replace("-", "_").replace(" ", "_")


def _surface_for_run(args: argparse.Namespace, run_number: int) -> str:
    if args.initial_surface in {"message-list", "current-thread"}:
        return str(args.initial_surface)
    if run_number == 2 and int(args.runs) > 1:
        return "current-thread"
    return "message-list"


def _payload_command_violation(payload: dict[str, Any]) -> str | None:
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return "smoke_steps_missing"
    for step in steps:
        if not isinstance(step, dict):
            continue
        violation = _command_violation(step.get("cmd"))
        if violation is not None:
            return violation
    command = payload.get("_smoke_command")
    violation = _command_violation(command)
    if violation is not None:
        return violation
    return None


def _steps_command_violation(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        violation = _command_violation(step.get("cmd"))
        if violation is not None:
            return violation
    return None


def _any_command_violation(steps: list[dict[str, Any]], smoke_runs: list[dict[str, Any]]) -> str | None:
    violation = _steps_command_violation(steps)
    if violation is not None:
        return violation
    for run in smoke_runs:
        violation = _run_command_violation(run)
        if violation is not None:
            return violation
    return None


def _bundle_smokes_command_violation(bundle_smokes: dict[int, dict[str, Any]]) -> str | None:
    for run_number, payload in sorted(bundle_smokes.items()):
        violation = _payload_command_violation(payload)
        if violation is not None:
            return f"run_{run_number:02d}:{violation}"
    return None


def _run_command_violation(run: dict[str, Any]) -> str | None:
    smoke_json = run.get("smoke_json")
    if not isinstance(smoke_json, str):
        return None
    payload = _read_json_file(Path(smoke_json))
    if payload is None:
        return None
    return _payload_command_violation(payload)


def _zero_live_send_execution(steps: list[dict[str, Any]], smoke_runs: list[dict[str, Any]]) -> bool:
    if _steps_live_send_violation(steps) is not None:
        return False
    for run in smoke_runs:
        if _run_live_send_violation(run) is not None:
            return False
        alpha_gate = run.get("alpha_release_gate") if isinstance(run.get("alpha_release_gate"), dict) else {}
        checks = alpha_gate.get("checks") if isinstance(alpha_gate.get("checks"), dict) else {}
        if checks.get("live_send_not_executed") is False:
            return False
    return True


def _bundle_smokes_zero_live_send_execution(bundle_smokes: dict[int, dict[str, Any]]) -> bool:
    for payload in bundle_smokes.values():
        if _payload_live_send_violation(payload) is not None:
            return False
    return True


def _steps_live_send_violation(steps: list[dict[str, Any]]) -> str | None:
    for step in steps:
        violation = _live_send_command_violation(step.get("cmd"))
        if violation is not None:
            return violation
    return None


def _run_live_send_violation(run: dict[str, Any]) -> str | None:
    smoke_json = run.get("smoke_json")
    if not isinstance(smoke_json, str):
        return None
    payload = _read_json_file(Path(smoke_json))
    if payload is None:
        return None
    return _payload_live_send_violation(payload)


def _payload_live_send_violation(payload: dict[str, Any]) -> str | None:
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            violation = _live_send_command_violation(step.get("cmd"))
            if violation is not None:
                return violation
    violation = _live_send_command_violation(payload.get("_smoke_command"))
    if violation is not None:
        return violation
    gate = payload.get("alpha_release_gate") if isinstance(payload.get("alpha_release_gate"), dict) else {}
    checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
    if checks.get("live_send_not_executed") is False:
        return "live_send_executed_by_alpha_gate"
    stage_result = gate.get("stage_result") if isinstance(gate.get("stage_result"), dict) else {}
    evidence = stage_result.get("evidence") if isinstance(stage_result.get("evidence"), dict) else {}
    if evidence.get("live_send_executed") is True:
        return "live_send_executed_by_stage_result"
    return None


def _live_send_command_violation(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    tokens = [str(item) for item in command]
    normalized_tokens = {_normalize_command_token(token) for token in tokens}
    for token in tokens:
        if token in LIVE_SEND_COMMAND_TOKENS or _normalize_command_token(token) in {
            _normalize_command_token(forbidden) for forbidden in LIVE_SEND_COMMAND_TOKENS
        }:
            return f"live_send_command_present:{token}"
    if normalized_tokens.intersection({"live"}):
        return "live_send_mode_token_present"
    if "--send-mode" in tokens:
        index = tokens.index("--send-mode")
        if index + 1 < len(tokens) and tokens[index + 1] != "stage":
            return "non_stage_send_mode_present"
    return None


def _command_violation(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    tokens = [str(item) for item in command]
    forbidden_normalized = {_normalize_command_token(token) for token in FORBIDDEN_COMMAND_TOKENS}
    for token in tokens:
        if token in FORBIDDEN_COMMAND_TOKENS or _normalize_command_token(token) in forbidden_normalized:
            return f"forbidden_command_present:{token}"
    if "--send-mode" in tokens:
        index = tokens.index("--send-mode")
        if index + 1 < len(tokens) and tokens[index + 1] != "stage":
            return "non_stage_send_mode_present"
    return None


def _normalize_command_token(token: str) -> str:
    return token.strip().lower().replace("_", "-")


def _script_args(command: list[str]) -> list[str]:
    if len(command) >= 2 and command[1].endswith(".py"):
        return command[1:]
    return command


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _gate_env(env_file: Path | None) -> dict[str, str]:
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
