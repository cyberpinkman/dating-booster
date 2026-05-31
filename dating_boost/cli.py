from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.automation import AutomationRepository
from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.feedback import create_feedback_event
from dating_boost.core.identity import resolve_match_identity
from dating_boost.core.models import Divergence, MemoryItem, ReplyMode, UserProfile
from dating_boost.core.planner import PlannerRepository, planner_context_items
from dating_boost.core.repositories import JsonMemoryRepository, MatchRepository, ObservationRepository
from dating_boost.core.scan_authoring import (
    assemble_scan_batch,
    normalize_scan_batch,
    scan_template,
    validate_scan_batch,
)
from dating_boost.core.skill_doctor import run_skill_doctor
from dating_boost.intelligence.backends import ModelBackend, OpenAIBackend, ScriptedBackend
from dating_boost.intelligence.reply_generator import DraftResponse, generate_reply
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.policy import Action, authorize_action
from dating_boost.policy.content import ContentPolicyDecision, evaluate_draft_content


MVP_TIMESTAMP = "2026-05-25T00:00:00Z"


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    argv_list = None if argv is None else list(argv)
    command_tokens = sys.argv[1:] if argv is None else argv_list
    if command_tokens and command_tokens[0] in {action.value for action in Action}:
        return _run_authorization(command_tokens)

    parser = argparse.ArgumentParser(
        prog="dating-boost",
        description="Local-first dating workflow copilot.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="Print machine-readable CLI and schema compatibility metadata.",
    )
    capabilities_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    capabilities_parser.add_argument("--data-dir", type=Path)
    capabilities_parser.set_defaults(handler=_handle_capabilities)

    skill_parser = subparsers.add_parser("skill", help="Codex skill packaging and diagnostics.")
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command", required=True)
    skill_doctor_parser = skill_subparsers.add_parser("doctor", help="Check skill/CLI compatibility.")
    skill_doctor_parser.add_argument("--package", required=True, type=Path)
    skill_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    skill_doctor_parser.add_argument("--json", action="store_true")
    skill_doctor_parser.set_defaults(handler=_handle_skill_doctor)

    authorize_parser = subparsers.add_parser(
        "authorize",
        help="Authorize an action before any harness executes it.",
    )
    authorize_parser.add_argument(
        "action",
        choices=[action.value for action in Action],
        help="Action to authorize.",
    )
    authorize_parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Enable high-risk autonomous mode for this action after accepting the risks.",
    )
    authorize_parser.set_defaults(handler=_handle_authorize)

    init_parser = subparsers.add_parser("init-profile", help="Initialize local user profile memory.")
    init_parser.add_argument("--data-dir", required=True, type=Path)
    init_parser.add_argument("--input", required=True, type=Path)
    init_parser.set_defaults(handler=_handle_init_profile)

    import_parser = subparsers.add_parser("import-observation", help="Import an app observation fixture.")
    import_parser.add_argument("--data-dir", required=True, type=Path)
    import_parser.add_argument("--input", required=True, type=Path)
    import_parser.set_defaults(handler=_handle_import_observation)

    memory_parser = subparsers.add_parser("memory", help="Agent-native memory commands.")
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_ingest_parser = memory_subparsers.add_parser(
        "ingest-observation",
        help="Import an app observation into local match memory.",
    )
    memory_ingest_parser.add_argument("--data-dir", required=True, type=Path)
    memory_ingest_parser.add_argument("--input", required=True, type=Path)
    memory_ingest_parser.set_defaults(handler=_handle_import_observation)
    memory_get_parser = memory_subparsers.add_parser(
        "get-match",
        help="Read a match identity record from local memory.",
    )
    memory_get_parser.add_argument("--data-dir", required=True, type=Path)
    memory_get_parser.add_argument("--match-id", required=True)
    memory_get_parser.set_defaults(handler=_handle_memory_get_match)

    screenshot_parser = subparsers.add_parser(
        "observe-screenshot",
        help="Import a screenshot plus manual/OCR/VLM analysis as an observation.",
    )
    screenshot_parser.add_argument("--data-dir", required=True, type=Path)
    screenshot_parser.add_argument("--screenshot", required=True, type=Path)
    screenshot_parser.add_argument("--analysis", required=True, type=Path)
    screenshot_parser.set_defaults(handler=_handle_observe_screenshot)

    draft_parser = subparsers.add_parser("draft", help="Generate a reply draft.")
    draft_parser.add_argument("--data-dir", required=True, type=Path)
    draft_parser.add_argument("--match-id", required=True)
    draft_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    draft_parser.add_argument("--backend", choices=["openai", "scripted"])
    draft_parser.add_argument("--model", default="gpt-4.1-mini")
    draft_parser.add_argument("--scripted-backend-output", type=Path)
    draft_parser.add_argument("--debug-context", action="store_true")
    draft_parser.set_defaults(handler=_handle_draft)

    context_parser = subparsers.add_parser("context", help="Agent-native context commands.")
    context_subparsers = context_parser.add_subparsers(dest="context_command", required=True)
    context_build_parser = context_subparsers.add_parser(
        "build",
        help="Build a context pack for a host-agent workflow.",
    )
    context_build_parser.add_argument("--data-dir", required=True, type=Path)
    context_build_parser.add_argument("--match-id", required=True)
    context_build_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    context_build_parser.set_defaults(handler=_handle_context_build)

    policy_parser = subparsers.add_parser("policy", help="Agent-native policy commands.")
    policy_subparsers = policy_parser.add_subparsers(dest="policy_command", required=True)
    policy_check_action_parser = policy_subparsers.add_parser(
        "check-action",
        help="Authorize a host-agent action before execution.",
    )
    policy_check_action_parser.add_argument("action", choices=[action.value for action in Action])
    policy_check_action_parser.add_argument("--autonomous", action="store_true")
    policy_check_action_parser.set_defaults(handler=_handle_policy_check_action)
    policy_check_draft_parser = policy_subparsers.add_parser(
        "check-draft",
        help="Check a host-generated draft against content policy.",
    )
    policy_check_draft_parser.add_argument("--input", required=True, type=Path)
    policy_check_draft_parser.add_argument("--context", required=True, type=Path)
    policy_check_draft_parser.set_defaults(handler=_handle_policy_check_draft)

    action_parser = subparsers.add_parser("action", help="Agent-native host action audit commands.")
    action_subparsers = action_parser.add_subparsers(dest="action_command", required=True)
    action_record_parser = action_subparsers.add_parser(
        "record-result",
        help="Record host-executed action verification evidence.",
    )
    action_record_parser.add_argument("--data-dir", required=True, type=Path)
    action_record_parser.add_argument("--input", required=True, type=Path)
    action_record_parser.set_defaults(handler=_handle_action_record_result)

    feedback_parser = subparsers.add_parser("feedback", help="Append local feedback for a draft.")
    feedback_parser.add_argument("feedback_action", nargs="?", choices=["record"])
    feedback_parser.add_argument("--data-dir", required=True, type=Path)
    feedback_parser.add_argument("--match-id", required=True)
    feedback_parser.add_argument("--draft-id", required=True)
    feedback_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    feedback_parser.add_argument("--label", required=True)
    feedback_parser.set_defaults(handler=_handle_feedback)

    workflow_parser = subparsers.add_parser("workflow", help="Agent-native workflow runners.")
    workflow_subparsers = workflow_parser.add_subparsers(dest="workflow_command", required=True)
    workflow_draft_parser = workflow_subparsers.add_parser(
        "draft",
        help="Run the host-agent draft workflow without calling an LLM.",
    )
    workflow_draft_parser.add_argument("--data-dir", required=True, type=Path)
    workflow_draft_parser.add_argument("--observation", required=True, type=Path)
    workflow_draft_parser.add_argument("--draft", required=True, type=Path)
    workflow_draft_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    workflow_draft_parser.add_argument("--feedback-label")
    workflow_draft_parser.add_argument("--draft-id")
    workflow_draft_parser.set_defaults(handler=_handle_workflow_draft)

    planner_parser = subparsers.add_parser("planner", help="Goal-oriented conversation planning commands.")
    planner_subparsers = planner_parser.add_subparsers(dest="planner_command", required=True)
    planner_update_parser = planner_subparsers.add_parser("update")
    planner_update_parser.add_argument("--data-dir", required=True, type=Path)
    planner_update_parser.add_argument("--match-id", required=True)
    planner_update_parser.add_argument("--goal-id", required=True)
    planner_update_parser.add_argument("--observation", required=True, type=Path)
    planner_update_parser.add_argument("--assessment", required=True, type=Path)
    planner_update_parser.add_argument("--json", action="store_true")
    planner_update_parser.set_defaults(handler=_handle_planner_update)
    planner_get_parser = planner_subparsers.add_parser("get")
    planner_get_parser.add_argument("--data-dir", required=True, type=Path)
    planner_get_parser.add_argument("--match-id", required=True)
    planner_get_parser.add_argument("--json", action="store_true")
    planner_get_parser.set_defaults(handler=_handle_planner_get)
    planner_recommend_parser = planner_subparsers.add_parser("recommend")
    planner_recommend_parser.add_argument("--data-dir", required=True, type=Path)
    planner_recommend_parser.add_argument("--match-id", required=True)
    planner_recommend_parser.add_argument("--json", action="store_true")
    planner_recommend_parser.set_defaults(handler=_handle_planner_recommend)
    planner_event_log_parser = planner_subparsers.add_parser("event-log")
    planner_event_log_parser.add_argument("--data-dir", required=True, type=Path)
    planner_event_log_parser.add_argument("--match-id", required=True)
    planner_event_log_parser.add_argument("--json", action="store_true")
    planner_event_log_parser.set_defaults(handler=_handle_planner_event_log)

    automation_parser = subparsers.add_parser("automation", help="Host-orchestrated automation commands.")
    automation_subparsers = automation_parser.add_subparsers(dest="automation_command", required=True)

    automation_session_parser = automation_subparsers.add_parser("session", help="Automation session commands.")
    automation_session_subparsers = automation_session_parser.add_subparsers(
        dest="automation_session_command",
        required=True,
    )
    session_start_parser = automation_session_subparsers.add_parser("start")
    session_start_parser.add_argument("--data-dir", required=True, type=Path)
    session_start_parser.add_argument("--authorization", required=True, type=Path)
    session_start_parser.set_defaults(handler=_handle_automation_session_start)
    session_step_parser = automation_session_subparsers.add_parser("step")
    session_step_parser.add_argument("--data-dir", required=True, type=Path)
    session_step_parser.add_argument("--scan-batch", required=True, type=Path)
    session_step_parser.set_defaults(handler=_handle_automation_session_step)
    session_stop_parser = automation_session_subparsers.add_parser("stop")
    session_stop_parser.add_argument("--data-dir", required=True, type=Path)
    session_stop_parser.set_defaults(handler=_handle_automation_session_stop)

    automation_report_parser = automation_subparsers.add_parser("report", help="Automation report commands.")
    automation_report_subparsers = automation_report_parser.add_subparsers(
        dest="automation_report_command",
        required=True,
    )
    report_latest_parser = automation_report_subparsers.add_parser("latest")
    report_latest_parser.add_argument("--data-dir", required=True, type=Path)
    report_latest_parser.add_argument("--format", choices=["json", "md"], default="json")
    report_latest_parser.set_defaults(handler=_handle_automation_report_latest)

    automation_scan_parser = automation_subparsers.add_parser("scan", help="Automation scan authoring commands.")
    automation_scan_subparsers = automation_scan_parser.add_subparsers(
        dest="automation_scan_command",
        required=True,
    )
    scan_template_parser = automation_scan_subparsers.add_parser("template")
    scan_template_parser.add_argument("--json", action="store_true")
    scan_template_parser.set_defaults(handler=_handle_automation_scan_template)
    scan_validate_parser = automation_scan_subparsers.add_parser("validate")
    scan_validate_parser.add_argument("--input", required=True, type=Path)
    scan_validate_parser.add_argument("--json", action="store_true")
    scan_validate_parser.set_defaults(handler=_handle_automation_scan_validate)
    scan_normalize_parser = automation_scan_subparsers.add_parser("normalize")
    scan_normalize_parser.add_argument("--input", required=True, type=Path)
    scan_normalize_parser.add_argument("--json", action="store_true")
    scan_normalize_parser.set_defaults(handler=_handle_automation_scan_normalize)
    scan_assemble_parser = automation_scan_subparsers.add_parser("assemble")
    scan_assemble_parser.add_argument("--message-list", required=True, type=Path)
    scan_assemble_parser.add_argument("--threads", required=True, type=Path)
    scan_assemble_parser.add_argument("--session-id", required=True)
    scan_assemble_parser.add_argument("--captured-at", required=True)
    scan_assemble_parser.add_argument("--app-id", default="tinder")
    scan_assemble_parser.add_argument("--scan-budget", type=int, default=5)
    scan_assemble_parser.add_argument("--json", action="store_true")
    scan_assemble_parser.set_defaults(handler=_handle_automation_scan_assemble)

    automation_get_state_parser = automation_subparsers.add_parser("get-state")
    automation_get_state_parser.add_argument("--data-dir", required=True, type=Path)
    automation_get_state_parser.set_defaults(handler=_handle_automation_get_state)

    automation_record_auth_parser = automation_subparsers.add_parser("record-authorization")
    automation_record_auth_parser.add_argument("--data-dir", required=True, type=Path)
    automation_record_auth_parser.add_argument("--input", required=True, type=Path)
    automation_record_auth_parser.set_defaults(handler=_handle_automation_record_authorization)

    automation_pause_parser = automation_subparsers.add_parser("pause")
    automation_pause_parser.add_argument("--data-dir", required=True, type=Path)
    automation_pause_parser.set_defaults(handler=_handle_automation_pause)
    automation_resume_parser = automation_subparsers.add_parser("resume")
    automation_resume_parser.add_argument("--data-dir", required=True, type=Path)
    automation_resume_parser.set_defaults(handler=_handle_automation_resume)

    automation_availability_parser = automation_subparsers.add_parser("availability")
    automation_availability_subparsers = automation_availability_parser.add_subparsers(
        dest="automation_availability_command",
        required=True,
    )
    availability_set_parser = automation_availability_subparsers.add_parser("set")
    availability_set_parser.add_argument("--data-dir", required=True, type=Path)
    availability_set_parser.add_argument("--input", required=True, type=Path)
    availability_set_parser.set_defaults(handler=_handle_automation_availability_set)

    automation_goal_parser = automation_subparsers.add_parser("goal")
    automation_goal_subparsers = automation_goal_parser.add_subparsers(
        dest="automation_goal_command",
        required=True,
    )
    goal_set_parser = automation_goal_subparsers.add_parser("set")
    goal_set_parser.add_argument("--data-dir", required=True, type=Path)
    goal_set_parser.add_argument("--input", required=True, type=Path)
    goal_set_parser.set_defaults(handler=_handle_automation_goal_set)

    args = parser.parse_args(argv_list)
    return args.handler(args)


def _run_authorization(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dating-boost",
        description="Local-first dating workflow copilot safety gate.",
    )
    parser.add_argument(
        "action",
        choices=[action.value for action in Action],
        help="Action to authorize before any harness executes it.",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Enable high-risk autonomous mode for this action after accepting the risks.",
    )
    args = parser.parse_args(argv)
    return _handle_authorize(args)


def _handle_capabilities(args: argparse.Namespace) -> int:
    _print_json(build_capabilities(args.data_dir))
    return 0


def _handle_skill_doctor(args: argparse.Namespace) -> int:
    payload = run_skill_doctor(args.package, args.data_dir)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_authorize(args: argparse.Namespace) -> int:
    return _print_action_decision(args)


def _handle_policy_check_action(args: argparse.Namespace) -> int:
    return _print_action_decision(args)


def _print_action_decision(args: argparse.Namespace) -> int:
    decision = authorize_action(
        Action(args.action),
        autonomous=args.autonomous,
    )

    _print_json(
        {
            "allowed": decision.allowed,
            "action": decision.action.value,
            "autonomous": decision.autonomous,
            "reason": decision.reason,
        }
    )
    return 0 if decision.allowed else 2


def _handle_init_profile(args: argparse.Namespace) -> int:
    data = _read_json_object(args.input)
    profile = _profile_from_dict(data)
    JsonMemoryRepository(args.data_dir).save_user_profile(profile)

    _print_json(
        {
            "status": "ok",
            "user_id": profile.user_id,
            "path": "user_profile.json",
        }
    )
    return 0


def _handle_import_observation(args: argparse.Namespace) -> int:
    observation = load_observation(args.input)
    return _persist_observation(args.data_dir, observation)


def _handle_observe_screenshot(args: argparse.Namespace) -> int:
    if not args.screenshot.exists():
        raise ValueError(f"screenshot does not exist: {args.screenshot}")
    observation = build_observation_from_screenshot_analysis(
        screenshot_path=args.screenshot,
        analysis=_read_json_object(args.analysis),
    )
    return _persist_observation(args.data_dir, observation)


def _persist_observation(data_dir: Path, observation: AppObservation) -> int:
    _print_json(_store_observation(data_dir, observation))
    return 0


def _store_observation(data_dir: Path, observation: AppObservation) -> dict[str, Any]:
    match_repo = MatchRepository(data_dir)
    identity = resolve_match_identity(observation, existing_matches=match_repo.list_match_candidates())
    _validate_storage_id(identity.match_id, "match_id")
    _validate_storage_id(observation.observation_id, "observation_id")

    ObservationRepository(data_dir).save_observation(identity.match_id, observation)
    match_repo.upsert_match_from_observation(
        match_id=identity.match_id,
        observation=observation,
        confidence=identity.confidence.value,
        requires_user_confirmation=identity.requires_user_confirmation,
    )
    if identity.requires_user_confirmation:
        match_repo.append_identity_confirmation(
            match_id=identity.match_id,
            observation_id=observation.observation_id,
            confidence=identity.confidence.value,
            reason=identity.reason,
        )

    return {
        "status": "ok",
        "match_id": identity.match_id,
        "confidence": identity.confidence.value,
        "requires_user_confirmation": identity.requires_user_confirmation,
        "observation_id": observation.observation_id,
    }


def _handle_memory_get_match(args: argparse.Namespace) -> int:
    for record in MatchRepository(args.data_dir).list_match_candidates():
        if record.get("match_id") == args.match_id:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "ok",
                    "match": record,
                }
            )
            return 0
    _print_json(
        {
            "schema_version": 1,
            "status": "not_found",
            "match_id": args.match_id,
        }
    )
    return 2


def _handle_draft(args: argparse.Namespace) -> int:
    repo = JsonMemoryRepository(args.data_dir)
    profile = repo.load_user_profile()
    reply_mode = ReplyMode(args.mode)
    backend = _select_backend(args)
    observation = ObservationRepository(args.data_dir).load_latest_observation(args.match_id)
    context_pack = _build_mvp_context_pack(profile, args.match_id, reply_mode, observation, args.data_dir)
    draft = generate_reply(context_pack, reply_mode, backend)
    policy = evaluate_draft_content(draft, context_pack)

    if not policy.allowed:
        _print_json(
            {
                "status": "blocked",
                "match_id": args.match_id,
                "mode": reply_mode.value,
                "policy": _policy_to_dict(policy),
            }
        )
        return 2

    payload: dict[str, Any] = {
        "status": "ok",
        "match_id": args.match_id,
        "mode": reply_mode.value,
        "best_reply": draft.best_reply,
        "draft": _draft_to_dict(draft),
        "policy": _policy_to_dict(policy),
    }
    if args.debug_context:
        payload["context_pack"] = context_pack
    _print_json(payload)
    return 0


def _handle_context_build(args: argparse.Namespace) -> int:
    profile = JsonMemoryRepository(args.data_dir).load_user_profile()
    reply_mode = ReplyMode(args.mode)
    observation = ObservationRepository(args.data_dir).load_latest_observation(args.match_id)
    context_pack = _build_mvp_context_pack(profile, args.match_id, reply_mode, observation, args.data_dir)
    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "mode": reply_mode.value,
            "context_pack": context_pack,
        }
    )
    return 0


def _handle_policy_check_draft(args: argparse.Namespace) -> int:
    draft = _draft_from_dict(_read_json_object(args.input))
    context_payload = _read_json_object(args.context)
    context_pack = context_payload.get("context_pack", context_payload)
    if not isinstance(context_pack, dict):
        raise ValueError("--context must contain a JSON object or a context_pack object")
    policy = evaluate_draft_content(draft, context_pack)
    _print_json(
        {
            "schema_version": 1,
            "status": "ok" if policy.allowed else "blocked",
            "policy": _policy_to_dict(policy),
        }
    )
    return 0 if policy.allowed else 2


def _handle_workflow_draft(args: argparse.Namespace) -> int:
    reply_mode = ReplyMode(args.mode)
    steps: dict[str, str] = {
        "capabilities": "ok",
    }
    capabilities = build_capabilities(args.data_dir)

    observation = load_observation(args.observation)
    ingest = _store_observation(args.data_dir, observation)
    steps["ingest_observation"] = "ok"

    match_id = str(ingest["match_id"])
    profile = JsonMemoryRepository(args.data_dir).load_user_profile()
    latest_observation = ObservationRepository(args.data_dir).load_latest_observation(match_id)
    context_pack = _build_mvp_context_pack(profile, match_id, reply_mode, latest_observation, args.data_dir)
    steps["context_build"] = "ok"

    draft = _draft_from_dict(_read_json_object(args.draft))
    policy = evaluate_draft_content(draft, context_pack)
    steps["policy_check_draft"] = "ok" if policy.allowed else "blocked"

    payload: dict[str, Any] = {
        "schema_version": 1,
        "workflow": "draft",
        "status": "ok" if policy.allowed else "blocked",
        "data_dir": str(args.data_dir.resolve()),
        "tool_version": capabilities["tool_version"],
        "steps": steps,
        "match_id": match_id,
        "observation_id": observation.observation_id,
        "identity_confidence": ingest["confidence"],
        "requires_user_confirmation": ingest["requires_user_confirmation"],
        "mode": reply_mode.value,
        "context_pack": context_pack,
        "policy": _policy_to_dict(policy),
    }

    if not policy.allowed:
        payload["feedback"] = None
        _print_json(payload)
        return 2

    payload["draft"] = _draft_to_dict(draft)
    if args.feedback_label:
        draft_id = args.draft_id or args.draft.stem
        payload["feedback"] = _record_feedback(
            data_dir=args.data_dir,
            match_id=match_id,
            draft_id=draft_id,
            mode=reply_mode,
            label=args.feedback_label,
        )
        steps["feedback_record"] = "ok"
    else:
        payload["feedback"] = None
        steps["feedback_record"] = "skipped"

    _print_json(payload)
    return 0


def _handle_planner_update(args: argparse.Namespace) -> int:
    observation = load_observation(args.observation)
    assessment = _read_json_object(args.assessment)
    try:
        payload = PlannerRepository(args.data_dir).update_plan(
            match_id=args.match_id,
            goal_id=args.goal_id,
            observation=observation,
            assessment=assessment,
            now=_now_iso(),
        )
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
    return 0


def _handle_planner_get(args: argparse.Namespace) -> int:
    payload = PlannerRepository(args.data_dir).get_plan_payload(args.match_id)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_planner_recommend(args: argparse.Namespace) -> int:
    payload = PlannerRepository(args.data_dir).recommend(args.match_id)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_planner_event_log(args: argparse.Namespace) -> int:
    _print_json(PlannerRepository(args.data_dir).event_log_payload(args.match_id))
    return 0


def _handle_action_record_result(args: argparse.Namespace) -> int:
    payload = _read_json_object(args.input)
    try:
        event = ActionAuditRepository(args.data_dir).append_action_result(
            payload,
            created_at=MVP_TIMESTAMP,
        )
    except ValueError as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "reason": str(exc),
            }
        )
        return 2

    AutomationRepository(args.data_dir).apply_action_result(event)

    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "event_id": event["event_id"],
            "action_request_id": event.get("action_request_id"),
            "result_status": event["result_status"],
            "path": "audit/action_results.jsonl",
        }
    )
    return 0


def _handle_automation_goal_set(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).save_goal(_read_json_object(args.input)))
    return 0


def _handle_automation_availability_set(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).save_availability(_read_json_object(args.input)))
    return 0


def _handle_automation_record_authorization(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).save_authorization(_read_json_object(args.input)))
    return 0


def _handle_automation_session_start(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).start_session(_read_json_object(args.authorization)))
    return 0


def _handle_automation_session_step(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).step(_read_json_object(args.scan_batch)))
    return 0


def _handle_automation_session_stop(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).stop_session())
    return 0


def _handle_automation_report_latest(args: argparse.Namespace) -> int:
    payload = AutomationRepository(args.data_dir).latest_report()
    if args.format == "md":
        if payload["status"] != "ok":
            _print_json(payload)
            return 2
        sys.stdout.write(AutomationRepository(args.data_dir).latest_human_report() + "\n")
        return 0
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_automation_scan_template(args: argparse.Namespace) -> int:
    _print_json(scan_template())
    return 0


def _handle_automation_scan_validate(args: argparse.Namespace) -> int:
    payload = validate_scan_batch(_read_json_object(args.input))
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_automation_scan_normalize(args: argparse.Namespace) -> int:
    scan_batch = normalize_scan_batch(_read_json_object(args.input))
    validation = validate_scan_batch(scan_batch)
    payload = {
        "schema_version": 1,
        "status": validation["status"],
        "scan_batch": scan_batch,
        "validation": validation,
    }
    _print_json(payload)
    return 0 if validation["status"] == "ok" else 2


def _handle_automation_scan_assemble(args: argparse.Namespace) -> int:
    scan_batch = assemble_scan_batch(
        message_list=_read_json_object(args.message_list),
        threads=_read_json_payload(args.threads),
        session_id=args.session_id,
        captured_at=args.captured_at,
        app_id=args.app_id,
        scan_budget=args.scan_budget,
    )
    validation = validate_scan_batch(scan_batch)
    payload = {
        "schema_version": 1,
        "status": validation["status"],
        "scan_batch": scan_batch,
        "validation": validation,
    }
    _print_json(payload)
    return 0 if validation["status"] == "ok" else 2


def _handle_automation_get_state(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).get_state_payload())
    return 0


def _handle_automation_pause(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).pause_session())
    return 0


def _handle_automation_resume(args: argparse.Namespace) -> int:
    _print_json(AutomationRepository(args.data_dir).resume_session())
    return 0


def _select_backend(args: argparse.Namespace) -> ModelBackend:
    backend_name = args.backend or ("scripted" if args.scripted_backend_output else "openai")
    if backend_name == "scripted":
        if args.scripted_backend_output is None:
            raise ValueError("--backend scripted requires --scripted-backend-output")
        return ScriptedBackend(_read_json_object(args.scripted_backend_output))
    if args.scripted_backend_output is not None:
        raise ValueError("--scripted-backend-output can only be used with --backend scripted")
    return OpenAIBackend(model=args.model)


def _handle_feedback(args: argparse.Namespace) -> int:
    event_payload = _record_feedback(
        data_dir=args.data_dir,
        match_id=args.match_id,
        draft_id=args.draft_id,
        mode=ReplyMode(args.mode),
        label=args.label,
    )
    _print_json(event_payload)
    return 0


def _record_feedback(
    *,
    data_dir: Path,
    match_id: str,
    draft_id: str,
    mode: ReplyMode,
    label: str,
) -> dict[str, Any]:
    event = create_feedback_event(
        event_id=f"feedback_{match_id}_{draft_id}_{label}",
        match_id=match_id,
        draft_id=draft_id,
        mode=mode,
        label=label,
        created_at=MVP_TIMESTAMP,
    )
    JsonMemoryRepository(data_dir).append_feedback_event(match_id, event)
    return {
        "status": "ok",
        "match_id": match_id,
        "event_id": event["event_id"],
        "draft_id": draft_id,
        "label": label,
    }


def _build_mvp_context_pack(
    profile: UserProfile,
    match_id: str,
    reply_mode: ReplyMode,
    observation: AppObservation | None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    user_profile = _profile_to_context_dict(profile)
    if observation is None:
        match_profile = {
            "match_id": match_id,
            "conversation_hooks": [],
            "possible_interests": [],
        }
        conversation_memory = {
            "recent_messages": [],
            "open_threads": [],
            "commitments": [],
            "running_summary": "No imported observation was available for this match.",
        }
    else:
        match_profile = _match_profile_from_observation(match_id, observation)
        conversation_memory = _conversation_memory_from_observation(observation)
    if data_dir is not None:
        conversation_memory.update(planner_context_items(PlannerRepository(data_dir).load_plan(match_id)))

    return build_context_pack(
        user_profile=user_profile,
        match_profile=match_profile,
        conversation_memory=conversation_memory,
        reply_mode=reply_mode,
        max_items=None,
    )


def _match_profile_from_observation(match_id: str, observation: AppObservation) -> dict[str, Any]:
    profile = observation.profile_observation
    possible_interest_cues = [*profile.photo_cues, *profile.hook_candidates]
    return {
        "match_id": match_id,
        "display_name": observation.match_identity_hints.visible_name,
        "profile_text": profile.profile_text,
        "conversation_hooks": list(profile.hook_candidates),
        "possible_interests": [
            {"name": cue, "confidence": "medium"}
            for cue in possible_interest_cues
        ],
    }


def _conversation_memory_from_observation(observation: AppObservation) -> dict[str, Any]:
    conversation = observation.conversation_observation
    visible_messages = [dict(message) for message in conversation.visible_messages]
    latest_inbound_messages = [dict(message) for message in conversation.latest_inbound_messages]
    return {
        "recent_messages": visible_messages,
        "latest_inbound_messages": latest_inbound_messages,
        "open_threads": list(conversation.thread_cues),
        "commitments": [],
        "running_summary": _observation_summary(observation),
    }


def _observation_summary(observation: AppObservation) -> str:
    profile_text = observation.profile_observation.profile_text.strip()
    messages = observation.conversation_observation.visible_messages
    latest_inbound = observation.conversation_observation.latest_inbound_messages
    latest_message = (
        latest_inbound[-1].get("text", "").strip()
        if latest_inbound
        else messages[-1].get("text", "").strip()
        if messages
        else ""
    )
    parts = [part for part in [profile_text, latest_message] if part]
    if parts:
        return " ".join(parts)
    return "Imported observation contained no visible conversation text."


def _profile_from_dict(data: dict[str, Any]) -> UserProfile:
    return UserProfile(
        schema_version=data["schema_version"],
        user_id=data["user_id"],
        facts=[MemoryItem.from_dict(item) for item in data["facts"]],
        preferences=[MemoryItem.from_dict(item) for item in data["preferences"]],
        boundaries=[MemoryItem.from_dict(item) for item in data["boundaries"]],
        style_examples=list(data["style_examples"]),
        goals=list(data["goals"]),
        persona_baseline=data["persona_baseline"],
        persona_range=list(data["persona_range"]),
        stance_range=list(data["stance_range"]),
        updated_at=data["updated_at"],
        default_reply_mode=ReplyMode(data.get("default_reply_mode", ReplyMode.ADAPTIVE.value)),
    )


def _profile_to_context_dict(profile: UserProfile) -> dict[str, Any]:
    return {
        "facts": [item.to_dict() for item in profile.facts],
        "preferences": [item.to_dict() for item in profile.preferences],
        "boundaries": [item.to_dict() for item in profile.boundaries],
        "style_examples": list(profile.style_examples),
        "goals": list(profile.goals),
        "persona_baseline": profile.persona_baseline,
        "persona_range": list(profile.persona_range),
        "stance_range": list(profile.stance_range),
    }


def _draft_to_dict(draft: DraftResponse) -> dict[str, Any]:
    data = asdict(draft)
    data["persona_divergence"] = draft.persona_divergence.value
    data["stance_divergence"] = draft.stance_divergence.value
    return data


def _draft_from_dict(data: dict[str, Any]) -> DraftResponse:
    return DraftResponse(
        best_reply=str(data["best_reply"]),
        safer_reply=str(data["safer_reply"]),
        bolder_reply=str(data["bolder_reply"]),
        why_this_works=str(data["why_this_works"]),
        situation_read=str(data["situation_read"]),
        conversation_move=str(data["conversation_move"]),
        hook_source=str(data["hook_source"]),
        naturalness_notes=[str(item) for item in data["naturalness_notes"]],
        followup_if_match_replies=str(data["followup_if_match_replies"]),
        risk_flags=[str(item) for item in data["risk_flags"]],
        missing_info=[str(item) for item in data["missing_info"]],
        mode_notes=str(data["mode_notes"]),
        persona_divergence=Divergence(str(data["persona_divergence"])),
        stance_divergence=Divergence(str(data["stance_divergence"])),
    )


def _policy_to_dict(policy: ContentPolicyDecision) -> dict[str, Any]:
    return {
        "allowed": policy.allowed,
        "severity": policy.severity,
        "reason": policy.reason,
        "requires_user_confirmation": policy.requires_user_confirmation,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _read_json_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_storage_id(value: str, label: str) -> None:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}: {value!r}")


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
