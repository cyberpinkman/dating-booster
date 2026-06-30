from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost import __version__
from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.runtime_scope import RuntimeScopeRepository, normalize_runtime
from dating_boost.core.safety import SafetyRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.core.user_disclosure import UserDisclosureRepository
from dating_boost.intelligence.backends import MINIMAX_DEFAULT_API_KEY_ENV, MINIMAX_DEFAULT_MODEL


BETA_SCHEMA_VERSION = 1
BETA_FEEDBACK_SCHEMA_VERSION = 1
BETA_SESSION_PATH = Path("beta") / "tashuo_stage_session.json"
BETA_REPORT_PATH = Path("beta") / "tashuo_stage_beta_report.json"
BETA_FEEDBACK_PATH = Path("beta") / "tashuo_stage_feedback.jsonl"
DEFAULT_WORK_DIR = Path(".local") / "dating-boost-tashuo-stage-beta"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALPHA_EVIDENCE_JSON = (
    ROOT
    / ".local"
    / "dating-boost-tashuo-stage-alpha-gate-20run-retry32"
    / "alpha_release_evidence.json"
)
DEFAULT_ALPHA_EVIDENCE_BUNDLE = (
    ROOT
    / ".local"
    / "dating-boost-tashuo-stage-alpha-gate-20run-retry32"
    / "alpha_release_evidence_bundle.zip"
)

STAGE_ONLY_ALLOWED_ACTIONS = {"send_message"}
FEEDBACK_STATUSES = {
    "accepted_as_is",
    "edited",
    "rejected",
    "unsafe",
    "off_tone",
    "wrong_target",
    "stale_context",
}
FORBIDDEN_BETA_COMMAND_TOKENS = {
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
RAW_FEEDBACK_KEYS = {
    "draft_text",
    "raw_draft",
    "raw_chat",
    "raw_conversation",
    "raw_profile",
    "screenshot",
    "screen",
    "clipboard",
    "clipboard_content",
    "profile_text",
    "visible_messages",
}


def beta_readiness(
    *,
    data_dir: Path,
    env_file: Path | None = None,
    minimax_api_key_env: str = MINIMAX_DEFAULT_API_KEY_ENV,
    alpha_evidence_json: Path | None = None,
    alpha_evidence_bundle: Path | None = None,
) -> dict[str, Any]:
    env = _merged_env(env_file)
    profile_readiness = UserDisclosureRepository(data_dir).readiness(mode="autonomous")
    runtime = RuntimeScopeRepository(data_dir).read()
    safety = SafetyRepository(data_dir).status()
    data_doctor = ProductionDataStore(data_dir).doctor()
    model_backend = {
        "backend": "minimax",
        "model": MINIMAX_DEFAULT_MODEL,
        "vision_backend": "minimax",
        "vision_model": MINIMAX_DEFAULT_MODEL,
        "api_key_env": minimax_api_key_env,
        "api_key_present": bool(env.get(minimax_api_key_env)),
    }
    alpha_gate = _last_alpha_gate(
        alpha_evidence_json=alpha_evidence_json or DEFAULT_ALPHA_EVIDENCE_JSON,
        alpha_evidence_bundle=alpha_evidence_bundle or DEFAULT_ALPHA_EVIDENCE_BUNDLE,
    )
    shareable_summary = _shareable_material_summary(profile_readiness)
    runtime_ok = _runtime_scope_ok(runtime)
    ready = (
        profile_readiness.get("ready") is True
        and runtime_ok
        and safety.get("paused") is not True
        and model_backend["api_key_present"] is True
        and data_doctor.get("status") == "ok"
    )
    run_blocked_count = len(failed_runs) + (0 if audit_summary["complete"] else 1)
    if run_payload.get("status") == "blocked" and not failed_runs and audit_summary["complete"]:
        run_blocked_count += 1
    return {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": "ok" if ready else "blocked",
        "reason": "ready" if ready else _readiness_block_reason(
            profile_readiness=profile_readiness,
            runtime_ok=runtime_ok,
            safety=safety,
            model_backend=model_backend,
            data_doctor=data_doctor,
        ),
        "ready": ready,
        "app_id": "tashuo",
        "required_runtime": "mac-ios-app",
        "profile_readiness": profile_readiness,
        "shareable_material": shareable_summary,
        "runtime": runtime or {"status": "not_found", "reason": "runtime_scope_not_selected"},
        "safety": safety,
        "backup_status": _backup_status(data_dir),
        "data_doctor": _doctor_summary(data_doctor),
        "model_backend": model_backend,
        "last_alpha_gate": alpha_gate,
    }


def start_tashuo_stage_beta(
    *,
    data_dir: Path,
    authorization_path: Path,
    work_dir: Path | None = None,
    env_file: Path | None = None,
    minimax_api_key_env: str = MINIMAX_DEFAULT_API_KEY_ENV,
    host: str = "codex",
) -> dict[str, Any]:
    work_dir = work_dir or DEFAULT_WORK_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    storage = JsonStorage(data_dir)
    steps: list[dict[str, Any]] = []
    env = _merged_env(env_file)
    authorization = _read_json_file(authorization_path)
    authorization_check = validate_stage_beta_authorization(authorization)
    if authorization_check.get("status") != "ok":
        return _start_blocked(
            authorization_check["reason"],
            data_dir=data_dir,
            work_dir=work_dir,
            authorization_check=authorization_check,
            steps=steps,
        )

    release = _run_cli(steps, ["release", "doctor", "--json"], env=env, name="release_doctor")
    if release.get("status") != "ok":
        return _start_blocked(str(release.get("reason") or "release_doctor_failed"), data_dir=data_dir, work_dir=work_dir, steps=steps)

    data_doctor = _run_cli(steps, ["data", "doctor", "--data-dir", str(data_dir), "--json"], env=env, name="data_doctor")
    if data_doctor.get("status") == "needs_migration":
        migrate = _run_cli(steps, ["data", "migrate", "--data-dir", str(data_dir), "--json"], env=env, name="data_migrate")
        if migrate.get("status") != "ok":
            return _start_blocked(str(migrate.get("reason") or "data_migrate_failed"), data_dir=data_dir, work_dir=work_dir, steps=steps)
        data_doctor = _run_cli(
            steps,
            ["data", "doctor", "--data-dir", str(data_dir), "--json"],
            env=env,
            name="data_doctor_after_migrate",
        )
    if data_doctor.get("status") != "ok":
        return _start_blocked(str(data_doctor.get("reason") or "data_doctor_failed"), data_dir=data_dir, work_dir=work_dir, steps=steps)

    capabilities = _run_cli(steps, ["capabilities", "--json", "--data-dir", str(data_dir)], env=env, name="capabilities")
    capabilities_check = _capabilities_check(capabilities)
    if capabilities_check is not None:
        return _start_blocked(capabilities_check, data_dir=data_dir, work_dir=work_dir, steps=steps)

    readiness = _run_cli(
        steps,
        ["user", "readiness", "--data-dir", str(data_dir), "--mode", "autonomous", "--json"],
        env=env,
        name="user_readiness_autonomous",
    )
    if readiness.get("ready") is not True:
        return _start_blocked(str(readiness.get("reason") or "needs_user_profile"), data_dir=data_dir, work_dir=work_dir, steps=steps)

    runtime_select = _run_cli(
        steps,
        [
            "runtime",
            "select",
            "--data-dir",
            str(data_dir),
            "--app-id",
            "tashuo",
            "--runtime",
            "mac-ios-app",
            "--json",
        ],
        env=env,
        name="runtime_select_mac_ios_app",
    )
    if runtime_select.get("status") != "selected":
        return _start_blocked(str(runtime_select.get("reason") or "runtime_scope_mismatch"), data_dir=data_dir, work_dir=work_dir, steps=steps)
    runtime_status = _run_cli(
        steps,
        ["runtime", "status", "--data-dir", str(data_dir), "--json"],
        env=env,
        name="runtime_status_mac_ios_app",
    )
    if not _runtime_scope_ok(runtime_status):
        return _start_blocked(str(runtime_status.get("reason") or "runtime_scope_mismatch"), data_dir=data_dir, work_dir=work_dir, steps=steps)

    safety = _run_cli(steps, ["safety", "status", "--data-dir", str(data_dir), "--json"], env=env, name="safety_status")
    if safety.get("paused") is True:
        return _start_blocked("safety_paused", data_dir=data_dir, work_dir=work_dir, steps=steps)

    if not env.get(minimax_api_key_env):
        return _start_blocked(f"{minimax_api_key_env}_missing", data_dir=data_dir, work_dir=work_dir, steps=steps)

    support = _run_cli(
        steps,
        [
            "support",
            "session",
            "start",
            "--data-dir",
            str(data_dir),
            "--host",
            host,
            "--app-id",
            "tashuo",
            "--json",
        ],
        env=env,
        name="support_session_start",
    )
    support_session_id = str(support.get("session_id") or "").strip()
    if support.get("status") != "active" or not support_session_id:
        return _start_blocked(str(support.get("reason") or "support_session_start_failed"), data_dir=data_dir, work_dir=work_dir, steps=steps)

    now = _now_iso()
    session = {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": "active",
        "reason": "tashuo_stage_beta_started",
        "session_id": f"beta_tashuo_stage_{_session_id_suffix(now)}",
        "app_id": "tashuo",
        "harness_runtime": "mac-ios-app",
        "send_mode": "stage",
        "management_mode": "conservative",
        "allowed_runtime_actions": ["observe", "open_ordinary_chat", "stage_draft", "clear_input"],
        "forbidden_actions": sorted(FORBIDDEN_BETA_COMMAND_TOKENS),
        "authorization_path": str(authorization_path),
        "authorization_id": authorization.get("authorization_id"),
        "data_dir": str(data_dir),
        "work_dir": str(work_dir),
        "support_session_id": support_session_id,
        "stage_result_count_at_start": _stage_result_count(data_dir),
        "stage_result_cursor": _stage_result_count(data_dir),
        "run_records": [],
        "started_at": now,
        "stopped_at": None,
        "last_run": None,
        "steps": steps,
    }
    storage.write_json(BETA_SESSION_PATH, session)
    report = _write_beta_report(
        data_dir=data_dir,
        work_dir=work_dir,
        session=session,
        run_payload=None,
        support_bundle_path=None,
    )
    return {
        **session,
        "report_path": str(data_dir / BETA_REPORT_PATH),
        "beta_report": report,
    }


def run_tashuo_stage_beta(
    *,
    data_dir: Path,
    runs: int = 1,
    work_dir: Path | None = None,
    env_file: Path | None = None,
    authorization_path: Path | None = None,
    initial_surface: str = "mixed",
    continue_on_failure: bool = False,
    vision_backend: str = "minimax",
    backend: str = "minimax",
    vision_model: str | None = None,
    model: str | None = None,
    scripted_vision_output: Path | None = None,
    scripted_backend_output: Path | None = None,
    minimax_api_key_env: str = MINIMAX_DEFAULT_API_KEY_ENV,
    minimax_base_url: str | None = None,
    minimax_request_timeout_seconds: float | None = None,
    max_ticks: int | None = None,
    step_timeout_seconds: float | None = None,
    smoke_timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if runs <= 0:
        return _blocked("beta_runs_must_be_positive")
    session = _read_session(data_dir)
    if not isinstance(session, dict) or session.get("status") != "active":
        return _blocked("tashuo_stage_beta_session_not_active")
    work_dir = work_dir or Path(str(session.get("work_dir") or DEFAULT_WORK_DIR))
    authorization_path = authorization_path or Path(str(session.get("authorization_path") or ""))
    authorization_check = validate_stage_beta_authorization(_read_json_file(authorization_path))
    if authorization_check.get("status") != "ok":
        return _blocked(authorization_check["reason"], authorization_check=authorization_check)
    runtime_block = RuntimeScopeRepository(data_dir).validate(app_id="tashuo", runtime="mac-ios-app", require_selected=True)
    if runtime_block is not None:
        return runtime_block
    if SafetyRepository(data_dir).is_paused():
        return _blocked("safety_paused")

    env = _merged_env(env_file)
    if (backend == "minimax" or vision_backend == "minimax") and not env.get(minimax_api_key_env):
        return _blocked(f"{minimax_api_key_env}_missing")

    run_started_at = _now_iso()
    stage_result_start_index = int(session.get("stage_result_cursor", session.get("stage_result_count_at_start") or 0) or 0)
    run_dir = work_dir / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "dating_boost.cli",
        "release",
        "gate",
        "tashuo-stage-alpha",
        "--data-dir",
        str(data_dir),
        "--work-dir",
        str(run_dir),
        "--authorization",
        str(authorization_path),
        "--runs",
        str(runs),
        "--initial-surface",
        initial_surface,
        "--vision-backend",
        vision_backend,
        "--backend",
        backend,
        "--minimax-api-key-env",
        minimax_api_key_env,
        "--json",
    ]
    support_session_id = str(session.get("support_session_id") or "").strip()
    if support_session_id:
        cmd.extend(["--support-session-id", support_session_id])
    if env_file is not None:
        cmd.extend(["--env-file", str(env_file)])
    if continue_on_failure:
        cmd.append("--continue-on-failure")
    if vision_model is not None:
        cmd.extend(["--vision-model", vision_model])
    if model is not None:
        cmd.extend(["--model", model])
    if scripted_vision_output is not None:
        cmd.extend(["--scripted-vision-output", str(scripted_vision_output)])
    if scripted_backend_output is not None:
        cmd.extend(["--scripted-backend-output", str(scripted_backend_output)])
    if minimax_base_url is not None:
        cmd.extend(["--minimax-base-url", minimax_base_url])
    if minimax_request_timeout_seconds is not None:
        cmd.extend(["--minimax-request-timeout-seconds", str(minimax_request_timeout_seconds)])
    if max_ticks is not None:
        cmd.extend(["--max-ticks", str(max_ticks)])
    if step_timeout_seconds is not None:
        cmd.extend(["--step-timeout-seconds", str(step_timeout_seconds)])
    if smoke_timeout_seconds is not None:
        cmd.extend(["--smoke-timeout-seconds", str(smoke_timeout_seconds)])

    token_violation = _command_token_violation(cmd)
    if token_violation is not None:
        return _blocked(token_violation)
    result = _run_system_json(cmd, env=env, timeout=float(smoke_timeout_seconds or 1800.0))
    run_payload = result["payload"]
    run_payload["_returncode"] = result["returncode"]
    run_payload["_command"] = _safe_command_args(cmd)
    stage_results = _read_stage_results(data_dir)
    stage_result_end_index = len(stage_results)
    run_stage_results = stage_results[stage_result_start_index:stage_result_end_index]
    run_record = _build_run_record(
        run_payload=run_payload,
        run_dir=run_dir,
        started_at=run_started_at,
        completed_at=_now_iso(),
        stage_result_start_index=stage_result_start_index,
        stage_result_end_index=stage_result_end_index,
        stage_results=run_stage_results,
        runs_requested=runs,
    )
    run_records = session.get("run_records") if isinstance(session.get("run_records"), list) else []
    run_records.append(run_record)
    session["run_records"] = run_records
    session["stage_result_cursor"] = stage_result_end_index
    session["last_run"] = {
        "status": run_record.get("status"),
        "reason": run_record.get("reason"),
        "runs_requested": runs,
        "runs_passed": run_payload.get("runs_passed"),
        "run_dir": str(run_dir),
        "completed_at": run_record.get("completed_at"),
    }
    JsonStorage(data_dir).write_json(BETA_SESSION_PATH, session)
    report = _write_beta_report(
        data_dir=data_dir,
        work_dir=work_dir,
        session=session,
        run_payload=run_payload,
        support_bundle_path=run_payload.get("support_bundle_path"),
    )
    audit_complete = bool(run_record.get("audit_summary", {}).get("complete")) if isinstance(run_record.get("audit_summary"), dict) else False
    run_ok = run_record.get("status") == "ok" and audit_complete and run_record.get("live_send_execution_count") == 0 and run_record.get("high_risk_action_count") == 0
    return {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": "ok" if run_ok else "blocked",
        "reason": "tashuo_stage_beta_run_complete"
        if run_ok
        else ("beta_stage_audit_incomplete" if not audit_complete else str(run_payload.get("reason") or "tashuo_stage_beta_run_failed")),
        "session_id": session.get("session_id"),
        "run": _gate_run_summary(run_payload) | {"stage_result_count": run_record.get("stage_result_count")},
        "beta_report": report,
        "beta_report_path": str(data_dir / BETA_REPORT_PATH),
    }


def status_tashuo_stage_beta(*, data_dir: Path) -> dict[str, Any]:
    session = _read_session(data_dir)
    report = _read_json_optional(data_dir / BETA_REPORT_PATH)
    if not isinstance(session, dict):
        return {"schema_version": BETA_SCHEMA_VERSION, "status": "not_found", "reason": "tashuo_stage_beta_session_not_found"}
    return {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": session.get("status"),
        "session": session,
        "beta_report": report,
    }


def stop_tashuo_stage_beta(
    *,
    data_dir: Path,
    work_dir: Path | None = None,
    reason: str = "manual_stop",
    env_file: Path | None = None,
) -> dict[str, Any]:
    session = _read_session(data_dir)
    if not isinstance(session, dict):
        return {"schema_version": BETA_SCHEMA_VERSION, "status": "not_found", "reason": "tashuo_stage_beta_session_not_found"}
    work_dir = work_dir or Path(str(session.get("work_dir") or DEFAULT_WORK_DIR))
    work_dir.mkdir(parents=True, exist_ok=True)
    env = _merged_env(env_file)
    steps: list[dict[str, Any]] = []
    support_session_id = str(session.get("support_session_id") or "").strip()
    support_bundle_path: str | None = None
    if support_session_id:
        _run_cli(
            steps,
            ["support", "session", "stop", "--data-dir", str(data_dir), "--session-id", support_session_id, "--json"],
            env=env,
            name="support_session_stop",
            allow_failure=True,
        )
        bundle_path = work_dir / "dating-boost-beta-support-strict.zip"
        support_bundle = _run_cli(
            steps,
            [
                "support",
                "bundle",
                "--data-dir",
                str(data_dir),
                "--session-id",
                support_session_id,
                "--output",
                str(bundle_path),
                "--redaction",
                "strict",
                "--json",
            ],
            env=env,
            name="support_bundle_strict",
            allow_failure=True,
        )
        if support_bundle.get("status") == "ok":
            support_bundle_path = str(support_bundle.get("output") or bundle_path)
            session["support_bundle_path"] = support_bundle_path
    session["status"] = "stopped"
    session["reason"] = reason
    session["stopped_at"] = _now_iso()
    session.setdefault("stop_steps", []).extend(steps)
    JsonStorage(data_dir).write_json(BETA_SESSION_PATH, session)
    report = _write_beta_report(
        data_dir=data_dir,
        work_dir=work_dir,
        session=session,
        run_payload=None,
        support_bundle_path=support_bundle_path,
    )
    return {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": "stopped",
        "reason": reason,
        "session_id": session.get("session_id"),
        "support_bundle_path": support_bundle_path,
        "beta_report_path": str(data_dir / BETA_REPORT_PATH),
        "beta_report": report,
    }


def report_tashuo_stage_beta(*, data_dir: Path, format: str = "json") -> dict[str, Any] | str:
    report = _read_json_optional(data_dir / BETA_REPORT_PATH)
    if not isinstance(report, dict):
        payload = {"schema_version": BETA_SCHEMA_VERSION, "status": "not_found", "reason": "tashuo_stage_beta_report_not_found"}
        return _human_report(payload) if format == "md" else payload
    if format == "md":
        return _human_report(report)
    return report


def record_stage_beta_feedback(*, data_dir: Path, feedback: dict[str, Any]) -> dict[str, Any]:
    raw_key = _raw_feedback_key(feedback)
    if raw_key is not None:
        return _blocked("beta_feedback_raw_sensitive_content_not_allowed", raw_key=raw_key)
    status = str(feedback.get("status") or "").strip()
    if status not in FEEDBACK_STATUSES:
        return _blocked("invalid_beta_feedback_status", allowed_statuses=sorted(FEEDBACK_STATUSES))
    target_match_id = str(feedback.get("target_match_id") or "").strip()
    draft_hash = str(feedback.get("staged_draft_hash") or feedback.get("draft_hash") or "").strip()
    if not target_match_id:
        return _blocked("beta_feedback_target_match_id_required")
    if not draft_hash:
        return _blocked("beta_feedback_staged_draft_hash_required")
    event = {
        "schema_version": BETA_FEEDBACK_SCHEMA_VERSION,
        "event_id": f"beta_feedback_{_digest({'target_match_id': target_match_id, 'draft_hash': draft_hash, 'status': status})[:16]}",
        "status": status,
        "target_match_id": target_match_id,
        "staged_draft_hash": draft_hash,
        "action_request_id": feedback.get("action_request_id"),
        "stage_event_id": feedback.get("stage_event_id"),
        "created_at": _now_iso(),
    }
    for optional in ("reason_code", "edited_draft_hash", "context_hash"):
        if feedback.get(optional) is not None:
            event[optional] = feedback[optional]
    JsonStorage(data_dir).append_jsonl(BETA_FEEDBACK_PATH, event)
    return {
        "schema_version": BETA_FEEDBACK_SCHEMA_VERSION,
        "status": "ok",
        "reason": "beta_feedback_recorded",
        "event": event,
        "path": str(BETA_FEEDBACK_PATH),
    }


def validate_stage_beta_authorization(authorization: dict[str, Any]) -> dict[str, Any]:
    allowed_actions = set(authorization.get("allowed_actions") or [])
    if authorization.get("app_id") != "tashuo":
        return _blocked("beta_authorization_app_id_must_be_tashuo")
    if authorization.get("live_send") is not False:
        return _blocked("beta_authorization_live_send_must_be_false")
    if authorization.get("autonomous_send") is not True:
        return _blocked("beta_authorization_autonomous_send_must_be_true")
    if authorization.get("revoked_at"):
        return _blocked("beta_authorization_revoked")
    expiration_check = _authorization_expiration_block_reason(authorization)
    if expiration_check is not None:
        return _blocked(expiration_check)
    if allowed_actions != STAGE_ONLY_ALLOWED_ACTIONS:
        return _blocked(
            "beta_authorization_allowed_actions_must_be_send_message_only",
            allowed_actions=sorted(allowed_actions),
        )
    if authorization.get("scope") != "send_chat_messages":
        return _blocked("beta_authorization_scope_must_be_send_chat_messages")
    return {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": "ok",
        "reason": "stage_only_beta_authorization_valid",
        "authorization_id": authorization.get("authorization_id"),
    }


def _build_run_record(
    *,
    run_payload: dict[str, Any],
    run_dir: Path,
    started_at: str,
    completed_at: str,
    stage_result_start_index: int,
    stage_result_end_index: int,
    stage_results: list[dict[str, Any]],
    runs_requested: int,
) -> dict[str, Any]:
    smoke_runs = run_payload.get("smoke_runs") if isinstance(run_payload.get("smoke_runs"), list) else []
    audit_summary = _audit_summary(smoke_runs, stage_results)
    zero_live_send = _zero_live_send(run_payload)
    zero_high_risk = not run_payload.get("command_safety_violation")
    failure_reasons = _failure_reason_counts(smoke_runs, run_payload)
    if not audit_summary["complete"]:
        failure_reasons["beta_stage_audit_incomplete"] = failure_reasons.get("beta_stage_audit_incomplete", 0) + 1
    if not zero_live_send:
        failure_reasons["live_send_execution_not_ruled_out"] = failure_reasons.get("live_send_execution_not_ruled_out", 0) + 1
    if not zero_high_risk:
        failure_reasons["high_risk_action_detected"] = failure_reasons.get("high_risk_action_detected", 0) + 1
    run_ok = run_payload.get("status") == "ok" and audit_summary["complete"] and zero_live_send and zero_high_risk
    failed_runs = [run for run in smoke_runs if isinstance(run, dict) and run.get("status") != "ok"]
    run_blocked_count = len(failed_runs) + (0 if audit_summary["complete"] else 1)
    if run_payload.get("status") == "blocked" and not failed_runs and audit_summary["complete"]:
        run_blocked_count += 1
    return {
        "schema_version": BETA_SCHEMA_VERSION,
        "run_id": f"beta_run_{_digest({'run_dir': str(run_dir), 'started_at': started_at})[:16]}",
        "status": "ok" if run_ok else "blocked",
        "reason": "tashuo_stage_beta_run_complete"
        if run_ok
        else ("beta_stage_audit_incomplete" if not audit_summary["complete"] else str(run_payload.get("reason") or "tashuo_stage_beta_run_failed")),
        "started_at": started_at,
        "completed_at": completed_at,
        "run_dir": str(run_dir),
        "stage_result_start_index": stage_result_start_index,
        "stage_result_end_index": stage_result_end_index,
        "stage_result_count": len(stage_results),
        "runs_requested": runs_requested,
        "runs_required": run_payload.get("runs_required"),
        "runs_completed": run_payload.get("runs_completed"),
        "runs_passed": run_payload.get("runs_passed"),
        "initial_surface": run_payload.get("initial_surface"),
        "failure_reasons": failure_reasons,
        "blocked_count": run_blocked_count,
        "audit_summary": audit_summary,
        "target_verification_summary": _target_verification_summary(smoke_runs, stage_results),
        "support_bundle_path": run_payload.get("support_bundle_path"),
        "evidence_bundle_path": run_payload.get("evidence_bundle_path") or run_payload.get("evidence_bundle"),
        "live_send_execution_count": 0 if zero_live_send else 1,
        "high_risk_action_count": 0 if zero_high_risk else 1,
        "run_summary": _gate_run_summary(run_payload),
    }


def _write_beta_report(
    *,
    data_dir: Path,
    work_dir: Path,
    session: dict[str, Any],
    run_payload: dict[str, Any] | None,
    support_bundle_path: str | None,
) -> dict[str, Any]:
    records = _run_records(session)
    run_payload = run_payload if isinstance(run_payload, dict) else {}
    aggregate = _aggregate_run_records(records)
    support_bundle_path = support_bundle_path or session.get("support_bundle_path") or aggregate.get("support_bundle_path") or _latest_support_bundle_path(run_payload)
    report_status = "ok" if aggregate["ok"] else "blocked"
    report = {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": report_status,
        "reason": run_payload.get("reason") or session.get("reason") or "tashuo_stage_beta_report",
        "app_id": "tashuo",
        "harness_runtime": "mac-ios-app",
        "send_mode": "stage",
        "management_mode": "conservative",
        "session_id": session.get("session_id"),
        "started_at": session.get("started_at"),
        "stopped_at": session.get("stopped_at"),
        "staged_count": aggregate["staged_count"],
        "blocked_count": aggregate["blocked_count"],
        "failure_reasons": aggregate["failure_reasons"],
        "queue_summary": {
            "bounded": True,
            "runs_requested": aggregate["runs_requested"],
            "runs_completed": aggregate["runs_completed"],
            "runs_passed": aggregate["runs_passed"],
            "initial_surface": aggregate["initial_surface"],
            "allowed_runtime_actions": session.get("allowed_runtime_actions") or [],
        },
        "target_verification_summary": aggregate["target_verification_summary"],
        "draft_review_summary": _draft_review_summary(data_dir),
        "audit_summary": aggregate["audit_summary"],
        "support_bundle_path": support_bundle_path,
        "evidence_bundle_path": aggregate.get("evidence_bundle_path") or run_payload.get("evidence_bundle_path") or run_payload.get("evidence_bundle"),
        "live_send_execution_count": aggregate["live_send_execution_count"],
        "high_risk_action_count": aggregate["high_risk_action_count"],
        "feedback_summary": _feedback_summary(data_dir),
        "run_records": records,
        "user_summary": _user_summary(stage_count=aggregate["staged_count"], failure_reasons=aggregate["failure_reasons"]),
    }
    JsonStorage(data_dir).write_json(BETA_REPORT_PATH, report)
    (work_dir / "beta_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _run_records(session: dict[str, Any]) -> list[dict[str, Any]]:
    records = session.get("run_records")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _aggregate_run_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    failure_reasons: dict[str, int] = {}
    target_summary = {"smoke_target_verified": 0, "smoke_target_blocked": 0, "audit_target_verified": 0}
    audit_missing: list[str] = []
    stage_result_count = 0
    blocked_count = 0
    runs_requested = 0
    runs_completed = 0
    runs_passed = 0
    live_send_execution_count = 0
    high_risk_action_count = 0
    initial_surfaces: list[str] = []
    support_bundle_path: str | None = None
    evidence_bundle_path: str | None = None
    all_ok = True

    for index, record in enumerate(records, start=1):
        if record.get("status") != "ok":
            all_ok = False
        stage_result_count += _int_value(record.get("stage_result_count"))
        blocked_count += _int_value(record.get("blocked_count"))
        runs_requested += _int_value(record.get("runs_requested") or record.get("runs_required"))
        runs_completed += _int_value(record.get("runs_completed"))
        runs_passed += _int_value(record.get("runs_passed"))
        live_send_execution_count += _int_value(record.get("live_send_execution_count"))
        high_risk_action_count += _int_value(record.get("high_risk_action_count"))
        if isinstance(record.get("initial_surface"), str) and record["initial_surface"] not in initial_surfaces:
            initial_surfaces.append(record["initial_surface"])
        if isinstance(record.get("support_bundle_path"), str) and record["support_bundle_path"]:
            support_bundle_path = record["support_bundle_path"]
        if isinstance(record.get("evidence_bundle_path"), str) and record["evidence_bundle_path"]:
            evidence_bundle_path = record["evidence_bundle_path"]
        _merge_counts(failure_reasons, record.get("failure_reasons"))
        summary = record.get("target_verification_summary") if isinstance(record.get("target_verification_summary"), dict) else {}
        for key in target_summary:
            target_summary[key] += _int_value(summary.get(key))
        audit = record.get("audit_summary") if isinstance(record.get("audit_summary"), dict) else {}
        if audit.get("complete") is not True:
            all_ok = False
        for item in audit.get("missing") if isinstance(audit.get("missing"), list) else []:
            audit_missing.append(f"run[{index}].{item}")

    return {
        "ok": all_ok,
        "staged_count": stage_result_count,
        "blocked_count": blocked_count,
        "failure_reasons": failure_reasons,
        "runs_requested": runs_requested,
        "runs_completed": runs_completed,
        "runs_passed": runs_passed,
        "initial_surface": ",".join(initial_surfaces) if initial_surfaces else None,
        "target_verification_summary": target_summary,
        "audit_summary": {
            "stage_result_count": stage_result_count,
            "complete": not audit_missing,
            "missing": audit_missing[:50],
            "truncated": len(audit_missing) > 50,
        },
        "support_bundle_path": support_bundle_path,
        "evidence_bundle_path": evidence_bundle_path,
        "live_send_execution_count": live_send_execution_count,
        "high_risk_action_count": high_risk_action_count,
    }


def _merge_counts(target: dict[str, int], value: Any) -> None:
    if not isinstance(value, dict):
        return
    for key, count in value.items():
        target[str(key)] = target.get(str(key), 0) + _int_value(count)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _run_cli(
    steps: list[dict[str, Any]],
    args: list[str],
    *,
    env: dict[str, str],
    name: str,
    allow_failure: bool = False,
) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "dating_boost.cli", *args]
    result = _run_system_json(cmd, env=env, timeout=300.0)
    payload = result["payload"]
    payload["_returncode"] = result["returncode"]
    steps.append(_step(name, args, payload))
    if result["returncode"] != 0 and not allow_failure:
        payload.setdefault("status", "blocked")
        payload.setdefault("reason", f"{name}_failed")
    return payload


def _run_system_json(cmd: list[str], *, env: dict[str, str], timeout: float) -> dict[str, Any]:
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
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "payload": {
                "schema_version": BETA_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "beta_command_timeout",
                "error_type": "TimeoutExpired",
                "error_message": _truncate(str(exc)),
            },
        }
    payload = _json_or_empty(result.stdout)
    if not payload:
        payload = {
            "schema_version": BETA_SCHEMA_VERSION,
            "status": "blocked",
            "reason": "beta_command_non_json_output",
            "stderr": _truncate(result.stderr),
        }
    return {"returncode": result.returncode, "payload": payload}


def _step(name: str, cmd: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "cmd": cmd,
        "returncode": payload.get("_returncode"),
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "summary": _summary(payload),
    }


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload[key]
        for key in (
            "status",
            "reason",
            "schema_version",
            "ready",
            "missing",
            "paused",
            "app_id",
            "selected_app_id",
            "selected_runtime",
            "session_id",
            "output",
            "redaction",
        )
        if key in payload
    }


def _start_blocked(
    reason: str,
    *,
    data_dir: Path,
    work_dir: Path,
    steps: list[dict[str, Any]],
    authorization_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": BETA_SCHEMA_VERSION,
        "status": "blocked",
        "reason": reason,
        "app_id": "tashuo",
        "harness_runtime": "mac-ios-app",
        "send_mode": "stage",
        "data_dir": str(data_dir),
        "work_dir": str(work_dir),
        "authorization_check": authorization_check,
        "steps": steps,
        "next_host_action": "fix_beta_preflight_blocker_then_restart",
    }
    return payload


def _blocked(reason: str, **extras: Any) -> dict[str, Any]:
    payload = {"schema_version": BETA_SCHEMA_VERSION, "status": "blocked", "reason": reason}
    payload.update(extras)
    return payload


def _capabilities_check(payload: dict[str, Any]) -> str | None:
    if payload.get("schema_version") != 1:
        return "capabilities_schema_version_unsupported"
    if "tashuo" not in list(payload.get("supported_app_profiles") or []):
        return "tashuo_profile_not_supported"
    native = payload.get("agent_native_capabilities") if isinstance(payload.get("agent_native_capabilities"), dict) else {}
    if native.get("tashuo_mac_ios_app_runtime") is not True:
        return "tashuo_mac_ios_app_runtime_not_supported"
    guidance = payload.get("managed_live_send_guidance") if isinstance(payload.get("managed_live_send_guidance"), dict) else {}
    if guidance.get("direct_harness_scope") != "executor_internal_only":
        return "direct_harness_scope_not_executor_internal_only"
    return None


def _runtime_scope_ok(runtime: dict[str, Any] | None) -> bool:
    if not isinstance(runtime, dict) or runtime.get("status") != "selected":
        return False
    return runtime.get("selected_app_id") == "tashuo" and normalize_runtime(runtime.get("selected_runtime_key") or runtime.get("selected_runtime")) == "mac_ios_app"


def _readiness_block_reason(
    *,
    profile_readiness: dict[str, Any],
    runtime_ok: bool,
    safety: dict[str, Any],
    model_backend: dict[str, Any],
    data_doctor: dict[str, Any],
) -> str:
    if data_doctor.get("status") != "ok":
        return str(data_doctor.get("status") or data_doctor.get("reason") or "data_doctor_not_ok")
    if profile_readiness.get("ready") is not True:
        return str(profile_readiness.get("reason") or "needs_user_profile")
    if not runtime_ok:
        return "runtime_scope_mismatch"
    if safety.get("paused") is True:
        return "safety_paused"
    if model_backend.get("api_key_present") is not True:
        return f"{model_backend.get('api_key_env')}_missing"
    return "beta_readiness_incomplete"


def _shareable_material_summary(profile_readiness: dict[str, Any]) -> dict[str, Any]:
    profile = profile_readiness.get("profile") if isinstance(profile_readiness.get("profile"), dict) else {}
    materials = profile.get("shareable_material") if isinstance(profile.get("shareable_material"), list) else []
    low_risk = [
        item
        for item in materials
        if isinstance(item, dict)
        and item.get("text")
        and item.get("risk_level", item.get("sensitivity", "low")) == "low"
        and item.get("sensitivity", "low") in {"low", "medium"}
    ]
    repair = [
        item
        for item in materials
        if isinstance(item, dict) and "low_investment_repair" in list(item.get("usable_moves") or [])
    ]
    date_pref = [
        item
        for item in materials
        if isinstance(item, dict)
        and any(str(tag).lower() in {"date", "meeting", "logistics", "date_preference"} for tag in list(item.get("tags") or []))
    ]
    return {
        "count": len(materials),
        "low_risk_count": len(low_risk),
        "low_investment_repair_count": len(repair),
        "date_preference_count": len(date_pref),
    }


def _backup_status(data_dir: Path) -> dict[str, Any]:
    candidates = sorted(data_dir.glob("*.zip")) + sorted((data_dir / "backups").glob("*.zip"))
    latest = candidates[-1] if candidates else None
    return {
        "status": "available" if latest is not None else "not_found",
        "latest_backup_path": str(latest) if latest is not None else None,
        "backup_required_before_beta": True,
    }


def _doctor_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in ("schema_version", "status", "storage_backend", "db_path") if key in payload}


def _last_alpha_gate(*, alpha_evidence_json: Path, alpha_evidence_bundle: Path) -> dict[str, Any]:
    source = alpha_evidence_json if alpha_evidence_json.is_file() else None
    if source is None and alpha_evidence_bundle.is_file():
        try:
            with zipfile.ZipFile(alpha_evidence_bundle) as archive:
                payload = json.loads(archive.read("alpha_release_evidence.json").decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"status": "blocked", "reason": "alpha_gate_evidence_unreadable", "error_type": type(exc).__name__}
    elif source is not None:
        payload = _read_json_file(source)
    else:
        return {"status": "not_found", "reason": "alpha_gate_evidence_not_found"}
    return {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "runs_required": payload.get("runs_required"),
        "runs_passed": payload.get("runs_passed"),
        "evidence_json": str(source) if source is not None else None,
        "evidence_bundle": str(alpha_evidence_bundle) if alpha_evidence_bundle.is_file() else payload.get("evidence_bundle"),
        "support_bundle_path": payload.get("support_bundle_path"),
    }


def _read_session(data_dir: Path) -> dict[str, Any] | None:
    return _read_json_optional(data_dir / BETA_SESSION_PATH)


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    parsed = _read_json_file(path)
    return parsed if isinstance(parsed, dict) else None


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _read_stage_results(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "audit" / "stage_results.jsonl"
    if not path.is_file():
        return []
    results: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            results.append(parsed)
    return results


def _stage_result_count(data_dir: Path) -> int:
    return len(_read_stage_results(data_dir))


def _failure_reason_counts(smoke_runs: list[Any], run_payload: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if run_payload.get("status") == "blocked" and run_payload.get("reason"):
        counts[str(run_payload["reason"])] = counts.get(str(run_payload["reason"]), 0) + 1
    for run in smoke_runs:
        if isinstance(run, dict) and run.get("status") != "ok":
            reason = str(run.get("reason") or "unknown_failure")
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def _target_verification_summary(smoke_runs: list[Any], stage_results: list[dict[str, Any]]) -> dict[str, Any]:
    smoke_ok = 0
    smoke_blocked = 0
    for run in smoke_runs:
        if not isinstance(run, dict):
            continue
        gate = run.get("alpha_release_gate") if isinstance(run.get("alpha_release_gate"), dict) else {}
        checks = gate.get("checks") if isinstance(gate.get("checks"), dict) else {}
        if checks.get("target_verified") is True:
            smoke_ok += 1
        else:
            smoke_blocked += 1
    audit_ok = sum(1 for event in stage_results if isinstance(event.get("target_verification"), dict) and event["target_verification"].get("status") == "ok")
    return {"smoke_target_verified": smoke_ok, "smoke_target_blocked": smoke_blocked, "audit_target_verified": audit_ok}


def _draft_review_summary(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "audit" / "draft_reviews.jsonl"
    if not path.is_file():
        return {"status": "not_found", "count": 0}
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return {"status": "available", "count": count, "path": "audit/draft_reviews.jsonl"}


def _audit_summary(smoke_runs: list[Any], stage_results: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[str] = []
    for index, event in enumerate(stage_results, start=1):
        for key in (
            "action_request_id",
            "target_match_id",
            "payload_hash",
            "precondition_hash",
            "target_verification",
            "staged_text_verification",
            "stage_attempt_status",
        ):
            if key not in event or event.get(key) in (None, ""):
                missing.append(f"stage_result[{index}].{key}")
        final_cleanup = _smoke_final_input_for_binding(smoke_runs, event)
        if final_cleanup.get("input_cleared") is not True:
            missing.append(f"stage_result[{index}].final_input_cleanup")
    return {"stage_result_count": len(stage_results), "complete": not missing, "missing": missing[:50], "truncated": len(missing) > 50}


def _smoke_final_input_for_binding(smoke_runs: list[Any], event: dict[str, Any]) -> dict[str, Any]:
    for run in smoke_runs:
        if not isinstance(run, dict):
            continue
        binding = run.get("stage_binding") if isinstance(run.get("stage_binding"), dict) else {}
        if all(event.get(key) == binding.get(key) for key in ("action_request_id", "target_match_id", "payload_hash")):
            return run.get("final_input_verification") if isinstance(run.get("final_input_verification"), dict) else {}
    return {}


def _feedback_summary(data_dir: Path) -> dict[str, Any]:
    path = data_dir / BETA_FEEDBACK_PATH
    if not path.is_file():
        return {"status": "not_found", "count": 0, "by_status": {}}
    counts: dict[str, int] = {}
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = str(event.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        total += 1
    return {"status": "available", "count": total, "by_status": counts}


def _user_summary(*, stage_count: int, failure_reasons: dict[str, int]) -> dict[str, Any]:
    failures = failure_reasons
    staged = stage_count
    blocked = sum(failures.values())
    return {
        "processed_targets": staged + blocked,
        "staged_pending_user_confirmation": staged,
        "failed_or_blocked": blocked,
        "next_recommendation": "review_staged_drafts" if staged else "fix_blockers_or_continue_bounded_run",
    }


def _zero_live_send(run_payload: dict[str, Any]) -> bool:
    checks = run_payload.get("checks") if isinstance(run_payload.get("checks"), dict) else {}
    if "zero_live_send_execution" in checks:
        return checks.get("zero_live_send_execution") is True
    return run_payload.get("status") in {None, "ok"}


def _latest_support_bundle_path(run_payload: dict[str, Any]) -> str | None:
    path = run_payload.get("support_bundle_path")
    if isinstance(path, str) and path:
        return path
    support_bundle = run_payload.get("support_bundle") if isinstance(run_payload.get("support_bundle"), dict) else {}
    output = support_bundle.get("output")
    return str(output) if output else None


def _gate_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "reason": payload.get("reason"),
        "runs_required": payload.get("runs_required"),
        "runs_completed": payload.get("runs_completed"),
        "runs_passed": payload.get("runs_passed"),
        "support_bundle_path": payload.get("support_bundle_path"),
        "evidence_bundle_path": payload.get("evidence_bundle_path") or payload.get("evidence_bundle"),
    }


def _command_token_violation(cmd: list[str]) -> str | None:
    tokens = {str(token) for token in cmd}
    violation = sorted(tokens & FORBIDDEN_BETA_COMMAND_TOKENS)
    if violation:
        return f"beta_forbidden_command_token:{violation[0]}"
    return None


def _safe_command_args(cmd: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for token in cmd:
        if skip_next:
            redacted.append("[redacted]")
            skip_next = False
            continue
        redacted.append(str(token))
        if token in {"--authorization", "--env-file", "--scripted-backend-output", "--scripted-vision-output"}:
            skip_next = True
    return redacted


def _raw_feedback_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in RAW_FEEDBACK_KEYS:
                return str(key)
            nested = _raw_feedback_key(item)
            if nested is not None:
                return nested
    if isinstance(value, list):
        for item in value:
            nested = _raw_feedback_key(item)
            if nested is not None:
                return nested
    return None


def _merged_env(env_file: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if env_file is not None and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def _json_or_empty(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _human_report(report: dict[str, Any]) -> str:
    if report.get("status") == "not_found":
        return "TaShuo stage beta report not found."
    user_summary = report.get("user_summary") if isinstance(report.get("user_summary"), dict) else {}
    failures = report.get("failure_reasons") if isinstance(report.get("failure_reasons"), dict) else {}
    lines = [
        "# TaShuo Stage-only Beta Report",
        "",
        f"- Status: {report.get('status')}",
        f"- Session: {report.get('session_id')}",
        f"- Staged pending user confirmation: {user_summary.get('staged_pending_user_confirmation', report.get('staged_count'))}",
        f"- Failed or blocked: {user_summary.get('failed_or_blocked', report.get('blocked_count'))}",
        f"- Live-send executions: {report.get('live_send_execution_count')}",
        f"- High-risk actions: {report.get('high_risk_action_count')}",
        f"- Support bundle: {report.get('support_bundle_path')}",
        f"- Evidence bundle: {report.get('evidence_bundle_path')}",
    ]
    if failures:
        lines.append("- Failure reasons: " + ", ".join(f"{key}={value}" for key, value in sorted(failures.items())))
    return "\n".join(lines)


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _session_id_suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _authorization_expiration_block_reason(authorization: dict[str, Any]) -> str | None:
    expires_at = authorization.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at.strip():
        return "beta_authorization_expires_at_required"
    try:
        expires = _parse_iso(expires_at)
    except ValueError:
        return "beta_authorization_invalid_expires_at"
    if expires <= datetime.now(timezone.utc):
        return "beta_authorization_expired"
    return None


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _truncate(value: Any, limit: int = 800) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."
