from __future__ import annotations

from dating_boost import cli_ops as _cli_ops
from dating_boost.cli_ops import (
    annotations, argparse, datetime, timezone,
    hashlib, json, os, sys,
    time, asdict, Path, Any,
    adapter_manifests, create_adapter, managed_session_policy, manifest_for_app,
    supported_app_ids, install_claude_code_adapter, install_codex_adapter, install_openclaw_adapter,
    run_claude_code_adapter_doctor, run_codex_adapter_doctor, run_openclaw_adapter_doctor, ActionAuditRepository,
    AutomationRepository, build_capabilities, build_context_pack, DaemonRepository,
    DiagnosticsRepository, DraftEvidencePack, build_draft_evidence, DraftReviewAuditRepository,
    create_feedback_event, live_send_action_request_block_reason, live_send_authorization_block_reason, live_send_next_host_action,
    managed_live_send_guidance, validate_live_send_contract, DEFAULT_NUDGE_DELAY_MINUTES, MANAGED_SESSION_SCAN_BOUNDARY,
    MANAGED_SESSION_USER_CONFIGURABLE_FIELDS, ManagedSessionRepository, managed_session_config_confirm_token, managed_session_proposed_config,
    store_observation_with_memory, CommitmentMemory, EvidenceRef, MemoryEvent,
    MemoryEventType, MemoryFact, MemoryFactType, MemoryScope,
    MemoryRepository, build_memory_context, Divergence, MemoryItem,
    ReplyMode, UserProfile, normalize_observation, observation_template,
    validate_observation, OperatorRepository, PlannerRepository, planner_context_items,
    ProductionDataStore, payload_digest, release_doctor, latest_replay_markdown,
    latest_replay_payload, JsonMemoryRepository, MatchRepository, ObservationRepository,
    user_profile_from_dict, RuntimeScopeRepository, assemble_scan_batch, normalize_scan_batch,
    scan_template, validate_scan_batch, run_skill_doctor, SafetyRepository,
    StorageError, SupportLogRepository, classify_text_topics, context_source_manifest,
    create_model_backend, MINIMAX_DEFAULT_API_KEY_ENV, MINIMAX_DEFAULT_BASE_URL, MINIMAX_DEFAULT_MODEL,
    ModelBackend, DraftGenerationResult, generate_reply_with_refinement, DraftResponse,
    run_conversation_eval, run_memory_eval, run_memory_review_eval, load_observation,
    AppObservation, build_observation_from_screenshot_analysis, Action, authorize_action,
    DraftReviewDecision, review_draft, UserDisclosureRepository, interview_template,
    MVP_TIMESTAMP, SUPPORTED_NATIVE_HARNESS_APPS, SUPPORTED_MANAGED_SESSION_APPS, _now_iso,
    _run_authorization, _unsupported_harness_app_argv_payload, _run_handler_with_support_logging, _handle_capabilities,
    _handle_skill_doctor, _handle_adapter_claude_code_install, _handle_adapter_claude_code_doctor, _handle_adapter_openclaw_install,
    _handle_adapter_openclaw_doctor, _handle_adapter_hermes_install, _handle_adapter_hermes_doctor, _handle_adapter_codex_install,
    _handle_adapter_codex_doctor, _handle_data_doctor, _handle_data_migrate, _handle_data_export,
    _handle_data_delete, _handle_data_unlock, _handle_data_lock, _handle_data_rekey,
    _handle_data_backup, _handle_data_restore, _recovery_passphrase, _handle_safety_pause,
    _handle_safety_resume, _handle_safety_status, _handle_daemon_run, _handle_daemon_install,
    _handle_daemon_uninstall, _handle_daemon_status, _handle_daemon_stop, _handle_diagnostics_doctor,
    _handle_diagnostics_bundle, _handle_support_session_start, _handle_support_session_stop, _handle_support_record_event,
    _handle_support_bundle, _handle_runtime_select, _handle_runtime_status, _handle_runtime_clear,
    _handle_confirmation_create, _handle_confirmation_confirm, _handle_confirmation_validate, _handle_authorize,
    _handle_policy_check_action, _print_action_decision, _handle_init_profile, _handle_user_interview_template,
    _handle_user_ingest_profile, _handle_user_ingest_interview, _handle_user_disclosure_profile, _handle_user_readiness,
    _select_backend, _record_support_draft_review, _record_support_draft_generation, _record_support_harness_result,
    _record_support_harness_action, _support_target_match_id, _support_safe_harness_payload, _read_json_object,
    _read_json_payload, _add_confirmation_binding_args, _unique_cli_strings, _digest,
    _validate_storage_id, _print_json,
)
from dating_boost.cli_harness import (
    annotations, sys, _registry_create_adapter, argparse,
    datetime, timezone, hashlib, json,
    os, time, asdict, Path,
    Any, adapter_manifests, create_adapter, managed_session_policy,
    manifest_for_app, supported_app_ids, install_claude_code_adapter, install_codex_adapter,
    install_openclaw_adapter, run_claude_code_adapter_doctor, run_codex_adapter_doctor, run_openclaw_adapter_doctor,
    ActionAuditRepository, AutomationRepository, build_capabilities, build_context_pack,
    DaemonRepository, DiagnosticsRepository, DraftEvidencePack, build_draft_evidence,
    DraftReviewAuditRepository, create_feedback_event, live_send_action_request_block_reason, live_send_authorization_block_reason,
    live_send_next_host_action, managed_live_send_guidance, validate_live_send_contract, DEFAULT_NUDGE_DELAY_MINUTES,
    MANAGED_SESSION_SCAN_BOUNDARY, MANAGED_SESSION_USER_CONFIGURABLE_FIELDS, ManagedSessionRepository, managed_session_config_confirm_token,
    managed_session_proposed_config, store_observation_with_memory, CommitmentMemory, EvidenceRef,
    MemoryEvent, MemoryEventType, MemoryFact, MemoryFactType,
    MemoryScope, MemoryRepository, build_memory_context, Divergence,
    MemoryItem, ReplyMode, UserProfile, normalize_observation,
    observation_template, validate_observation, OperatorRepository, PlannerRepository,
    planner_context_items, ProductionDataStore, payload_digest, release_doctor,
    latest_replay_markdown, latest_replay_payload, JsonMemoryRepository, MatchRepository,
    ObservationRepository, user_profile_from_dict, RuntimeScopeRepository, assemble_scan_batch,
    normalize_scan_batch, scan_template, validate_scan_batch, run_skill_doctor,
    SafetyRepository, StorageError, SupportLogRepository, classify_text_topics,
    context_source_manifest, create_model_backend, MINIMAX_DEFAULT_API_KEY_ENV, MINIMAX_DEFAULT_BASE_URL,
    MINIMAX_DEFAULT_MODEL, ModelBackend, DraftGenerationResult, generate_reply_with_refinement,
    DraftResponse, run_conversation_eval, run_memory_eval, run_memory_review_eval,
    load_observation, AppObservation, build_observation_from_screenshot_analysis, Action,
    authorize_action, DraftReviewDecision, review_draft, UserDisclosureRepository,
    interview_template, MVP_TIMESTAMP, SUPPORTED_NATIVE_HARNESS_APPS, SUPPORTED_MANAGED_SESSION_APPS,
    _now_iso, _run_authorization, _unsupported_harness_app_argv_payload, _run_handler_with_support_logging,
    _handle_capabilities, _handle_skill_doctor, _handle_adapter_claude_code_install, _handle_adapter_claude_code_doctor,
    _handle_adapter_openclaw_install, _handle_adapter_openclaw_doctor, _handle_adapter_hermes_install, _handle_adapter_hermes_doctor,
    _handle_adapter_codex_install, _handle_adapter_codex_doctor, _handle_data_doctor, _handle_data_migrate,
    _handle_data_export, _handle_data_delete, _handle_data_unlock, _handle_data_lock,
    _handle_data_rekey, _handle_data_backup, _handle_data_restore, _recovery_passphrase,
    _handle_safety_pause, _handle_safety_resume, _handle_safety_status, _handle_daemon_run,
    _handle_daemon_install, _handle_daemon_uninstall, _handle_daemon_status, _handle_daemon_stop,
    _handle_diagnostics_doctor, _handle_diagnostics_bundle, _handle_support_session_start, _handle_support_session_stop,
    _handle_support_record_event, _handle_support_bundle, _handle_runtime_select, _handle_runtime_status,
    _handle_runtime_clear, _handle_confirmation_create, _handle_confirmation_confirm, _handle_confirmation_validate,
    _handle_authorize, _handle_policy_check_action, _print_action_decision, _handle_init_profile,
    _handle_user_interview_template, _handle_user_ingest_profile, _handle_user_ingest_interview, _handle_user_disclosure_profile,
    _handle_user_readiness, _select_backend, _record_support_draft_review, _record_support_draft_generation,
    _record_support_harness_result, _record_support_harness_action, _support_target_match_id, _support_safe_harness_payload,
    _read_json_object, _read_json_payload, _add_confirmation_binding_args, _unique_cli_strings,
    _digest, _validate_storage_id, _print_json, _add_harness_app_parsers,
    _add_harness_common_args, _manifest_supports_stage_draft, _handle_harness_doctor, _handle_harness_screenshot,
    _unsupported_native_harness_payload, _create_harness_adapter, _active_cli_adapter_factory, _runtime_scope_block_payload,
    _options_from_json, _handle_harness_app_launch, _handle_harness_app_alias, _handle_harness_app_observe,
    _handle_harness_app_action, _handle_harness_app_workflow, _handle_harness_app_stage_draft, _handle_harness_app_send_message,
    _live_send_cli_block_payload, _wechat_live_send_authorization_block_reason, _live_send_authorization_block_reason, _wechat_live_send_action_request_block_reason,
    _live_send_action_request_block_reason, _live_send_next_host_action, _harness_window_title, _handle_release_doctor,
    _handle_release_gate_tashuo_stage_alpha, _release_gate_tashuo_stage_alpha_argv, _handle_beta_readiness, _handle_beta_feedback_record,
    _handle_beta_tashuo_stage_start, _handle_beta_tashuo_stage_run, _handle_beta_tashuo_stage_status, _handle_beta_tashuo_stage_stop,
    _handle_beta_tashuo_stage_report,
)
from dating_boost.cli_memory import (
    annotations, argparse, datetime, timezone,
    hashlib, json, os, sys,
    time, asdict, Path, Any,
    adapter_manifests, create_adapter, managed_session_policy, manifest_for_app,
    supported_app_ids, install_claude_code_adapter, install_codex_adapter, install_openclaw_adapter,
    run_claude_code_adapter_doctor, run_codex_adapter_doctor, run_openclaw_adapter_doctor, ActionAuditRepository,
    AutomationRepository, build_capabilities, build_context_pack, DaemonRepository,
    DiagnosticsRepository, DraftEvidencePack, build_draft_evidence, DraftReviewAuditRepository,
    create_feedback_event, live_send_action_request_block_reason, live_send_authorization_block_reason, live_send_next_host_action,
    managed_live_send_guidance, validate_live_send_contract, DEFAULT_NUDGE_DELAY_MINUTES, MANAGED_SESSION_SCAN_BOUNDARY,
    MANAGED_SESSION_USER_CONFIGURABLE_FIELDS, ManagedSessionRepository, managed_session_config_confirm_token, managed_session_proposed_config,
    store_observation_with_memory, CommitmentMemory, EvidenceRef, MemoryEvent,
    MemoryEventType, MemoryFact, MemoryFactType, MemoryScope,
    MemoryRepository, build_memory_context, Divergence, MemoryItem,
    ReplyMode, UserProfile, normalize_observation, observation_template,
    validate_observation, OperatorRepository, PlannerRepository, planner_context_items,
    ProductionDataStore, payload_digest, release_doctor, latest_replay_markdown,
    latest_replay_payload, JsonMemoryRepository, MatchRepository, ObservationRepository,
    user_profile_from_dict, RuntimeScopeRepository, assemble_scan_batch, normalize_scan_batch,
    scan_template, validate_scan_batch, run_skill_doctor, SafetyRepository,
    StorageError, SupportLogRepository, classify_text_topics, context_source_manifest,
    create_model_backend, MINIMAX_DEFAULT_API_KEY_ENV, MINIMAX_DEFAULT_BASE_URL, MINIMAX_DEFAULT_MODEL,
    ModelBackend, DraftGenerationResult, generate_reply_with_refinement, DraftResponse,
    run_conversation_eval, run_memory_eval, run_memory_review_eval, load_observation,
    AppObservation, build_observation_from_screenshot_analysis, Action, authorize_action,
    DraftReviewDecision, review_draft, UserDisclosureRepository, interview_template,
    MVP_TIMESTAMP, SUPPORTED_NATIVE_HARNESS_APPS, SUPPORTED_MANAGED_SESSION_APPS, _now_iso,
    _run_authorization, _unsupported_harness_app_argv_payload, _run_handler_with_support_logging, _handle_capabilities,
    _handle_skill_doctor, _handle_adapter_claude_code_install, _handle_adapter_claude_code_doctor, _handle_adapter_openclaw_install,
    _handle_adapter_openclaw_doctor, _handle_adapter_hermes_install, _handle_adapter_hermes_doctor, _handle_adapter_codex_install,
    _handle_adapter_codex_doctor, _handle_data_doctor, _handle_data_migrate, _handle_data_export,
    _handle_data_delete, _handle_data_unlock, _handle_data_lock, _handle_data_rekey,
    _handle_data_backup, _handle_data_restore, _recovery_passphrase, _handle_safety_pause,
    _handle_safety_resume, _handle_safety_status, _handle_daemon_run, _handle_daemon_install,
    _handle_daemon_uninstall, _handle_daemon_status, _handle_daemon_stop, _handle_diagnostics_doctor,
    _handle_diagnostics_bundle, _handle_support_session_start, _handle_support_session_stop, _handle_support_record_event,
    _handle_support_bundle, _handle_runtime_select, _handle_runtime_status, _handle_runtime_clear,
    _handle_confirmation_create, _handle_confirmation_confirm, _handle_confirmation_validate, _handle_authorize,
    _handle_policy_check_action, _print_action_decision, _handle_init_profile, _handle_user_interview_template,
    _handle_user_ingest_profile, _handle_user_ingest_interview, _handle_user_disclosure_profile, _handle_user_readiness,
    _select_backend, _record_support_draft_review, _record_support_draft_generation, _record_support_harness_result,
    _record_support_harness_action, _support_target_match_id, _support_safe_harness_payload, _read_json_object,
    _read_json_payload, _add_confirmation_binding_args, _unique_cli_strings, _digest,
    _validate_storage_id, _print_json, _core_user_profile_from_dict, _handle_import_observation,
    _handle_observe_screenshot, _handle_observation_template, _handle_observation_validate, _handle_observation_normalize,
    _persist_observation, _store_observation, _handle_memory_get_match, _handle_memory_rebuild,
    _handle_memory_rebuild_all, _rebuild_memory_match, _handle_memory_update_match, _handle_memory_export,
    _handle_memory_delete_match, _handle_memory_propose, _handle_memory_review_list, _handle_memory_review_decide,
    _apply_memory_update, _apply_memory_identity_merge, _memory_update_event, _corrected_fact,
    _find_memory_fact, _merged_memory_event, _apply_memory_inheritance, _inherited_memory_event,
    _memory_event_id, _manual_evidence, _required_text, _match_record,
    _handle_draft, _handle_context_build, _handle_policy_check_draft, _handle_planner_update,
    _handle_planner_get, _handle_planner_recommend, _handle_planner_event_log, _handle_action_record_result,
    _handle_action_record_correction, _build_mvp_context_pack, _suppress_unbudgeted_memory_context, _semantic_hook_provider,
    _match_profile_from_observation, _conversation_memory_from_observation, _observation_runtime, _observation_summary,
    _profile_from_dict, _profile_to_context_dict, _draft_to_dict, _draft_from_dict,
    _draft_review_public_dict,
)
from dating_boost.cli_sessions import (
    annotations, argparse, datetime, timezone,
    hashlib, json, os, sys,
    time, asdict, Path, Any,
    adapter_manifests, create_adapter, managed_session_policy, manifest_for_app,
    supported_app_ids, install_claude_code_adapter, install_codex_adapter, install_openclaw_adapter,
    run_claude_code_adapter_doctor, run_codex_adapter_doctor, run_openclaw_adapter_doctor, ActionAuditRepository,
    AutomationRepository, build_capabilities, build_context_pack, DaemonRepository,
    DiagnosticsRepository, DraftEvidencePack, build_draft_evidence, DraftReviewAuditRepository,
    create_feedback_event, live_send_action_request_block_reason, live_send_authorization_block_reason, live_send_next_host_action,
    managed_live_send_guidance, validate_live_send_contract, DEFAULT_NUDGE_DELAY_MINUTES, MANAGED_SESSION_SCAN_BOUNDARY,
    MANAGED_SESSION_USER_CONFIGURABLE_FIELDS, ManagedSessionRepository, managed_session_config_confirm_token, managed_session_proposed_config,
    store_observation_with_memory, CommitmentMemory, EvidenceRef, MemoryEvent,
    MemoryEventType, MemoryFact, MemoryFactType, MemoryScope,
    MemoryRepository, build_memory_context, Divergence, MemoryItem,
    ReplyMode, UserProfile, normalize_observation, observation_template,
    validate_observation, OperatorRepository, PlannerRepository, planner_context_items,
    ProductionDataStore, payload_digest, release_doctor, latest_replay_markdown,
    latest_replay_payload, JsonMemoryRepository, MatchRepository, ObservationRepository,
    user_profile_from_dict, RuntimeScopeRepository, assemble_scan_batch, normalize_scan_batch,
    scan_template, validate_scan_batch, run_skill_doctor, SafetyRepository,
    StorageError, SupportLogRepository, classify_text_topics, context_source_manifest,
    create_model_backend, MINIMAX_DEFAULT_API_KEY_ENV, MINIMAX_DEFAULT_BASE_URL, MINIMAX_DEFAULT_MODEL,
    ModelBackend, DraftGenerationResult, generate_reply_with_refinement, DraftResponse,
    run_conversation_eval, run_memory_eval, run_memory_review_eval, load_observation,
    AppObservation, build_observation_from_screenshot_analysis, Action, authorize_action,
    DraftReviewDecision, review_draft, UserDisclosureRepository, interview_template,
    MVP_TIMESTAMP, SUPPORTED_NATIVE_HARNESS_APPS, SUPPORTED_MANAGED_SESSION_APPS, _now_iso,
    _run_authorization, _unsupported_harness_app_argv_payload, _run_handler_with_support_logging, _handle_capabilities,
    _handle_skill_doctor, _handle_adapter_claude_code_install, _handle_adapter_claude_code_doctor, _handle_adapter_openclaw_install,
    _handle_adapter_openclaw_doctor, _handle_adapter_hermes_install, _handle_adapter_hermes_doctor, _handle_adapter_codex_install,
    _handle_adapter_codex_doctor, _handle_data_doctor, _handle_data_migrate, _handle_data_export,
    _handle_data_delete, _handle_data_unlock, _handle_data_lock, _handle_data_rekey,
    _handle_data_backup, _handle_data_restore, _recovery_passphrase, _handle_safety_pause,
    _handle_safety_resume, _handle_safety_status, _handle_daemon_run, _handle_daemon_install,
    _handle_daemon_uninstall, _handle_daemon_status, _handle_daemon_stop, _handle_diagnostics_doctor,
    _handle_diagnostics_bundle, _handle_support_session_start, _handle_support_session_stop, _handle_support_record_event,
    _handle_support_bundle, _handle_runtime_select, _handle_runtime_status, _handle_runtime_clear,
    _handle_confirmation_create, _handle_confirmation_confirm, _handle_confirmation_validate, _handle_authorize,
    _handle_policy_check_action, _print_action_decision, _handle_init_profile, _handle_user_interview_template,
    _handle_user_ingest_profile, _handle_user_ingest_interview, _handle_user_disclosure_profile, _handle_user_readiness,
    _select_backend, _record_support_draft_review, _record_support_draft_generation, _record_support_harness_result,
    _record_support_harness_action, _support_target_match_id, _support_safe_harness_payload, _read_json_object,
    _read_json_payload, _add_confirmation_binding_args, _unique_cli_strings, _digest,
    _validate_storage_id, _print_json, _handle_automation_goal_set, _handle_automation_availability_set,
    _handle_automation_record_authorization, _handle_automation_session_start, _handle_automation_session_step, _handle_automation_session_stop,
    _handle_automation_report_latest, _handle_automation_scan_template, _handle_automation_scan_validate, _handle_automation_scan_normalize,
    _handle_automation_scan_assemble, _handle_automation_get_state, _handle_automation_pause, _handle_automation_resume,
    _handle_managed_session_start, _handle_managed_session_tick, _handle_managed_session_run, _handle_managed_session_notify,
    _handle_managed_session_status, _handle_managed_session_stop, _handle_standalone_session_start, _handle_standalone_session_tick,
    _handle_standalone_session_status, _handle_standalone_session_stop, _standalone_observation_source_payload, _standalone_backend_payload,
    _standalone_minimax_request_timeout, _handle_operator_session_start, _handle_operator_next, _handle_operator_ingest_observation,
    _handle_operator_record_action_result, _handle_operator_record_stage_result, _handle_operator_stop, _handle_operator_report_latest,
    _handle_operator_get_state, _handle_feedback, _handle_eval_run, _handle_replay_latest,
    _record_feedback, _derive_run_id, _derive_idempotency_key, _replayed_action_requests_still_active,
    _idempotency_seed, _lock_blocked_payload,
)


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
    daemon_run_parser.add_argument("--standalone-tick", action="store_true")
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
    support_payload_group = support_record_parser.add_mutually_exclusive_group(required=True)
    support_payload_group.add_argument("--payload", type=Path, help="Path to a JSON payload file.")
    support_payload_group.add_argument("--payload-json", help="Inline JSON object payload.")
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

    runtime_parser = subparsers.add_parser("runtime", help="Select and enforce the target app/runtime for this data-dir.")
    runtime_subparsers = runtime_parser.add_subparsers(dest="runtime_command", required=True)
    runtime_select_parser = runtime_subparsers.add_parser("select")
    runtime_select_parser.add_argument("--data-dir", required=True, type=Path)
    runtime_select_parser.add_argument("--app-id", required=True, choices=SUPPORTED_NATIVE_HARNESS_APPS)
    runtime_select_parser.add_argument("--runtime", default="default")
    runtime_select_parser.add_argument("--json", action="store_true")
    runtime_select_parser.set_defaults(handler=_handle_runtime_select)
    runtime_status_parser = runtime_subparsers.add_parser("status")
    runtime_status_parser.add_argument("--data-dir", required=True, type=Path)
    runtime_status_parser.add_argument("--json", action="store_true")
    runtime_status_parser.set_defaults(handler=_handle_runtime_status)
    runtime_clear_parser = runtime_subparsers.add_parser("clear")
    runtime_clear_parser.add_argument("--data-dir", required=True, type=Path)
    runtime_clear_parser.add_argument("--reason", default="manual_clear")
    runtime_clear_parser.add_argument("--json", action="store_true")
    runtime_clear_parser.set_defaults(handler=_handle_runtime_clear)

    harness_parser = subparsers.add_parser("harness", help="Native GUI harness diagnostics and safe navigation.")
    harness_subparsers = harness_parser.add_subparsers(dest="harness_command", required=True)
    harness_doctor_parser = harness_subparsers.add_parser("doctor")
    harness_doctor_parser.add_argument("--app-id", default="tinder")
    harness_doctor_parser.add_argument("--data-dir", type=Path)
    harness_doctor_parser.add_argument("--window-title")
    harness_doctor_parser.add_argument("--runtime")
    harness_doctor_parser.add_argument("--no-capture", action="store_true")
    harness_doctor_parser.add_argument("--output", type=Path)
    harness_doctor_parser.add_argument("--json", action="store_true")
    harness_doctor_parser.set_defaults(handler=_handle_harness_doctor)
    harness_screenshot_parser = harness_subparsers.add_parser("screenshot")
    harness_screenshot_parser.add_argument("--app-id", default="tinder")
    harness_screenshot_parser.add_argument("--data-dir", type=Path)
    harness_screenshot_parser.add_argument("--window-title")
    harness_screenshot_parser.add_argument("--runtime")
    harness_screenshot_parser.add_argument("--output", required=True, type=Path)
    harness_screenshot_parser.add_argument("--json", action="store_true")
    harness_screenshot_parser.set_defaults(handler=_handle_harness_screenshot)
    _add_harness_app_parsers(harness_subparsers)

    release_parser = subparsers.add_parser("release", help="Public release diagnostics.")
    release_subparsers = release_parser.add_subparsers(dest="release_command", required=True)
    release_doctor_parser = release_subparsers.add_parser("doctor")
    release_doctor_parser.add_argument("--json", action="store_true")
    release_doctor_parser.set_defaults(handler=_handle_release_doctor)
    release_gate_parser = release_subparsers.add_parser("gate", help="Release gate commands.")
    release_gate_subparsers = release_gate_parser.add_subparsers(dest="release_gate_command", required=True)
    tashuo_stage_alpha_parser = release_gate_subparsers.add_parser("tashuo-stage-alpha")
    tashuo_stage_alpha_parser.add_argument("--data-dir", type=Path)
    tashuo_stage_alpha_parser.add_argument("--work-dir", type=Path)
    tashuo_stage_alpha_parser.add_argument("--authorization", type=Path)
    tashuo_stage_alpha_parser.add_argument("--env-file", type=Path)
    tashuo_stage_alpha_parser.add_argument("--runs", type=int)
    tashuo_stage_alpha_parser.add_argument(
        "--initial-surface",
        choices=["mixed", "message-list", "current-thread"],
    )
    tashuo_stage_alpha_parser.add_argument("--continue-on-failure", action="store_true")
    tashuo_stage_alpha_parser.add_argument("--vision-backend", choices=["scripted", "openai", "minimax"])
    tashuo_stage_alpha_parser.add_argument("--vision-model")
    tashuo_stage_alpha_parser.add_argument("--scripted-vision-output", type=Path)
    tashuo_stage_alpha_parser.add_argument("--backend", choices=["scripted", "openai", "minimax"])
    tashuo_stage_alpha_parser.add_argument("--model")
    tashuo_stage_alpha_parser.add_argument("--scripted-backend-output", type=Path)
    tashuo_stage_alpha_parser.add_argument("--minimax-base-url")
    tashuo_stage_alpha_parser.add_argument("--minimax-api-key-env")
    tashuo_stage_alpha_parser.add_argument("--minimax-request-timeout-seconds", type=float)
    tashuo_stage_alpha_parser.add_argument("--max-ticks", type=int)
    tashuo_stage_alpha_parser.add_argument("--step-timeout-seconds", type=float)
    tashuo_stage_alpha_parser.add_argument("--smoke-timeout-seconds", type=float)
    tashuo_stage_alpha_parser.add_argument("--support-session-id")
    tashuo_stage_alpha_parser.add_argument("--validate-evidence-json", type=Path)
    tashuo_stage_alpha_parser.add_argument("--validate-evidence-bundle", type=Path)
    tashuo_stage_alpha_parser.add_argument("--json", action="store_true")
    tashuo_stage_alpha_parser.set_defaults(handler=_handle_release_gate_tashuo_stage_alpha)

    beta_parser = subparsers.add_parser("beta", help="Controlled beta commands.")
    beta_subparsers = beta_parser.add_subparsers(dest="beta_command", required=True)
    beta_readiness_parser = beta_subparsers.add_parser("readiness")
    beta_readiness_parser.add_argument("--data-dir", required=True, type=Path)
    beta_readiness_parser.add_argument("--env-file", type=Path)
    beta_readiness_parser.add_argument("--minimax-api-key-env", default=MINIMAX_DEFAULT_API_KEY_ENV)
    beta_readiness_parser.add_argument("--alpha-evidence-json", type=Path)
    beta_readiness_parser.add_argument("--alpha-evidence-bundle", type=Path)
    beta_readiness_parser.add_argument("--json", action="store_true")
    beta_readiness_parser.set_defaults(handler=_handle_beta_readiness)

    beta_feedback_parser = beta_subparsers.add_parser("feedback")
    beta_feedback_subparsers = beta_feedback_parser.add_subparsers(dest="beta_feedback_command", required=True)
    beta_feedback_record_parser = beta_feedback_subparsers.add_parser("record")
    beta_feedback_record_parser.add_argument("--data-dir", required=True, type=Path)
    beta_feedback_record_parser.add_argument("--input", required=True, type=Path)
    beta_feedback_record_parser.add_argument("--json", action="store_true")
    beta_feedback_record_parser.set_defaults(handler=_handle_beta_feedback_record)

    beta_tashuo_parser = beta_subparsers.add_parser("tashuo-stage")
    beta_tashuo_subparsers = beta_tashuo_parser.add_subparsers(dest="beta_tashuo_stage_command", required=True)
    beta_tashuo_start_parser = beta_tashuo_subparsers.add_parser("start")
    beta_tashuo_start_parser.add_argument("--data-dir", required=True, type=Path)
    beta_tashuo_start_parser.add_argument("--authorization", required=True, type=Path)
    beta_tashuo_start_parser.add_argument("--work-dir", type=Path)
    beta_tashuo_start_parser.add_argument("--env-file", type=Path)
    beta_tashuo_start_parser.add_argument("--minimax-api-key-env", default=MINIMAX_DEFAULT_API_KEY_ENV)
    beta_tashuo_start_parser.add_argument("--host", default="codex")
    beta_tashuo_start_parser.add_argument("--json", action="store_true")
    beta_tashuo_start_parser.set_defaults(handler=_handle_beta_tashuo_stage_start)
    beta_tashuo_run_parser = beta_tashuo_subparsers.add_parser("run")
    beta_tashuo_run_parser.add_argument("--data-dir", required=True, type=Path)
    beta_tashuo_run_parser.add_argument("--authorization", type=Path)
    beta_tashuo_run_parser.add_argument("--work-dir", type=Path)
    beta_tashuo_run_parser.add_argument("--env-file", type=Path)
    beta_tashuo_run_parser.add_argument("--runs", type=int, default=1)
    beta_tashuo_run_parser.add_argument("--initial-surface", choices=["mixed", "message-list", "current-thread"], default="mixed")
    beta_tashuo_run_parser.add_argument("--continue-on-failure", action="store_true")
    beta_tashuo_run_parser.add_argument("--vision-backend", choices=["scripted", "openai", "minimax"], default="minimax")
    beta_tashuo_run_parser.add_argument("--vision-model")
    beta_tashuo_run_parser.add_argument("--scripted-vision-output", type=Path)
    beta_tashuo_run_parser.add_argument("--backend", choices=["scripted", "openai", "minimax"], default="minimax")
    beta_tashuo_run_parser.add_argument("--model")
    beta_tashuo_run_parser.add_argument("--scripted-backend-output", type=Path)
    beta_tashuo_run_parser.add_argument("--minimax-base-url")
    beta_tashuo_run_parser.add_argument("--minimax-api-key-env", default=MINIMAX_DEFAULT_API_KEY_ENV)
    beta_tashuo_run_parser.add_argument("--minimax-request-timeout-seconds", type=float)
    beta_tashuo_run_parser.add_argument("--max-ticks", type=int)
    beta_tashuo_run_parser.add_argument("--step-timeout-seconds", type=float)
    beta_tashuo_run_parser.add_argument("--smoke-timeout-seconds", type=float)
    beta_tashuo_run_parser.add_argument("--json", action="store_true")
    beta_tashuo_run_parser.set_defaults(handler=_handle_beta_tashuo_stage_run)
    beta_tashuo_status_parser = beta_tashuo_subparsers.add_parser("status")
    beta_tashuo_status_parser.add_argument("--data-dir", required=True, type=Path)
    beta_tashuo_status_parser.add_argument("--json", action="store_true")
    beta_tashuo_status_parser.set_defaults(handler=_handle_beta_tashuo_stage_status)
    beta_tashuo_stop_parser = beta_tashuo_subparsers.add_parser("stop")
    beta_tashuo_stop_parser.add_argument("--data-dir", required=True, type=Path)
    beta_tashuo_stop_parser.add_argument("--work-dir", type=Path)
    beta_tashuo_stop_parser.add_argument("--env-file", type=Path)
    beta_tashuo_stop_parser.add_argument("--reason", default="manual_stop")
    beta_tashuo_stop_parser.add_argument("--json", action="store_true")
    beta_tashuo_stop_parser.set_defaults(handler=_handle_beta_tashuo_stage_stop)
    beta_tashuo_report_parser = beta_tashuo_subparsers.add_parser("report")
    beta_tashuo_report_parser.add_argument("--data-dir", required=True, type=Path)
    beta_tashuo_report_parser.add_argument("--format", choices=["json", "md"], default="json")
    beta_tashuo_report_parser.add_argument("--json", action="store_const", const="json", dest="format")
    beta_tashuo_report_parser.set_defaults(handler=_handle_beta_tashuo_stage_report)

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
    memory_review_list_parser.add_argument("--json", action="store_true")
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
    draft_parser.add_argument("--backend", choices=["openai", "scripted", "minimax"])
    draft_parser.add_argument("--model")
    draft_parser.add_argument("--scripted-backend-output", type=Path)
    draft_parser.add_argument("--minimax-base-url", default=MINIMAX_DEFAULT_BASE_URL)
    draft_parser.add_argument("--minimax-api-key-env", default=MINIMAX_DEFAULT_API_KEY_ENV)
    draft_parser.add_argument("--debug-context", action="store_true")
    draft_parser.add_argument("--draft-kind", choices=["reply", "opener"], default="reply")
    draft_parser.add_argument("--reactivation-requested", action="store_true")
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
    context_build_parser.add_argument("--include-draft-evidence", action="store_true")
    context_build_parser.add_argument("--draft-kind", choices=["reply", "opener"], default="reply")
    context_build_parser.add_argument("--reactivation-requested", action="store_true")
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
    policy_check_draft_parser.add_argument(
        "--review-mode",
        choices=["display", "stage", "managed-live"],
        default="display",
    )
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
    action_correction_parser = action_subparsers.add_parser(
        "record-correction",
        help="Append a correction for a previous action or stage audit event.",
    )
    action_correction_parser.add_argument("--data-dir", required=True, type=Path)
    action_correction_parser.add_argument("--input", required=True, type=Path)
    action_correction_parser.set_defaults(handler=_handle_action_record_correction)

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
    managed_start_parser.add_argument("--management-mode", choices=["conservative", "high-throughput"], default="conservative")
    managed_start_parser.add_argument("--max-threads-per-cycle", type=int)
    managed_start_parser.add_argument("--max-pages-per-cycle", type=int, help=argparse.SUPPRESS)
    managed_start_parser.add_argument("--cycle-send-limit", type=int)
    managed_start_parser.add_argument("--harness-runtime")
    managed_start_parser.add_argument("--config-confirm")
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

    standalone_parser = subparsers.add_parser("standalone-session", help="Standalone local agent session commands.")
    standalone_subparsers = standalone_parser.add_subparsers(dest="standalone_session_command", required=True)
    standalone_start_parser = standalone_subparsers.add_parser("start")
    standalone_start_parser.add_argument("--data-dir", required=True, type=Path)
    standalone_start_parser.add_argument("--authorization", required=True, type=Path)
    standalone_start_parser.add_argument("--app-id", required=True, choices=SUPPORTED_MANAGED_SESSION_APPS)
    standalone_start_parser.add_argument("--runtime")
    standalone_start_parser.add_argument("--send-mode", choices=["stage", "live"], default="stage")
    standalone_start_parser.add_argument("--managed-gui-send", action="store_true")
    standalone_start_parser.add_argument("--observation-source", choices=["fixture", "live-gui"], default="live-gui")
    standalone_start_parser.add_argument("--initial-surface", choices=["message-list", "current-thread"], default="message-list")
    standalone_start_parser.add_argument("--observation-fixture-dir", type=Path)
    standalone_start_parser.add_argument("--output-dir", type=Path)
    standalone_start_parser.add_argument("--backend", choices=["scripted", "openai", "minimax"], default="scripted")
    standalone_start_parser.add_argument("--model")
    standalone_start_parser.add_argument("--scripted-backend-output", type=Path)
    standalone_start_parser.add_argument("--minimax-base-url", default=MINIMAX_DEFAULT_BASE_URL)
    standalone_start_parser.add_argument("--minimax-api-key-env", default=MINIMAX_DEFAULT_API_KEY_ENV)
    standalone_start_parser.add_argument("--minimax-request-timeout-seconds", type=float)
    standalone_start_parser.add_argument("--vision-backend", choices=["scripted", "openai", "minimax"])
    standalone_start_parser.add_argument("--vision-model")
    standalone_start_parser.add_argument("--scripted-vision-output", type=Path)
    standalone_start_parser.add_argument("--scan-interval", type=int, default=120)
    standalone_start_parser.add_argument("--config-confirm")
    standalone_start_parser.add_argument("--json", action="store_true")
    standalone_start_parser.set_defaults(handler=_handle_standalone_session_start)
    standalone_tick_parser = standalone_subparsers.add_parser("tick")
    standalone_tick_parser.add_argument("--data-dir", required=True, type=Path)
    standalone_tick_parser.add_argument("--json", action="store_true")
    standalone_tick_parser.set_defaults(handler=_handle_standalone_session_tick)
    standalone_status_parser = standalone_subparsers.add_parser("status")
    standalone_status_parser.add_argument("--data-dir", required=True, type=Path)
    standalone_status_parser.add_argument("--json", action="store_true")
    standalone_status_parser.set_defaults(handler=_handle_standalone_session_status)
    standalone_stop_parser = standalone_subparsers.add_parser("stop")
    standalone_stop_parser.add_argument("--data-dir", required=True, type=Path)
    standalone_stop_parser.add_argument("--reason", default="manual_stop")
    standalone_stop_parser.add_argument("--json", action="store_true")
    standalone_stop_parser.set_defaults(handler=_handle_standalone_session_stop)

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
    operator_session_start_parser.add_argument(
        "--initial-surface",
        choices=["message-list", "current-thread"],
        default="message-list",
    )
    operator_session_start_parser.add_argument("--management-mode", choices=["conservative", "high-throughput"], default="conservative")
    operator_session_start_parser.add_argument("--max-threads-per-cycle", type=int, default=5)
    operator_session_start_parser.add_argument("--max-pages-per-cycle", type=int, help=argparse.SUPPRESS)
    operator_session_start_parser.add_argument("--cycle-send-limit", type=int, default=1)
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

    operator_record_stage_parser = operator_subparsers.add_parser("record-stage-result")
    operator_record_stage_parser.add_argument("--data-dir", required=True, type=Path)
    operator_record_stage_parser.add_argument("--input", required=True, type=Path)
    operator_record_stage_parser.set_defaults(handler=_handle_operator_record_stage_result)

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
    operator_report_latest_parser.add_argument("--json", action="store_const", const="json", dest="format")
    operator_report_latest_parser.set_defaults(handler=_handle_operator_report_latest)

    operator_get_state_parser = operator_subparsers.add_parser("get-state")
    operator_get_state_parser.add_argument("--data-dir", required=True, type=Path)
    operator_get_state_parser.set_defaults(handler=_handle_operator_get_state)

    args = parser.parse_args(argv_list)
    return _run_handler_with_support_logging(args, command_tokens)


def _print_json(data: dict[str, Any]) -> None:
    _cli_ops._print_json(data)


if __name__ == "__main__":
    raise SystemExit(main())
