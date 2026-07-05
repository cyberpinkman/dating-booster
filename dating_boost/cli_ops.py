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

from dating_boost.apps.registry import adapter_manifests, create_adapter, managed_session_policy, manifest_for_app, supported_app_ids
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
from dating_boost.core.draft_evidence import DraftEvidencePack, build_draft_evidence
from dating_boost.core.draft_review_audit import DraftReviewAuditRepository
from dating_boost.core.feedback import create_feedback_event
from dating_boost.core.live_send_contract import (
    live_send_action_request_block_reason,
    live_send_authorization_block_reason,
    live_send_next_host_action,
    managed_live_send_guidance,
    validate_live_send_contract,
)
from dating_boost.core.managed_session import (
    DEFAULT_NUDGE_DELAY_MINUTES,
    MANAGED_SESSION_SCAN_BOUNDARY,
    MANAGED_SESSION_USER_CONFIGURABLE_FIELDS,
    ManagedSessionRepository,
    managed_session_config_confirm_token,
    managed_session_proposed_config,
)
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
from dating_boost.core.repositories import (
    JsonMemoryRepository,
    MatchRepository,
    ObservationRepository,
    user_profile_from_dict,
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository
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
from dating_boost.intelligence.backend_factory import create_model_backend
from dating_boost.intelligence.backends import (
    MINIMAX_DEFAULT_API_KEY_ENV,
    MINIMAX_DEFAULT_BASE_URL,
    MINIMAX_DEFAULT_MODEL,
    ModelBackend,
)
from dating_boost.intelligence.draft_generation import DraftGenerationResult, generate_reply_with_refinement
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.evals.runner import run_conversation_eval, run_memory_eval, run_memory_review_eval
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.policy import Action, authorize_action
from dating_boost.policy.draft_review import DraftReviewDecision, review_draft
from dating_boost.core.user_disclosure import UserDisclosureRepository, interview_template


MVP_TIMESTAMP = "2026-05-25T00:00:00Z"
SUPPORTED_NATIVE_HARNESS_APPS = tuple(supported_app_ids())
SUPPORTED_MANAGED_SESSION_APPS = tuple(supported_app_ids())



def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    payload = DaemonRepository(args.data_dir).run(
        once=args.once,
        owner="dating-boostd",
        now=_now_iso(),
        standalone_tick=bool(args.standalone_tick),
    )
    _print_json(payload)
    standalone_tick = payload.get("standalone_tick") if isinstance(payload.get("standalone_tick"), dict) else None
    if standalone_tick and standalone_tick.get("status") == "blocked":
        return 2
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
    event_payload = json.loads(args.payload_json) if args.payload_json is not None else _read_json_object(args.payload)
    if not isinstance(event_payload, dict):
        raise ValueError("--payload-json must decode to a JSON object")
    payload = SupportLogRepository(args.data_dir).record_event(
        session_id=args.session_id,
        event_type=args.event_type,
        payload=event_payload,
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


def _handle_runtime_select(args: argparse.Namespace) -> int:
    try:
        payload = RuntimeScopeRepository(args.data_dir).select(
            app_id=args.app_id,
            runtime=args.runtime,
            source="runtime_select",
        )
    except ValueError as exc:
        payload = {"schema_version": 1, "status": "blocked", "reason": str(exc)}
    _print_json(payload)
    return 0 if payload.get("status") == "selected" else 2


def _handle_runtime_status(args: argparse.Namespace) -> int:
    payload = RuntimeScopeRepository(args.data_dir).read()
    if payload is None:
        payload = {"schema_version": 1, "status": "not_found", "reason": "runtime_scope_not_selected"}
    _print_json(payload)
    return 0 if payload.get("status") in {"selected", "not_found"} else 2


def _handle_runtime_clear(args: argparse.Namespace) -> int:
    payload = RuntimeScopeRepository(args.data_dir).clear(reason=args.reason)
    _print_json(payload)
    return 0


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
    profile = user_profile_from_dict(data)
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


def _select_backend(args: argparse.Namespace) -> ModelBackend:
    backend_name = args.backend or ("scripted" if args.scripted_backend_output else "openai")
    if backend_name == "scripted":
        if args.scripted_backend_output is None:
            raise ValueError("--backend scripted requires --scripted-backend-output")
        return create_model_backend({"type": "scripted", "path": str(args.scripted_backend_output)})
    if args.scripted_backend_output is not None:
        raise ValueError("--scripted-backend-output can only be used with --backend scripted")
    if backend_name == "minimax":
        return create_model_backend(
            {
                "type": "minimax",
                "model": args.model or MINIMAX_DEFAULT_MODEL,
                "base_url": args.minimax_base_url or MINIMAX_DEFAULT_BASE_URL,
                "api_key_env": args.minimax_api_key_env or MINIMAX_DEFAULT_API_KEY_ENV,
            }
        )
    return create_model_backend({"type": "openai", "model": args.model or "gpt-4.1-mini"})


def _record_support_draft_review(
    data_dir: Path,
    *,
    draft_payload: dict[str, Any],
    context_pack: dict[str, Any],
    review: DraftReviewDecision,
    command: str = "policy_check_draft",
) -> None:
    try:
        repository = SupportLogRepository(data_dir)
        active = repository.active_session()
        if not active:
            return
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type="draft_review",
            payload={
                "command": command,
                "target_match_id": context_pack.get("match_id"),
                "review_id": review.review_id,
                "draft_review_summary": review.summary,
                "context_source_manifest": context_source_manifest(context_pack),
                "draft_fingerprint": hashlib.sha256(
                    str(draft_payload.get("best_reply") or "").encode("utf-8")
                ).hexdigest(),
                "draft_character_count": len(str(draft_payload.get("best_reply") or "")),
                "draft_topic_labels": classify_text_topics(str(draft_payload.get("best_reply") or "")),
            },
            sensitive={
                "draft_payload": draft_payload,
                "context_pack": context_pack,
                "draft_review": review.to_dict(),
            },
            sensitive_kind="draft",
        )
    except Exception:
        return


def _record_support_draft_generation(
    data_dir: Path,
    *,
    evidence: DraftEvidencePack,
    generation: DraftGenerationResult,
    command: str,
) -> None:
    try:
        repository = SupportLogRepository(data_dir)
        active = repository.active_session()
        if not active:
            return
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type="draft_generation",
            payload={
                "command": command,
                "target_match_id": evidence.match_id,
                "evidence_id": evidence.evidence_id,
                "generation_id": generation.generation_id,
                "status": generation.status,
                "primary_reason": generation.primary_reason,
                "draft_generation_summary": generation.summary(),
                "evidence_manifest": evidence.evidence_manifest,
            },
            sensitive={
                "draft_evidence": evidence.to_dict(),
                "draft_prompt": generation.prompt.to_dict(),
                "draft_payload": generation.draft_payload,
            },
            sensitive_kind="draft",
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


__all__ = [name for name in globals() if not name.startswith("__")]
