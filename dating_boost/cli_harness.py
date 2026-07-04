from __future__ import annotations

from dating_boost.cli_ops import *

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

        if _manifest_supports_stage_draft(manifest):
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
    parser.add_argument("--runtime")
    parser.add_argument("--output-dir", type=Path)
    if include_dry_run:
        parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")


def _manifest_supports_stage_draft(manifest: Any) -> bool:
    if "stage_draft" in manifest.supported_stage_actions:
        return True
    for runtime in manifest.runtime_profiles.values():
        if "stage_draft" in list(runtime.get("supported_stage_actions") or []):
            return True
    return False


def _handle_harness_doctor(args: argparse.Namespace) -> int:
    block_payload = _unsupported_native_harness_payload(args.app_id)
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="doctor", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="doctor", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    adapter = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None))
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
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="screenshot", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    payload = _create_harness_adapter(
        args.app_id,
        args.window_title,
        runtime=getattr(args, "runtime", None),
    ).session.capture_window(output=args.output)
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


def _create_harness_adapter(app_id: str, window_title: str | None, *, runtime: str | None = None):
    from dating_boost import cli as cli_module

    return cli_module.create_adapter(
        app_id,
        window_title=_harness_window_title(app_id, window_title, runtime),
        runtime=runtime,
    )


def _runtime_scope_block_payload(args: argparse.Namespace, app_id: str, runtime: str | None) -> dict[str, Any] | None:
    data_dir = getattr(args, "data_dir", None)
    if data_dir is None:
        return {
            "schema_version": 1,
            "status": "blocked",
            "reason": "runtime_scope_data_dir_required",
            "app_id": app_id,
            "requested_app_id": app_id,
            "requested_runtime": runtime or "default",
            "next_host_action": "select_runtime_scope_with_data_dir_before_gui_harness",
            "recovery_commands": [
                (
                    "dating-boost runtime select --data-dir .local/dating-boost "
                    f"--app-id {app_id} --runtime {runtime or 'default'} --json"
                )
            ],
        }
    return RuntimeScopeRepository(data_dir).validate(app_id=app_id, runtime=runtime, require_selected=True)


def _options_from_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _read_json_object(path)


def _handle_harness_app_launch(args: argparse.Namespace) -> int:
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="launch", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    payload = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None)).launch(
        dry_run=args.dry_run,
        output_dir=args.output_dir,
    )
    _record_support_harness_result(args.data_dir, app_id=args.app_id, action="launch", harness_payload=payload)
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_alias(args: argparse.Namespace) -> int:
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action=str(getattr(args, "harness_alias", "alias")), harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    adapter = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None))
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
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="observe", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    payload = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None)).observe(
        output_dir=args.output_dir,
    )
    _record_support_harness_result(args.data_dir, app_id=args.app_id, action="observe", harness_payload=payload)
    _print_json(payload)
    return 0 if payload.get("status") in {"ok", "needs_verification"} else 2


def _handle_harness_app_action(args: argparse.Namespace) -> int:
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action=f"action_{args.action}", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    options = _options_from_json(getattr(args, "options_json", None))
    payload = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None)).run_action(
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
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action=f"workflow_{args.workflow}", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    options = _options_from_json(getattr(args, "options_json", None))
    payload = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None)).run_workflow(
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
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_result(args.data_dir, app_id=args.app_id, action="stage_draft", harness_payload=block_payload)
        _print_json(block_payload)
        return 2
    draft_text = args.text_file.read_text(encoding="utf-8")
    payload = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None)).stage_draft(
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
    block_payload = _runtime_scope_block_payload(args, args.app_id, getattr(args, "runtime", None))
    if block_payload is not None:
        _record_support_harness_action(
            args.data_dir,
            app_id=args.app_id,
            action="send_message",
            draft_text=draft_text,
            harness_payload=block_payload,
            action_request=action_request,
        )
        _print_json(block_payload)
        return 2
    payload = _create_harness_adapter(args.app_id, args.window_title, runtime=getattr(args, "runtime", None)).send_message(
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


def _harness_window_title(app_id: str, explicit: str | None, runtime: str | None = None) -> str:
    if explicit:
        return explicit
    if app_id == "tashuo" and runtime and runtime.strip().replace("-", "_") == "mac_ios_app":
        return "tashuo"
    try:
        default_title = manifest_for_app(app_id).default_window_title
    except KeyError:
        default_title = ""
    return default_title or "iPhone Mirroring"


def _handle_release_doctor(args: argparse.Namespace) -> int:
    payload = release_doctor()
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_release_gate_tashuo_stage_alpha(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_alpha_release_gate import main as release_gate_main

    return int(release_gate_main(_release_gate_tashuo_stage_alpha_argv(args)))


def _release_gate_tashuo_stage_alpha_argv(args: argparse.Namespace) -> list[str]:
    argv: list[str] = []
    path_options = (
        ("--data-dir", "data_dir"),
        ("--work-dir", "work_dir"),
        ("--authorization", "authorization"),
        ("--env-file", "env_file"),
        ("--scripted-vision-output", "scripted_vision_output"),
        ("--scripted-backend-output", "scripted_backend_output"),
        ("--validate-evidence-json", "validate_evidence_json"),
        ("--validate-evidence-bundle", "validate_evidence_bundle"),
    )
    value_options = (
        ("--runs", "runs"),
        ("--initial-surface", "initial_surface"),
        ("--vision-backend", "vision_backend"),
        ("--vision-model", "vision_model"),
        ("--backend", "backend"),
        ("--model", "model"),
        ("--minimax-base-url", "minimax_base_url"),
        ("--minimax-api-key-env", "minimax_api_key_env"),
        ("--minimax-request-timeout-seconds", "minimax_request_timeout_seconds"),
        ("--max-ticks", "max_ticks"),
        ("--step-timeout-seconds", "step_timeout_seconds"),
        ("--smoke-timeout-seconds", "smoke_timeout_seconds"),
        ("--support-session-id", "support_session_id"),
    )
    for flag, attr in path_options:
        value = getattr(args, attr, None)
        if value is not None:
            argv.extend([flag, str(value)])
    for flag, attr in value_options:
        value = getattr(args, attr, None)
        if value is not None:
            argv.extend([flag, str(value)])
    if args.continue_on_failure:
        argv.append("--continue-on-failure")
    if args.json:
        argv.append("--json")
    return argv


def _handle_beta_readiness(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import beta_readiness

    payload = beta_readiness(
        data_dir=args.data_dir,
        env_file=args.env_file,
        minimax_api_key_env=args.minimax_api_key_env,
        alpha_evidence_json=args.alpha_evidence_json,
        alpha_evidence_bundle=args.alpha_evidence_bundle,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_beta_feedback_record(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import record_stage_beta_feedback

    payload = record_stage_beta_feedback(data_dir=args.data_dir, feedback=_read_json_object(args.input))
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_beta_tashuo_stage_start(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import start_tashuo_stage_beta

    payload = start_tashuo_stage_beta(
        data_dir=args.data_dir,
        authorization_path=args.authorization,
        work_dir=args.work_dir,
        env_file=args.env_file,
        minimax_api_key_env=args.minimax_api_key_env,
        host=args.host,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "active" else 2


def _handle_beta_tashuo_stage_run(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import run_tashuo_stage_beta

    payload = run_tashuo_stage_beta(
        data_dir=args.data_dir,
        runs=args.runs,
        work_dir=args.work_dir,
        env_file=args.env_file,
        authorization_path=args.authorization,
        initial_surface=args.initial_surface,
        continue_on_failure=args.continue_on_failure,
        vision_backend=args.vision_backend,
        backend=args.backend,
        vision_model=args.vision_model,
        model=args.model,
        scripted_vision_output=args.scripted_vision_output,
        scripted_backend_output=args.scripted_backend_output,
        minimax_api_key_env=args.minimax_api_key_env,
        minimax_base_url=args.minimax_base_url,
        minimax_request_timeout_seconds=args.minimax_request_timeout_seconds,
        max_ticks=args.max_ticks,
        step_timeout_seconds=args.step_timeout_seconds,
        smoke_timeout_seconds=args.smoke_timeout_seconds,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "ok" else 2


def _handle_beta_tashuo_stage_status(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import status_tashuo_stage_beta

    payload = status_tashuo_stage_beta(data_dir=args.data_dir)
    _print_json(payload)
    return 0 if payload.get("status") != "not_found" else 2


def _handle_beta_tashuo_stage_stop(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import stop_tashuo_stage_beta

    payload = stop_tashuo_stage_beta(
        data_dir=args.data_dir,
        work_dir=args.work_dir,
        reason=args.reason,
        env_file=args.env_file,
    )
    _print_json(payload)
    return 0 if payload.get("status") == "stopped" else 2


def _handle_beta_tashuo_stage_report(args: argparse.Namespace) -> int:
    from dating_boost.core.tashuo_stage_beta import report_tashuo_stage_beta

    payload = report_tashuo_stage_beta(data_dir=args.data_dir, format=args.format)
    if args.format == "md":
        sys.stdout.write(str(payload) + "\n")
        return 0 if not str(payload).endswith("not found.") else 2
    _print_json(payload)
    return 0 if isinstance(payload, dict) and payload.get("status") != "not_found" else 2


__all__ = [name for name in globals() if not name.startswith("__")]
