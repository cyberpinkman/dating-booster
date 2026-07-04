from __future__ import annotations

from dating_boost.cli_ops import *

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
        if replayed_action_requests and not _replayed_action_requests_still_active(args.data_dir, replayed_action_requests):
            replay = None
        else:
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
        if args.max_pages_per_cycle is not None:
            payload = {
                "schema_version": 1,
                "status": "blocked",
                "reason": "message_list_scan_boundary_framework_controlled",
                "message_list_scan_boundary": dict(MANAGED_SESSION_SCAN_BOUNDARY),
                "user_configurable_fields": list(MANAGED_SESSION_USER_CONFIGURABLE_FIELDS),
            }
            _print_json(payload)
            return 2
        proposed_config = managed_session_proposed_config(
            managed_session_policy(args.app_id),
            app_id=args.app_id,
            send_mode=args.send_mode,
            managed_gui_send=args.managed_gui_send,
            scan_interval_seconds=args.scan_interval,
            nudge_delay_minutes=args.nudge_delay_minutes,
            management_mode=args.management_mode,
            max_threads_per_cycle=args.max_threads_per_cycle,
            cycle_send_limit=args.cycle_send_limit,
            harness_runtime=args.harness_runtime,
        )
        required_confirm_token = managed_session_config_confirm_token(proposed_config)
        if args.config_confirm != required_confirm_token:
            payload = {
                "schema_version": 1,
                "status": "blocked",
                "reason": "managed_session_config_confirmation_required",
                "required_confirm_token": required_confirm_token,
                "proposed_config": proposed_config,
                "user_configurable_fields": list(MANAGED_SESSION_USER_CONFIGURABLE_FIELDS),
                "framework_controlled_fields": ["message_list_scan_boundary"],
                "next_host_action": "present_managed_session_config_and_get_user_confirmation",
            }
            _print_json(payload)
            return 2
        payload = ManagedSessionRepository(args.data_dir).start(
            app_id=args.app_id,
            authorization=_read_json_object(args.authorization),
            goal=_read_json_object(args.goal),
            availability=_read_json_object(args.availability),
            send_mode=args.send_mode,
            managed_gui_send=args.managed_gui_send,
            scan_interval_seconds=args.scan_interval,
            nudge_delay_minutes=args.nudge_delay_minutes,
            management_mode=args.management_mode,
            max_threads_per_cycle=args.max_threads_per_cycle,
            max_pages_per_cycle=args.max_pages_per_cycle,
            cycle_send_limit=args.cycle_send_limit,
            harness_runtime=args.harness_runtime,
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


def _handle_standalone_session_start(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_provider_factory import build_standalone_runtime_ports
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    repository = StandaloneSessionRepository(args.data_dir)
    current = repository.status()
    if current.get("status") == "active":
        payload = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "standalone_session_already_active",
            "session": current.get("session"),
        }
        _print_json(payload)
        return 2

    if args.send_mode == "live" and not args.managed_gui_send:
        payload = {"schema_version": 1, "status": "blocked", "reason": "managed_gui_send_required_for_live_mode"}
        _print_json(payload)
        return 2

    source_payload = _standalone_observation_source_payload(args)
    if source_payload.get("status") == "blocked":
        _print_json(source_payload)
        return 2
    observation_source = source_payload["observation_source"]
    vision_backend = source_payload.get("vision_backend") if isinstance(source_payload.get("vision_backend"), dict) else {}

    backend_payload = _standalone_backend_payload(args)
    if backend_payload.get("status") == "blocked":
        _print_json(backend_payload)
        return 2
    proposed_config = managed_session_proposed_config(
        managed_session_policy(args.app_id),
        app_id=args.app_id,
        send_mode=args.send_mode,
        managed_gui_send=args.managed_gui_send,
        scan_interval_seconds=args.scan_interval,
        nudge_delay_minutes=DEFAULT_NUDGE_DELAY_MINUTES,
        management_mode="conservative",
        max_threads_per_cycle=None,
        cycle_send_limit=None,
        harness_runtime=args.runtime,
        initial_surface=args.initial_surface,
    )
    required_confirm_token = managed_session_config_confirm_token(proposed_config)
    if args.config_confirm != required_confirm_token:
        payload = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "managed_session_config_confirmation_required",
            "required_confirm_token": required_confirm_token,
            "proposed_config": proposed_config,
            "user_configurable_fields": list(MANAGED_SESSION_USER_CONFIGURABLE_FIELDS),
            "framework_controlled_fields": ["message_list_scan_boundary"],
            "next_host_action": "present_managed_session_config_and_get_user_confirmation",
        }
        _print_json(payload)
        return 2
    backend = backend_payload["backend"]
    ports = build_standalone_runtime_ports(
        args.data_dir,
        {
            "app_id": args.app_id,
            "runtime": args.runtime,
            "send_mode": args.send_mode,
            "managed_gui_send": bool(args.managed_gui_send),
            "observation_source": observation_source,
            "vision_backend": vision_backend,
        },
    )
    if ports.get("status") != "ok":
        _print_json(ports)
        return 2
    try:
        managed_payload = ManagedSessionRepository(
            args.data_dir,
            harness_factory=ports["harness_factory"],
        ).start(
            app_id=args.app_id,
            authorization=_read_json_object(args.authorization),
            goal=None,
            availability=None,
            send_mode=args.send_mode,
            managed_gui_send=args.managed_gui_send,
            scan_interval_seconds=args.scan_interval,
            harness_runtime=args.runtime,
            initial_surface=args.initial_surface,
        )
    except ValueError as exc:
        managed_payload = {"schema_version": 1, "status": "blocked", "reason": str(exc)}
    if managed_payload.get("status") not in {"active", "paused"}:
        _print_json(managed_payload)
        return 2

    payload = repository.start(
        app_id=args.app_id,
        runtime=args.runtime,
        send_mode=args.send_mode,
        observation_source=observation_source,
        backend=backend,
        scan_interval_seconds=args.scan_interval,
        managed_gui_send=bool(args.managed_gui_send),
        vision_backend=vision_backend,
        initial_surface=args.initial_surface,
    )
    payload["managed_session"] = managed_payload
    if payload.get("status") != "active":
        ManagedSessionRepository(args.data_dir).stop(reason="standalone_session_start_failed")
    _print_json(payload)
    return 0 if payload.get("status") == "active" else 2


def _handle_standalone_session_tick(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_provider_factory import build_standalone_runtime_ports
    from dating_boost.core.standalone_runtime import StandaloneAgentRuntime, StandaloneDraftPlanner
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    repository = StandaloneSessionRepository(args.data_dir)
    status = repository.status()
    session = status.get("session") if isinstance(status.get("session"), dict) else None
    if not isinstance(session, dict):
        _print_json(status)
        return 2
    ports = build_standalone_runtime_ports(args.data_dir, session)
    if ports.get("status") != "ok":
        _print_json(ports)
        return 2
    payload = StandaloneAgentRuntime(
        args.data_dir,
        observation_provider=ports["observation_provider"],
        harness_factory=ports["harness_factory"],
        action_executor=ports["action_executor"],
        draft_planner=StandaloneDraftPlanner(
            args.data_dir,
            backend_config=session.get("backend") or {},
            allow_stage_soft_accept=str(session.get("send_mode") or "").strip() == "stage",
        ),
    ).tick()
    repository.record_tick(payload)
    _print_json(payload)
    return 0 if payload.get("status") not in {"blocked", "error"} else 2


def _handle_standalone_session_status(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    payload = StandaloneSessionRepository(args.data_dir).status()
    _print_json(payload)
    return 0 if payload.get("status") != "not_found" else 2


def _handle_standalone_session_stop(args: argparse.Namespace) -> int:
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    payload = StandaloneSessionRepository(args.data_dir).stop(reason=args.reason)
    payload["managed_session"] = ManagedSessionRepository(args.data_dir).stop(reason=args.reason)
    _print_json(payload)
    return 0


def _standalone_observation_source_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.observation_source == "fixture":
        if args.observation_fixture_dir is None:
            return {"schema_version": 1, "status": "blocked", "reason": "standalone_observation_fixture_dir_required"}
        fixture_dir = args.observation_fixture_dir.expanduser().resolve()
        if not fixture_dir.is_dir():
            return {"schema_version": 1, "status": "blocked", "reason": "observation_fixture_dir_not_found"}
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source": {"type": "fixture_dir", "path": str(fixture_dir)},
            "vision_backend": {},
        }

    if args.observation_source == "live-gui":
        if args.vision_backend is None:
            return {"schema_version": 1, "status": "blocked", "reason": "vision_backend_required_for_live_gui_source"}
        if args.vision_backend == "scripted":
            if args.scripted_vision_output is None:
                return {"schema_version": 1, "status": "blocked", "reason": "scripted_vision_output_required"}
            path = args.scripted_vision_output.expanduser().resolve()
            if not path.is_file():
                return {"schema_version": 1, "status": "blocked", "reason": "scripted_vision_output_not_found"}
            vision_backend = {"type": "scripted", "path": str(path)}
        elif args.vision_backend == "openai":
            if args.scripted_vision_output is not None:
                return {
                    "schema_version": 1,
                    "status": "blocked",
                    "reason": "scripted_vision_output_only_for_scripted_vision_backend",
                }
            vision_backend = {"type": "openai", "model": args.vision_model or "gpt-4.1-mini"}
        else:
            if args.scripted_vision_output is not None:
                return {
                    "schema_version": 1,
                    "status": "blocked",
                    "reason": "scripted_vision_output_only_for_scripted_vision_backend",
                }
            vision_backend = {
                "type": "minimax",
                "model": args.vision_model or MINIMAX_DEFAULT_MODEL,
                "base_url": args.minimax_base_url or MINIMAX_DEFAULT_BASE_URL,
                "api_key_env": args.minimax_api_key_env or MINIMAX_DEFAULT_API_KEY_ENV,
            }
            timeout_seconds = _standalone_minimax_request_timeout(args)
            if timeout_seconds is not None:
                vision_backend["timeout_seconds"] = timeout_seconds
        source: dict[str, Any] = {
            "type": "live_gui",
            "app_id": args.app_id,
            "runtime": args.runtime,
        }
        if args.output_dir is not None:
            source["output_dir"] = str(args.output_dir.expanduser().resolve())
        return {
            "schema_version": 1,
            "status": "ok",
            "observation_source": source,
            "vision_backend": vision_backend,
        }

    return {"schema_version": 1, "status": "blocked", "reason": "unsupported_standalone_observation_source"}


def _standalone_backend_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.backend == "scripted":
        if args.scripted_backend_output is None:
            return {"schema_version": 1, "status": "blocked", "reason": "scripted_backend_output_required"}
        path = args.scripted_backend_output.expanduser().resolve()
        if not path.is_file():
            return {"schema_version": 1, "status": "blocked", "reason": "scripted_backend_output_not_found"}
        return {
            "schema_version": 1,
            "status": "ok",
            "backend": {"type": "scripted", "model": args.model, "path": str(path)},
        }
    if args.scripted_backend_output is not None:
        return {"schema_version": 1, "status": "blocked", "reason": "scripted_backend_output_only_for_scripted_backend"}
    if args.backend == "minimax":
        backend = {
            "type": "minimax",
            "model": args.model or MINIMAX_DEFAULT_MODEL,
            "base_url": args.minimax_base_url or MINIMAX_DEFAULT_BASE_URL,
            "api_key_env": args.minimax_api_key_env or MINIMAX_DEFAULT_API_KEY_ENV,
        }
        timeout_seconds = _standalone_minimax_request_timeout(args)
        if timeout_seconds is not None:
            backend["timeout_seconds"] = timeout_seconds
        return {
            "schema_version": 1,
            "status": "ok",
            "backend": backend,
        }
    return {"schema_version": 1, "status": "ok", "backend": {"type": args.backend, "model": args.model or "gpt-4.1-mini"}}


def _standalone_minimax_request_timeout(args: argparse.Namespace) -> float | None:
    value = getattr(args, "minimax_request_timeout_seconds", None)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _handle_operator_session_start(args: argparse.Namespace) -> int:
    if args.max_pages_per_cycle is not None:
        _print_json(
            {
                "schema_version": 1,
                "status": "blocked",
                "reason": "message_list_scan_boundary_framework_controlled",
                "message_list_scan_boundary": dict(MANAGED_SESSION_SCAN_BOUNDARY),
            }
        )
        return 2
    try:
        payload = OperatorRepository(args.data_dir).start_session(
            _read_json_object(args.authorization),
            initial_surface=args.initial_surface,
            management_mode=args.management_mode,
            max_threads_per_cycle=args.max_threads_per_cycle,
            max_pages_per_cycle=args.max_pages_per_cycle,
            cycle_send_limit=args.cycle_send_limit,
        )
    except ValueError as exc:
        _print_json({"schema_version": 1, "status": "error", "reason": str(exc)})
        return 2
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


def _handle_operator_record_stage_result(args: argparse.Namespace) -> int:
    try:
        payload = OperatorRepository(args.data_dir).record_stage_result(_read_json_object(args.input))
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


def _derive_run_id(scan_batch: dict[str, Any]) -> str:
    return f"run_{_digest({'idempotency': _idempotency_seed(scan_batch), 'now': _now_iso()})[:16]}"


def _derive_idempotency_key(scan_batch: dict[str, Any]) -> str:
    return "idem:" + _digest(_idempotency_seed(scan_batch))


def _replayed_action_requests_still_active(data_dir: Path, action_requests: list[Any]) -> bool:
    active_requests: set[tuple[str, str | None]] = set()
    for state in AutomationRepository(data_dir).load_states():
        if state.get("state") != "send_requested":
            continue
        action_request_id = state.get("last_action_request_id")
        if not action_request_id:
            continue
        payload_hash = state.get("last_outbound_payload_hash")
        active_requests.add((str(action_request_id), str(payload_hash) if payload_hash else None))
    for item in action_requests:
        if not isinstance(item, dict):
            continue
        action_request_id = item.get("action_request_id")
        if not action_request_id:
            continue
        payload_hash = item.get("payload_hash")
        request_key = (str(action_request_id), str(payload_hash) if payload_hash else None)
        if request_key not in active_requests:
            return False
    return True


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


__all__ = [name for name in globals() if not name.startswith("__")]
