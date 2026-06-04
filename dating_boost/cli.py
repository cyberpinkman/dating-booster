from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
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
from dating_boost.core.daemon import DaemonRepository
from dating_boost.core.diagnostics import DiagnosticsRepository
from dating_boost.core.feedback import create_feedback_event
from dating_boost.core.gui_harness import NativeGuiHarness
from dating_boost.core.identity import resolve_match_identity
from dating_boost.core.models import Divergence, MemoryItem, ReplyMode, UserProfile
from dating_boost.core.observation_authoring import (
    normalize_observation,
    observation_template,
    validate_observation,
)
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.planner import PlannerRepository, planner_context_items
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.release import release_doctor
from dating_boost.core.replay import latest_replay_markdown, latest_replay_payload
from dating_boost.core.repositories import JsonMemoryRepository, MatchRepository, ObservationRepository
from dating_boost.core.scan_authoring import (
    assemble_scan_batch,
    normalize_scan_batch,
    scan_template,
    validate_scan_batch,
)
from dating_boost.core.skill_doctor import run_skill_doctor
from dating_boost.core.safety import SafetyRepository
from dating_boost.intelligence.backends import ModelBackend, OpenAIBackend, ScriptedBackend
from dating_boost.intelligence.reply_generator import DraftResponse, generate_reply
from dating_boost.evals.runner import run_conversation_eval
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.policy import Action, authorize_action
from dating_boost.policy.content import ContentPolicyDecision, evaluate_draft_content
from dating_boost.core.user_disclosure import UserDisclosureRepository, interview_template


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

    data_parser = subparsers.add_parser("data", help="SQLite data-store diagnostics and privacy commands.")
    data_subparsers = data_parser.add_subparsers(dest="data_command", required=True)
    data_doctor_parser = data_subparsers.add_parser("doctor")
    data_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    data_doctor_parser.add_argument("--json", action="store_true")
    data_doctor_parser.set_defaults(handler=_handle_data_doctor)
    data_migrate_parser = data_subparsers.add_parser("migrate")
    data_migrate_parser.add_argument("--data-dir", required=True, type=Path)
    data_migrate_parser.add_argument("--json", action="store_true")
    data_migrate_parser.set_defaults(handler=_handle_data_migrate)
    data_export_parser = data_subparsers.add_parser("export")
    data_export_parser.add_argument("--data-dir", required=True, type=Path)
    data_export_parser.add_argument("--output", required=True, type=Path)
    data_export_parser.add_argument("--json", action="store_true")
    data_export_parser.set_defaults(handler=_handle_data_export)
    data_delete_parser = data_subparsers.add_parser("delete")
    data_delete_parser.add_argument("--data-dir", required=True, type=Path)
    data_delete_parser.add_argument("--scope", required=True, choices=["match", "archived", "all"])
    data_delete_parser.add_argument("--match-id")
    data_delete_parser.add_argument("--confirm", required=True)
    data_delete_parser.add_argument("--json", action="store_true")
    data_delete_parser.set_defaults(handler=_handle_data_delete)
    data_unlock_parser = data_subparsers.add_parser("unlock")
    data_unlock_parser.add_argument("--data-dir", required=True, type=Path)
    data_unlock_parser.add_argument("--json", action="store_true")
    data_unlock_parser.set_defaults(handler=_handle_data_unlock)
    data_lock_parser = data_subparsers.add_parser("lock")
    data_lock_parser.add_argument("--data-dir", required=True, type=Path)
    data_lock_parser.add_argument("--json", action="store_true")
    data_lock_parser.set_defaults(handler=_handle_data_lock)
    data_rekey_parser = data_subparsers.add_parser("rekey")
    data_rekey_parser.add_argument("--data-dir", required=True, type=Path)
    data_rekey_parser.add_argument("--json", action="store_true")
    data_rekey_parser.set_defaults(handler=_handle_data_rekey)
    data_backup_parser = data_subparsers.add_parser("backup")
    data_backup_parser.add_argument("--data-dir", required=True, type=Path)
    data_backup_parser.add_argument("--output", required=True, type=Path)
    data_backup_parser.add_argument("--recovery-passphrase-file", type=Path)
    data_backup_parser.add_argument("--json", action="store_true")
    data_backup_parser.set_defaults(handler=_handle_data_backup)
    data_restore_parser = data_subparsers.add_parser("restore")
    data_restore_parser.add_argument("--data-dir", required=True, type=Path)
    data_restore_parser.add_argument("--input", required=True, type=Path)
    data_restore_parser.add_argument("--confirm", required=True)
    data_restore_parser.add_argument("--recovery-passphrase-file", type=Path)
    data_restore_parser.add_argument("--json", action="store_true")
    data_restore_parser.set_defaults(handler=_handle_data_restore)

    safety_parser = subparsers.add_parser("safety", help="Global local safety switch commands.")
    safety_subparsers = safety_parser.add_subparsers(dest="safety_command", required=True)
    safety_pause_parser = safety_subparsers.add_parser("pause")
    safety_pause_parser.add_argument("--data-dir", required=True, type=Path)
    safety_pause_parser.add_argument("--reason", required=True)
    safety_pause_parser.add_argument("--json", action="store_true")
    safety_pause_parser.set_defaults(handler=_handle_safety_pause)
    safety_resume_parser = safety_subparsers.add_parser("resume")
    safety_resume_parser.add_argument("--data-dir", required=True, type=Path)
    safety_resume_parser.add_argument("--json", action="store_true")
    safety_resume_parser.set_defaults(handler=_handle_safety_resume)
    safety_status_parser = safety_subparsers.add_parser("status")
    safety_status_parser.add_argument("--data-dir", required=True, type=Path)
    safety_status_parser.add_argument("--json", action="store_true")
    safety_status_parser.set_defaults(handler=_handle_safety_status)

    daemon_parser = subparsers.add_parser("daemon", help="Local daemon supervisor commands.")
    daemon_subparsers = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    daemon_run_parser = daemon_subparsers.add_parser("run")
    daemon_run_parser.add_argument("--data-dir", required=True, type=Path)
    daemon_run_parser.add_argument("--once", action="store_true")
    daemon_run_parser.add_argument("--json", action="store_true")
    daemon_run_parser.set_defaults(handler=_handle_daemon_run)
    for command, handler in (
        ("install", _handle_daemon_install),
        ("uninstall", _handle_daemon_uninstall),
        ("status", _handle_daemon_status),
        ("stop", _handle_daemon_stop),
    ):
        daemon_subparser = daemon_subparsers.add_parser(command)
        daemon_subparser.add_argument("--data-dir", required=True, type=Path)
        daemon_subparser.add_argument("--dry-run", action="store_true")
        daemon_subparser.add_argument("--json", action="store_true")
        daemon_subparser.set_defaults(handler=handler)

    diagnostics_parser = subparsers.add_parser("diagnostics", help="Local redacted diagnostics commands.")
    diagnostics_subparsers = diagnostics_parser.add_subparsers(dest="diagnostics_command", required=True)
    diagnostics_doctor_parser = diagnostics_subparsers.add_parser("doctor")
    diagnostics_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    diagnostics_doctor_parser.add_argument("--json", action="store_true")
    diagnostics_doctor_parser.set_defaults(handler=_handle_diagnostics_doctor)
    diagnostics_bundle_parser = diagnostics_subparsers.add_parser("bundle")
    diagnostics_bundle_parser.add_argument("--data-dir", required=True, type=Path)
    diagnostics_bundle_parser.add_argument("--output", required=True, type=Path)
    diagnostics_bundle_parser.add_argument("--json", action="store_true")
    diagnostics_bundle_parser.set_defaults(handler=_handle_diagnostics_bundle)

    harness_parser = subparsers.add_parser("harness", help="Native GUI harness diagnostics and safe navigation.")
    harness_subparsers = harness_parser.add_subparsers(dest="harness_command", required=True)
    harness_doctor_parser = harness_subparsers.add_parser("doctor")
    harness_doctor_parser.add_argument("--app-id", default="tinder")
    harness_doctor_parser.add_argument("--window-title")
    harness_doctor_parser.add_argument("--no-capture", action="store_true")
    harness_doctor_parser.add_argument("--output", type=Path)
    harness_doctor_parser.add_argument("--json", action="store_true")
    harness_doctor_parser.set_defaults(handler=_handle_harness_doctor)
    harness_screenshot_parser = harness_subparsers.add_parser("screenshot")
    harness_screenshot_parser.add_argument("--app-id", default="tinder")
    harness_screenshot_parser.add_argument("--window-title")
    harness_screenshot_parser.add_argument("--output", required=True, type=Path)
    harness_screenshot_parser.add_argument("--json", action="store_true")
    harness_screenshot_parser.set_defaults(handler=_handle_harness_screenshot)
    harness_tinder_parser = harness_subparsers.add_parser("tinder")
    harness_tinder_subparsers = harness_tinder_parser.add_subparsers(dest="harness_tinder_command", required=True)
    harness_tinder_launch_parser = harness_tinder_subparsers.add_parser("launch")
    harness_tinder_launch_parser.add_argument("--window-title", default="iPhone Mirroring")
    harness_tinder_launch_parser.add_argument("--dry-run", action="store_true")
    harness_tinder_launch_parser.add_argument("--output-dir", type=Path)
    harness_tinder_launch_parser.add_argument("--json", action="store_true")
    harness_tinder_launch_parser.set_defaults(handler=_handle_harness_tinder_launch)
    harness_tinder_profile_parser = harness_tinder_subparsers.add_parser("open-profile")
    harness_tinder_profile_parser.add_argument("--window-title", default="iPhone Mirroring")
    harness_tinder_profile_parser.add_argument("--dry-run", action="store_true")
    harness_tinder_profile_parser.add_argument("--launch-if-needed", action="store_true")
    harness_tinder_profile_parser.add_argument("--output-dir", type=Path)
    harness_tinder_profile_parser.add_argument("--json", action="store_true")
    harness_tinder_profile_parser.set_defaults(handler=_handle_harness_tinder_open_profile)
    harness_tinder_observe_parser = harness_tinder_subparsers.add_parser("observe")
    harness_tinder_observe_parser.add_argument("--window-title", default="iPhone Mirroring")
    harness_tinder_observe_parser.add_argument("--output-dir", type=Path)
    harness_tinder_observe_parser.add_argument("--json", action="store_true")
    harness_tinder_observe_parser.set_defaults(handler=_handle_harness_tinder_observe)
    harness_tinder_action_parser = harness_tinder_subparsers.add_parser("action")
    harness_tinder_action_parser.add_argument("action")
    harness_tinder_action_parser.add_argument("--window-title", default="iPhone Mirroring")
    harness_tinder_action_parser.add_argument("--dry-run", action="store_true")
    harness_tinder_action_parser.add_argument("--output-dir", type=Path)
    harness_tinder_action_parser.add_argument("--row-index", type=int)
    harness_tinder_action_parser.add_argument("--match-index", type=int)
    harness_tinder_action_parser.add_argument("--target", choices=["row", "avatar"], default="row")
    harness_tinder_action_parser.add_argument("--json", action="store_true")
    harness_tinder_action_parser.set_defaults(handler=_handle_harness_tinder_action)
    harness_tinder_workflow_parser = harness_tinder_subparsers.add_parser("workflow")
    harness_tinder_workflow_parser.add_argument("workflow")
    harness_tinder_workflow_parser.add_argument("--window-title", default="iPhone Mirroring")
    harness_tinder_workflow_parser.add_argument("--dry-run", action="store_true")
    harness_tinder_workflow_parser.add_argument("--output-dir", type=Path)
    harness_tinder_workflow_parser.add_argument("--photo-steps", type=int)
    harness_tinder_workflow_parser.add_argument("--scroll-steps", type=int)
    harness_tinder_workflow_parser.add_argument("--carousel-swipes", type=int)
    harness_tinder_workflow_parser.add_argument("--conversation-row", type=int)
    harness_tinder_workflow_parser.add_argument("--profile-scroll-steps", type=int)
    harness_tinder_workflow_parser.add_argument("--json", action="store_true")
    harness_tinder_workflow_parser.set_defaults(handler=_handle_harness_tinder_workflow)
    harness_wechat_parser = harness_subparsers.add_parser("wechat")
    harness_wechat_subparsers = harness_wechat_parser.add_subparsers(dest="harness_wechat_command", required=True)
    harness_wechat_launch_parser = harness_wechat_subparsers.add_parser("launch")
    harness_wechat_launch_parser.add_argument("--window-title", default="WeChat")
    harness_wechat_launch_parser.add_argument("--dry-run", action="store_true")
    harness_wechat_launch_parser.add_argument("--output-dir", type=Path)
    harness_wechat_launch_parser.add_argument("--json", action="store_true")
    harness_wechat_launch_parser.set_defaults(handler=_handle_harness_wechat_launch)
    harness_wechat_observe_parser = harness_wechat_subparsers.add_parser("observe")
    harness_wechat_observe_parser.add_argument("--window-title", default="WeChat")
    harness_wechat_observe_parser.add_argument("--output-dir", type=Path)
    harness_wechat_observe_parser.add_argument("--json", action="store_true")
    harness_wechat_observe_parser.set_defaults(handler=_handle_harness_wechat_observe)
    harness_wechat_stage_parser = harness_wechat_subparsers.add_parser("stage-draft")
    harness_wechat_stage_parser.add_argument("--window-title", default="WeChat")
    harness_wechat_stage_parser.add_argument("--text-file", required=True, type=Path)
    harness_wechat_stage_parser.add_argument("--data-dir", type=Path)
    harness_wechat_stage_parser.add_argument("--dry-run", action="store_true")
    harness_wechat_stage_parser.add_argument("--output-dir", type=Path)
    harness_wechat_stage_parser.add_argument("--json", action="store_true")
    harness_wechat_stage_parser.set_defaults(handler=_handle_harness_wechat_stage_draft)
    harness_wechat_send_parser = harness_wechat_subparsers.add_parser("send-message")
    harness_wechat_send_parser.add_argument("--window-title", default="WeChat")
    harness_wechat_send_parser.add_argument("--text-file", required=True, type=Path)
    harness_wechat_send_parser.add_argument("--data-dir", type=Path)
    harness_wechat_send_parser.add_argument("--authorization", type=Path)
    harness_wechat_send_parser.add_argument("--action-request", type=Path)
    harness_wechat_send_parser.add_argument("--dry-run", action="store_true")
    harness_wechat_send_parser.add_argument("--output-dir", type=Path)
    harness_wechat_send_parser.add_argument("--json", action="store_true")
    harness_wechat_send_parser.set_defaults(handler=_handle_harness_wechat_send_message)

    release_parser = subparsers.add_parser("release", help="Public release diagnostics.")
    release_subparsers = release_parser.add_subparsers(dest="release_command", required=True)
    release_doctor_parser = release_subparsers.add_parser("doctor")
    release_doctor_parser.add_argument("--json", action="store_true")
    release_doctor_parser.set_defaults(handler=_handle_release_doctor)

    confirmation_parser = subparsers.add_parser("confirmation", help="Create and validate send confirmations.")
    confirmation_subparsers = confirmation_parser.add_subparsers(dest="confirmation_command", required=True)
    confirmation_create_parser = confirmation_subparsers.add_parser("create")
    _add_confirmation_binding_args(confirmation_create_parser)
    confirmation_create_parser.add_argument("--expires-at", required=True)
    confirmation_create_parser.add_argument("--json", action="store_true")
    confirmation_create_parser.set_defaults(handler=_handle_confirmation_create)
    confirmation_confirm_parser = confirmation_subparsers.add_parser("confirm")
    confirmation_confirm_parser.add_argument("--data-dir", required=True, type=Path)
    confirmation_confirm_parser.add_argument("--confirmation-id", required=True)
    confirmation_confirm_parser.add_argument("--json", action="store_true")
    confirmation_confirm_parser.set_defaults(handler=_handle_confirmation_confirm)
    confirmation_validate_parser = confirmation_subparsers.add_parser("validate")
    confirmation_validate_parser.add_argument("--confirmation-id", required=True)
    _add_confirmation_binding_args(confirmation_validate_parser)
    confirmation_validate_parser.add_argument("--json", action="store_true")
    confirmation_validate_parser.set_defaults(handler=_handle_confirmation_validate)

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
    authorize_parser.add_argument("--data-dir", type=Path)
    authorize_parser.set_defaults(handler=_handle_authorize)

    init_parser = subparsers.add_parser("init-profile", help="Initialize local user profile memory.")
    init_parser.add_argument("--data-dir", required=True, type=Path)
    init_parser.add_argument("--input", required=True, type=Path)
    init_parser.set_defaults(handler=_handle_init_profile)

    user_parser = subparsers.add_parser("user", help="User self model and disclosure readiness commands.")
    user_subparsers = user_parser.add_subparsers(dest="user_command", required=True)
    user_interview_parser = user_subparsers.add_parser("interview", help="User interview helpers.")
    user_interview_subparsers = user_interview_parser.add_subparsers(
        dest="user_interview_command",
        required=True,
    )
    user_interview_template_parser = user_interview_subparsers.add_parser("template")
    user_interview_template_parser.add_argument("--json", action="store_true")
    user_interview_template_parser.set_defaults(handler=_handle_user_interview_template)
    user_ingest_profile_parser = user_subparsers.add_parser("ingest-profile")
    user_ingest_profile_parser.add_argument("--data-dir", required=True, type=Path)
    user_ingest_profile_parser.add_argument("--input", required=True, type=Path)
    user_ingest_profile_parser.set_defaults(handler=_handle_user_ingest_profile)
    user_ingest_interview_parser = user_subparsers.add_parser("ingest-interview")
    user_ingest_interview_parser.add_argument("--data-dir", required=True, type=Path)
    user_ingest_interview_parser.add_argument("--input", required=True, type=Path)
    user_ingest_interview_parser.set_defaults(handler=_handle_user_ingest_interview)
    user_disclosure_profile_parser = user_subparsers.add_parser("disclosure-profile")
    user_disclosure_profile_parser.add_argument("--data-dir", required=True, type=Path)
    user_disclosure_profile_parser.add_argument("--json", action="store_true")
    user_disclosure_profile_parser.set_defaults(handler=_handle_user_disclosure_profile)
    user_readiness_parser = user_subparsers.add_parser("readiness")
    user_readiness_parser.add_argument("--data-dir", required=True, type=Path)
    user_readiness_parser.add_argument("--mode", required=True, choices=["draft", "autonomous"])
    user_readiness_parser.add_argument("--json", action="store_true")
    user_readiness_parser.set_defaults(handler=_handle_user_readiness)

    import_parser = subparsers.add_parser("import-observation", help="Import an app observation fixture.")
    import_parser.add_argument("--data-dir", required=True, type=Path)
    import_parser.add_argument("--input", required=True, type=Path)
    import_parser.set_defaults(handler=_handle_import_observation)

    observation_parser = subparsers.add_parser("observation", help="Host observation authoring helpers.")
    observation_subparsers = observation_parser.add_subparsers(dest="observation_command", required=True)
    observation_template_parser = observation_subparsers.add_parser("template")
    observation_template_parser.add_argument("--type", choices=["message_list", "thread"], default="thread")
    observation_template_parser.add_argument("--app-id", default="tinder")
    observation_template_parser.add_argument("--json", action="store_true")
    observation_template_parser.set_defaults(handler=_handle_observation_template)
    observation_validate_parser = observation_subparsers.add_parser("validate")
    observation_validate_parser.add_argument("--input", required=True, type=Path)
    observation_validate_parser.add_argument("--json", action="store_true")
    observation_validate_parser.set_defaults(handler=_handle_observation_validate)
    observation_normalize_parser = observation_subparsers.add_parser("normalize")
    observation_normalize_parser.add_argument("--input", required=True, type=Path)
    observation_normalize_parser.add_argument("--json", action="store_true")
    observation_normalize_parser.set_defaults(handler=_handle_observation_normalize)

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
    policy_check_action_parser.add_argument("--data-dir", type=Path)
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

    eval_parser = subparsers.add_parser("eval", help="Offline evaluation commands.")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("--suite", required=True, choices=["conversation"])
    eval_run_parser.add_argument("--input", type=Path)
    eval_run_parser.add_argument("--json", action="store_true")
    eval_run_parser.set_defaults(handler=_handle_eval_run)

    replay_parser = subparsers.add_parser("replay", help="Host loop replay commands.")
    replay_subparsers = replay_parser.add_subparsers(dest="replay_command", required=True)
    replay_latest_parser = replay_subparsers.add_parser("latest")
    replay_latest_parser.add_argument("--data-dir", required=True, type=Path)
    replay_latest_parser.add_argument("--format", choices=["json", "md"], default="json")
    replay_latest_parser.set_defaults(handler=_handle_replay_latest)

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
    session_step_parser.add_argument("--run-id")
    session_step_parser.add_argument("--idempotency-key")
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

    operator_parser = subparsers.add_parser("operator", help="Goal-oriented managed operator session commands.")
    operator_subparsers = operator_parser.add_subparsers(dest="operator_command", required=True)

    operator_session_parser = operator_subparsers.add_parser("session", help="Operator session commands.")
    operator_session_subparsers = operator_session_parser.add_subparsers(
        dest="operator_session_command",
        required=True,
    )
    operator_session_start_parser = operator_session_subparsers.add_parser("start")
    operator_session_start_parser.add_argument("--data-dir", required=True, type=Path)
    operator_session_start_parser.add_argument("--authorization", required=True, type=Path)
    operator_session_start_parser.set_defaults(handler=_handle_operator_session_start)

    operator_next_parser = operator_subparsers.add_parser("next")
    operator_next_parser.add_argument("--data-dir", required=True, type=Path)
    operator_next_parser.set_defaults(handler=_handle_operator_next)

    operator_ingest_parser = operator_subparsers.add_parser("ingest-observation")
    operator_ingest_parser.add_argument("--data-dir", required=True, type=Path)
    operator_ingest_parser.add_argument("--input", required=True, type=Path)
    operator_ingest_parser.set_defaults(handler=_handle_operator_ingest_observation)

    operator_record_result_parser = operator_subparsers.add_parser("record-action-result")
    operator_record_result_parser.add_argument("--data-dir", required=True, type=Path)
    operator_record_result_parser.add_argument("--input", required=True, type=Path)
    operator_record_result_parser.set_defaults(handler=_handle_operator_record_action_result)

    operator_stop_parser = operator_subparsers.add_parser("stop")
    operator_stop_parser.add_argument("--data-dir", required=True, type=Path)
    operator_stop_parser.set_defaults(handler=_handle_operator_stop)

    operator_report_parser = operator_subparsers.add_parser("report", help="Operator report commands.")
    operator_report_subparsers = operator_report_parser.add_subparsers(
        dest="operator_report_command",
        required=True,
    )
    operator_report_latest_parser = operator_report_subparsers.add_parser("latest")
    operator_report_latest_parser.add_argument("--data-dir", required=True, type=Path)
    operator_report_latest_parser.add_argument("--format", choices=["json", "md"], default="json")
    operator_report_latest_parser.set_defaults(handler=_handle_operator_report_latest)

    operator_get_state_parser = operator_subparsers.add_parser("get-state")
    operator_get_state_parser.add_argument("--data-dir", required=True, type=Path)
    operator_get_state_parser.set_defaults(handler=_handle_operator_get_state)

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


def _handle_data_doctor(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).doctor()
    _print_json(payload)
    return 0 if payload.get("status") != "blocked" else 2


def _handle_data_migrate(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).migrate()
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_data_export(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).export(args.output)
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_data_delete(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).delete(
        scope=args.scope,
        match_id=args.match_id,
        confirm=args.confirm,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_data_unlock(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).doctor()
    payload = {
        "schema_version": payload["schema_version"],
        "status": "ok" if payload.get("encryption", {}).get("status") != "unknown" else "blocked",
        "encryption": payload.get("encryption"),
        "db_path": payload.get("db_path"),
    }
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_data_lock(args: argparse.Namespace) -> int:
    _print_json(
        {
            "schema_version": 2,
            "status": "ok",
            "data_dir": str(args.data_dir.resolve()),
            "note": "no plaintext key cache is kept by this CLI process",
        }
    )
    return 0


def _handle_data_rekey(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).rekey()
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_data_backup(args: argparse.Namespace) -> int:
    passphrase = _recovery_passphrase(args)
    payload = ProductionDataStore(args.data_dir).backup(args.output, recovery_passphrase=passphrase)
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_data_restore(args: argparse.Namespace) -> int:
    passphrase = _recovery_passphrase(args)
    payload = ProductionDataStore(args.data_dir).restore(
        args.input,
        confirm=args.confirm,
        recovery_passphrase=passphrase,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _recovery_passphrase(args: argparse.Namespace) -> str | None:
    file_path = getattr(args, "recovery_passphrase_file", None)
    if file_path is not None:
        return Path(file_path).read_text(encoding="utf-8").rstrip("\r\n")
    return os.environ.get("DATING_BOOST_RECOVERY_PASSPHRASE")


def _handle_safety_pause(args: argparse.Namespace) -> int:
    payload = SafetyRepository(args.data_dir).pause(reason=args.reason, created_at=_now_iso())
    _print_json(payload)
    return 0


def _handle_safety_resume(args: argparse.Namespace) -> int:
    payload = SafetyRepository(args.data_dir).resume(created_at=_now_iso())
    _print_json(payload)
    return 0


def _handle_safety_status(args: argparse.Namespace) -> int:
    payload = SafetyRepository(args.data_dir).status()
    _print_json(payload)
    return 0


def _handle_daemon_run(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).run(once=args.once, owner="dating-boostd", now=_now_iso())
    _print_json(payload)
    return 0 if payload.get("status") != "blocked" else 2


def _handle_daemon_install(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).install(dry_run=args.dry_run)
    _print_json(payload)
    return 0


def _handle_daemon_uninstall(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).uninstall(dry_run=args.dry_run)
    _print_json(payload)
    return 0


def _handle_daemon_status(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).status()
    _print_json(payload)
    return 0


def _handle_daemon_stop(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).stop(now=_now_iso())
    _print_json(payload)
    return 0


def _handle_diagnostics_doctor(args: argparse.Namespace) -> int:
    payload = DiagnosticsRepository(args.data_dir).doctor()
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_diagnostics_bundle(args: argparse.Namespace) -> int:
    payload = DiagnosticsRepository(args.data_dir).bundle(args.output)
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_harness_doctor(args: argparse.Namespace) -> int:
    harness = NativeGuiHarness(app_id=args.app_id, window_title=_harness_window_title(args.app_id, args.window_title))
    if args.app_id == "wechat":
        payload = harness.doctor_wechat(capture=not args.no_capture, output=args.output)
    else:
        payload = harness.doctor(capture=not args.no_capture, output=args.output)
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "degraded"} else 2


def _handle_harness_screenshot(args: argparse.Namespace) -> int:
    payload = NativeGuiHarness(
        app_id=args.app_id,
        window_title=_harness_window_title(args.app_id, args.window_title),
    ).capture_window(output=args.output)
    payload.pop("text", None)
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_harness_tinder_launch(args: argparse.Namespace) -> int:
    payload = NativeGuiHarness(app_id="tinder", window_title=args.window_title).launch_tinder(
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_harness_tinder_open_profile(args: argparse.Namespace) -> int:
    payload = NativeGuiHarness(app_id="tinder", window_title=args.window_title).open_tinder_profile(
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        launch_if_needed=args.launch_if_needed,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_harness_tinder_observe(args: argparse.Namespace) -> int:
    payload = NativeGuiHarness(app_id="tinder", window_title=args.window_title).observe_tinder_screen(
        output_dir=args.output_dir,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_tinder_action(args: argparse.Namespace) -> int:
    options = {
        "row_index": args.row_index,
        "match_index": args.match_index,
        "target": args.target,
    }
    payload = NativeGuiHarness(app_id="tinder", window_title=args.window_title).run_tinder_action(
        args.action,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        **{key: value for key, value in options.items() if value is not None},
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_tinder_workflow(args: argparse.Namespace) -> int:
    options = {
        "photo_steps": args.photo_steps,
        "scroll_steps": args.scroll_steps,
        "carousel_swipes": args.carousel_swipes,
        "conversation_row": args.conversation_row,
        "profile_scroll_steps": args.profile_scroll_steps,
    }
    payload = NativeGuiHarness(app_id="tinder", window_title=args.window_title).run_tinder_workflow(
        args.workflow,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        **{key: value for key, value in options.items() if value is not None},
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_wechat_launch(args: argparse.Namespace) -> int:
    payload = NativeGuiHarness(app_id="wechat", window_title=args.window_title).launch_wechat(
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_wechat_observe(args: argparse.Namespace) -> int:
    payload = NativeGuiHarness(app_id="wechat", window_title=args.window_title).observe_wechat_screen(
        output_dir=args.output_dir,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_wechat_stage_draft(args: argparse.Namespace) -> int:
    if not args.dry_run:
        if args.data_dir is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "stage_draft",
                    "reason": "data_dir_required_for_safety_check",
                    "next_host_action": "rerun_with_data_dir_or_use_dry_run",
                }
            )
            return 2
        if SafetyRepository(args.data_dir).is_paused():
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "stage_draft",
                    "reason": "safety_paused",
                    "next_host_action": "resume_safety_before_staging",
                }
            )
            return 2
    draft_text = args.text_file.read_text(encoding="utf-8")
    payload = NativeGuiHarness(app_id="wechat", window_title=args.window_title).stage_wechat_draft(
        draft_text,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_wechat_send_message(args: argparse.Namespace) -> int:
    draft_text = args.text_file.read_text(encoding="utf-8")
    action_request: dict[str, Any] | None = None
    if not args.dry_run:
        if args.data_dir is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "send_message",
                    "reason": "data_dir_required_for_safety_check",
                    "next_host_action": "rerun_with_data_dir_or_use_dry_run",
                }
            )
            return 2
        if args.authorization is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "send_message",
                    "reason": "authorization_required_for_live_send",
                    "next_host_action": "provide_explicit_live_send_authorization",
                }
            )
            return 2
        if SafetyRepository(args.data_dir).is_paused():
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "send_message",
                    "reason": "safety_paused",
                    "next_host_action": "resume_safety_before_live_send",
                }
            )
            return 2
        if args.action_request is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "send_message",
                    "reason": "action_request_required_for_live_send",
                    "next_host_action": "provide_policy_checked_action_request",
                }
            )
            return 2
        authorization = _read_json_object(args.authorization)
        auth_reason = _wechat_live_send_authorization_block_reason(authorization)
        if auth_reason is not None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "send_message",
                    "reason": auth_reason,
                    "next_host_action": "provide_explicit_live_send_authorization",
                }
            )
            return 2
        action_request = _read_json_object(args.action_request)
        action_reason = _wechat_live_send_action_request_block_reason(action_request, draft_text)
        if action_reason is not None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": "wechat",
                    "action": "send_message",
                    "reason": action_reason,
                    "next_host_action": "provide_policy_checked_action_request",
                }
            )
            return 2
    payload = NativeGuiHarness(app_id="wechat", window_title=args.window_title).send_wechat_message(
        draft_text,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        target_binding=action_request.get("target_binding") if isinstance(action_request, dict) else None,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _wechat_live_send_authorization_block_reason(authorization: dict[str, Any]) -> str | None:
    if authorization.get("scope") != "send_chat_messages":
        return "authorization_scope_not_send_chat_messages"
    if authorization.get("app_id") != "wechat":
        return "authorization_app_mismatch"
    if authorization.get("revoked_at"):
        return "authorization_revoked"
    expires_at = authorization.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            now = datetime.fromisoformat(_now_iso().replace("Z", "+00:00"))
            if expires <= now:
                return "authorization_expired"
        except ValueError:
            return "authorization_expired"
    else:
        return "authorization_expired"
    if authorization.get("autonomous_send") is not True:
        return "authorization_autonomous_send_disabled"
    if authorization.get("live_send") is not True:
        return "live_send_authorization_required"
    if "send_message" not in authorization.get("allowed_actions", []):
        return "authorization_action_not_allowed"
    if authorization.get("requires_post_action_verification") is not True:
        return "authorization_requires_post_action_verification"
    return None


def _wechat_live_send_action_request_block_reason(action_request: dict[str, Any], draft_text: str) -> str | None:
    if action_request.get("action") != "send_message":
        return "action_request_not_send_message"
    if not isinstance(action_request.get("action_request_id"), str) or not action_request["action_request_id"].strip():
        return "action_request_id_required"
    expected_hash = hashlib.sha256(draft_text.encode("utf-8")).hexdigest()
    if action_request.get("payload_hash") != expected_hash:
        return "action_request_payload_hash_mismatch"
    if action_request.get("requires_post_action_verification") is not True:
        return "action_request_requires_post_action_verification"
    policy = action_request.get("policy")
    if not isinstance(policy, dict) or policy.get("allowed") is not True:
        return "action_request_policy_not_allowed"
    target_binding = action_request.get("target_binding")
    if not isinstance(target_binding, dict):
        return "action_request_target_binding_required"
    required_visible_text = target_binding.get("required_visible_text")
    visible_name = target_binding.get("visible_name")
    has_required_marker = (
        isinstance(required_visible_text, list)
        and any(isinstance(item, str) and item.strip() for item in required_visible_text)
    ) or (isinstance(visible_name, str) and visible_name.strip())
    if not has_required_marker:
        return "action_request_target_binding_required"
    return None


def _harness_window_title(app_id: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    if app_id == "wechat":
        return "WeChat"
    return "iPhone Mirroring"


def _handle_release_doctor(args: argparse.Namespace) -> int:
    payload = release_doctor()
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_confirmation_create(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).create_confirmation(
        action=args.action,
        target_match_id=args.target_match_id,
        payload=_read_json_payload(args.payload_json),
        precondition=_read_json_payload(args.precondition_json),
        expires_at=args.expires_at,
    )
    _print_json(payload)
    return 0


def _handle_confirmation_confirm(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).confirm_confirmation(args.confirmation_id)
    _print_json(payload)
    return 0 if payload.get("status") == "confirmed" else 2


def _handle_confirmation_validate(args: argparse.Namespace) -> int:
    payload = ProductionDataStore(args.data_dir).validate_confirmation(
        confirmation_id=args.confirmation_id,
        action=args.action,
        target_match_id=args.target_match_id,
        payload=_read_json_payload(args.payload_json),
        precondition=_read_json_payload(args.precondition_json),
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_authorize(args: argparse.Namespace) -> int:
    return _print_action_decision(args)


def _handle_policy_check_action(args: argparse.Namespace) -> int:
    return _print_action_decision(args)


def _print_action_decision(args: argparse.Namespace) -> int:
    data_dir = getattr(args, "data_dir", None)
    if data_dir is not None and SafetyRepository(data_dir).is_paused():
        _print_json(
            {
                "allowed": False,
                "action": Action(args.action).value,
                "autonomous": bool(args.autonomous),
                "reason": "safety_paused",
            }
        )
        return 2
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


def _handle_user_interview_template(args: argparse.Namespace) -> int:
    _print_json(interview_template())
    return 0


def _handle_user_ingest_profile(args: argparse.Namespace) -> int:
    payload = UserDisclosureRepository(args.data_dir).save_dating_profile(_read_json_object(args.input), updated_at=_now_iso())
    _print_json(payload)
    return 0


def _handle_user_ingest_interview(args: argparse.Namespace) -> int:
    try:
        payload = UserDisclosureRepository(args.data_dir).save_interview(_read_json_object(args.input), updated_at=_now_iso())
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
    return 0


def _handle_user_disclosure_profile(args: argparse.Namespace) -> int:
    try:
        profile = UserDisclosureRepository(args.data_dir).load_profile()
    except FileNotFoundError:
        _print_json({"schema_version": 1, "status": "not_found", "reason": "missing_user_disclosure_profile"})
        return 2
    _print_json({"schema_version": 1, "status": "ok", "profile": profile})
    return 0


def _handle_user_readiness(args: argparse.Namespace) -> int:
    payload = UserDisclosureRepository(args.data_dir).readiness(mode=args.mode)
    _print_json(payload)
    return 0 if payload["ready"] else 2


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


def _handle_observation_template(args: argparse.Namespace) -> int:
    _print_json(observation_template(args.type, args.app_id))
    return 0


def _handle_observation_validate(args: argparse.Namespace) -> int:
    payload = validate_observation(_read_json_object(args.input))
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_observation_normalize(args: argparse.Namespace) -> int:
    observation = normalize_observation(_read_json_object(args.input))
    validation = validate_observation(observation)
    payload = {
        "schema_version": 1,
        "status": validation["status"],
        "observation": observation,
        "validation": validation,
    }
    _print_json(payload)
    return 0 if validation["status"] == "ok" else 2


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
    payload = AutomationRepository(args.data_dir).start_session(_read_json_object(args.authorization))
    _print_json(payload)
    return 0 if payload.get("status") == "active" else 2


def _handle_automation_session_step(args: argparse.Namespace) -> int:
    scan_batch = _read_json_object(args.scan_batch)
    run_id = args.run_id or _derive_run_id(scan_batch)
    idempotency_key = args.idempotency_key or _derive_idempotency_key(scan_batch)
    store = ProductionDataStore(args.data_dir)
    replay = store.load_idempotency(idempotency_key)
    if replay is not None:
        payload = dict(replay)
        replayed_action_requests = list(payload.get("action_requests", []))
        replayed_scheduled_actions = list(payload.get("scheduled_actions", []))
        replay_warnings = [*payload.get("warnings", []), "idempotency_replay"]
        if replayed_action_requests:
            replay_warnings.append("duplicate_send_request_suppressed")
        if replayed_scheduled_actions:
            replay_warnings.append("duplicate_scheduled_action_suppressed")
        payload["warnings"] = _unique_cli_strings(replay_warnings)
        payload["replayed_action_request_ids"] = [
            item.get("action_request_id")
            for item in replayed_action_requests
            if isinstance(item, dict) and item.get("action_request_id")
        ]
        payload["replayed_scheduled_action_count"] = len(replayed_scheduled_actions)
        payload["action_requests"] = []
        payload["handoffs"] = []
        payload["scan_requests"] = []
        payload["scheduled_actions"] = []
        payload["lock"] = {
            "schema_version": 1,
            "lock_name": "automation_session_step",
            "status": "replayed",
        }
        _print_json(payload)
        return 0

    lock_result = store.acquire_lock(
        "automation_session_step",
        owner="dating-boost-cli",
        run_id=run_id,
    )
    if not lock_result.acquired:
        _print_json(_lock_blocked_payload(lock_result.lock, run_id=run_id, idempotency_key=idempotency_key))
        return 0

    try:
        payload = AutomationRepository(args.data_dir).step(scan_batch)
    finally:
        released_lock = store.release_lock("automation_session_step", run_id=run_id)
    payload["run_id"] = run_id
    payload["idempotency_key"] = idempotency_key
    payload["lock"] = {**released_lock, "takeover": bool(lock_result.lock.get("takeover"))}
    if payload.get("status") == "ok" and payload.get("action_requests"):
        store.store_idempotency(idempotency_key, run_id=run_id, response=payload)
    _print_json(payload)
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


def _handle_operator_session_start(args: argparse.Namespace) -> int:
    payload = OperatorRepository(args.data_dir).start_session(_read_json_object(args.authorization))
    _print_json(payload)
    return 0 if payload.get("status") == "active" else 2


def _handle_operator_next(args: argparse.Namespace) -> int:
    run_id = f"run_operator_next_{_digest({'now': _now_iso(), 'data_dir': str(args.data_dir)})[:12]}"
    store = ProductionDataStore(args.data_dir)
    lock_result = store.acquire_lock(
        "operator_next",
        owner="dating-boost-cli",
        run_id=run_id,
    )
    if not lock_result.acquired:
        _print_json(
            {
                "schema_version": 1,
                "status": "blocked",
                "reason": "automation_lock_active",
                "work_item": None,
                "lock": lock_result.lock,
            }
        )
        return 2
    try:
        payload = OperatorRepository(args.data_dir).next_work_item()
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    finally:
        released_lock = store.release_lock("operator_next", run_id=run_id)
    payload["lock"] = {**released_lock, "takeover": bool(lock_result.lock.get("takeover"))}
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_operator_ingest_observation(args: argparse.Namespace) -> int:
    try:
        payload = OperatorRepository(args.data_dir).ingest_observation(_read_json_object(args.input))
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
    return 0


def _handle_operator_record_action_result(args: argparse.Namespace) -> int:
    try:
        payload = OperatorRepository(args.data_dir).record_action_result(_read_json_object(args.input))
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
    return 0


def _handle_operator_stop(args: argparse.Namespace) -> int:
    try:
        payload = OperatorRepository(args.data_dir).stop_session()
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
    return 0


def _handle_operator_report_latest(args: argparse.Namespace) -> int:
    repo = OperatorRepository(args.data_dir)
    payload = repo.latest_report()
    if args.format == "md":
        if payload["status"] != "ok":
            _print_json(payload)
            return 2
        sys.stdout.write(repo.latest_human_report() + "\n")
        return 0
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_operator_get_state(args: argparse.Namespace) -> int:
    _print_json(OperatorRepository(args.data_dir).get_state_payload())
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


def _handle_eval_run(args: argparse.Namespace) -> int:
    if args.suite != "conversation":
        _print_json({"schema_version": 1, "status": "error", "reason": "unsupported_eval_suite"})
        return 2
    result = run_conversation_eval(args.input)
    payload = {
        "schema_version": 1,
        "status": "ok" if result.passed else "failed",
        "suite": "conversation",
        "case_count": result.case_count,
        "passed": result.passed,
        "failures": list(result.failures),
        "cases": result.cases,
    }
    _print_json(payload)
    return 0 if result.passed else 2


def _handle_replay_latest(args: argparse.Namespace) -> int:
    payload = latest_replay_payload(args.data_dir)
    if args.format == "md":
        sys.stdout.write(latest_replay_markdown(args.data_dir) + "\n")
        return 0 if payload["status"] == "ok" else 2
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


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
    if data_dir is not None:
        disclosure_repo = UserDisclosureRepository(data_dir)
        disclosure_profile = disclosure_repo.load_profile_or_none()
        if disclosure_profile is not None:
            user_profile["disclosure_profile"] = disclosure_profile
        user_profile["disclosure_readiness"] = disclosure_repo.readiness(mode="draft")
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


def _add_confirmation_binding_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--action", required=True, choices=[action.value for action in Action])
    parser.add_argument("--target-match-id", required=True)
    parser.add_argument("--payload-json", required=True, type=Path)
    parser.add_argument("--precondition-json", required=True, type=Path)


def _derive_run_id(scan_batch: dict[str, Any]) -> str:
    return f"run_{_digest({'idempotency': _idempotency_seed(scan_batch), 'now': _now_iso()})[:16]}"


def _derive_idempotency_key(scan_batch: dict[str, Any]) -> str:
    return "idem:" + _digest(_idempotency_seed(scan_batch))


def _idempotency_seed(scan_batch: dict[str, Any]) -> dict[str, Any]:
    entries = list(scan_batch.get("message_list_snapshot", {}).get("entries", []))
    first_candidate = entries[0].get("candidate_key") if entries and isinstance(entries[0], dict) else None
    fingerprints: list[str] = []
    for item in scan_batch.get("thread_observations", []):
        if not isinstance(item, dict):
            continue
        assessment = item.get("assessment")
        if isinstance(assessment, dict) and assessment.get("latest_inbound_fingerprint"):
            fingerprints.append(str(assessment["latest_inbound_fingerprint"]))
    return {
        "session_id": scan_batch.get("session_id"),
        "candidate_key": first_candidate,
        "latest_inbound_fingerprint": fingerprints[0] if fingerprints else None,
    }


def _lock_blocked_payload(lock: dict[str, Any], *, run_id: str, idempotency_key: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": "automation_lock_active",
        "run_id": run_id,
        "idempotency_key": idempotency_key,
        "lock": lock,
        "action_requests": [],
        "handoffs": [],
        "scan_requests": [],
        "scheduled_actions": [],
        "warnings": ["automation_lock_active"],
    }


def _unique_cli_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item)
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_storage_id(value: str, label: str) -> None:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}: {value!r}")


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
