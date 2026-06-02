#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "intelligence"
AUTOMATION_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "automation"
SKILL_PACKAGE_PATH = ROOT / "skills" / "dating-booster-codex" / "skill-package.json"
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-smoke"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the agent-native Dating Booster fixture workflow end to end.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Local Dating Booster data directory. Defaults to .local/dating-boost-smoke.",
    )
    args = parser.parse_args(argv)

    return _run_smoke(args.data_dir or DEFAULT_DATA_DIR)


def _run_smoke(data_dir: Path) -> int:
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    commands: dict[str, int] = {}

    skill_doctor = _run_cli(
        "skill",
        "doctor",
        "--package",
        str(SKILL_PACKAGE_PATH),
        "--data-dir",
        str(data_dir),
        "--json",
        command_key="skill_doctor",
        commands=commands,
    )
    data_doctor_initial = _run_cli(
        "data",
        "doctor",
        "--data-dir",
        str(data_dir),
        "--json",
        command_key="data_doctor_initial",
        commands=commands,
    )
    data_migration = _run_cli(
        "data",
        "migrate",
        "--data-dir",
        str(data_dir),
        "--json",
        command_key="data_migrate",
        commands=commands,
    )
    data_doctor = _run_cli(
        "data",
        "doctor",
        "--data-dir",
        str(data_dir),
        "--json",
        command_key="data_doctor",
        commands=commands,
    )
    capabilities = _run_cli(
        "capabilities",
        "--json",
        "--data-dir",
        str(data_dir),
        command_key="capabilities",
        commands=commands,
    )
    compatibility = _check_compatibility(capabilities)
    _run_cli(
        "init-profile",
        "--data-dir",
        str(data_dir),
        "--input",
        str(FIXTURE_DIR / "user_profile.json"),
        command_key="init_profile",
        commands=commands,
    )
    _run_cli(
        "user",
        "ingest-profile",
        "--data-dir",
        str(data_dir),
        "--input",
        str(FIXTURE_DIR / "user_dating_profile.json"),
        command_key="user_ingest_profile",
        commands=commands,
    )
    _run_cli(
        "user",
        "ingest-interview",
        "--data-dir",
        str(data_dir),
        "--input",
        str(FIXTURE_DIR / "user_self_interview.json"),
        command_key="user_ingest_interview",
        commands=commands,
    )
    _run_cli(
        "user",
        "readiness",
        "--data-dir",
        str(data_dir),
        "--mode",
        "autonomous",
        "--json",
        command_key="user_readiness",
        commands=commands,
    )
    ingest = _run_cli(
        "memory",
        "ingest-observation",
        "--data-dir",
        str(data_dir),
        "--input",
        str(FIXTURE_DIR / "app_observation_chat.json"),
        command_key="memory_ingest_observation",
        commands=commands,
    )
    match_id = str(ingest["match_id"])
    planner_assessment_path = data_dir / "planner_assessment.json"
    _write_json(planner_assessment_path, _planner_assessment_fixture())
    _run_cli(
        "planner",
        "update",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        "--goal-id",
        "goal_meet",
        "--observation",
        str(FIXTURE_DIR / "app_observation_chat.json"),
        "--assessment",
        str(planner_assessment_path),
        "--json",
        command_key="planner_update",
        commands=commands,
    )
    _run_cli(
        "planner",
        "recommend",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        "--json",
        command_key="planner_recommend",
        commands=commands,
    )
    _run_cli(
        "memory",
        "get-match",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        command_key="memory_get_match",
        commands=commands,
    )
    context = _run_cli(
        "context",
        "build",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        "--mode",
        "adaptive",
        command_key="context_build",
        commands=commands,
    )
    context_path = data_dir / "context.json"
    _write_json(context_path, context)

    host_draft = _read_json(FIXTURE_DIR / "scripted_reply.json")
    draft_path = data_dir / "host_draft.json"
    _write_json(draft_path, host_draft)
    _run_cli(
        "policy",
        "check-draft",
        "--input",
        str(draft_path),
        "--context",
        str(context_path),
        command_key="policy_check_draft",
        commands=commands,
    )
    _run_cli(
        "policy",
        "check-action",
        "paste_draft",
        command_key="policy_check_action",
        commands=commands,
    )

    action_result_path = data_dir / "action_result.json"
    _write_json(
        action_result_path,
        {
            "action": "paste_draft",
            "target_match_id": match_id,
            "payload_hash": _payload_hash(host_draft),
            "pre_action_observation_id": "obs_chat_001",
            "post_action_observation_id": "obs_chat_001",
            "result_status": "succeeded",
            "evidence": {
                "verification": "Fixture smoke test records host paste-draft success.",
            },
        },
    )
    _run_cli(
        "action",
        "record-result",
        "--data-dir",
        str(data_dir),
        "--input",
        str(action_result_path),
        command_key="action_record_result",
        commands=commands,
    )
    _run_cli(
        "feedback",
        "record",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        "--draft-id",
        "smoke_draft_1",
        "--mode",
        "adaptive",
        "--label",
        "accepted",
        command_key="feedback_record",
        commands=commands,
    )

    _run_cli(
        "automation",
        "goal",
        "set",
        "--data-dir",
        str(data_dir),
        "--input",
        str(AUTOMATION_FIXTURE_DIR / "goal_meet.json"),
        command_key="automation_goal_set",
        commands=commands,
    )
    _run_cli(
        "automation",
        "availability",
        "set",
        "--data-dir",
        str(data_dir),
        "--input",
        str(AUTOMATION_FIXTURE_DIR / "availability_weekend.json"),
        command_key="automation_availability_set",
        commands=commands,
    )
    _run_cli(
        "automation",
        "session",
        "start",
        "--data-dir",
        str(data_dir),
        "--authorization",
        str(AUTOMATION_FIXTURE_DIR / "auth_send.json"),
        command_key="automation_session_start",
        commands=commands,
    )
    scan_template = _run_cli(
        "automation",
        "scan",
        "template",
        "--json",
        command_key="automation_scan_template",
        commands=commands,
    )
    automation_fixture = _read_json(AUTOMATION_FIXTURE_DIR / "scan_batch_initial.json")
    message_list_path = data_dir / "automation_message_list.json"
    threads_path = data_dir / "automation_threads.json"
    _write_json(message_list_path, automation_fixture["message_list_snapshot"])
    _write_json(threads_path, {"thread_observations": automation_fixture["thread_observations"]})
    assembled_scan = _run_cli(
        "automation",
        "scan",
        "assemble",
        "--message-list",
        str(message_list_path),
        "--threads",
        str(threads_path),
        "--session-id",
        str(automation_fixture["session_id"]),
        "--captured-at",
        str(automation_fixture["captured_at"]),
        "--json",
        command_key="automation_scan_assemble",
        commands=commands,
    )
    scan_path = data_dir / "automation_scan_batch.json"
    _write_json(scan_path, assembled_scan["scan_batch"])
    _run_cli(
        "automation",
        "scan",
        "validate",
        "--input",
        str(scan_path),
        "--json",
        command_key="automation_scan_validate",
        commands=commands,
    )
    automation_step = _run_cli(
        "automation",
        "session",
        "step",
        "--data-dir",
        str(data_dir),
        "--scan-batch",
        str(scan_path),
        command_key="automation_session_step",
        commands=commands,
    )
    automation_action_path = None
    if automation_step.get("action_requests"):
        request = automation_step["action_requests"][0]
        automation_action_path = data_dir / "automation_action_result.json"
        _write_json(
            automation_action_path,
            {
                "action_request_id": request["action_request_id"],
                "action": "send_message",
                "target_match_id": request["match_id"],
                "payload_hash": request["payload_hash"],
                "precondition_hash": request.get("precondition_hash"),
                "autonomous_audit_binding": request.get("autonomous_audit_binding"),
                "pre_action_observation_id": request["pre_action_observation_id"],
                "post_action_observation_id": "obs_automation_sent_001",
                "result_status": "succeeded",
                "evidence": {
                    "verification": "Fixture smoke test records automation send success.",
                },
            },
        )
        _run_cli(
            "action",
            "record-result",
            "--data-dir",
            str(data_dir),
            "--input",
            str(automation_action_path),
            command_key="automation_action_record_result",
            commands=commands,
        )
    automation_stop = _run_cli(
        "automation",
        "session",
        "stop",
        "--data-dir",
        str(data_dir),
        command_key="automation_session_stop",
        commands=commands,
    )
    _run_cli(
        "automation",
        "report",
        "latest",
        "--data-dir",
        str(data_dir),
        command_key="automation_report_latest",
        commands=commands,
    )
    report_md = _run_text(
        "automation",
        "report",
        "latest",
        "--data-dir",
        str(data_dir),
        "--format",
        "md",
        command_key="automation_report_latest_md",
        commands=commands,
    )

    operator_data_dir = data_dir / "operator-smoke"
    shutil.rmtree(operator_data_dir, ignore_errors=True)
    _run_cli(
        "init-profile",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(FIXTURE_DIR / "user_profile.json"),
        command_key="operator_init_profile",
        commands=commands,
    )
    _run_cli(
        "user",
        "ingest-profile",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(FIXTURE_DIR / "user_dating_profile.json"),
        command_key="operator_user_ingest_profile",
        commands=commands,
    )
    _run_cli(
        "user",
        "ingest-interview",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(FIXTURE_DIR / "user_self_interview.json"),
        command_key="operator_user_ingest_interview",
        commands=commands,
    )
    _run_cli(
        "user",
        "readiness",
        "--data-dir",
        str(operator_data_dir),
        "--mode",
        "autonomous",
        "--json",
        command_key="operator_user_readiness",
        commands=commands,
    )
    _run_cli(
        "automation",
        "goal",
        "set",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(AUTOMATION_FIXTURE_DIR / "goal_meet.json"),
        command_key="operator_goal_set",
        commands=commands,
    )
    _run_cli(
        "operator",
        "session",
        "start",
        "--data-dir",
        str(operator_data_dir),
        "--authorization",
        str(AUTOMATION_FIXTURE_DIR / "auth_send.json"),
        command_key="operator_session_start",
        commands=commands,
    )
    _run_cli(
        "operator",
        "next",
        "--data-dir",
        str(operator_data_dir),
        command_key="operator_next_initial",
        commands=commands,
    )
    operator_list_path = data_dir / "operator_message_list.json"
    _write_json(operator_list_path, _operator_message_list_observation(automation_fixture))
    _run_cli(
        "operator",
        "ingest-observation",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(operator_list_path),
        command_key="operator_ingest_list",
        commands=commands,
    )
    _run_cli(
        "operator",
        "next",
        "--data-dir",
        str(operator_data_dir),
        command_key="operator_next_open_thread",
        commands=commands,
    )
    operator_thread_path = data_dir / "operator_thread_ada.json"
    _write_json(operator_thread_path, _operator_thread_observation(automation_fixture, "row_ada"))
    _run_cli(
        "operator",
        "ingest-observation",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(operator_thread_path),
        command_key="operator_ingest_thread",
        commands=commands,
    )
    operator_send = _run_cli(
        "operator",
        "next",
        "--data-dir",
        str(operator_data_dir),
        command_key="operator_next_send",
        commands=commands,
    )
    operator_request = operator_send["work_item"]
    operator_action_path = data_dir / "operator_action_result.json"
    _write_json(
        operator_action_path,
        {
            "action_request_id": operator_request["action_request_id"],
            "action": "send_message",
            "target_match_id": operator_request["match_id"],
            "payload_hash": operator_request["payload_hash"],
            "precondition_hash": operator_request["precondition_hash"],
            "autonomous_audit_binding": operator_request["autonomous_audit_binding"],
            "pre_action_observation_id": operator_request["pre_action_observation_id"],
            "post_action_observation_id": "obs_operator_sent_001",
            "result_status": "succeeded",
            "evidence": {
                "verification": "Fixture smoke test records operator send success.",
            },
        },
    )
    _run_cli(
        "operator",
        "record-action-result",
        "--data-dir",
        str(operator_data_dir),
        "--input",
        str(operator_action_path),
        command_key="operator_record_action_result",
        commands=commands,
    )
    operator_stop = _run_cli(
        "operator",
        "stop",
        "--data-dir",
        str(operator_data_dir),
        command_key="operator_stop",
        commands=commands,
    )
    _run_cli(
        "operator",
        "report",
        "latest",
        "--data-dir",
        str(operator_data_dir),
        command_key="operator_report_latest",
        commands=commands,
    )
    export_path = data_dir / "export.json"
    data_export = _run_cli(
        "data",
        "export",
        "--data-dir",
        str(data_dir),
        "--output",
        str(export_path),
        "--json",
        command_key="data_export",
        commands=commands,
    )
    data_doctor_final = _run_cli(
        "data",
        "doctor",
        "--data-dir",
        str(data_dir),
        "--json",
        command_key="data_doctor_final",
        commands=commands,
    )

    stage_fixture_dir = ROOT / "tests" / "fixtures" / "host_loop" / "tinder"
    stage_data_dir = data_dir / "host-loop-stage"
    stage_work_dir = stage_data_dir / "host-work"
    shutil.rmtree(stage_data_dir, ignore_errors=True)
    stage_result = _run_host_loop(
        "run",
        "--data-dir",
        str(stage_data_dir),
        "--authorization",
        str(stage_fixture_dir / "auth.json"),
        "--goal",
        str(stage_fixture_dir / "goal.json"),
        "--availability",
        str(stage_fixture_dir / "availability.json"),
        "--app-id",
        "tinder",
        "--send-mode",
        "stage",
        "--fixture-host",
        str(stage_fixture_dir),
        "--work-dir",
        str(stage_work_dir),
        "--max-steps",
        "10",
        "--wait-timeout",
        "0",
        "--json",
        command_key="host_loop_fixture_stage",
        commands=commands,
    )
    if stage_result.get("status") != "staged_waiting_user_confirmation":
        raise RuntimeError(f"host-loop stage smoke did not stop at staged confirmation: {stage_result.get('status')}")
    stage_migration = _run_cli(
        "data",
        "migrate",
        "--data-dir",
        str(stage_data_dir),
        "--json",
        command_key="host_loop_stage_data_migrate",
        commands=commands,
    )
    stage_export_path = data_dir / "host_loop_stage_export.json"
    stage_export = _run_cli(
        "data",
        "export",
        "--data-dir",
        str(stage_data_dir),
        "--output",
        str(stage_export_path),
        "--json",
        command_key="host_loop_stage_data_export",
        commands=commands,
    )
    stage_replay = _run_cli(
        "replay",
        "latest",
        "--data-dir",
        str(stage_data_dir),
        "--format",
        "json",
        command_key="host_loop_stage_replay",
        commands=commands,
    )
    staged_artifacts = sorted(stage_work_dir.glob("staged_verification.*.json"))
    if not staged_artifacts:
        raise RuntimeError("host-loop stage smoke did not write staged verification artifact")

    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "ok",
                "production_smoke": True,
                "data_dir": str(data_dir),
                "match_id": match_id,
                "skill_doctor": skill_doctor,
                "data_doctor_initial": data_doctor_initial,
                "data_migration": data_migration,
                "data_doctor_after_migration": data_doctor,
                "data_doctor": data_doctor_final,
                "tool_version": capabilities["tool_version"],
                "compatibility": compatibility,
                "commands": commands,
                "host_loop_fixture_stage": {
                    "status": stage_result["status"],
                    "stop_reason": stage_result.get("stop_reason"),
                    "stage_data_dir": str(stage_data_dir),
                    "stage_work_dir": str(stage_work_dir),
                    "current_work_item": str(stage_work_dir / "current_work_item.json"),
                    "staged_verification": str(staged_artifacts[0]),
                    "replay_status": stage_replay.get("status"),
                },
                "artifacts": {
                    "context": str(context_path),
                    "planner_assessment": str(planner_assessment_path),
                    "host_draft": str(draft_path),
                    "action_result": str(action_result_path),
                    "action_audit": str(data_dir / "audit" / "action_results.jsonl"),
                    "feedback": str(data_dir / "matches" / match_id / "feedback_events.jsonl"),
                    "automation_scan_template_example": scan_template["session_id"],
                    "automation_scan_batch": str(scan_path),
                    "automation_action_result": str(automation_action_path) if automation_action_path else None,
                    "automation_machine_report": str(data_dir / automation_stop["machine_report_path"]),
                    "automation_human_report": str(data_dir / automation_stop["human_report_path"]),
                    "automation_human_report_preview": report_md.splitlines()[:3],
                    "operator_data_dir": str(operator_data_dir),
                    "operator_message_list": str(operator_list_path),
                    "operator_thread": str(operator_thread_path),
                    "operator_action_result": str(operator_action_path),
                    "operator_machine_report": str(operator_data_dir / operator_stop["machine_report_path"]),
                    "data_export": str(export_path),
                    "data_export_document_count": data_export["document_count"],
                    "host_loop_stage_export": str(stage_export_path),
                    "host_loop_stage_export_document_count": stage_export["document_count"],
                    "host_loop_stage_migration_backup": stage_migration["backup_dir"],
                    "host_loop_stage_replay": stage_replay.get("timeline_path"),
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_cli(*args: str, command_key: str, commands: dict[str, int]) -> dict[str, Any]:
    env = dict(os.environ)
    env.setdefault("DATING_BOOST_NOW", "2026-05-26T00:00:00Z")
    result = subprocess.run(
        [sys.executable, "-m", "dating_boost.cli", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    commands[command_key] = result.returncode
    if result.returncode != 0:
        raise RuntimeError(
            f"dating-boost {' '.join(args)} failed with exit {result.returncode}: {result.stderr or result.stdout}"
        )
    return json.loads(result.stdout)


def _run_host_loop(*args: str, command_key: str, commands: dict[str, int]) -> dict[str, Any]:
    env = dict(os.environ)
    env.setdefault("DATING_BOOST_NOW", "2026-05-26T00:00:00Z")
    result = subprocess.run(
        [sys.executable, "-m", "dating_boost.host_loop", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    commands[command_key] = result.returncode
    if result.returncode != 0:
        raise RuntimeError(
            f"dating-boost-host-loop {' '.join(args)} failed with exit {result.returncode}: "
            f"{result.stderr or result.stdout}"
        )
    return json.loads(result.stdout)


def _run_text(*args: str, command_key: str, commands: dict[str, int]) -> str:
    env = dict(os.environ)
    env.setdefault("DATING_BOOST_NOW", "2026-05-26T00:00:00Z")
    result = subprocess.run(
        [sys.executable, "-m", "dating_boost.cli", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    commands[command_key] = result.returncode
    if result.returncode != 0:
        raise RuntimeError(
            f"dating-boost {' '.join(args)} failed with exit {result.returncode}: {result.stderr or result.stdout}"
        )
    return result.stdout


def _check_compatibility(capabilities: dict[str, Any]) -> dict[str, Any]:
    metadata = _read_json(SKILL_PACKAGE_PATH)
    errors: list[str] = []
    warnings: list[str] = []

    if _version_tuple(str(capabilities.get("tool_version", "0.0.0"))) < _version_tuple(
        str(metadata["dating_boost_min_version"])
    ):
        errors.append(
            "tool_version is lower than dating_boost_min_version "
            f"{metadata['dating_boost_min_version']}"
        )

    schema_versions = capabilities.get("schema_versions", {})
    if not isinstance(schema_versions, dict):
        errors.append("capabilities.schema_versions must be an object")
    else:
        for schema_name, schema_version in metadata["required_schema_versions"].items():
            if schema_versions.get(schema_name) != schema_version:
                errors.append(f"schema_versions.{schema_name} must equal {schema_version}")

    supported_commands = capabilities.get("supported_commands", [])
    if not isinstance(supported_commands, list):
        errors.append("capabilities.supported_commands must be a list")
    else:
        missing_commands = [
            command for command in metadata["required_commands"] if command not in supported_commands
        ]
        if missing_commands:
            errors.append("missing supported_commands: " + ", ".join(missing_commands))

    source_spec_commit = metadata.get("source_spec_commit")
    git_commit = capabilities.get("git_commit")
    if _looks_like_git_commit(source_spec_commit) and git_commit and source_spec_commit != git_commit:
        warnings.append(
            f"source_spec_commit {source_spec_commit} differs from current git_commit {git_commit}"
        )

    if errors:
        raise RuntimeError("Compatibility check failed: " + "; ".join(errors))

    return {
        "status": "ok",
        "warnings": warnings,
    }


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = version.split(".")
    values: list[int] = []
    for part in parts:
        digits = "".join(character for character in part if character.isdigit())
        values.append(int(digits or "0"))
    return tuple(values)


def _looks_like_git_commit(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return 7 <= len(value) <= 40 and all(character in "0123456789abcdef" for character in value.lower())


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _operator_message_list_observation(scan_batch: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "observation_type": "message_list",
        "session_id": scan_batch["session_id"],
        "app_id": scan_batch["app_id"],
        "captured_at": scan_batch["captured_at"],
        "scan_cursor": scan_batch.get("scan_cursor"),
        "scan_budget": scan_batch.get("scan_budget", 5),
        "provenance": scan_batch.get("provenance"),
        "message_list_snapshot": scan_batch["message_list_snapshot"],
    }


def _operator_thread_observation(scan_batch: dict[str, Any], candidate_key: str) -> dict[str, Any]:
    for item in scan_batch["thread_observations"]:
        if item["candidate_key"] == candidate_key:
            thread = dict(item)
            thread["schema_version"] = 1
            thread["observation_type"] = "thread"
            return thread
    raise ValueError(f"missing thread observation for {candidate_key}")


def _planner_assessment_fixture() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "latest_turn_summary": "The match responded to the current chat thread with a lightweight opening.",
        "latest_turn_type": "short_answer",
        "inbound_intent": "answer",
        "topic": {
            "current_topic": "weekend_plans",
            "topic_state": "active",
            "new_information": ["match mentioned weekend context"],
            "stale_hooks": [],
        },
        "scores": {
            "engagement": 52,
            "warmth": 45,
            "curiosity": 30,
            "comfort": 40,
            "momentum": 46,
            "topic_saturation": 25,
            "logistics_readiness": 20,
            "risk": 10,
        },
        "recommended_stage": "warmup",
        "recommended_move": "bridge_topic",
        "next_milestone": "Build a little comfort before probing meeting interest.",
        "avoid_next": ["do not jump directly to exact meeting details"],
        "soft_invite_allowed": False,
        "confidence": "high",
        "evidence": "Fixture assessment for smoke testing the planner contract.",
    }


if __name__ == "__main__":
    raise SystemExit(main())
