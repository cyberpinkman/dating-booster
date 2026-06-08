from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dating_boost.apps.registry import adapter_manifests, create_adapter, manifest_for_app, supported_app_ids
from dating_boost.core.agent_adapters import (
    install_claude_code_adapter,
    install_codex_adapter,
    install_openclaw_adapter,
    run_claude_code_adapter_doctor,
    run_codex_adapter_doctor,
    run_openclaw_adapter_doctor,
)
from dating_boost.core.action_audit import ActionAuditRepository
from dating_boost.core.automation import AutomationRepository
from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.daemon import DaemonRepository
from dating_boost.core.diagnostics import DiagnosticsRepository
from dating_boost.core.feedback import create_feedback_event
from dating_boost.core.live_send_contract import (
    live_send_action_request_block_reason,
    live_send_authorization_block_reason,
    live_send_next_host_action,
    managed_live_send_guidance,
    validate_live_send_contract,
)
from dating_boost.core.managed_session import ManagedSessionRepository
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.models import (
    CommitmentMemory,
    EvidenceRef,
    MemoryEvent,
    MemoryEventType,
    MemoryFact,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.memory.retrieval import build_memory_context
from dating_boost.core.models import Divergence, MemoryItem, ReplyMode, UserProfile
from dating_boost.core.observation_authoring import (
    normalize_observation,
    observation_template,
    validate_observation,
)
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.planner import PlannerRepository, planner_context_items
from dating_boost.core.production_store import ProductionDataStore, payload_digest
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
from dating_boost.core.storage import StorageError
from dating_boost.core.support import SupportLogRepository, classify_text_topics, context_source_manifest
from dating_boost.intelligence.backends import ModelBackend, OpenAIBackend, ScriptedBackend
from dating_boost.intelligence.reply_generator import DraftResponse, generate_reply
from dating_boost.evals.runner import run_conversation_eval, run_memory_eval, run_memory_review_eval
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.policy import Action, authorize_action
from dating_boost.policy.content import ContentPolicyDecision, evaluate_draft_content
from dating_boost.core.user_disclosure import UserDisclosureRepository, interview_template


MVP_TIMESTAMP = "2026-05-25T00:00:00Z"
SUPPORTED_NATIVE_HARNESS_APPS = tuple(supported_app_ids())
SUPPORTED_MANAGED_SESSION_APPS = tuple(supported_app_ids())


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    argv_list = None if argv is None else list(argv)
    command_tokens = sys.argv[1:] if argv is None else argv_list
    if command_tokens and command_tokens[0] in {action.value for action in Action}:
        return _run_authorization(command_tokens)
    unsupported_harness_payload = _unsupported_harness_app_argv_payload(command_tokens)
    if unsupported_harness_payload is not None:
        _print_json(unsupported_harness_payload)
        return 2

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

    adapter_parser = subparsers.add_parser("adapter", help="Host-agent adapter installation and diagnostics.")
    adapter_subparsers = adapter_parser.add_subparsers(dest="adapter_command", required=True)

    codex_parser = adapter_subparsers.add_parser("codex", help="Codex adapter commands.")
    codex_subparsers = codex_parser.add_subparsers(dest="codex_command", required=True)
    codex_install_parser = codex_subparsers.add_parser("install")
    codex_install_parser.add_argument("--scope", choices=["project", "user"], default="user")
    codex_install_parser.add_argument("--target", type=Path)
    codex_install_parser.add_argument("--dry-run", action="store_true")
    codex_install_parser.add_argument("--json", action="store_true")
    codex_install_parser.set_defaults(handler=_handle_adapter_codex_install)
    codex_doctor_parser = codex_subparsers.add_parser("doctor")
    codex_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    codex_doctor_parser.add_argument("--json", action="store_true")
    codex_doctor_parser.set_defaults(handler=_handle_adapter_codex_doctor)

    claude_parser = adapter_subparsers.add_parser("claude-code", help="Claude Code adapter commands.")
    claude_subparsers = claude_parser.add_subparsers(dest="claude_code_command", required=True)
    claude_install_parser = claude_subparsers.add_parser("install")
    claude_install_parser.add_argument("--scope", choices=["project", "user"], default="project")
    claude_install_parser.add_argument("--target", type=Path)
    claude_install_parser.add_argument("--dry-run", action="store_true")
    claude_install_parser.add_argument("--json", action="store_true")
    claude_install_parser.set_defaults(handler=_handle_adapter_claude_code_install)
    claude_doctor_parser = claude_subparsers.add_parser("doctor")
    claude_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    claude_doctor_parser.add_argument("--json", action="store_true")
    claude_doctor_parser.set_defaults(handler=_handle_adapter_claude_code_doctor)

    openclaw_parser = adapter_subparsers.add_parser("openclaw", help="OpenClaw adapter commands.")
    openclaw_subparsers = openclaw_parser.add_subparsers(dest="openclaw_command", required=True)
    openclaw_install_parser = openclaw_subparsers.add_parser("install")
    openclaw_install_parser.add_argument("--scope", choices=["project", "user"], default="project")
    openclaw_install_parser.add_argument("--target", type=Path)
    openclaw_install_parser.add_argument("--dry-run", action="store_true")
    openclaw_install_parser.add_argument("--json", action="store_true")
    openclaw_install_parser.set_defaults(handler=_handle_adapter_openclaw_install)
    openclaw_doctor_parser = openclaw_subparsers.add_parser("doctor")
    openclaw_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    openclaw_doctor_parser.add_argument("--json", action="store_true")
    openclaw_doctor_parser.set_defaults(handler=_handle_adapter_openclaw_doctor)

    hermes_parser = adapter_subparsers.add_parser(
        "hermes",
        help="Hermes adapter commands using the OpenClaw-compatible skill contract.",
    )
    hermes_subparsers = hermes_parser.add_subparsers(dest="hermes_command", required=True)
    hermes_install_parser = hermes_subparsers.add_parser("install")
    hermes_install_parser.add_argument("--scope", choices=["project", "user"], default="project")
    hermes_install_parser.add_argument("--target", type=Path)
    hermes_install_parser.add_argument("--dry-run", action="store_true")
    hermes_install_parser.add_argument("--json", action="store_true")
    hermes_install_parser.set_defaults(handler=_handle_adapter_hermes_install)
    hermes_doctor_parser = hermes_subparsers.add_parser("doctor")
    hermes_doctor_parser.add_argument("--data-dir", required=True, type=Path)
    hermes_doctor_parser.add_argument("--json", action="store_true")
    hermes_doctor_parser.set_defaults(handler=_handle_adapter_hermes_doctor)

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

    support_parser = subparsers.add_parser("support", help="Local support logging and evidence bundle commands.")
    support_subparsers = support_parser.add_subparsers(dest="support_command", required=True)
    support_session_parser = support_subparsers.add_parser("session")
    support_session_subparsers = support_session_parser.add_subparsers(dest="support_session_command", required=True)
    support_session_start_parser = support_session_subparsers.add_parser("start")
    support_session_start_parser.add_argument("--data-dir", required=True, type=Path)
    support_session_start_parser.add_argument("--host", required=True, choices=["codex", "claude-code", "openclaw", "hermes"])
    support_session_start_parser.add_argument("--app-id", required=True)
    support_session_start_parser.add_argument("--json", action="store_true")
    support_session_start_parser.set_defaults(handler=_handle_support_session_start)
    support_session_stop_parser = support_session_subparsers.add_parser("stop")
    support_session_stop_parser.add_argument("--data-dir", required=True, type=Path)
    support_session_stop_parser.add_argument("--session-id", required=True)
    support_session_stop_parser.add_argument("--json", action="store_true")
    support_session_stop_parser.set_defaults(handler=_handle_support_session_stop)
    support_record_parser = support_subparsers.add_parser("record-event")
    support_record_parser.add_argument("--data-dir", required=True, type=Path)
    support_record_parser.add_argument("--session-id", required=True)
    support_record_parser.add_argument("--event-type", required=True)
    support_record_parser.add_argument("--payload", required=True, type=Path)
    support_record_parser.add_argument("--sensitive", type=Path)
    support_record_parser.add_argument("--sensitive-kind")
    support_record_parser.add_argument("--json", action="store_true")
    support_record_parser.set_defaults(handler=_handle_support_record_event)
    support_bundle_parser = support_subparsers.add_parser("bundle")
    support_bundle_parser.add_argument("--data-dir", required=True, type=Path)
    support_bundle_parser.add_argument("--session-id", required=True)
    support_bundle_parser.add_argument("--output", required=True, type=Path)
    support_bundle_parser.add_argument("--redaction", choices=["strict", "standard", "full-with-consent"], default="strict")
    support_bundle_parser.add_argument("--include-sensitive", default="")
    support_bundle_parser.add_argument("--confirm")
    support_bundle_parser.add_argument("--json", action="store_true")
    support_bundle_parser.set_defaults(handler=_handle_support_bundle)

    harness_parser = subparsers.add_parser("harness", help="Native GUI harness diagnostics and safe navigation.")
    harness_subparsers = harness_parser.add_subparsers(dest="harness_command", required=True)
    harness_doctor_parser = harness_subparsers.add_parser("doctor")
    harness_doctor_parser.add_argument("--app-id", default="tinder")
    harness_doctor_parser.add_argument("--data-dir", type=Path)
    harness_doctor_parser.add_argument("--window-title")
    harness_doctor_parser.add_argument("--no-capture", action="store_true")
    harness_doctor_parser.add_argument("--output", type=Path)
    harness_doctor_parser.add_argument("--json", action="store_true")
    harness_doctor_parser.set_defaults(handler=_handle_harness_doctor)
    harness_screenshot_parser = harness_subparsers.add_parser("screenshot")
    harness_screenshot_parser.add_argument("--app-id", default="tinder")
    harness_screenshot_parser.add_argument("--data-dir", type=Path)
    harness_screenshot_parser.add_argument("--window-title")
    harness_screenshot_parser.add_argument("--output", required=True, type=Path)
    harness_screenshot_parser.add_argument("--json", action="store_true")
    harness_screenshot_parser.set_defaults(handler=_handle_harness_screenshot)
    _add_harness_app_parsers(harness_subparsers)

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
    memory_rebuild_parser = memory_subparsers.add_parser(
        "rebuild",
        help="Rebuild one match memory projection from existing observations.",
    )
    memory_rebuild_parser.add_argument("--data-dir", required=True, type=Path)
    memory_rebuild_target = memory_rebuild_parser.add_mutually_exclusive_group(required=True)
    memory_rebuild_target.add_argument("--match-id")
    memory_rebuild_target.add_argument("--all", action="store_true")
    memory_rebuild_parser.set_defaults(handler=_handle_memory_rebuild)
    memory_update_parser = memory_subparsers.add_parser(
        "update-match",
        help="Append a user-authored memory update event and rebuild the match projection.",
    )
    memory_update_parser.add_argument("--data-dir", required=True, type=Path)
    memory_update_parser.add_argument("--match-id", required=True)
    memory_update_parser.add_argument("--input", required=True, type=Path)
    memory_update_parser.set_defaults(handler=_handle_memory_update_match)
    memory_export_parser = memory_subparsers.add_parser(
        "export",
        help="Export one match memory projection and event stream without raw screenshots.",
    )
    memory_export_parser.add_argument("--data-dir", required=True, type=Path)
    memory_export_parser.add_argument("--match-id", required=True)
    memory_export_parser.set_defaults(handler=_handle_memory_export)
    memory_delete_parser = memory_subparsers.add_parser(
        "delete-match",
        help="Delete one match-local memory record after exact confirmation.",
    )
    memory_delete_parser.add_argument("--data-dir", required=True, type=Path)
    memory_delete_parser.add_argument("--match-id", required=True)
    memory_delete_parser.add_argument("--confirm", required=True)
    memory_delete_parser.set_defaults(handler=_handle_memory_delete_match)
    memory_propose_parser = memory_subparsers.add_parser(
        "propose",
        help="Extract memory proposals from an observation without writing to long-term memory.",
    )
    memory_propose_parser.add_argument("--data-dir", required=True, type=Path)
    memory_propose_parser.add_argument("--match-id", required=True)
    memory_propose_parser.add_argument("--input", required=True, type=Path)
    memory_propose_parser.add_argument("--session-id", default="")
    memory_propose_parser.add_argument("--store-review-queue", action="store_true")
    memory_propose_parser.set_defaults(handler=_handle_memory_propose)
    memory_review_parser = memory_subparsers.add_parser("review", help="Memory review queue commands.")
    memory_review_subparsers = memory_review_parser.add_subparsers(dest="memory_review_command", required=True)
    memory_review_list_parser = memory_review_subparsers.add_parser(
        "list",
        help="List pending or filtered memory review items.",
    )
    memory_review_list_parser.add_argument("--data-dir", required=True, type=Path)
    memory_review_list_parser.add_argument("--status", default="pending")
    memory_review_list_parser.add_argument("--match-id", default=None)
    memory_review_list_parser.add_argument("--session-id", default=None)
    memory_review_list_parser.set_defaults(handler=_handle_memory_review_list)
    memory_review_decide_parser = memory_review_subparsers.add_parser(
        "decide",
        help="Accept or reject memory review items.",
    )
    memory_review_decide_parser.add_argument("--data-dir", required=True, type=Path)
    memory_review_decide_parser.add_argument("--accept", nargs="*", default=[])
    memory_review_decide_parser.add_argument("--reject", nargs="*", default=[])
    memory_review_decide_parser.add_argument("--confirm", required=True)
    memory_review_decide_parser.set_defaults(handler=_handle_memory_review_decide)

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
    context_build_parser.add_argument("--max-memory-items", type=int)
    context_build_parser.add_argument("--include-memory-diagnostics", action="store_true")
    context_build_parser.add_argument("--semantic-provider", choices=["none", "lexical"], default="none")
    context_build_parser.add_argument("--semantic-query", default=None)
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
    policy_check_draft_parser.add_argument("--data-dir", type=Path)
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
    feedback_parser.add_argument("--referenced-memory-id", action="append", default=[])
    feedback_parser.add_argument("--conversation-move")
    feedback_parser.add_argument("--hook-source")
    feedback_parser.add_argument("--edited-text-ref")
    feedback_parser.add_argument("--user-confirmed-style-promotion", action="store_true")
    feedback_parser.set_defaults(handler=_handle_feedback)

    eval_parser = subparsers.add_parser("eval", help="Offline evaluation commands.")
    eval_subparsers = eval_parser.add_subparsers(dest="eval_command", required=True)
    eval_run_parser = eval_subparsers.add_parser("run")
    eval_run_parser.add_argument("--suite", required=True, choices=["conversation", "memory", "memory-review"])
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
    planner_update_parser.add_argument("--goal-type", default="meet_in_person")
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

    managed_session_parser = subparsers.add_parser("managed-session", help="Session-scoped managed runner commands.")
    managed_session_subparsers = managed_session_parser.add_subparsers(dest="managed_session_command", required=True)
    managed_start_parser = managed_session_subparsers.add_parser("start")
    managed_start_parser.add_argument("--app-id", required=True, choices=SUPPORTED_MANAGED_SESSION_APPS)
    managed_start_parser.add_argument("--data-dir", required=True, type=Path)
    managed_start_parser.add_argument("--authorization", required=True, type=Path)
    managed_start_parser.add_argument("--goal", required=True, type=Path)
    managed_start_parser.add_argument("--availability", required=True, type=Path)
    managed_start_parser.add_argument("--send-mode", choices=["stage", "live"], default="stage")
    managed_start_parser.add_argument("--managed-gui-send", action="store_true")
    managed_start_parser.add_argument("--scan-interval", type=int, default=120)
    managed_start_parser.add_argument("--nudge-delay-minutes", type=int, default=30)
    managed_start_parser.add_argument("--json", action="store_true")
    managed_start_parser.set_defaults(handler=_handle_managed_session_start)
    managed_tick_parser = managed_session_subparsers.add_parser("tick")
    managed_tick_parser.add_argument("--data-dir", required=True, type=Path)
    managed_tick_parser.add_argument("--json", action="store_true")
    managed_tick_parser.set_defaults(handler=_handle_managed_session_tick)
    managed_run_parser = managed_session_subparsers.add_parser("run")
    managed_run_parser.add_argument("--data-dir", required=True, type=Path)
    managed_run_parser.add_argument("--wait", action="store_true")
    managed_run_parser.add_argument("--wait-timeout", type=float)
    managed_run_parser.add_argument("--poll-interval", type=float, default=1.0)
    managed_run_parser.add_argument("--json", action="store_true")
    managed_run_parser.set_defaults(handler=_handle_managed_session_run)
    managed_notify_parser = managed_session_subparsers.add_parser("notify")
    managed_notify_parser.add_argument("--data-dir", required=True, type=Path)
    managed_notify_parser.add_argument("--source", required=True, choices=["host_notification", "manual"])
    managed_notify_parser.add_argument("--app-id", required=True, choices=SUPPORTED_MANAGED_SESSION_APPS)
    managed_notify_parser.add_argument("--json", action="store_true")
    managed_notify_parser.set_defaults(handler=_handle_managed_session_notify)
    managed_status_parser = managed_session_subparsers.add_parser("status")
    managed_status_parser.add_argument("--data-dir", required=True, type=Path)
    managed_status_parser.add_argument("--json", action="store_true")
    managed_status_parser.set_defaults(handler=_handle_managed_session_status)
    managed_stop_parser = managed_session_subparsers.add_parser("stop")
    managed_stop_parser.add_argument("--data-dir", required=True, type=Path)
    managed_stop_parser.add_argument("--reason", default="manual_stop")
    managed_stop_parser.add_argument("--json", action="store_true")
    managed_stop_parser.set_defaults(handler=_handle_managed_session_stop)

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
    return _run_handler_with_support_logging(args, command_tokens)


def _add_harness_app_parsers(harness_subparsers: argparse._SubParsersAction) -> None:
    for app_id, manifest in adapter_manifests().items():
        app_parser = harness_subparsers.add_parser(app_id)
        app_subparsers = app_parser.add_subparsers(dest="harness_app_command", required=True)

        launch_parser = app_subparsers.add_parser("launch")
        _add_harness_common_args(launch_parser, include_dry_run=True)
        launch_parser.set_defaults(handler=_handle_harness_app_launch, app_id=app_id)

        observe_parser = app_subparsers.add_parser("observe")
        _add_harness_common_args(observe_parser)
        observe_parser.set_defaults(handler=_handle_harness_app_observe, app_id=app_id)

        if manifest.supported_actions:
            action_parser = app_subparsers.add_parser("action")
            action_parser.add_argument("action")
            _add_harness_common_args(action_parser, include_dry_run=True)
            action_parser.add_argument("--options-json", type=Path)
            action_parser.set_defaults(handler=_handle_harness_app_action, app_id=app_id)

        if manifest.supported_workflows:
            workflow_parser = app_subparsers.add_parser("workflow")
            workflow_parser.add_argument("workflow")
            _add_harness_common_args(workflow_parser, include_dry_run=True)
            workflow_parser.add_argument("--options-json", type=Path)
            workflow_parser.set_defaults(handler=_handle_harness_app_workflow, app_id=app_id)

        if "stage_draft" in manifest.supported_stage_actions:
            stage_parser = app_subparsers.add_parser("stage-draft")
            _add_harness_common_args(stage_parser, include_dry_run=True)
            stage_parser.add_argument("--text-file", required=True, type=Path)
            stage_parser.set_defaults(handler=_handle_harness_app_stage_draft, app_id=app_id)

        if "send_message" in manifest.supported_live_actions:
            send_parser = app_subparsers.add_parser("send-message")
            _add_harness_common_args(send_parser, include_dry_run=True)
            send_parser.add_argument("--text-file", required=True, type=Path)
            send_parser.add_argument("--authorization", type=Path)
            send_parser.add_argument("--action-request", type=Path)
            send_parser.set_defaults(handler=_handle_harness_app_send_message, app_id=app_id)

        for alias_name, alias_spec in manifest.cli_aliases.items():
            alias_parser = app_subparsers.add_parser(alias_name)
            include_dry_run = alias_spec.get("include_dry_run") is not False
            _add_harness_common_args(alias_parser, include_dry_run=include_dry_run)
            for option in alias_spec.get("options") or []:
                if not isinstance(option, dict):
                    continue
                option_name = str(option.get("name") or "")
                if not option_name:
                    continue
                kwargs: dict[str, Any] = {}
                if option.get("dest"):
                    kwargs["dest"] = str(option["dest"])
                if option.get("action") == "store_true":
                    kwargs["action"] = "store_true"
                alias_parser.add_argument(option_name, **kwargs)
            alias_parser.set_defaults(
                handler=_handle_harness_app_alias,
                app_id=app_id,
                harness_alias=alias_name,
                harness_alias_spec=alias_spec,
            )


def _add_harness_common_args(parser: argparse.ArgumentParser, *, include_dry_run: bool = False) -> None:
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--window-title")
    parser.add_argument("--output-dir", type=Path)
    if include_dry_run:
        parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")


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


def _unsupported_harness_app_argv_payload(argv: list[str]) -> dict[str, Any] | None:
    if len(argv) < 3 or argv[0] != "harness":
        return None
    app_id = argv[1]
    if app_id in {"doctor", "screenshot"} or app_id in SUPPORTED_NATIVE_HARNESS_APPS:
        return None
    return {
        "schema_version": 2,
        "status": "blocked",
        "reason": "unsupported_native_harness_for_app",
        "app_id": app_id,
        "supported_native_harness_apps": list(SUPPORTED_NATIVE_HARNESS_APPS),
    }


def _run_handler_with_support_logging(args: argparse.Namespace, command_tokens: list[str]) -> int:
    data_dir = getattr(args, "data_dir", None)
    if data_dir is None or getattr(args, "command", None) == "support":
        return args.handler(args)
    repository = SupportLogRepository(data_dir)
    started = repository.record_command_started(command_tokens)
    start = time.monotonic()
    try:
        exit_code = args.handler(args)
    except Exception:
        repository.record_command_finished(
            started,
            argv=command_tokens,
            exit_code=99,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise
    repository.record_command_finished(
        started,
        argv=command_tokens,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return exit_code


def _handle_capabilities(args: argparse.Namespace) -> int:
    _print_json(build_capabilities(args.data_dir))
    return 0


def _handle_skill_doctor(args: argparse.Namespace) -> int:
    payload = run_skill_doctor(args.package, args.data_dir)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_adapter_claude_code_install(args: argparse.Namespace) -> int:
    payload = install_claude_code_adapter(scope=args.scope, target=args.target, dry_run=args.dry_run)
    _print_json(payload)
    return 0 if payload["status"] in {"ok", "dry_run"} else 2


def _handle_adapter_claude_code_doctor(args: argparse.Namespace) -> int:
    payload = run_claude_code_adapter_doctor(args.data_dir)
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_adapter_openclaw_install(args: argparse.Namespace) -> int:
    payload = install_openclaw_adapter(
        scope=args.scope,
        target=args.target,
        dry_run=args.dry_run,
        target_host="openclaw",
    )
    _print_json(payload)
    return 0 if payload["status"] in {"ok", "dry_run"} else 2


def _handle_adapter_openclaw_doctor(args: argparse.Namespace) -> int:
    payload = run_openclaw_adapter_doctor(args.data_dir, target_host="openclaw")
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_adapter_hermes_install(args: argparse.Namespace) -> int:
    payload = install_openclaw_adapter(
        scope=args.scope,
        target=args.target,
        dry_run=args.dry_run,
        target_host="hermes",
    )
    _print_json(payload)
    return 0 if payload["status"] in {"ok", "dry_run"} else 2


def _handle_adapter_hermes_doctor(args: argparse.Namespace) -> int:
    payload = run_openclaw_adapter_doctor(args.data_dir, target_host="hermes")
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _handle_adapter_codex_install(args: argparse.Namespace) -> int:
    payload = install_codex_adapter(scope=args.scope, target=args.target, dry_run=args.dry_run)
    _print_json(payload)
    return 0 if payload["status"] in {"ok", "dry_run"} else 2


def _handle_adapter_codex_doctor(args: argparse.Namespace) -> int:
    payload = run_codex_adapter_doctor(args.data_dir)
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


def _handle_support_session_start(args: argparse.Namespace) -> int:
    payload = SupportLogRepository(args.data_dir).start_session(host=args.host, app_id=args.app_id)
    _print_json(payload)
    return 0 if payload.get("status") == "active" else 2


def _handle_support_session_stop(args: argparse.Namespace) -> int:
    payload = SupportLogRepository(args.data_dir).stop_session(session_id=args.session_id)
    _print_json(payload)
    return 0 if payload.get("status") == "stopped" else 2


def _handle_support_record_event(args: argparse.Namespace) -> int:
    sensitive = _read_json_object(args.sensitive) if args.sensitive is not None else None
    payload = SupportLogRepository(args.data_dir).record_event(
        session_id=args.session_id,
        event_type=args.event_type,
        payload=_read_json_object(args.payload),
        sensitive=sensitive,
        sensitive_kind=args.sensitive_kind,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_support_bundle(args: argparse.Namespace) -> int:
    include_sensitive = [item.strip() for item in str(args.include_sensitive or "").split(",") if item.strip()]
    payload = SupportLogRepository(args.data_dir).bundle(
        session_id=args.session_id,
        output=args.output,
        redaction=args.redaction,
        include_sensitive=include_sensitive,
        confirm=args.confirm,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_harness_doctor(args: argparse.Namespace) -> int:
    block_payload = _unsupported_native_harness_payload(args.app_id)
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="doctor", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    adapter = _create_harness_adapter(args.app_id, args.window_title)
    payload = adapter.doctor(capture=not args.no_capture, output=args.output)
    _record_support_harness_result(args.data_dir, app_id=args.app_id, action="doctor", harness_payload=payload)
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "degraded"} else 2


def _handle_harness_screenshot(args: argparse.Namespace) -> int:
    block_payload = _unsupported_native_harness_payload(args.app_id)
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="screenshot", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    payload = _create_harness_adapter(args.app_id, args.window_title).session.capture_window(output=args.output)
    payload.pop("text", None)
    _record_support_harness_result(args.data_dir, app_id=args.app_id, action="screenshot", harness_payload=payload)
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _unsupported_native_harness_payload(app_id: str) -> dict[str, object] | None:
    if app_id in SUPPORTED_NATIVE_HARNESS_APPS:
        return None
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": "unsupported_native_harness_for_app",
        "app_id": app_id,
        "supported_native_harness_apps": list(SUPPORTED_NATIVE_HARNESS_APPS),
    }


def _create_harness_adapter(app_id: str, window_title: str | None):
    return create_adapter(app_id, window_title=_harness_window_title(app_id, window_title))


def _options_from_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _read_json_object(path)


def _handle_harness_app_launch(args: argparse.Namespace) -> int:
    payload = _create_harness_adapter(args.app_id, args.window_title).launch(
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
    _record_support_harness_result(args.data_dir, app_id=args.app_id, action="launch", harness_payload=payload)
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_alias(args: argparse.Namespace) -> int:
    adapter = _create_harness_adapter(args.app_id, args.window_title)
    alias_spec = getattr(args, "harness_alias_spec", {})
    operation = str(alias_spec.get("operation") or "")
    if not operation or not hasattr(adapter, operation):
        payload = {
            "schema_version": 2,
            "status": "blocked",
            "app_id": args.app_id,
            "reason": "harness_alias_not_supported_for_app",
            "alias": getattr(args, "harness_alias", None),
        }
    else:
        kwargs: dict[str, Any] = {"output_dir": args.output_dir}
        if alias_spec.get("include_dry_run") is not False:
            kwargs["dry_run"] = args.dry_run
        for option in alias_spec.get("options") or []:
            if isinstance(option, dict) and option.get("dest"):
                kwargs[str(option["dest"])] = getattr(args, str(option["dest"]))
        payload = getattr(adapter, operation)(**kwargs)
    _record_support_harness_result(
        args.data_dir,
        app_id=args.app_id,
        action=str(operation or getattr(args, "harness_alias", "alias")),
        harness_payload=payload,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_observe(args: argparse.Namespace) -> int:
    payload = _create_harness_adapter(args.app_id, args.window_title).observe(
        output_dir=args.output_dir,
    )
    _record_support_harness_result(args.data_dir, app_id=args.app_id, action="observe", harness_payload=payload)
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_action(args: argparse.Namespace) -> int:
    options = _options_from_json(getattr(args, "options_json", None))
    payload = _create_harness_adapter(args.app_id, args.window_title).run_action(
        args.action,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        **options,
    )
    _record_support_harness_result(
        args.data_dir,
        app_id=args.app_id,
        action=f"action_{args.action}",
        harness_payload=payload,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_workflow(args: argparse.Namespace) -> int:
    options = _options_from_json(getattr(args, "options_json", None))
    payload = _create_harness_adapter(args.app_id, args.window_title).run_workflow(
        args.workflow,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        **options,
    )
    _record_support_harness_result(
        args.data_dir,
        app_id=args.app_id,
        action=f"workflow_{args.workflow}",
        harness_payload=payload,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_stage_draft(args: argparse.Namespace) -> int:
    if not args.dry_run:
        if args.data_dir is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "app_id": args.app_id,
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
                    "app_id": args.app_id,
                    "action": "stage_draft",
                    "reason": "safety_paused",
                    "next_host_action": "resume_safety_before_staging",
                }
            )
            return 2
    draft_text = args.text_file.read_text(encoding="utf-8")
    payload = _create_harness_adapter(args.app_id, args.window_title).stage_draft(
        draft_text,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
    _record_support_harness_action(
        args.data_dir,
        app_id=args.app_id,
        action="stage_draft",
        draft_text=draft_text,
        harness_payload=payload,
        action_request=None,
    )
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_send_message(args: argparse.Namespace) -> int:
    draft_text = args.text_file.read_text(encoding="utf-8")
    action_request: dict[str, Any] | None = None
    if not args.dry_run:
        block_payload = _live_send_cli_block_payload(args, app_id=args.app_id, draft_text=draft_text)
        if block_payload is not None:
            _record_support_harness_action(
                args.data_dir,
                app_id=args.app_id,
                action="send_message",
                draft_text=draft_text,
                harness_payload=block_payload,
                action_request=None,
            )
            _print_json(block_payload)
            return 2
        action_request = _read_json_object(args.action_request)
    payload = _create_harness_adapter(args.app_id, args.window_title).send_message(
        draft_text,
        dry_run=args.dry_run,
        output_dir=args.output_dir,
        target_binding=action_request.get("target_binding") if isinstance(action_request, dict) else None,
    )
    _record_support_harness_action(
        args.data_dir,
        app_id=args.app_id,
        action="send_message",
        draft_text=draft_text,
        harness_payload=payload,
        action_request=action_request,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _live_send_cli_block_payload(args: argparse.Namespace, *, app_id: str, draft_text: str) -> dict[str, Any] | None:
    if args.data_dir is None:
        return {
            "schema_version": 1,
            "status": "blocked",
            "app_id": app_id,
            "action": "send_message",
            "reason": "data_dir_required_for_safety_check",
            "next_host_action": "rerun_with_data_dir_or_use_dry_run",
        }
    if args.authorization is None:
        return {
            "schema_version": 1,
            "status": "blocked",
            "app_id": app_id,
            "action": "send_message",
            "reason": "authorization_required_for_live_send",
            "next_host_action": "provide_explicit_live_send_authorization",
        }
    if SafetyRepository(args.data_dir).is_paused():
        return {
            "schema_version": 1,
            "status": "blocked",
            "app_id": app_id,
            "action": "send_message",
            "reason": "safety_paused",
            "next_host_action": "resume_safety_before_live_send",
        }
    if args.action_request is None:
        guidance = managed_live_send_guidance("action_request_required_for_live_send")
        return {
            "schema_version": 1,
            "status": "blocked",
            "app_id": app_id,
            "action": "send_message",
            "reason": "action_request_required_for_live_send",
            "next_host_action": guidance["next_host_action"],
            "managed_live_send_guidance": guidance,
            "recovery_commands": guidance["recovery_commands"],
            "forbidden_actions": guidance["forbidden_actions"],
        }
    action_request = _read_json_object(args.action_request)
    authorization = _read_json_object(args.authorization)
    reason = validate_live_send_contract(
        authorization,
        action_request,
        app_id=app_id,
        draft_text=draft_text,
        data_dir=args.data_dir,
    )
    if reason is not None:
        guidance = managed_live_send_guidance(reason)
        return {
            "schema_version": 1,
            "status": "blocked",
            "app_id": app_id,
            "action": "send_message",
            "reason": reason,
            "next_host_action": guidance["next_host_action"],
            "managed_live_send_guidance": guidance,
            "recovery_commands": guidance["recovery_commands"],
            "forbidden_actions": guidance["forbidden_actions"],
        }
    return None


def _wechat_live_send_authorization_block_reason(authorization: dict[str, Any]) -> str | None:
    return _live_send_authorization_block_reason(authorization, app_id="wechat")


def _live_send_authorization_block_reason(authorization: dict[str, Any], *, app_id: str) -> str | None:
    return live_send_authorization_block_reason(authorization, app_id=app_id)


def _wechat_live_send_action_request_block_reason(action_request: dict[str, Any], draft_text: str) -> str | None:
    return _live_send_action_request_block_reason(action_request, draft_text)


def _live_send_action_request_block_reason(action_request: dict[str, Any], draft_text: str) -> str | None:
    return live_send_action_request_block_reason(
        action_request,
        draft_text,
        authorization={},
        app_id=str(action_request.get("app_id") or ""),
        data_dir=None,
    )


def _live_send_next_host_action(reason: str) -> str:
    return live_send_next_host_action(reason)


def _harness_window_title(app_id: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        default_title = manifest_for_app(app_id).default_window_title
    except KeyError:
        default_title = ""
    return default_title or "iPhone Mirroring"


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
    payload = store_observation_with_memory(data_dir, observation)
    _validate_storage_id(str(payload["match_id"]), "match_id")
    _validate_storage_id(observation.observation_id, "observation_id")
    return payload


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


def _handle_memory_rebuild(args: argparse.Namespace) -> int:
    if args.all:
        return _handle_memory_rebuild_all(args)
    try:
        payload = _rebuild_memory_match(args.data_dir, args.match_id)
        if payload is None:
            _print_json(
                {
                    "schema_version": 1,
                    "status": "not_found",
                    "match_id": args.match_id,
                }
            )
            return 2
    except (StorageError, ValueError, KeyError, TypeError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2
    _print_json(payload)
    return 0


def _handle_memory_rebuild_all(args: argparse.Namespace) -> int:
    memory_repo = MemoryRepository(args.data_dir)
    match_ids = memory_repo.match_ids_with_observations()
    if not match_ids:
        _print_json(
            {
                "schema_version": 1,
                "status": "not_found",
                "rebuilt_count": 0,
                "error_count": 0,
                "matches": [],
            }
        )
        return 2

    results: list[dict[str, Any]] = []
    for match_id in match_ids:
        try:
            result = _rebuild_memory_match(args.data_dir, match_id)
        except (StorageError, ValueError, KeyError, TypeError) as exc:
            result = {
                "schema_version": 1,
                "status": "error",
                "match_id": match_id,
                "reason": str(exc),
            }
        if result is None:
            result = {
                "schema_version": 1,
                "status": "not_found",
                "match_id": match_id,
                "reason": "missing_observations",
            }
        results.append(result)

    rebuilt_count = sum(1 for item in results if item["status"] == "ok")
    error_count = len(results) - rebuilt_count
    status = "ok" if error_count == 0 else "partial"
    _print_json(
        {
            "schema_version": 1,
            "status": status,
            "rebuilt_count": rebuilt_count,
            "error_count": error_count,
            "matches": results,
        }
    )
    return 0 if status == "ok" else 2


def _rebuild_memory_match(data_dir: Path, match_id: str) -> dict[str, Any] | None:
    observations = ObservationRepository(data_dir).load_observations(match_id)
    if not observations:
        return None
    memory_repo = MemoryRepository(data_dir)
    match_record = _match_record(data_dir, match_id)
    projection = memory_repo.rebuild_projection_from_observations(
        match_id,
        observations,
        identity_confidence=(
            str(match_record["identity_confidence"])
            if match_record is not None and match_record.get("identity_confidence")
            else None
        ),
        requires_user_confirmation=(
            bool(match_record["requires_user_confirmation"])
            if match_record is not None and "requires_user_confirmation" in match_record
            else None
        ),
    )
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": match_id,
        "memory_event_count": len(memory_repo.load_events(match_id)),
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _handle_memory_update_match(args: argparse.Namespace) -> int:
    update = _read_json_object(args.input)
    try:
        payload = _apply_memory_update(args.data_dir, args.match_id, update)
    except (StorageError, ValueError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2
    _print_json(payload)
    return 0


def _handle_memory_export(args: argparse.Namespace) -> int:
    try:
        export_payload = MemoryRepository(args.data_dir).export_match(args.match_id)
    except (StorageError, ValueError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2
    status = "ok" if export_payload["projection"] is not None or export_payload["events"] else "not_found"
    _print_json(
        {
            "schema_version": 1,
            "status": status,
            "match_id": args.match_id,
            "export": export_payload,
        }
    )
    return 0 if status == "ok" else 2


def _handle_memory_delete_match(args: argparse.Namespace) -> int:
    required = f"delete-match:{args.match_id}"
    if args.confirm != required:
        _print_json(
            {
                "schema_version": 1,
                "status": "blocked",
                "match_id": args.match_id,
                "reason": "confirm_token_mismatch",
                "required_confirm_token": required,
            }
        )
        return 2

    try:
        prefix = f"matches/{args.match_id}/"
        deleted_sqlite_documents = 0
        deleted_sqlite_events = 0
        store = ProductionDataStore(args.data_dir)
        if (args.data_dir / "dating_boost.sqlite3").exists():
            deleted_sqlite_documents = store.delete_documents_with_prefix(prefix)
            deleted_sqlite_events = store.delete_audit_events_with_stream_prefix(prefix)
        match_repo = MatchRepository(args.data_dir)
        removed_identity_confirmations = match_repo.remove_identity_confirmations(args.match_id)
        removed_index_records = match_repo.delete_match(args.match_id)
        deleted_json_files = MemoryRepository(args.data_dir).delete_match_documents(args.match_id)
    except (OSError, RuntimeError, StorageError, ValueError) as exc:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "match_id": args.match_id,
                "reason": str(exc),
            }
        )
        return 2

    _print_json(
        {
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "deleted_json_files": deleted_json_files,
            "deleted_sqlite_documents": deleted_sqlite_documents,
            "deleted_sqlite_events": deleted_sqlite_events,
            "removed_identity_confirmations": removed_identity_confirmations,
            "removed_index_records": removed_index_records,
        }
    )
    return 0


def _handle_memory_propose(args: argparse.Namespace) -> int:
    from dating_boost.core.memory.proposals import extract_proposals
    from dating_boost.core.memory.review_queue import ReviewQueueRepository
    from dating_boost.perception.fixture_loader import load_observation

    observation = load_observation(args.input)
    memory_repo = MemoryRepository(args.data_dir)
    projection = memory_repo.load_projection(args.match_id)
    if projection is None:
        _print_json({"schema_version": 1, "status": "not_found", "match_id": args.match_id})
        return 2
    proposals = extract_proposals(
        args.match_id,
        observation,
        projection,
        session_id=args.session_id or None,
        observation_id=observation.observation_id,
        source="deterministic",
    )
    if args.store_review_queue:
        review_repo = ReviewQueueRepository(args.data_dir)
        enqueued = []
        for proposal in proposals:
            if review_repo.reject_dedupe_key_exists(proposal.dedupe_key):
                continue
            review_repo.enqueue(proposal)
            enqueued.append(proposal.to_dict())
        _print_json({
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "enqueued_count": len(enqueued),
            "items": enqueued,
        })
    else:
        _print_json({
            "schema_version": 1,
            "status": "ok",
            "match_id": args.match_id,
            "proposal_count": len(proposals),
            "items": [item.to_dict() for item in proposals],
        })
    return 0


def _handle_memory_review_list(args: argparse.Namespace) -> int:
    from dating_boost.core.memory.review_queue import ReviewQueueRepository

    review_repo = ReviewQueueRepository(args.data_dir)
    items = review_repo.load_items(
        status=args.status or None,
        match_id=args.match_id,
        session_id=args.session_id,
    )
    _print_json({
        "schema_version": 1,
        "status": "ok",
        "count": len(items),
        "items": [item.to_dict() for item in items],
    })
    return 0


def _handle_memory_review_decide(args: argparse.Namespace) -> int:
    from dating_boost.core.memory.review_queue import ReviewQueueRepository

    accept_ids = list(args.accept or [])
    reject_ids = list(args.reject or [])
    if not accept_ids and not reject_ids:
        _print_json({"schema_version": 1, "status": "error", "reason": "no_ids_provided"})
        return 2
    confirm_token = str(args.confirm or "")
    if not confirm_token.startswith("memory-review:"):
        _print_json({
            "schema_version": 1,
            "status": "blocked",
            "reason": "confirm_token_mismatch",
            "required_format": "memory-review:<session_id>",
        })
        return 2
    confirm_session_id = confirm_token[len("memory-review:"):]
    review_repo = ReviewQueueRepository(args.data_dir)
    all_ids = [*accept_ids, *reject_ids]
    target_items = review_repo.load_items()
    id_to_item = {item.review_item_id: item for item in target_items}
    for item_id in all_ids:
        item = id_to_item.get(item_id)
        if item is None:
            _print_json({
                "schema_version": 1,
                "status": "error",
                "reason": f"review_item_not_found:{item_id}",
            })
            return 2
        if item.session_id != confirm_session_id:
            _print_json({
                "schema_version": 1,
                "status": "blocked",
                "reason": "confirm_token_session_mismatch",
                "item_id": item_id,
                "item_session_id": item.session_id,
                "confirm_session_id": confirm_session_id,
            })
            return 2
        if item.status != "pending":
            _print_json({
                "schema_version": 1,
                "status": "error",
                "reason": f"item_not_pending:{item_id}",
                "current_status": item.status,
            })
            return 2
    memory_repo = MemoryRepository(args.data_dir)
    accepted = []
    rejected = []
    errors = []
    for item_id in accept_ids:
        try:
            item = id_to_item[item_id]
            proposal = item.proposal
            scope = MemoryScope(proposal.get("scope", MemoryScope.MATCH_PROFILE.value))
            fact_type = MemoryFactType(proposal.get("fact_type", MemoryFactType.VISIBLE_FACT.value))
            predicate = str(proposal.get("predicate", ""))
            value = proposal.get("value")
            projection = memory_repo.load_projection(item.match_id)
            if projection is not None and not projection.trusted_for_context:
                identity_predicates = {"identity", "real_name", "phone_number", "email", "address"}
                if predicate not in identity_predicates:
                    errors.append({
                        "id": item_id,
                        "action": "accept",
                        "reason": "identity_not_trusted",
                    })
                    continue
            fact = MemoryFact(
                fact_id=item.review_item_id,
                scope=scope,
                fact_type=fact_type,
                subject=proposal.get("subject", ""),
                predicate=predicate,
                value=value,
                qualifiers=dict(proposal.get("qualifiers", {})),
                confidence=proposal.get("confidence", "medium"),
                evidence=EvidenceRef(
                    source_type="memory_review",
                    evidence_text=str(proposal.get("evidence_text", "")),
                    confidence=proposal.get("confidence", "medium"),
                    source_observation_id=item.observation_id,
                    metadata={
                        "dedupe_key": item.dedupe_key,
                        "review_source": item.source,
                        "risk": item.risk,
                        "session_id": item.session_id,
                    },
                ),
                created_at=item.created_at,
                last_seen_at=item.created_at,
            )
            event = MemoryEvent(
                event_id=_memory_event_id(item.match_id, "review_accept", {"review_item_id": item_id}),
                event_type=MemoryEventType.PROFILE_FACT_OBSERVED,
                match_id=item.match_id,
                scope=scope,
                created_at=_now_iso(),
                payload={
                    "fact": fact.to_dict(),
                    "review_item_id": item_id,
                    "source": "memory_review",
                    "review_source": item.source,
                    "risk": item.risk,
                    "dedupe_key": item.dedupe_key,
                    "observation_id": item.observation_id,
                    "session_id": item.session_id,
                },
                evidence=fact.evidence,
            )
            memory_repo.append_event(item.match_id, event)
            memory_repo.rebuild_projection(item.match_id)
            review_repo.update_status(item_id, "accepted")
            accepted.append(item_id)
        except (ValueError, StorageError) as exc:
            errors.append({"id": item_id, "action": "accept", "reason": str(exc)})
    for item_id in reject_ids:
        try:
            review_repo.update_status(item_id, "rejected")
            rejected.append(item_id)
        except ValueError as exc:
            errors.append({"id": item_id, "action": "reject", "reason": str(exc)})
    _print_json({
        "schema_version": 1,
        "status": "ok" if not errors else "partial",
        "accepted": accepted,
        "rejected": rejected,
        "errors": errors,
    })
    return 0 if not errors else 2


def _apply_memory_update(data_dir: Path, match_id: str, update: dict[str, Any]) -> dict[str, Any]:
    action = str(update.get("action") or "")
    if action == "merge_identity":
        return _apply_memory_identity_merge(data_dir, match_id, update)
    if action == "inherit_memory":
        return _apply_memory_inheritance(data_dir, match_id, update)

    memory_repo = MemoryRepository(data_dir)
    event = _memory_update_event(data_dir, match_id, update)
    memory_repo.append_event(match_id, event)
    projection = memory_repo.rebuild_projection(match_id)
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": match_id,
        "action": action,
        "event_id": event.event_id,
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _apply_memory_identity_merge(data_dir: Path, match_id: str, update: dict[str, Any]) -> dict[str, Any]:
    source_match_id = str(update.get("source_match_id") or "")
    target_match_id = str(update.get("target_match_id") or "")
    confirmation_token = str(update.get("confirmation_token") or "")
    expected_token = f"merge_identity:{source_match_id}:{target_match_id}"
    if not source_match_id or not target_match_id:
        raise ValueError("merge_identity requires source_match_id and target_match_id")
    if target_match_id != match_id:
        raise ValueError("merge_identity target_match_id must match --match-id")
    if confirmation_token != expected_token:
        raise ValueError(f"merge_identity requires confirmation_token {expected_token!r}")

    memory_repo = MemoryRepository(data_dir)
    observation_repo = ObservationRepository(data_dir)
    source_events = memory_repo.load_events(source_match_id)
    target_events_before = memory_repo.load_events(target_match_id)
    for observation in observation_repo.load_observations(source_match_id):
        observation_repo.save_observation(target_match_id, observation)
    MatchRepository(data_dir).merge_matches(
        source_match_id=source_match_id,
        target_match_id=target_match_id,
    )
    for source_event in source_events:
        memory_repo.append_event(
            target_match_id,
            _merged_memory_event(
                source_event,
                source_match_id=source_match_id,
                target_match_id=target_match_id,
            ),
        )
    event = MemoryEvent(
        event_id=_memory_event_id(
            target_match_id,
            "merge_identity",
            {"source_match_id": source_match_id, "target_match_id": target_match_id},
        ),
        event_type=MemoryEventType.MATCH_IDENTITY_CONFIRMED,
        match_id=target_match_id,
        scope=MemoryScope.MATCH_PROFILE,
        created_at=_now_iso(),
        payload={
            "confirmed_by": str(update.get("confirmed_by") or "user"),
            "action": "merge_identity",
            "source_match_id": source_match_id,
            "target_match_id": target_match_id,
            "merged_event_count": len(source_events),
            "target_event_count_before_merge": len(target_events_before),
        },
        evidence=_manual_evidence("identity_merge", "User confirmed identity merge."),
    )
    memory_repo.append_event(target_match_id, event)
    projection = memory_repo.rebuild_projection(target_match_id)
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": target_match_id,
        "action": "merge_identity",
        "event_id": event.event_id,
        "source_match_id": source_match_id,
        "target_match_id": target_match_id,
        "merged_event_count": len(source_events),
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _memory_update_event(data_dir: Path, match_id: str, update: dict[str, Any]) -> MemoryEvent:
    action = str(update.get("action") or "")
    created_at = str(update.get("created_at") or _now_iso())
    if action == "confirm_identity":
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.MATCH_IDENTITY_CONFIRMED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "confirmed_by": str(update.get("confirmed_by") or "user"),
                "action": action,
            },
            evidence=_manual_evidence("user_confirmation", "User confirmed match identity."),
        )
    if action in {"reject_fact", "archive_fact"}:
        target_fact_id = _required_text(update, "target_fact_id")
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.FACT_REJECTED if action == "reject_fact" else MemoryEventType.FACT_ARCHIVED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "target_fact_id": target_fact_id,
                "reason": str(update.get("reason") or action),
            },
            evidence=_manual_evidence("user_correction", f"User requested {action}."),
        )
    if action == "correct_fact":
        target_fact_id = _required_text(update, "target_fact_id")
        fact = _corrected_fact(data_dir, match_id, target_fact_id, update, created_at)
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.FACT_CORRECTED,
            match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE,
            created_at=created_at,
            payload={
                "target_fact_id": target_fact_id,
                "fact": fact.to_dict(),
                "reason": str(update.get("reason") or "user_correction"),
            },
            evidence=_manual_evidence("user_correction", "User corrected a memory fact."),
        )
    if action == "create_commitment":
        commitment = CommitmentMemory(
            commitment_id=str(update.get("commitment_id") or f"commitment_{_digest(update)[:12]}"),
            text=_required_text(update, "text"),
            evidence=_manual_evidence("user_update", "User created a commitment memory."),
            created_at=created_at,
            last_seen_at=created_at,
        )
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.COMMITMENT_CREATED,
            match_id=match_id,
            scope=MemoryScope.COMMITMENT,
            created_at=created_at,
            payload={"commitment": commitment.to_dict()},
            evidence=commitment.evidence,
        )
    if action == "resolve_commitment":
        commitment_id = _required_text(update, "commitment_id")
        return MemoryEvent(
            event_id=_memory_event_id(match_id, action, update),
            event_type=MemoryEventType.COMMITMENT_RESOLVED,
            match_id=match_id,
            scope=MemoryScope.COMMITMENT,
            created_at=created_at,
            payload={
                "commitment_id": commitment_id,
                "resolved_at": str(update.get("resolved_at") or created_at),
            },
            evidence=_manual_evidence("user_update", "User resolved a commitment memory."),
        )
    raise ValueError(f"unsupported memory update action: {action!r}")


def _corrected_fact(
    data_dir: Path,
    match_id: str,
    target_fact_id: str,
    update: dict[str, Any],
    created_at: str,
) -> MemoryFact:
    if isinstance(update.get("fact"), dict):
        fact_data = dict(update["fact"])
        fact_data.setdefault("evidence", _manual_evidence("user_correction", "User corrected a memory fact.").to_dict())
        fact_data.setdefault("created_at", created_at)
        fact_data.setdefault("last_seen_at", created_at)
        fact_data.setdefault("fact_type", MemoryFactType.USER_CONFIRMED.value)
        return MemoryFact.from_dict(fact_data)
    target = _find_memory_fact(data_dir, match_id, target_fact_id)
    subject = str(update.get("subject") or (target.subject if target else match_id))
    predicate = str(update.get("predicate") or (target.predicate if target else "user_corrected_fact"))
    qualifiers = dict(update.get("qualifiers") or (target.qualifiers if target else {}))
    return MemoryFact(
        fact_id=str(update.get("fact_id") or "manual_corrected_fact"),
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=MemoryFactType.USER_CONFIRMED,
        subject=subject,
        predicate=predicate,
        value=update.get("value"),
        qualifiers=qualifiers,
        confidence=str(update.get("confidence") or "high"),
        evidence=_manual_evidence("user_correction", "User corrected a memory fact."),
        created_at=created_at,
        last_seen_at=created_at,
    )


def _find_memory_fact(data_dir: Path, match_id: str, fact_id: str) -> MemoryFact | None:
    projection = MemoryRepository(data_dir).load_projection(match_id)
    if projection is None:
        return None
    for fact in [*projection.facts, *projection.inferences]:
        if fact.fact_id == fact_id:
            return fact
    return None


def _merged_memory_event(
    event: MemoryEvent,
    *,
    source_match_id: str,
    target_match_id: str,
) -> MemoryEvent:
    payload = dict(event.payload)
    payload["original_match_id"] = source_match_id
    payload["original_event_id"] = event.event_id
    return MemoryEvent(
        event_id=f"merged_{_digest({'source': source_match_id, 'target': target_match_id, 'event_id': event.event_id})[:16]}",
        event_type=event.event_type,
        match_id=target_match_id,
        scope=event.scope,
        created_at=event.created_at,
        payload=payload,
        evidence=EvidenceRef(
            source_type="identity_merge",
            source_event_id=event.event_id,
            evidence_text="Source match memory event preserved during identity merge.",
            metadata={"source_match_id": source_match_id},
        ),
    )


def _apply_memory_inheritance(data_dir: Path, match_id: str, update: dict[str, Any]) -> dict[str, Any]:
    source_match_id = str(update.get("source_match_id") or "")
    target_match_id = str(update.get("target_match_id") or "")
    confirmation_token = str(update.get("confirmation_token") or "")
    direction = str(update.get("direction") or "dating_app_to_wechat")
    expected_token = f"inherit_memory:{source_match_id}:{target_match_id}"
    if not source_match_id or not target_match_id:
        raise ValueError("inherit_memory requires source_match_id and target_match_id")
    if source_match_id == target_match_id:
        raise ValueError("inherit_memory source_match_id and target_match_id must differ")
    if target_match_id != match_id:
        raise ValueError("inherit_memory target_match_id must match --match-id")
    if confirmation_token != expected_token:
        raise ValueError(f"inherit_memory requires confirmation_token {expected_token!r}")

    memory_repo = MemoryRepository(data_dir)
    source_events = memory_repo.load_events(source_match_id)
    if not source_events:
        raise ValueError(f"source match {source_match_id!r} has no memory events")
    if memory_repo.load_projection(target_match_id) is None and not memory_repo.load_events(target_match_id):
        raise ValueError(f"target match {target_match_id!r} does not exist")

    target_events_before = memory_repo.load_events(target_match_id)
    existing_inherited_ids = {
        event.payload.get("original_event_id")
        for event in target_events_before
        if event.evidence is not None
        and event.evidence.source_type == "memory_inheritance"
        and event.payload.get("original_event_id")
    }
    _inheritable_types = {
        MemoryEventType.PROFILE_FACT_OBSERVED,
        MemoryEventType.CONVERSATION_FACT_OBSERVED,
        MemoryEventType.INFERENCE_RECORDED,
        MemoryEventType.FACT_CORRECTED,
        MemoryEventType.FACT_REJECTED,
        MemoryEventType.FACT_ARCHIVED,
        MemoryEventType.COMMITMENT_CREATED,
        MemoryEventType.COMMITMENT_RESOLVED,
        MemoryEventType.FEEDBACK_RECORDED,
    }
    now = _now_iso()
    inherited_count = 0
    skipped_count = 0
    skipped_type_count = 0
    for source_event in source_events:
        if source_event.event_type not in _inheritable_types:
            skipped_type_count += 1
            continue
        if source_event.event_id in existing_inherited_ids:
            skipped_count += 1
            continue
        inherited_event = _inherited_memory_event(
            source_event,
            source_match_id=source_match_id,
            target_match_id=target_match_id,
            direction=direction,
            inherited_at=now,
        )
        memory_repo.append_event(target_match_id, inherited_event)
        inherited_count += 1

    summary_event = MemoryEvent(
        event_id=_memory_event_id(
            target_match_id,
            "inherit_memory",
            {"source_match_id": source_match_id, "target_match_id": target_match_id, "direction": direction},
        ),
        event_type=MemoryEventType.PROJECTION_REBUILT,
        match_id=target_match_id,
        scope=MemoryScope.MATCH_PROFILE,
        created_at=now,
        payload={
            "action": "inherit_memory",
            "source_match_id": source_match_id,
            "target_match_id": target_match_id,
            "direction": direction,
            "confirmed_by": str(update.get("confirmed_by") or "user"),
            "inherited_event_count": inherited_count,
            "skipped_existing_event_count": skipped_count,
            "skipped_non_inheritable_event_count": skipped_type_count,
        },
        evidence=_manual_evidence("memory_inheritance_summary", f"User authorized one-way memory inheritance from {source_match_id} to {target_match_id}."),
    )
    memory_repo.append_event(target_match_id, summary_event)
    projection = memory_repo.rebuild_projection(target_match_id)
    return {
        "schema_version": 1,
        "status": "ok",
        "match_id": target_match_id,
        "action": "inherit_memory",
        "event_id": summary_event.event_id,
        "source_match_id": source_match_id,
        "target_match_id": target_match_id,
        "inherited_event_count": inherited_count,
        "skipped_existing_event_count": skipped_count,
        "skipped_non_inheritable_event_count": skipped_type_count,
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
        "trusted_for_context": projection.trusted_for_context,
        "trusted_for_managed_send": projection.trusted_for_managed_send,
    }


def _inherited_memory_event(
    event: MemoryEvent,
    *,
    source_match_id: str,
    target_match_id: str,
    direction: str,
    inherited_at: str,
) -> MemoryEvent:
    payload = dict(event.payload)
    payload["inheritance_type"] = direction
    payload["source_match_id"] = source_match_id
    payload["original_event_id"] = event.event_id
    payload["inherited_at"] = inherited_at
    return MemoryEvent(
        event_id=f"inherited_{_digest({'source': source_match_id, 'target': target_match_id, 'event_id': event.event_id, 'action': 'inherit_memory'})[:16]}",
        event_type=event.event_type,
        match_id=target_match_id,
        scope=event.scope,
        created_at=event.created_at,
        payload=payload,
        evidence=EvidenceRef(
            source_type="memory_inheritance",
            source_event_id=event.event_id,
            evidence_text="Memory event inherited from source match via user-authorized one-way transfer.",
            metadata={"source_match_id": source_match_id, "inheritance_type": direction},
        ),
    )


def _memory_event_id(match_id: str, action: str, payload: dict[str, Any]) -> str:
    return f"mem_evt_{_digest({'match_id': match_id, 'action': action, 'payload': payload})[:16]}"


def _manual_evidence(source_type: str, evidence_text: str) -> EvidenceRef:
    return EvidenceRef(source_type=source_type, evidence_text=evidence_text, confidence="user_confirmed")


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "")
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _match_record(data_dir: Path, match_id: str) -> dict[str, object] | None:
    for record in MatchRepository(data_dir).list_match_candidates():
        if record.get("match_id") == match_id:
            return record
    return None


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
    if args.max_memory_items is not None and args.max_memory_items < 1:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "reason": "max_memory_items_must_be_positive",
            }
        )
        return 2
    profile = JsonMemoryRepository(args.data_dir).load_user_profile()
    reply_mode = ReplyMode(args.mode)
    observation = ObservationRepository(args.data_dir).load_latest_observation(args.match_id)
    context_pack = _build_mvp_context_pack(
        profile,
        args.match_id,
        reply_mode,
        observation,
        args.data_dir,
        max_memory_items=args.max_memory_items,
        include_memory_diagnostics=bool(args.include_memory_diagnostics),
        semantic_provider=args.semantic_provider,
        semantic_query=args.semantic_query,
    )
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
    draft_payload = _read_json_object(args.input)
    draft = _draft_from_dict(draft_payload)
    context_payload = _read_json_object(args.context)
    context_pack = context_payload.get("context_pack", context_payload)
    if not isinstance(context_pack, dict):
        raise ValueError("--context must contain a JSON object or a context_pack object")
    policy = evaluate_draft_content(draft, context_pack)
    if args.data_dir is not None:
        _record_support_policy_check_draft(
            args.data_dir,
            draft_payload=draft_payload,
            draft=draft,
            context_pack=context_pack,
            policy=policy,
        )
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
            goal_type=args.goal_type,
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
    try:
        payload = AutomationRepository(args.data_dir).save_goal(_read_json_object(args.input))
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
    _print_json(payload)
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


def _handle_managed_session_start(args: argparse.Namespace) -> int:
    try:
        payload = ManagedSessionRepository(args.data_dir).start(
            app_id=args.app_id,
            authorization=_read_json_object(args.authorization),
            goal=_read_json_object(args.goal),
            availability=_read_json_object(args.availability),
            send_mode=args.send_mode,
            managed_gui_send=args.managed_gui_send,
            scan_interval_seconds=args.scan_interval,
            nudge_delay_minutes=args.nudge_delay_minutes,
        )
    except ValueError as exc:
        payload = {"schema_version": 1, "status": "blocked", "reason": str(exc)}
    _print_json(payload)
    return 0 if payload.get("status") in {"active", "paused"} else 2


def _handle_managed_session_tick(args: argparse.Namespace) -> int:
    try:
        payload = ManagedSessionRepository(args.data_dir).tick()
    except ValueError as exc:
        payload = {"schema_version": 1, "status": "blocked", "reason": str(exc)}
    _print_json(payload)
    return 0 if payload.get("status") in {"no_work", "host_work_required", "paused", "stopped"} else 2


def _handle_managed_session_run(args: argparse.Namespace) -> int:
    try:
        payload = ManagedSessionRepository(args.data_dir).run(
            wait=args.wait,
            wait_timeout_seconds=args.wait_timeout,
            poll_interval_seconds=args.poll_interval,
        )
    except ValueError as exc:
        payload = {"schema_version": 1, "status": "blocked", "reason": str(exc)}
    _print_json(payload)
    return 0 if payload.get("status") in {"no_work", "host_work_required", "paused", "stopped"} else 2


def _handle_managed_session_notify(args: argparse.Namespace) -> int:
    try:
        payload = ManagedSessionRepository(args.data_dir).notify(source=args.source, app_id=args.app_id)
    except ValueError as exc:
        payload = {"schema_version": 1, "status": "blocked", "reason": str(exc)}
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_managed_session_status(args: argparse.Namespace) -> int:
    payload = ManagedSessionRepository(args.data_dir).status()
    _print_json(payload)
    return 0 if payload.get("status") != "not_found" else 2


def _handle_managed_session_stop(args: argparse.Namespace) -> int:
    payload = ManagedSessionRepository(args.data_dir).stop(reason=args.reason)
    _print_json(payload)
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
        referenced_memory_ids=list(args.referenced_memory_id),
        conversation_move=args.conversation_move,
        hook_source=args.hook_source,
        edited_text_ref=args.edited_text_ref,
        user_confirmed_style_promotion=bool(args.user_confirmed_style_promotion),
    )
    _print_json(event_payload)
    return 0


def _handle_eval_run(args: argparse.Namespace) -> int:
    if args.suite == "conversation":
        result = run_conversation_eval(args.input)
    elif args.suite == "memory":
        result = run_memory_eval(args.input)
    elif args.suite == "memory-review":
        from dating_boost.evals.runner import run_memory_review_eval
        result = run_memory_review_eval(args.input)
    else:
        _print_json({"schema_version": 1, "status": "error", "reason": "unsupported_eval_suite"})
        return 2
    payload = {
        "schema_version": 1,
        "status": "ok" if result.passed else "failed",
        "suite": args.suite,
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
    referenced_memory_ids: list[str] | None = None,
    conversation_move: str | None = None,
    hook_source: str | None = None,
    edited_text_ref: str | None = None,
    user_confirmed_style_promotion: bool = False,
) -> dict[str, Any]:
    event = create_feedback_event(
        event_id=f"feedback_{match_id}_{draft_id}_{label}",
        match_id=match_id,
        draft_id=draft_id,
        mode=mode,
        label=label,
        created_at=MVP_TIMESTAMP,
        referenced_memory_ids=referenced_memory_ids,
        conversation_move=conversation_move,
        hook_source=hook_source,
        edited_text_ref=edited_text_ref,
        user_confirmed_style_promotion=True if user_confirmed_style_promotion else None,
    )
    JsonMemoryRepository(data_dir).append_feedback_event(match_id, event)
    memory_event = MemoryEvent(
        event_id=str(event["event_id"]),
        event_type=MemoryEventType.FEEDBACK_RECORDED,
        match_id=match_id,
        scope=MemoryScope.FEEDBACK_PREFERENCE,
        created_at=str(event["created_at"]),
        payload=dict(event),
        evidence=EvidenceRef(
            source_type="user_feedback",
            evidence_text="User recorded feedback for a generated draft.",
            confidence="user_confirmed",
        ),
    )
    memory_repo = MemoryRepository(data_dir)
    memory_repo.append_event(match_id, memory_event)
    projection = memory_repo.rebuild_projection(match_id)
    return {
        "status": "ok",
        "match_id": match_id,
        "event_id": event["event_id"],
        "draft_id": draft_id,
        "label": label,
        "projection_updated": True,
        "identity_status": projection.identity_status.value,
    }


def _build_mvp_context_pack(
    profile: UserProfile,
    match_id: str,
    reply_mode: ReplyMode,
    observation: AppObservation | None,
    data_dir: Path | None = None,
    *,
    max_memory_items: int | None = None,
    include_memory_diagnostics: bool = False,
    semantic_provider: str = "none",
    semantic_query: str | None = None,
) -> dict[str, Any]:
    user_profile = _profile_to_context_dict(profile)
    if data_dir is not None:
        disclosure_repo = UserDisclosureRepository(data_dir)
        disclosure_profile = disclosure_repo.load_profile_or_none()
        if disclosure_profile is not None:
            user_profile["disclosure_profile"] = disclosure_profile
        user_profile["disclosure_readiness"] = disclosure_repo.readiness(mode="draft")
    memory_context: dict[str, Any] | None = None
    if data_dir is not None:
        projection = MemoryRepository(data_dir).load_projection(match_id)
        if projection is not None:
            hook_provider = _semantic_hook_provider(semantic_provider)
            memory_context = build_memory_context(
                match_id,
                projection,
                latest_observation=observation,
                now=_now_iso(),
                max_items=max_memory_items,
                reply_mode=reply_mode.value,
                semantic_hook_provider=hook_provider,
                semantic_query=semantic_query,
            )
    if memory_context is not None:
        match_profile = dict(memory_context["match_profile"])
        conversation_memory = dict(memory_context["conversation_memory"])
        conversation_memory["memory_items"] = memory_context.get("memory_items")
        if include_memory_diagnostics:
            conversation_memory["excluded_memory"] = memory_context.get("excluded_memory")
        if max_memory_items is not None:
            _suppress_unbudgeted_memory_context(match_profile, conversation_memory)
    elif observation is None:
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


def _suppress_unbudgeted_memory_context(
    match_profile: dict[str, Any],
    conversation_memory: dict[str, Any],
) -> None:
    match_profile["conversation_hooks"] = []
    match_profile["possible_interests"] = []
    conversation_memory["recent_messages"] = []
    conversation_memory["latest_inbound_messages"] = []
    conversation_memory["open_threads"] = []
    conversation_memory["commitments"] = []
    conversation_memory["running_summary"] = ""


def _semantic_hook_provider(name: str):
    from dating_boost.core.memory.semantic import (
        LocalLexicalSemanticHookProvider,
        NoOpSemanticHookProvider,
    )
    if name == "lexical":
        return LocalLexicalSemanticHookProvider()
    return NoOpSemanticHookProvider()


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


def _record_support_policy_check_draft(
    data_dir: Path,
    *,
    draft_payload: dict[str, Any],
    draft: DraftResponse,
    context_pack: dict[str, Any],
    policy: ContentPolicyDecision,
) -> None:
    try:
        repository = SupportLogRepository(data_dir)
        active = repository.active_session()
        if not active:
            return
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type="draft_generated",
            payload={
                "command": "policy_check_draft",
                "target_match_id": context_pack.get("match_id"),
                "draft": _draft_to_dict(draft),
                "context_source_manifest": context_source_manifest(context_pack),
                "policy": _policy_to_dict(policy),
            },
            sensitive={
                "draft_payload": draft_payload,
                "draft_text": draft.best_reply,
            },
            sensitive_kind="draft",
        )
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type="policy_check_draft",
            payload={
                "target_match_id": context_pack.get("match_id"),
                "context_source_manifest": context_source_manifest(context_pack),
                "policy": _policy_to_dict(policy),
            },
        )
    except Exception:
        return


def _record_support_harness_result(
    data_dir: Path | None,
    *,
    app_id: str,
    action: str,
    harness_payload: dict[str, Any],
) -> None:
    if data_dir is None:
        return
    try:
        repository = SupportLogRepository(data_dir)
        active = repository.active_session()
        if not active:
            return
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type=f"harness_{app_id}_{action}",
            payload={
                "command": f"harness {app_id} {action}",
                "app_id": app_id,
                "action": action,
                "status": harness_payload.get("status"),
                "reason": harness_payload.get("reason"),
                "mode": harness_payload.get("mode"),
                "screen_state": harness_payload.get("screen_state"),
                "harness_payload_hash": payload_digest(harness_payload),
                "harness_payload": _support_safe_harness_payload(harness_payload),
            },
        )
    except Exception:
        return


def _record_support_harness_action(
    data_dir: Path | None,
    *,
    app_id: str,
    action: str,
    draft_text: str,
    harness_payload: dict[str, Any],
    action_request: dict[str, Any] | None,
) -> None:
    if data_dir is None:
        return
    try:
        repository = SupportLogRepository(data_dir)
        active = repository.active_session()
        if not active:
            return
        target_binding = action_request.get("target_binding") if isinstance(action_request, dict) else None
        safe_payload = {
            "command": f"harness {app_id} {action}",
            "app_id": app_id,
            "action": action,
            "status": harness_payload.get("status"),
            "reason": harness_payload.get("reason"),
            "mode": harness_payload.get("mode"),
            "target_match_id": _support_target_match_id(action_request=action_request, target_binding=target_binding),
            "draft_fingerprint": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            "draft_character_count": len(draft_text),
            "draft_topic_labels": classify_text_topics(draft_text),
            "harness_payload_hash": payload_digest(harness_payload),
            "harness_payload": _support_safe_harness_payload(harness_payload),
        }
        if isinstance(action_request, dict):
            safe_payload["action_request_hash"] = payload_digest(action_request)
        if isinstance(target_binding, dict):
            safe_payload["target_binding_hash"] = payload_digest(target_binding)
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type=f"harness_{app_id}_{action}",
            payload=safe_payload,
            sensitive={
                "draft_text": draft_text,
                "action_request": action_request,
                "harness_payload": harness_payload,
            },
            sensitive_kind="draft",
        )
    except Exception:
        return


def _support_target_match_id(
    *,
    action_request: dict[str, Any] | None,
    target_binding: Any,
) -> str | None:
    if isinstance(action_request, dict):
        for key in ("target_match_id", "match_id"):
            if action_request.get(key):
                return str(action_request[key])
    if isinstance(target_binding, dict) and target_binding.get("target_match_id"):
        return str(target_binding["target_match_id"])
    return None


def _support_safe_harness_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "status",
        "app_id",
        "harness_backend",
        "action",
        "target",
        "mode",
        "reason",
        "next_host_action",
        "workflow",
        "screen_state",
        "layout_hints",
        "planned_steps",
        "executed_steps",
        "live_send",
        "requires_explicit_authorization",
        "requires_user_confirmation_before_send",
        "draft_fingerprint",
        "draft_character_count",
        "draft_clipboard_fingerprint",
        "draft_clipboard_character_count",
        "draft_clipboard_topic_labels",
        "previous_clipboard_read",
        "previous_clipboard_fingerprint",
        "previous_clipboard_character_count",
        "previous_clipboard_topic_labels",
        "draft_clipboard_copy",
        "clipboard_restored",
        "clipboard_restore_status",
        "clipboard_restore_reason",
        "stage_status",
        "staged_text_verified",
        "staged_text_verification",
        "post_send_verification",
        "outbound_message_verification",
        "target_binding_verification",
        "managed_live_send_guidance",
        "recovery_commands",
        "forbidden_actions",
        "subscription_paywall_recovery",
        "paywall_recovered_and_retried",
        "feedback_survey_recovery",
        "evidence",
    )
    return {key: payload[key] for key in keys if key in payload}


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
