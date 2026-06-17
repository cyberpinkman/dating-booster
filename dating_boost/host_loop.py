#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.apps.registry import host_loop_app_ids, manifest_for_app, supported_app_ids
from dating_boost.core.live_send_contract import target_binding_structural_evidence_present, validate_live_send_contract
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.relationship_report import (
    RELATIONSHIP_PROGRESS_NEXT_ACTION,
    build_relationship_progress_report,
)
from dating_boost.core.runtime_scope import RuntimeScopeRepository
from dating_boost.core.safety import SafetyRepository
from dating_boost.core.support import SupportLogRepository
from dating_boost.perception.observations import ProfileObservation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(".local") / "dating-boost-host-loop"
DEFAULT_FIXTURE_NOW = "2026-05-26T00:00:00Z"
REPORT_FINAL_STATUSES = {"wait", "blocked", "handoff", "scheduled_wait", "stopped", "error"}
MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE = 20


def main(argv: list[str] | None = None) -> int:
    command_tokens = sys.argv[1:] if argv is None else list(argv)
    args = _parse_args(command_tokens)
    support_command = _host_loop_support_command_started(args, command_tokens)

    try:
        supervisor = HostLoopSupervisor(args)
        command = getattr(args, "command", "run")
        if command == "doctor":
            payload, exit_code = supervisor.doctor()
        elif command == "init":
            payload, exit_code = supervisor.init()
        elif command == "status":
            payload, exit_code = supervisor.status()
        elif command == "confirm-staged":
            payload, exit_code = supervisor.confirm_staged()
        elif command == "resume":
            payload, exit_code = supervisor.resume()
        else:
            payload, exit_code = supervisor.run()
    except HostLoopError as exc:
        reason = str(exc)
        data_dir = (getattr(args, "data_dir", None) or DEFAULT_DATA_DIR).resolve()
        work_dir = (getattr(args, "work_dir", None) or data_dir / "host-loop").resolve()
        payload = {
            "schema_version": 1,
            "status": "blocked",
            "reason": reason,
            "stop_reason": reason,
            "send_mode": getattr(args, "send_mode", "stage"),
            "app_id": getattr(args, "app_id", "tinder"),
            "data_dir": str(data_dir),
            "work_dir": str(work_dir),
            "steps": [],
            "staged_verifications": [],
            "stage_results_recorded": [],
            "action_results_recorded": [],
            "next_host_action": "choose_supported_host_loop_app",
        }
        exit_code = 2
    _record_host_loop_support_event(
        args,
        "host_loop_command_result",
        {
            "command": f"host_loop {getattr(args, 'command', 'run')}",
            "status": payload.get("status"),
            "reason": payload.get("reason") or payload.get("stop_reason"),
            "app_id": payload.get("app_id"),
            "send_mode": payload.get("send_mode"),
            "payload": payload,
        },
    )
    _host_loop_support_command_finished(support_command, args, command_tokens, exit_code)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return exit_code


def _parse_args(argv: list[str]) -> argparse.Namespace:
    commands = {"doctor", "init", "run", "resume", "status", "confirm-staged"}
    normalized = list(argv)
    if not normalized or normalized[0].startswith("-") or normalized[0] not in commands:
        normalized = ["run", *normalized]

    parser = argparse.ArgumentParser(description="Drive a host-executed dating app operator loop.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("doctor", "init", "run", "resume", "status", "confirm-staged"):
        subparser = subparsers.add_parser(command)
        _add_common_args(subparser)
        if command == "confirm-staged":
            subparser.add_argument("--action-result", type=Path)
            subparser.add_argument("--cancel", action="store_true")
            subparser.add_argument("--clear-retry", action="store_true")
    return parser.parse_args(normalized)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--goal", type=Path)
    parser.add_argument("--availability", type=Path)
    parser.add_argument("--app-id", default="tinder")
    parser.add_argument("--send-mode", choices=["stage", "live"], default="stage")
    parser.add_argument("--managed-gui-send", action="store_true")
    parser.add_argument("--harness-runtime")
    parser.add_argument("--initial-surface", choices=["auto", "message-list", "current-thread"], default="auto")
    parser.add_argument("--management-mode", choices=["conservative", "high-throughput"], default="conservative")
    parser.add_argument("--max-threads-per-cycle", type=int, default=5)
    parser.add_argument("--max-pages-per-cycle", type=int, default=1)
    parser.add_argument("--cycle-send-limit", type=int, default=1)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fixture-host", type=Path)
    parser.add_argument("--wait-timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--adapter-package", type=Path)
    parser.add_argument("--skill-package", type=Path)


def _explicit_adapter_package(args: argparse.Namespace) -> Path | None:
    adapter_package = getattr(args, "adapter_package", None)
    legacy_skill_package = getattr(args, "skill_package", None)
    if adapter_package is not None and legacy_skill_package is not None:
        if adapter_package.expanduser().resolve() != legacy_skill_package.expanduser().resolve():
            raise HostLoopError("conflicting --adapter-package and --skill-package values")
    return adapter_package or legacy_skill_package


def _host_loop_support_data_dir(args: argparse.Namespace) -> Path:
    return (getattr(args, "data_dir", None) or DEFAULT_DATA_DIR).resolve()


def _host_loop_support_command_started(args: argparse.Namespace, command_tokens: list[str]) -> dict[str, Any]:
    marker: dict[str, Any] = {"started_monotonic": time.monotonic(), "event": None}
    try:
        marker["event"] = SupportLogRepository(_host_loop_support_data_dir(args)).record_command_started(
            ["dating-boost-host-loop", *command_tokens]
        )
    except Exception:
        marker["event"] = None
    return marker


def _host_loop_support_command_finished(
    marker: dict[str, Any] | None,
    args: argparse.Namespace,
    command_tokens: list[str],
    exit_code: int,
) -> None:
    if marker is None:
        return
    started = marker.get("started_monotonic")
    duration_ms = 0
    if isinstance(started, (int, float)):
        duration_ms = max(0, int((time.monotonic() - float(started)) * 1000))
    try:
        SupportLogRepository(_host_loop_support_data_dir(args)).record_command_finished(
            marker.get("event"),
            argv=["dating-boost-host-loop", *command_tokens],
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
    except Exception:
        return


def _record_host_loop_support_event(args: argparse.Namespace, event_type: str, payload: dict[str, Any]) -> None:
    try:
        repository = SupportLogRepository(_host_loop_support_data_dir(args))
        active = repository.active_session()
        if not active:
            return
        repository.record_event(
            session_id=str(active["session_id"]),
            event_type=event_type,
            payload=payload,
        )
    except Exception:
        return


class HostLoopSupervisor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.fixture_host = args.fixture_host.resolve() if getattr(args, "fixture_host", None) else None
        self.data_dir = (getattr(args, "data_dir", None) or DEFAULT_DATA_DIR).resolve()
        self.work_dir = (getattr(args, "work_dir", None) or self.data_dir / "host-loop").resolve()
        self.steps: list[dict[str, Any]] = []
        self.staged_verifications: list[dict[str, Any]] = []
        self.stage_results_recorded: list[dict[str, Any]] = []
        self.action_results_recorded: list[dict[str, Any]] = []
        self.operator_session_active = False
        self.skill_package_path = self._resolve_skill_package_path(_explicit_adapter_package(args))
        self.app_profile = _load_app_profile(getattr(args, "app_id", "tinder"))
        self.support = SupportLogRepository(self.data_dir)

    def doctor(self) -> tuple[dict[str, Any], int]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        missing: list[str] = []
        warnings: list[str] = []
        details: dict[str, Any] = {}

        try:
            capabilities = self._run_cli_json("capabilities", "--json", "--data-dir", str(self.data_dir))
            details["capabilities_ok"] = bool(capabilities.get("agent_native_capabilities", {}).get("host_loop_supervisor"))
            if not details["capabilities_ok"]:
                return self._doctor_payload("blocked", missing, "upgrade_or_reinstall_cli", details), 2
        except Exception as exc:  # noqa: BLE001 - doctor must return structured diagnostics.
            details["capabilities_error"] = str(exc)
            return self._doctor_payload("blocked", ["cli"], "fix_cli_installation", details), 2

        try:
            skill = self._run_cli_json(
                "skill",
                "doctor",
                "--package",
                str(self.skill_package_path),
                "--data-dir",
                str(self.data_dir),
                "--json",
            )
            details["skill_doctor"] = skill
            if skill.get("status") != "ok":
                return self._doctor_payload("needs_skill_upgrade", missing, "run_skill_bootstrap_or_upgrade", details), 2
        except Exception as exc:  # noqa: BLE001
            details["skill_doctor_error"] = str(exc)
            return self._doctor_payload("needs_skill_upgrade", missing, "run_skill_bootstrap_or_upgrade", details), 2

        details["app_profile"] = {
            "app_id": self.app_profile.get("app_id"),
            "support_level": self.app_profile.get("support_level"),
            "host_loop_supported": self.app_profile.get("host_loop_supported"),
            "profile_path": self.app_profile.get("_path"),
        }
        if self.app_profile.get("host_loop_supported") is not True:
            missing.append("host_loop_supported_app")
            return self._doctor_payload("blocked", missing, "choose_supported_host_loop_app", details), 2

        readiness = self._run_cli_json(
            "user",
            "readiness",
            "--data-dir",
            str(self.data_dir),
            "--mode",
            "autonomous",
            "--json",
            allow_error=True,
        )
        details["user_readiness"] = readiness
        if readiness.get("ready") is not True:
            missing.append("user_profile")
            missing.extend(str(item) for item in readiness.get("missing", []))
            return self._doctor_payload("needs_user_profile", missing, "complete_user_profile_and_interview", details), 0

        goal_path = self.args.goal or self._fixture_file("goal.json") or self.data_dir / "automation" / "goals.json"
        if not goal_path.exists():
            missing.append("goal")
            return self._doctor_payload("needs_goal", missing, "run_init_or_set_goal", details), 0
        availability_path = self.args.availability or self._fixture_file("availability.json") or self.data_dir / "automation" / "availability.json"
        if not availability_path.exists():
            missing.append("availability")
            return self._doctor_payload("needs_availability", missing, "run_init_or_set_availability", details), 0
        auth_path = self.args.authorization or self._fixture_file("auth.json") or self.data_dir / "automation" / "authorization.json"
        if not auth_path.exists():
            missing.append("authorization")
            return self._doctor_payload("needs_authorization", missing, "create_or_pass_authorization", details), 0

        if warnings:
            details["warnings"] = warnings
        return self._doctor_payload("ready", missing, "start_or_resume_host_loop", details), 0

    def init(self) -> tuple[dict[str, Any], int]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        automation_dir = self.data_dir / "automation"
        automation_dir.mkdir(parents=True, exist_ok=True)
        templates = {
            "authorization_template": automation_dir / "auth.template.json",
            "goal_template": automation_dir / "goal.template.json",
            "availability_template": automation_dir / "availability.template.json",
            "current_work_item": self.work_dir / "current_work_item.json",
        }
        _write_json(
            templates["authorization_template"],
            {
                "schema_version": 1,
                "authorization_id": "auth_local_TODO",
                "scope": "send_chat_messages",
                "app_id": self.args.app_id,
                "expires_at": "TODO_ISO_TIMESTAMP",
                "allowed_match_ids": [],
                "allowed_actions": ["send_message"],
                "autonomous_send": False,
                "live_send": False,
                "autonomous_nudge": True,
                "goal_ids": ["goal_meet_in_person"],
                "quiet_hours": [],
                "requires_post_action_verification": True,
                "created_at": "TODO_ISO_TIMESTAMP",
                "revoked_at": None,
            },
        )
        _write_json(
            templates["goal_template"],
            {
                "schema_version": 1,
                "goal_id": "goal_meet_in_person",
                "goal_type": "meet_in_person",
                "status": "active",
                "handoff_triggers": ["specific_day", "specific_time", "specific_venue", "contact_exchange"],
            },
        )
        _write_json(
            templates["availability_template"],
            {
                "schema_version": 1,
                "availability": [
                    {
                        "availability_id": "avail_TODO",
                        "date": "TODO_DATE",
                        "time_window": "TODO_TIME_WINDOW",
                        "area": "TODO_AREA",
                        "meeting_types": ["coffee"],
                        "constraints": [],
                        "confidence": "user_confirmed",
                        "expires_at": "TODO_ISO_TIMESTAMP",
                    }
                ],
            },
        )
        _write_json(
            templates["current_work_item"],
            {
                "schema_version": 1,
                "work_item_type": "not_started",
                "next_host_action": "run dating-boost-host-loop doctor, then run",
            },
        )
        return {
            "schema_version": 1,
            "status": "ok",
            "data_dir": str(self.data_dir),
            "work_dir": str(self.work_dir),
            "templates": {key: str(value) for key, value in templates.items()},
            "next_host_action": "fill_templates_then_run_doctor",
        }, 0

    def status(self) -> tuple[dict[str, Any], int]:
        current = self._read_current_work_item_or_none()
        if current is None:
            return {
                "schema_version": 1,
                "status": "idle",
                "data_dir": str(self.data_dir),
                "work_dir": str(self.work_dir),
                "next_host_action": "run_or_resume_host_loop",
            }, 0
        work_type = str(current.get("work_item_type") or "")
        status = "waiting_for_confirmation" if work_type == "send_message" and self._work_file(current, "staged_verification").exists() else "waiting_for_host"
        return {
            "schema_version": 1,
            "status": status,
            "data_dir": str(self.data_dir),
            "work_dir": str(self.work_dir),
            "work_item": current,
            "expected_input": str(self._expected_input_path(current)),
            "next_host_action": _next_host_action(status, current, self.args.send_mode),
            "app_profile": _host_instructions(self.app_profile, work_type),
        }, 0

    def confirm_staged(self) -> tuple[dict[str, Any], int]:
        current = self._read_current_work_item_or_none()
        if current is None or current.get("work_item_type") != "send_message":
            return self._finish("blocked", "no_staged_send_work_item", extra={"next_host_action": "run_status"}), 0
        if getattr(self.args, "cancel", False):
            try:
                operator_cancel = OperatorRepository(self.data_dir).cancel_current_work_item(
                    current,
                    reason="user_cancelled_staged_send",
                )
            except ValueError as exc:
                operator_cancel = {
                    "schema_version": 1,
                    "status": "skipped",
                    "reason": str(exc),
                }
            self._clear_host_work_item(current)
            self._append_timeline("stage_cancelled", current, {"reason": "user_cancelled"})
            return self._finish(
                "staged_cancelled",
                "user_cancelled_staged_send",
                current=current,
                extra={
                    "next_host_action": "clear_input_or_resume",
                    "operator_cancel": operator_cancel,
                },
            ), 0
        if getattr(self.args, "clear_retry", False):
            staged = self._work_file(current, "staged_verification")
            if staged.exists():
                staged.unlink()
            self._append_timeline("stage_retry_requested", current, {"reason": "user_requested_retry"})
            return self._finish("waiting_for_host", "staged_text_retry_requested", current=current, extra={"next_host_action": "clear_input_and_restage"}), 0
        staged_path = self._work_file(current, "staged_verification")
        if not staged_path.exists():
            return self._finish(
                "blocked",
                "staged_verification_required_before_confirmation",
                current=current,
                extra={
                    "expected_input": str(staged_path),
                    "next_host_action": "write_staged_verification_before_confirming",
                },
            ), 0
        staged = _read_json(staged_path)
        verification = _validate_staged_verification(staged, current)
        self.staged_verifications.append(verification)
        self._append_timeline("staged_verification", current, {"path": str(staged_path), "verification": verification})
        if verification["status"] != "ok":
            return self._finish("blocked", verification["reason"], current=current), 0
        action_result = getattr(self.args, "action_result", None)
        if action_result is not None:
            result = _read_json(action_result)
            _validate_action_result(result, current)
            recorded = self._run_cli_json("operator", "record-action-result", "--data-dir", str(self.data_dir), "--input", str(action_result))
            self.action_results_recorded.append(recorded)
            self._append_timeline("action_result", current, {"result": recorded})
            self._clear_host_work_item(current, consume=True)
            return self._finish("confirmed", "staged_send_confirmed_and_recorded", current=current, extra={"next_host_action": "resume_host_loop"}), 0
        return self._finish(
            "waiting_for_user_send",
            "stage_confirmed_but_action_result_missing",
            current=current,
            extra={"next_host_action": "send_staged_text_then_provide_action_result"},
        ), 0

    def resume(self) -> tuple[dict[str, Any], int]:
        return self.run(resume=True)

    def _doctor_payload(self, status: str, missing: list[str], next_host_action: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": status,
            "missing": _unique_strings(missing),
            "data_dir": str(self.data_dir),
            "work_dir": str(self.work_dir),
            "next_host_action": next_host_action,
            "details": details,
        }

    def run(self, *, resume: bool = False) -> tuple[dict[str, Any], int]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"run_host_loop_{_digest({'data_dir': str(self.data_dir), 'work_dir': str(self.work_dir), 'resume': resume, 'now': _now_iso()})[:12]}"
        store = ProductionDataStore(self.data_dir)
        lock_result = store.acquire_lock(
            "host_loop_run",
            owner="dating-boost-host-loop",
            run_id=run_id,
        )
        if not lock_result.acquired:
            return {
                "schema_version": 1,
                "status": "blocked",
                "stop_reason": "automation_lock_active",
                "send_mode": self.args.send_mode,
                "app_id": self.args.app_id,
                "data_dir": str(self.data_dir),
                "work_dir": str(self.work_dir),
                "steps": list(self.steps),
                "staged_verifications": list(self.staged_verifications),
                "stage_results_recorded": list(self.stage_results_recorded),
                "action_results_recorded": list(self.action_results_recorded),
                "next_host_action": "resume_after_lock_expires",
                "lock": lock_result.lock,
            }, 0
        try:
            payload, exit_code = self._run_unlocked(resume=resume)
        finally:
            released_lock = store.release_lock("host_loop_run", run_id=run_id)
        payload["lock"] = {**released_lock, "takeover": bool(lock_result.lock.get("takeover"))}
        return payload, exit_code

    def _run_unlocked(self, *, resume: bool = False) -> tuple[dict[str, Any], int]:
        try:
            self._bootstrap_fixture_profile()
            self._preflight()
            if resume:
                resumed_current = self._read_current_work_item_or_none()
                if isinstance(resumed_current, dict) and resumed_current.get("work_item_type") == "send_message":
                    if self._operator_session_status() != "active":
                        start = self._start_operator_session()
                        if start.get("status") != "active":
                            return self._finish("blocked", "operator_session_not_active", extra={"start": start}), 0
                    self.operator_session_active = True
                    self._write_current_work_item(resumed_current)
                    self._append_timeline("work_item", resumed_current, {"resumed_from_work_dir": True})
                    self.steps.append(
                        {
                            "work_item_type": "send_message",
                            "work_item_id": resumed_current.get("work_item_id"),
                            "candidate_key": resumed_current.get("candidate_key"),
                        }
                    )
                    status = self._handle_send_message(resumed_current)
                    if status is not None:
                        return status, 0
                    return self._finish(
                        "step_completed",
                        "resumed_current_send_work_item_completed",
                        current=resumed_current,
                    ), 0
            if self._operator_session_status() != "active":
                start = self._start_operator_session()
                if start.get("status") != "active":
                    return self._finish("blocked", "operator_session_not_active", extra={"start": start}), 0
            self.operator_session_active = True

            for _ in range(max(self.args.max_steps, 1)):
                next_payload = self._run_cli_json("operator", "next", "--data-dir", str(self.data_dir))
                work_item = next_payload.get("work_item")
                if not isinstance(work_item, dict):
                    return self._finish("error", "operator_next_returned_no_work_item", extra={"next": next_payload}), 2
                work_type = str(work_item.get("work_item_type") or "")
                self._write_current_work_item(work_item)
                self._append_timeline("work_item", work_item, {"reused": bool(next_payload.get("reused_current_work_item"))})
                self.steps.append(
                    {
                        "work_item_type": work_type,
                        "work_item_id": work_item.get("work_item_id"),
                        "candidate_key": work_item.get("candidate_key"),
                    }
                )

                if work_type == "scan_message_list":
                    status = self._handle_scan_message_list(work_item)
                elif work_type == "observe_current_thread":
                    status = self._handle_current_thread(work_item)
                elif work_type == "open_thread":
                    status = self._handle_open_thread(work_item)
                elif work_type == "send_message":
                    status = self._handle_send_message(work_item)
                elif work_type in {"wait", "blocked", "handoff", "scheduled_wait"}:
                    return self._finish(work_type, str(work_item.get("reason") or work_type), current=work_item), 0
                else:
                    return self._finish("blocked", f"unsupported_work_item_type:{work_type}", current=work_item), 0

                if status is not None:
                    return status, 0

                if self.args.once:
                    return self._finish("step_completed", "once_completed", current=work_item), 0

            return self._finish("stopped", "max_steps_reached"), 0
        except HostLoopCommandError as exc:
            reason = str(exc.payload.get("reason") or exc)
            return self._finish("blocked", reason, extra={"cli_error": exc.payload}), 0
        except HostLoopError as exc:
            return self._finish("blocked", str(exc)), 0
        except RuntimeError as exc:
            return self._finish("error", str(exc)), 2

    def _start_operator_session(self) -> dict[str, Any]:
        initial_surface = self._initial_surface()
        return self._run_cli_json(
            "operator",
            "session",
            "start",
            "--data-dir",
            str(self.data_dir),
            "--authorization",
            str(self._authorization_path()),
            "--initial-surface",
            initial_surface,
            "--management-mode",
            str(getattr(self.args, "management_mode", "conservative") or "conservative"),
            "--max-threads-per-cycle",
            str(getattr(self.args, "max_threads_per_cycle", 5) or 5),
            "--max-pages-per-cycle",
            str(getattr(self.args, "max_pages_per_cycle", 1) or 1),
            "--cycle-send-limit",
            str(getattr(self.args, "cycle_send_limit", 1) or 1),
        )

    def _preflight(self) -> None:
        if self.app_profile.get("host_loop_supported") is not True:
            raise HostLoopError(f"host loop is not supported for app_id={self.args.app_id}")
        send_modes = self.app_profile.get("host_loop_send_modes")
        if isinstance(send_modes, list) and send_modes and self.args.send_mode not in set(str(mode) for mode in send_modes):
            raise HostLoopError(f"send_mode {self.args.send_mode} is not supported for app_id={self.args.app_id}")
        runtime_scope = RuntimeScopeRepository(self.data_dir).ensure_selected(
            app_id=str(self.args.app_id),
            runtime=getattr(self.args, "harness_runtime", None),
            source="host_loop_preflight",
            require_explicit_runtime_choice=True,
        )
        if runtime_scope.get("status") == "blocked":
            raise HostLoopError(
                f"{runtime_scope.get('reason')}: "
                f"selected_app_id={runtime_scope.get('selected_app_id')} "
                f"selected_runtime={runtime_scope.get('selected_runtime')} "
                f"requested_app_id={runtime_scope.get('requested_app_id')} "
                f"requested_runtime={runtime_scope.get('requested_runtime')}"
            )
        capabilities = self._run_cli_json("capabilities", "--json", "--data-dir", str(self.data_dir))
        agent_caps = capabilities.get("agent_native_capabilities", {})
        if not agent_caps.get("host_loop_supervisor"):
            raise HostLoopError("capabilities missing host_loop_supervisor")
        host_loop_apps = set(agent_caps.get("host_loop_app_profiles") or [])
        if self.args.app_id not in host_loop_apps:
            raise HostLoopError(f"capabilities missing host loop support for app_id={self.args.app_id}")
        if agent_caps.get("live_gui_harness"):
            raise HostLoopError("this supervisor expects live_gui_harness=false")

        doctor = self._run_cli_json(
            "skill",
            "doctor",
            "--package",
            str(self.skill_package_path),
            "--data-dir",
            str(self.data_dir),
            "--json",
        )
        if doctor.get("status") not in {"ok"}:
            raise HostLoopError(f"skill doctor failed: {doctor.get('status')}")

        self._save_goal_and_availability()
        readiness = self._run_cli_json("user", "readiness", "--data-dir", str(self.data_dir), "--mode", "autonomous", "--json")
        if readiness.get("ready") is not True:
            raise HostLoopError(f"user readiness failed: {readiness.get('status') or readiness.get('reason')}")

    def _save_goal_and_availability(self) -> None:
        goal_path = self.args.goal or self._fixture_file("goal.json")
        availability_path = self.args.availability or self._fixture_file("availability.json")
        if goal_path is not None:
            self._run_cli_json("automation", "goal", "set", "--data-dir", str(self.data_dir), "--input", str(goal_path))
        if availability_path is not None:
            self._run_cli_json(
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(self.data_dir),
                "--input",
                str(availability_path),
            )
        if not (self.data_dir / "automation" / "goals.json").exists():
            raise HostLoopError("missing goal; pass --goal or configure automation goal first")
        if not (self.data_dir / "automation" / "availability.json").exists():
            raise HostLoopError("missing availability; pass --availability or configure availability first")

    def _initial_surface(self) -> str:
        requested = str(getattr(self.args, "initial_surface", "auto") or "auto")
        if requested in {"message-list", "current-thread"}:
            return requested
        if self.fixture_host is not None and (self.fixture_host / "current_thread_observation.json").exists():
            return "current-thread"
        if self.fixture_host is not None and (self.fixture_host / "message_list_observation.json").exists():
            return "message-list"
        command = ["harness", self.args.app_id, "observe", "--data-dir", str(self.data_dir), "--json"]
        harness_runtime = str(getattr(self.args, "harness_runtime", "") or "").strip()
        if harness_runtime:
            command.extend(["--runtime", harness_runtime])
        try:
            observed = self._run_cli_json(*command)
        except (HostLoopCommandError, HostLoopError):
            return "message-list"
        hints = observed.get("layout_hints") if isinstance(observed, dict) else {}
        if isinstance(hints, dict) and hints.get("conversation_present") is True:
            return "current-thread"
        return "message-list"

    def _handle_scan_message_list(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        path = self._work_file(work_item, "message_list_observation")
        if self.fixture_host is not None and not path.exists():
            fixture = self.fixture_host / "message_list_observation.json"
            if fixture.exists():
                shutil.copyfile(fixture, path)
        if not path.exists():
            _write_json(_template_path(path), _message_list_template(work_item, self.app_profile))
            waiting = self._waiting("message_list_observation", path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting
        validation = self._run_cli_json("observation", "validate", "--input", str(path), "--json")
        if validation.get("status") != "ok":
            return self._finish("blocked", "message_list_observation_invalid", current=work_item, extra={"validation": validation})
        ingest = self._run_cli_json("operator", "ingest-observation", "--data-dir", str(self.data_dir), "--input", str(path))
        self._append_timeline("observation", work_item, {"observation_type": "message_list", "path": str(path), "ingest": ingest})
        self._consume(path)
        if ingest.get("status") != "ok":
            return self._finish("blocked", str(ingest.get("reason") or "message_list_ingest_failed"), current=work_item)
        return None

    def _handle_open_thread(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        candidate_key = _required_string(work_item, "candidate_key")
        path = self._work_file(work_item, "thread_observation")
        if self.fixture_host is not None and not path.exists():
            fixture = self.fixture_host / "threads" / f"{candidate_key}.json"
            if fixture.exists():
                shutil.copyfile(fixture, path)
        if not path.exists():
            _write_json(_template_path(path), _thread_template(work_item, self.app_profile))
            waiting = self._waiting("thread_observation", path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting
        validation = self._run_cli_json("observation", "validate", "--input", str(path), "--json")
        if validation.get("status") != "ok":
            return self._finish("blocked", "thread_observation_invalid", current=work_item, extra={"validation": validation})
        ingest = self._run_cli_json("operator", "ingest-observation", "--data-dir", str(self.data_dir), "--input", str(path))
        self._append_timeline("observation", work_item, {"observation_type": "thread", "path": str(path), "ingest": ingest})
        self._consume(path)
        if ingest.get("status") != "ok":
            return self._finish("blocked", str(ingest.get("reason") or "thread_ingest_failed"), current=work_item)
        return None

    def _handle_current_thread(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        path = self._work_file(work_item, "thread_observation")
        if self.fixture_host is not None and not path.exists():
            fixture = self.fixture_host / "current_thread_observation.json"
            if fixture.exists():
                shutil.copyfile(fixture, path)
        if not path.exists():
            _write_json(_template_path(path), _thread_template(work_item, self.app_profile))
            waiting = self._waiting("thread_observation", path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting
        validation = self._run_cli_json("observation", "validate", "--input", str(path), "--json")
        if validation.get("status") != "ok":
            return self._finish("blocked", "thread_observation_invalid", current=work_item, extra={"validation": validation})
        ingest = self._run_cli_json("operator", "ingest-observation", "--data-dir", str(self.data_dir), "--input", str(path))
        self._append_timeline("observation", work_item, {"observation_type": "thread", "path": str(path), "ingest": ingest})
        self._consume(path)
        if ingest.get("status") != "ok":
            return self._finish("blocked", str(ingest.get("reason") or "thread_ingest_failed"), current=work_item)
        return None

    def _handle_send_message(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        if self.args.send_mode == "live" and getattr(self.args, "managed_gui_send", False):
            return self._handle_managed_gui_send(work_item)
        if self.args.send_mode == "live":
            runtime_block = self._runtime_live_send_block_reason()
            if runtime_block is not None:
                return self._finish("blocked", runtime_block, current=work_item)
        target_profile_block = self._target_profile_block_reason(work_item)
        if target_profile_block is not None:
            return self._finish(
                "blocked",
                target_profile_block,
                current=work_item,
                extra={"next_host_action": "open_target_profile_and_ingest_memory"},
            )
        staged_path = self._work_file(work_item, "staged_verification")
        if self.fixture_host is not None and not staged_path.exists():
            _write_json(staged_path, _staged_verification(work_item, result_status="succeeded"))
        if not staged_path.exists() and self._can_auto_stage_draft(work_item):
            stage_wait = self._stage_draft_with_harness(work_item, staged_path)
            if stage_wait is not None:
                return stage_wait
        if not staged_path.exists():
            _write_json(_template_path(staged_path), _staged_verification_template(work_item))
            waiting = self._waiting("staged_verification", staged_path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting

        staged = _read_json(staged_path)
        verification = _validate_staged_verification(staged, work_item)
        self.staged_verifications.append(verification)
        self._append_timeline("staged_verification", work_item, {"path": str(staged_path), "verification": verification})
        if verification["status"] != "ok":
            return self._finish("blocked", verification["reason"], current=work_item)
        if self.args.send_mode == "stage":
            stage_result_path = self._work_file(work_item, "stage_result")
            _write_json(stage_result_path, _stage_result_from_verification(work_item, verification))
            recorded = self._run_cli_json("operator", "record-stage-result", "--data-dir", str(self.data_dir), "--input", str(stage_result_path))
            self.stage_results_recorded.append(recorded)
            self._append_timeline("stage_result", work_item, {"path": str(stage_result_path), "recorded": recorded})
            self._consume(stage_result_path)
            return self._finish(
                "staged_waiting_user_confirmation",
                "stage mode recorded staged draft without recording send result or clicking send",
                current=work_item,
                extra={"next_host_action": "review_staged_text_and_confirm_or_cancel", "stage_result": recorded},
            )
        if SafetyRepository(self.data_dir).is_paused():
            return self._finish("blocked", "safety_paused", current=work_item)
        authorization = _read_json(self._authorization_path())
        contract_reason = self._live_send_contract_block_reason(work_item, authorization)
        if contract_reason is not None:
            return self._finish("blocked", contract_reason, current=work_item)

        result_path = self._work_file(work_item, "action_result")
        if self.fixture_host is not None and not result_path.exists():
            _write_json(result_path, _action_result_fixture(work_item))
        if not result_path.exists():
            _write_json(_template_path(result_path), _action_result_template(work_item))
            waiting = self._waiting("action_result", result_path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting

        result = _read_json(result_path)
        _validate_action_result(result, work_item)
        recorded = self._run_cli_json("operator", "record-action-result", "--data-dir", str(self.data_dir), "--input", str(result_path))
        self.action_results_recorded.append(recorded)
        self._append_timeline("action_result", work_item, {"path": str(result_path), "recorded": recorded})
        self._consume(staged_path)
        self._consume(result_path)
        return None

    def _can_auto_stage_draft(self, work_item: dict[str, Any]) -> bool:
        return (
            self.fixture_host is None
            and self.args.send_mode == "stage"
            and self.args.app_id == "tashuo"
            and str(work_item.get("work_item_type") or "") == "send_message"
            and _normalized_harness_runtime(str(getattr(self.args, "harness_runtime", "") or "")) == "mac_ios_app"
        )

    def _stage_draft_with_harness(self, work_item: dict[str, Any], staged_path: Path) -> dict[str, Any] | None:
        runtime = str(getattr(self.args, "harness_runtime", "") or "").strip()
        draft_path = self.work_dir / f"stage_payload.{_safe_name(str(work_item.get('work_item_id') or 'send'))}.txt"
        draft_path.write_text(_work_item_payload_text(work_item), encoding="utf-8")
        command_args = [
            "harness",
            self.args.app_id,
            "stage-draft",
            "--runtime",
            runtime,
            "--data-dir",
            str(self.data_dir),
            "--text-file",
            str(draft_path),
            "--output-dir",
            str(self.work_dir / "harness"),
            "--json",
        ]
        try:
            harness_payload = self._run_cli_json(*command_args, allow_error=True)
        finally:
            if draft_path.exists():
                draft_path.unlink()
        redacted = _redacted_stage_draft_payload(harness_payload)
        self._append_timeline("stage_draft", work_item, {"harness": redacted})
        if harness_payload.get("status") != "ok":
            return self._finish(
                "blocked",
                str(harness_payload.get("reason") or "stage_draft_failed"),
                current=work_item,
                extra={"stage_draft": redacted},
            )
        staged_text_verification = harness_payload.get("staged_text_verification")
        verification_status = (
            str(staged_text_verification.get("status") or "")
            if isinstance(staged_text_verification, dict)
            else ""
        )
        if harness_payload.get("stage_attempt_status") == "completed" and (
            harness_payload.get("staged_text_verified") is True or verification_status == "verified"
        ):
            _write_json(staged_path, _staged_verification_from_stage_draft(work_item, harness_payload))
            return None
        _write_json(_template_path(staged_path), _staged_verification_template(work_item))
        return self._finish(
            "waiting_for_host",
            "waiting_for_staged_verification",
            current=work_item,
            extra={
                "expected_input": str(staged_path),
                "stage_draft": redacted,
                "next_host_action": "verify_staged_text_visually_and_write_staged_verification",
                "app_profile": _host_instructions(self.app_profile, str(work_item.get("work_item_type") or "")),
            },
        )

    def _handle_managed_gui_send(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        if self.args.app_id not in set(host_loop_app_ids()):
            return self._finish("blocked", f"managed_gui_send_not_supported_for_app:{self.args.app_id}", current=work_item)
        runtime_block = self._runtime_live_send_block_reason()
        if runtime_block is not None:
            return self._finish("blocked", runtime_block, current=work_item)
        target_profile_block = self._target_profile_block_reason(work_item)
        if target_profile_block is not None:
            return self._finish(
                "blocked",
                target_profile_block,
                current=work_item,
                extra={"next_host_action": "open_target_profile_and_ingest_memory"},
            )
        if SafetyRepository(self.data_dir).is_paused():
            return self._finish("blocked", "safety_paused", current=work_item)
        authorization_path = self._authorization_path()
        authorization = _read_json(authorization_path)

        draft_path = self.work_dir / f"managed_payload.{_safe_name(str(work_item.get('work_item_id') or 'send'))}.txt"
        action_request_path = self.work_dir / f"managed_action_request.{_safe_name(str(work_item.get('work_item_id') or 'send'))}.json"
        action_request = self._live_send_action_request(work_item)
        contract_reason = validate_live_send_contract(
            authorization,
            action_request,
            app_id=self.args.app_id,
            draft_text=_work_item_payload_text(work_item),
            data_dir=self.data_dir,
        )
        if contract_reason is not None:
            return self._finish("blocked", contract_reason, current=work_item)
        payload_messages = _work_item_payload_messages(work_item)
        sequence_timing_enabled = len(payload_messages) > 1
        message_sequence_window_seconds = _managed_sequence_window_seconds(len(payload_messages))
        progress_path = _managed_sequence_progress_path(self.work_dir, work_item)
        result_path = self._work_file(work_item, "action_result")
        if result_path.exists():
            result = _read_json(result_path)
            _validate_action_result(result, work_item)
            recorded = self._run_cli_json(
                "operator",
                "record-action-result",
                "--data-dir",
                str(self.data_dir),
                "--input",
                str(result_path),
            )
            self.action_results_recorded.append(recorded)
            self._append_timeline("action_result", work_item, {"path": str(result_path), "recorded": recorded})
            if progress_path.exists():
                progress_path.unlink()
            self._clear_host_work_item(work_item, consume=True)
            return None
        sequence_progress = _managed_sequence_progress_load(progress_path, work_item)
        harness_payloads: list[dict[str, Any]] = []
        message_results: list[dict[str, Any]] = list(sequence_progress.get("message_results") or [])
        sequence_started_at = str(sequence_progress.get("sequence_started_at") or "")
        sequence_last_sent_at = str(sequence_progress.get("last_message_sent_at") or "")
        completed_indices = {
            int(result.get("index") or 0)
            for result in message_results
            if isinstance(result, dict) and result.get("status") == "ok"
        }
        harness_runtime = str(getattr(self.args, "harness_runtime", "") or "").strip()
        required_evidence = _managed_gui_send_required_evidence(self.args.app_id, harness_runtime)
        sequence_work_item = dict(work_item)
        if isinstance(sequence_progress.get("target_binding"), dict):
            sequence_work_item["target_binding"] = sequence_progress["target_binding"]
        pending_visual_result = _managed_sequence_pending_visual_result(message_results)
        if pending_visual_result is not None:
            pending_message = _managed_sequence_message_by_index(
                payload_messages,
                int(pending_visual_result.get("index") or 0),
            )
            if pending_message is None:
                return self._finish(
                    "blocked",
                    "message_sequence_pending_visual_message_missing",
                    current=work_item,
                    extra={
                        "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                        "message_results": message_results,
                        "next_host_action": "observe_current_thread_and_replan_sequence",
                    },
                )
            visual_confirmation_path = _managed_sequence_visual_confirmation_path(
                self.work_dir,
                work_item,
                int(pending_message["index"]),
            )
            if sequence_timing_enabled:
                expired = _managed_sequence_expiry(
                    sequence_started_at,
                    window_seconds=message_sequence_window_seconds,
                )
                if expired is not None and not visual_confirmation_path.exists():
                    return self._finish(
                        "blocked",
                        "message_sequence_window_expired",
                        current=work_item,
                        extra={
                            **expired,
                            "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                            "failed_message_index": pending_message.get("index"),
                            "message_results": message_results,
                            "next_host_action": "observe_current_thread_and_replan_sequence",
                        },
                    )
            if not visual_confirmation_path.exists():
                _write_json(
                    _template_path(visual_confirmation_path),
                    _managed_sequence_visual_confirmation_template(work_item, pending_message, pending_visual_result),
                )
                return self._finish(
                    "waiting_for_host",
                    "outbound_message_requires_visual_verification",
                    current=work_item,
                    extra={
                        "expected_input": str(visual_confirmation_path),
                        "next_host_action": "visually_verify_sequence_outbound_message_and_resume",
                        "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                        "pending_message_index": pending_message.get("index"),
                        "message_results": message_results,
                    },
                )
            visual_confirmation = _read_json(visual_confirmation_path)
            validation_reason = _validate_managed_sequence_visual_confirmation(
                visual_confirmation,
                work_item,
                pending_message,
            )
            if validation_reason is not None:
                return self._finish(
                    "blocked",
                    validation_reason,
                    current=work_item,
                    extra={
                        "expected_input": str(visual_confirmation_path),
                        "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                        "failed_message_index": pending_message.get("index"),
                        "message_results": message_results,
                    },
                )
            confirmation_evidence = _managed_sequence_visual_confirmation_evidence(
                visual_confirmation,
                pending_visual_result,
            )
            pending_visual_result["status"] = "ok"
            pending_visual_result["post_action_observation_id"] = (
                visual_confirmation.get("post_action_observation_id")
                or pending_visual_result.get("post_action_observation_id")
            )
            pending_visual_result["evidence"] = _managed_gui_send_message_evidence(confirmation_evidence)
            pending_visual_result["sent_at"] = str(
                pending_visual_result.get("sent_at")
                or visual_confirmation.get("confirmed_at")
                or _now_iso()
            )
            pending_visual_result["host_visual_verification"] = {
                "status": "ok",
                "path": str(visual_confirmation_path),
            }
            sequence_last_sent_at = str(pending_visual_result.get("sent_at") or sequence_last_sent_at or "")
            if visual_confirmation_path.exists():
                visual_confirmation_path.unlink()
            _managed_sequence_progress_save(
                progress_path,
                work_item,
                message_results=message_results,
                target_binding=sequence_work_item.get("target_binding") if isinstance(sequence_work_item.get("target_binding"), dict) else None,
                sequence_started_at=sequence_started_at,
                last_message_sent_at=sequence_last_sent_at or None,
                message_sequence_window_seconds=message_sequence_window_seconds,
            )
        completed_indices = {
            int(result.get("index") or 0)
            for result in message_results
            if isinstance(result, dict) and result.get("status") == "ok"
        }
        for message in payload_messages:
            if int(message["index"]) in completed_indices:
                continue
            if sequence_timing_enabled and completed_indices and not sequence_started_at:
                return self._finish(
                    "blocked",
                    "message_sequence_window_unverifiable",
                    current=work_item,
                    extra={
                        "message_sequence_window_seconds": message_sequence_window_seconds,
                        "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                        "next_host_action": "observe_current_thread_and_replan_sequence",
                    },
                )
            if sequence_timing_enabled:
                expired = _managed_sequence_expiry(
                    sequence_started_at,
                    window_seconds=message_sequence_window_seconds,
                )
                if expired is not None:
                    return self._finish(
                        "blocked",
                        "message_sequence_window_expired",
                        current=work_item,
                        extra={
                            **expired,
                            "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                            "failed_message_index": message.get("index"),
                            "message_results": message_results,
                            "next_host_action": "observe_current_thread_and_replan_sequence",
                        },
                    )
            if sequence_timing_enabled and not sequence_started_at:
                sequence_started_at = _now_iso()
                _managed_sequence_progress_save(
                    progress_path,
                    work_item,
                    message_results=message_results,
                    target_binding=sequence_work_item.get("target_binding") if isinstance(sequence_work_item.get("target_binding"), dict) else None,
                    sequence_started_at=sequence_started_at,
                    last_message_sent_at=sequence_last_sent_at or None,
                    message_sequence_window_seconds=message_sequence_window_seconds,
                )
            remaining_seconds = None
            if sequence_timing_enabled:
                remaining_seconds = _managed_sequence_remaining_seconds(
                    sequence_started_at,
                    window_seconds=message_sequence_window_seconds,
                )
                if remaining_seconds is not None and remaining_seconds <= 0:
                    return self._finish(
                        "blocked",
                        "message_sequence_window_expired",
                        current=work_item,
                        extra={
                            "message_sequence_started_at": sequence_started_at,
                            "message_sequence_window_seconds": message_sequence_window_seconds,
                            "message_sequence_elapsed_seconds": message_sequence_window_seconds,
                            "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                            "failed_message_index": message.get("index"),
                            "message_results": message_results,
                            "next_host_action": "observe_current_thread_and_replan_sequence",
                        },
                    )
            message_work_item = _single_message_work_item(sequence_work_item, message)
            message_action_request = self._live_send_action_request(message_work_item)
            draft_path = self.work_dir / (
                f"managed_payload.{_safe_name(str(work_item.get('work_item_id') or 'send'))}."
                f"{int(message['index']):02d}.txt"
            )
            action_request_path = self.work_dir / (
                f"managed_action_request.{_safe_name(str(work_item.get('work_item_id') or 'send'))}."
                f"{int(message['index']):02d}.json"
            )
            draft_path.write_text(str(message["text"]), encoding="utf-8")
            _write_json(action_request_path, message_action_request)
            command_args = [
                "harness",
                self.args.app_id,
                "send-message",
                "--data-dir",
                str(self.data_dir),
                "--authorization",
                str(authorization_path),
                "--text-file",
                str(draft_path),
                "--action-request",
                str(action_request_path),
                "--output-dir",
                str(self.work_dir / "harness"),
                "--json",
            ]
            if harness_runtime:
                command_args[3:3] = ["--runtime", harness_runtime]
            try:
                harness_payload = self._run_cli_json(
                    *command_args,
                    allow_error=True,
                    timeout_seconds=remaining_seconds,
                )
            finally:
                if draft_path.exists():
                    draft_path.unlink()
                if action_request_path.exists():
                    action_request_path.unlink()

            harness_payload["message_sequence_index"] = message["index"]
            harness_payload["message_sequence_count"] = len(payload_messages)
            harness_payloads.append(harness_payload)
            message_result = _managed_gui_send_message_result(message, harness_payload)
            message_results.append(message_result)
            self._append_timeline("managed_gui_send", message_work_item, {"harness": _redacted_managed_send_payload(harness_payload)})
            harness_evidence = _managed_gui_send_normalized_evidence(
                harness_payload.get("evidence") if isinstance(harness_payload.get("evidence"), dict) else {}
            )
            if harness_payload.get("status") == "needs_host_visual_verification":
                reason = str(harness_payload.get("reason") or "visual_verification_required")
                if reason == "outbound_message_requires_visual_verification" and sequence_timing_enabled:
                    sent_at = _now_iso()
                    message_results[-1]["status"] = "visual_verification_pending"
                    message_results[-1]["sent_at"] = sent_at
                    message_results[-1]["evidence"] = _managed_gui_send_message_evidence(harness_evidence)
                    if isinstance(harness_payload.get("visual_verification_request"), dict):
                        message_results[-1]["visual_verification_request"] = harness_payload.get("visual_verification_request")
                    sequence_last_sent_at = sent_at
                    sequence_work_item["target_binding"] = _managed_gui_send_refreshed_target_binding(
                        sequence_work_item.get("target_binding") if isinstance(sequence_work_item.get("target_binding"), dict) else None,
                        harness_payload,
                    )
                    visual_confirmation_path = _managed_sequence_visual_confirmation_path(
                        self.work_dir,
                        work_item,
                        int(message["index"]),
                    )
                    _write_json(
                        _template_path(visual_confirmation_path),
                        _managed_sequence_visual_confirmation_template(work_item, message, message_results[-1]),
                    )
                    _managed_sequence_progress_save(
                        progress_path,
                        work_item,
                        message_results=message_results,
                        target_binding=sequence_work_item.get("target_binding") if isinstance(sequence_work_item.get("target_binding"), dict) else None,
                        sequence_started_at=sequence_started_at,
                        last_message_sent_at=sequence_last_sent_at,
                        message_sequence_window_seconds=message_sequence_window_seconds,
                    )
                    return self._finish(
                        "waiting_for_host",
                        reason,
                        current=work_item,
                        extra={
                            "expected_input": str(visual_confirmation_path),
                            "next_host_action": "visually_verify_sequence_outbound_message_and_resume",
                            "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                            "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
                            "pending_message_index": message.get("index"),
                            "message_results": message_results,
                        },
                    )
                return self._finish(
                    "waiting_for_host",
                    reason,
                    current=work_item,
                    extra={
                        "expected_input": str(result_path) if reason == "outbound_message_requires_visual_verification" else None,
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            if harness_payload.get("status") != "ok":
                return self._finish(
                    "blocked",
                    str(harness_payload.get("reason") or "managed_gui_send_failed"),
                    current=work_item,
                    extra={
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            if not harness_payload.get("post_action_observation_id"):
                return self._finish(
                    "blocked",
                    "post_action_observation_required",
                    current=work_item,
                    extra={
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            required_for_payload = _managed_gui_send_required_evidence_for_payload(required_evidence, harness_payload)
            if any(harness_evidence.get(key) is not True for key in required_for_payload):
                return self._finish(
                    "blocked",
                    "managed_gui_send_verification_incomplete",
                    current=work_item,
                    extra={
                        "managed_gui_send": _redacted_managed_send_payload(harness_payload),
                        "completed_message_count": max(len(message_results) - 1, 0),
                        "failed_message_index": message.get("index"),
                        "message_results": message_results,
                    },
                )
            sent_at = _now_iso()
            sequence_last_sent_at = sent_at
            message_results[-1]["evidence"] = _managed_gui_send_message_evidence(harness_evidence)
            message_results[-1]["sent_at"] = sent_at
            sequence_work_item["target_binding"] = _managed_gui_send_refreshed_target_binding(
                sequence_work_item.get("target_binding") if isinstance(sequence_work_item.get("target_binding"), dict) else None,
                harness_payload,
            )
            _managed_sequence_progress_save(
                progress_path,
                work_item,
                message_results=message_results,
                target_binding=sequence_work_item.get("target_binding") if isinstance(sequence_work_item.get("target_binding"), dict) else None,
                sequence_started_at=sequence_started_at,
                last_message_sent_at=sequence_last_sent_at,
                message_sequence_window_seconds=message_sequence_window_seconds,
            )

        if not message_results:
            return self._finish("blocked", "managed_gui_send_no_message_results", current=work_item)
        final_harness_payload = harness_payloads[-1] if harness_payloads else {}
        final_evidence = _managed_gui_send_normalized_evidence(
            final_harness_payload.get("evidence") if isinstance(final_harness_payload.get("evidence"), dict) else {}
        )
        if not final_evidence:
            final_evidence = {
                key: bool(value)
                for key, value in (message_results[-1].get("evidence") if isinstance(message_results[-1].get("evidence"), dict) else {}).items()
            }
        sequence_elapsed_seconds = _managed_sequence_elapsed_seconds(
            sequence_started_at,
            now_iso=sequence_last_sent_at or _now_iso(),
        )
        verification = {
            "status": "ok",
            "action_request_id": work_item.get("action_request_id"),
            "payload_hash": work_item.get("payload_hash"),
            "verification_method": f"managed_{self.args.app_id}_gui_send",
        }
        self.staged_verifications.append(verification)
        result_payload = {
            "action_request_id": work_item.get("action_request_id"),
            "action": "send_message",
            "target_match_id": work_item.get("match_id"),
            "payload_hash": work_item.get("payload_hash"),
            "precondition_hash": work_item.get("precondition_hash"),
            "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
            "pre_action_observation_id": work_item.get("pre_action_observation_id"),
            "post_action_observation_id": message_results[-1].get("post_action_observation_id"),
            "result_status": "succeeded",
            "message_count": len(payload_messages),
            "payload_format": "message_sequence" if len(payload_messages) > 1 else "single_message",
            "message_sequence_started_at": sequence_started_at or None,
            "message_sequence_last_sent_at": sequence_last_sent_at or None,
            "message_sequence_window_seconds": message_sequence_window_seconds,
            "message_sequence_elapsed_seconds": sequence_elapsed_seconds,
            "message_results": message_results,
            "evidence": {
                "managed_gui_send": True,
                "message_sequence_send": len(payload_messages) > 1,
                "message_sequence_within_window": (
                    sequence_elapsed_seconds is None
                    or sequence_elapsed_seconds <= message_sequence_window_seconds
                ),
                **final_evidence,
            },
        }
        result_path = self._work_file(work_item, "action_result")
        _write_json(result_path, result_payload)
        recorded = self._run_cli_json("operator", "record-action-result", "--data-dir", str(self.data_dir), "--input", str(result_path))
        self.action_results_recorded.append(recorded)
        self._append_timeline("action_result", work_item, {"path": str(result_path), "recorded": recorded})
        if progress_path.exists():
            progress_path.unlink()
        self._clear_host_work_item(work_item, consume=True)
        return None

    def _live_send_contract_block_reason(self, work_item: dict[str, Any], authorization: dict[str, Any]) -> str | None:
        if self._requires_tashuo_mac_ios_structural_binding():
            scan_batch = self._target_binding_scan_batch_or_none(work_item)
            target_binding = _target_binding_for_work_item(work_item, scan_batch)
            if not target_binding_structural_evidence_present("tashuo", target_binding):
                if not isinstance(work_item.get("target_binding"), dict) and _thread_observation_for_work_item(work_item, scan_batch) is None:
                    return "target_binding_lost_current_thread"
                return "target_binding_structural_evidence_required"
        return validate_live_send_contract(
            authorization,
            self._live_send_action_request(work_item),
            app_id=self.args.app_id,
            draft_text=_work_item_payload_text(work_item),
            data_dir=self.data_dir,
        )

    def _live_send_action_request(self, work_item: dict[str, Any]) -> dict[str, Any]:
        action_request = dict(work_item)
        action_request.setdefault("action", "send_message")
        action_request.setdefault("app_id", self.args.app_id)
        action_request["target_binding"] = _target_binding_for_work_item(
            work_item,
            self._target_binding_scan_batch_or_none(work_item),
        )
        return action_request

    def _runtime_live_send_block_reason(self) -> str | None:
        runtime = _normalized_harness_runtime(str(getattr(self.args, "harness_runtime", "") or ""))
        if not runtime:
            return None
        native = self.app_profile.get("native_gui_harness")
        runtimes = native.get("alternate_runtimes") if isinstance(native, dict) else {}
        runtime_profile = runtimes.get(runtime) if isinstance(runtimes, dict) else None
        supported = runtime_profile.get("supported_live_actions") if isinstance(runtime_profile, dict) else []
        if "send_message" not in list(supported or []):
            return f"runtime_live_send_not_supported:{self.args.app_id}:{runtime.replace('_', '-')}"
        return None

    def _requires_tashuo_mac_ios_structural_binding(self) -> bool:
        return self.args.app_id == "tashuo" and _normalized_harness_runtime(
            str(getattr(self.args, "harness_runtime", "") or "")
        ) == "mac_ios_app"

    def _bootstrap_fixture_profile(self) -> None:
        if self.fixture_host is None:
            return
        files_and_args = [
            ("user_profile.json", ["init-profile", "--data-dir", str(self.data_dir), "--input"]),
            ("user_dating_profile.json", ["user", "ingest-profile", "--data-dir", str(self.data_dir), "--input"]),
            ("user_self_interview.json", ["user", "ingest-interview", "--data-dir", str(self.data_dir), "--input"]),
        ]
        for filename, prefix in files_and_args:
            path = self.fixture_host / filename
            if path.exists():
                self._run_cli_json(*prefix, str(path))

    def _authorization_path(self) -> Path:
        path = self.args.authorization or self._fixture_file("auth.json")
        if path is None:
            raise HostLoopError("missing authorization; pass --authorization")
        return path

    def _pending_scan_batch_or_none(self) -> dict[str, Any] | None:
        path = self.data_dir / "operator" / "pending_scan_batch.json"
        if not path.exists():
            return None
        try:
            return _read_json(path)
        except HostLoopError:
            return None

    def _target_binding_scan_batch_or_none(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        pending = self._pending_scan_batch_or_none()
        if pending is not None:
            return pending
        return _scan_batch_from_consumed_observations(self.work_dir, work_item)

    def _target_profile_block_reason(self, work_item: dict[str, Any]) -> str | None:
        if _target_profile_ready_for_work_item(work_item, self._target_binding_scan_batch_or_none(work_item)):
            return None
        return "target_profile_required"

    def _fixture_file(self, filename: str) -> Path | None:
        if self.fixture_host is None:
            return None
        path = self.fixture_host / filename
        return path if path.exists() else None

    def _resolve_skill_package_path(self, explicit: Path | None) -> Path:
        candidates: list[Path] = []
        if explicit is not None:
            candidates.append(explicit)
        adapter_env_path = os.environ.get("DATING_BOOST_ADAPTER_PACKAGE")
        if adapter_env_path:
            candidates.append(Path(adapter_env_path))
        skill_env_path = os.environ.get("DATING_BOOST_SKILL_PACKAGE")
        if skill_env_path:
            candidates.append(Path(skill_env_path))
        candidates.extend(
            [
                ROOT / "skills" / "dating-booster-codex" / "skill-package.json",
                Path.cwd() / "skills" / "dating-booster-codex" / "skill-package.json",
            ]
        )
        codex_home = os.environ.get("CODEX_HOME")
        if codex_home:
            candidates.append(Path(codex_home) / "skills" / "dating-booster-codex" / "skill-package.json")
        candidates.append(Path.home() / ".codex" / "skills" / "dating-booster-codex" / "skill-package.json")
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved.exists():
                return resolved
        raise HostLoopError(
            "missing adapter package; pass --adapter-package or --skill-package, or set DATING_BOOST_ADAPTER_PACKAGE"
        )

    def _waiting(self, expected: str, path: Path, work_item: dict[str, Any]) -> dict[str, Any]:
        if self.args.once or self.args.wait_timeout == 0:
            return self._finish(
                "waiting_for_host",
                f"waiting_for_{expected}",
                current=work_item,
                extra={
                    "expected_input": str(path),
                    "next_host_action": _next_host_action("waiting_for_host", work_item, self.args.send_mode),
                    "app_profile": _host_instructions(self.app_profile, str(work_item.get("work_item_type") or "")),
                },
            )
        deadline = None if self.args.wait_timeout is None else time.time() + self.args.wait_timeout
        while deadline is None or time.time() < deadline:
            if path.exists():
                return {"schema_version": 1, "status": "host_input_ready", "expected_input": str(path)}
            time.sleep(max(self.args.poll_interval, 0.1))
        return self._finish(
            "waiting_for_host",
            f"timeout_waiting_for_{expected}",
            current=work_item,
            extra={
                "expected_input": str(path),
                "next_host_action": _next_host_action("waiting_for_host", work_item, self.args.send_mode),
                "app_profile": _host_instructions(self.app_profile, str(work_item.get("work_item_type") or "")),
            },
        )

    def _finish(
        self,
        status: str,
        reason: str,
        *,
        current: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": status,
            "reason": reason,
            "stop_reason": reason,
            "send_mode": self.args.send_mode,
            "app_id": self.args.app_id,
            "data_dir": str(self.data_dir),
            "work_dir": str(self.work_dir),
            "steps": list(self.steps),
            "staged_verifications": list(self.staged_verifications),
            "stage_results_recorded": list(self.stage_results_recorded),
            "action_results_recorded": list(self.action_results_recorded),
            "next_host_action": _next_host_action(status, current, self.args.send_mode, reason=reason),
        }
        if current is not None:
            payload["current_work_item"] = current
        if extra:
            payload.update(extra)
        if status in REPORT_FINAL_STATUSES and self.operator_session_active:
            preserve_action = _next_host_action_for_block_reason(reason) is not None
            try:
                operator_stop = self._run_cli_json("operator", "stop", "--data-dir", str(self.data_dir))
                self.operator_session_active = False
                payload["operator_stop"] = operator_stop
                payload["machine_report_path"] = _data_dir_path(self.data_dir, operator_stop.get("machine_report_path"))
                payload["human_report_path"] = _data_dir_path(self.data_dir, operator_stop.get("human_report_path"))
                payload["report_summary"] = operator_stop.get("summary")
                relationship_report = operator_stop.get("relationship_progress_report")
                if isinstance(relationship_report, dict):
                    payload["relationship_progress_report"] = _host_loop_relationship_report_paths(
                        self.data_dir,
                        relationship_report,
                    )
                    if not preserve_action:
                        payload["next_host_action"] = RELATIONSHIP_PROGRESS_NEXT_ACTION
                elif operator_stop.get("human_report_path"):
                    payload["relationship_progress_report"] = build_relationship_progress_report(
                        data_dir=self.data_dir,
                        human_report_path=str(operator_stop.get("human_report_path")),
                        machine_report_path=operator_stop.get("machine_report_path"),
                        summary=dict(operator_stop.get("summary") or {}),
                    )
                    if not preserve_action:
                        payload["next_host_action"] = RELATIONSHIP_PROGRESS_NEXT_ACTION
            except (HostLoopError, HostLoopCommandError, RuntimeError) as exc:
                payload["report_error"] = str(exc)
        return payload

    def _write_current_work_item(self, work_item: dict[str, Any]) -> None:
        _write_json(self.work_dir / "current_work_item.json", work_item)

    def _clear_host_work_item(self, work_item: dict[str, Any], *, consume: bool = False) -> None:
        for kind in ("message_list_observation", "thread_observation", "staged_verification", "stage_result", "action_result"):
            path = self._work_file(work_item, kind)
            template = _template_path(path)
            if path.exists():
                if consume:
                    self._consume(path)
                else:
                    path.unlink()
            if template.exists():
                template.unlink()
        current_path = self.work_dir / "current_work_item.json"
        if not current_path.exists():
            return
        try:
            current = _read_json(current_path)
        except HostLoopError:
            current_path.unlink()
            return
        if _same_work_item(current, work_item):
            current_path.unlink()

    def _read_current_work_item_or_none(self) -> dict[str, Any] | None:
        path = self.work_dir / "current_work_item.json"
        if path.exists():
            try:
                return _read_json(path)
            except HostLoopError:
                return None
        operator_path = self.data_dir / "operator" / "current_work_item.json"
        if operator_path.exists():
            try:
                return _read_json(operator_path)
            except HostLoopError:
                return None
        return None

    def _work_file(self, work_item: dict[str, Any], kind: str) -> Path:
        work_item_id = _safe_name(str(work_item.get("work_item_id") or kind))
        return self.work_dir / f"{kind}.{work_item_id}.json"

    def _expected_input_path(self, work_item: dict[str, Any]) -> Path:
        work_type = str(work_item.get("work_item_type") or "")
        if work_type == "scan_message_list":
            return self._work_file(work_item, "message_list_observation")
        if work_type in {"open_thread", "observe_current_thread"}:
            return self._work_file(work_item, "thread_observation")
        if work_type == "send_message":
            staged = self._work_file(work_item, "staged_verification")
            return self._work_file(work_item, "action_result") if staged.exists() and self.args.send_mode == "live" else staged
        return self.work_dir / "current_work_item.json"

    def _append_timeline(self, event_type: str, work_item: dict[str, Any] | None, payload: dict[str, Any] | None = None) -> None:
        event = {
            "schema_version": 1,
            "event_type": event_type,
            "created_at": os.environ.get("DATING_BOOST_NOW") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "work_item_id": work_item.get("work_item_id") if isinstance(work_item, dict) else None,
            "work_item_type": work_item.get("work_item_type") if isinstance(work_item, dict) else None,
            "candidate_key": work_item.get("candidate_key") if isinstance(work_item, dict) else None,
            "payload": payload or {},
        }
        path = self.data_dir / "host_loop" / "timeline.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        self._record_support_event(f"host_loop_{event_type}", event)

    def _record_support_event(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            active = self.support.active_session()
            if not active:
                return
            self.support.record_event(
                session_id=str(active["session_id"]),
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            return

    def _operator_session_status(self) -> str | None:
        session_path = self.data_dir / "operator" / "session.json"
        if not session_path.exists():
            return None
        try:
            session = _read_json(session_path)
        except HostLoopError:
            return None
        status = session.get("status")
        return str(status) if status is not None else None

    def _consume(self, path: Path) -> None:
        consumed_dir = self.work_dir / "consumed"
        consumed_dir.mkdir(parents=True, exist_ok=True)
        target = consumed_dir / f"{len(list(consumed_dir.iterdir())) + 1:04d}_{path.name}"
        path.replace(target)

    def _run_cli_json(
        self,
        *args: str,
        allow_error: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        env = dict(os.environ)
        if self.fixture_host is not None:
            env.setdefault("DATING_BOOST_NOW", DEFAULT_FIXTURE_NOW)
        command = [sys.executable, "-m", "dating_boost.cli", *args]
        run_kwargs = {
            "cwd": ROOT,
            "check": False,
            "capture_output": True,
            "text": True,
            "env": env,
        }
        if timeout_seconds is not None:
            run_kwargs["timeout"] = timeout_seconds
        try:
            result = subprocess.run(command, **run_kwargs)
        except subprocess.TimeoutExpired:
            if allow_error:
                return {
                    "schema_version": 1,
                    "status": "blocked",
                    "reason": "cli_command_timeout",
                    "timeout_seconds": timeout_seconds,
                    "command": " ".join(args),
                }
            raise RuntimeError(f"dating-boost {' '.join(args)} timed out after {timeout_seconds}s")
        if result.returncode != 0:
            structured_error = _try_read_json_object(result.stdout)
            if allow_error and structured_error is not None:
                return structured_error
            if structured_error is not None:
                raise HostLoopCommandError(args, structured_error, result.returncode)
            raise RuntimeError(f"dating-boost {' '.join(args)} failed: {result.stderr or result.stdout}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"dating-boost {' '.join(args)} returned non-JSON output") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"dating-boost {' '.join(args)} returned non-object JSON")
        return payload


class HostLoopError(Exception):
    pass


class HostLoopCommandError(RuntimeError):
    def __init__(self, command: tuple[str, ...], payload: dict[str, Any], returncode: int):
        self.command = command
        self.payload = payload
        self.returncode = returncode
        reason = payload.get("reason") or payload.get("status") or "unknown_cli_error"
        super().__init__(f"dating-boost {' '.join(command)} failed: {reason}")


def _message_list_template(work_item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    return {
        "schema_version": 1,
        "observation_type": "message_list",
        "session_id": _session_hint(work_item),
        "app_id": app_id,
        "captured_at": "TODO_ISO_TIMESTAMP",
        "scan_cursor": work_item.get("scan_cursor") or {"current": None, "next": None, "exhausted": False},
        "page_index": None,
        "visible_range": {"start": None, "end": None},
        "entries_observed_count": 0,
        "scan_budget": int(work_item.get("thread_budget_remaining") or 5),
        "screenshot_ref": "",
        "provenance": {
            "author": "host_agent",
            "evidence": _message_list_evidence(profile),
        },
        "message_list_snapshot": {
            "entries": [
                {
                    "candidate_key": "visible_name_row_1_latest_preview_hash",
                    "visible_name": "TODO",
                    "latest_preview": "TODO",
                    "latest_preview_hash": "TODO_STABLE_HASH",
                    "timestamp_cue": "TODO",
                    "last_activity_at": "",
                    "days_since_last_activity": None,
                    "freshness_bucket": "fresh|within_week|historical",
                    "unread_cue": "present|absent",
                    "candidate_type": "continuation_candidate|open_chat_candidate|new_match_candidate",
                    "position": 1,
                    "identity_confidence": "medium",
                    "identity_evidence": "Visible row, stable name, and preview.",
                    "match_identity_hints": {
                        "visible_name": "TODO",
                        "profile_cues": [],
                        "conversation_fingerprint": "TODO",
                    },
                    "evidence": f"Visible {display_name} row.",
                }
            ]
        },
    }


def _thread_template(work_item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    app_id = str(profile.get("app_id") or "unknown")
    candidate_key = str(work_item.get("candidate_key") or "TODO")
    return {
        "schema_version": 1,
        "observation_type": "thread",
        "candidate_key": candidate_key,
        "identity_confidence": "medium",
        "identity_evidence": "Visible chat header matches the selected message-list row.",
        "turn_boundary_evidence": {
            "latest_user_outbound_text": "",
            "latest_user_outbound_index": None,
            "latest_inbound_after_user": [],
        },
        "screenshot_ref": "",
        "assessment": {
            "schema_version": 1,
            "latest_match_message": "TODO",
            "latest_inbound_fingerprint": "TODO_STABLE_INBOUND_FINGERPRINT",
            "reply_window_status": "open",
            "continuation_opportunity": "yes|no|unknown",
            "appointment_stage": "none|soft_probe|details_requested|handoff",
            "recommended_next": "reply|nudge_later|wait|handoff",
            "confidence": "low|medium|high",
            "evidence": "TODO",
            "risk_flags": [],
        },
        "planner_assessment": {
            "schema_version": 1,
            "latest_turn_summary": "TODO",
            "latest_turn_type": "short_answer|question|delegate|refusal|other",
            "inbound_intent": "TODO",
            "topic": {
                "current_topic": "TODO",
                "topic_state": "active|saturating|exhausted",
                "new_information": [],
                "stale_hooks": [],
            },
            "scores": {
                "engagement": 50,
                "warmth": 50,
                "curiosity": 50,
                "comfort": 50,
                "momentum": 50,
                "topic_saturation": 30,
                "logistics_readiness": 0,
                "risk": 0,
            },
            "recommended_stage": "warmup",
            "recommended_move": "answer_or_riff",
            "next_milestone": "TODO",
            "avoid_next": [],
            "soft_invite_allowed": False,
            "confidence": "low|medium|high",
            "evidence": "TODO",
        },
        "observation": {
            "observation_id": f"obs_{_safe_name(candidate_key)}_TODO",
            "source_type": "live_screenshot",
            "app_id": app_id,
            "captured_at": "TODO_ISO_TIMESTAMP",
            "page_type": "chat_thread",
            "page_confidence": "high|medium|low",
            "match_identity_hints": {
                "visible_name": "TODO",
                "profile_cues": [],
                "conversation_fingerprint": "TODO",
                "evidence": _thread_identity_evidence(profile),
            },
            "profile_observation": {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
            },
            "conversation_observation": {
                "visible_messages": [],
                "latest_inbound_messages": [
                    {
                        "sender": "match",
                        "text": "TODO",
                        "is_after_latest_outbound": True,
                    }
                ],
                "input_state": "empty",
                "thread_cues": [],
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {
                "evidence": _thread_provenance_evidence(profile),
            },
            "raw_ref": None,
        },
        "draft": None,
    }


def _staged_verification_template(work_item: dict[str, Any]) -> dict[str, Any]:
    return _staged_verification(work_item, result_status="unknown", staged_text="")


def _staged_verification(work_item: dict[str, Any], *, result_status: str, staged_text: str | None = None) -> dict[str, Any]:
    payload_text = _work_item_payload_text(work_item)
    return {
        "schema_version": 1,
        "verification_type": "staged_text",
        "action_request_id": work_item.get("action_request_id"),
        "match_id": work_item.get("match_id"),
        "candidate_key": work_item.get("candidate_key"),
        "expected_payload_hash": work_item.get("payload_hash"),
        "expected_payload_text": payload_text,
        "result_status": result_status,
        "staged_text": payload_text if staged_text is None else staged_text,
        "evidence": {
            "verification": "Input box text was checked before send.",
            "input_method": "paste",
        },
    }


def _staged_verification_from_stage_draft(work_item: dict[str, Any], harness_payload: dict[str, Any]) -> dict[str, Any]:
    verification = _staged_verification(work_item, result_status="succeeded")
    staged_text_verification = harness_payload.get("staged_text_verification")
    if not isinstance(staged_text_verification, dict):
        staged_text_verification = {}
    screen = staged_text_verification.get("screen") if isinstance(staged_text_verification.get("screen"), dict) else {}
    screenshot_ref = str(screen.get("path") or "") if isinstance(screen, dict) else ""
    verification.update(
        {
            "stage_attempt_status": harness_payload.get("stage_attempt_status"),
            "staged_text_verified": harness_payload.get("staged_text_verified") is True,
            "staged_text_verification": staged_text_verification,
        }
    )
    if screenshot_ref:
        verification["screenshot_ref"] = screenshot_ref
    evidence = dict(verification.get("evidence") if isinstance(verification.get("evidence"), dict) else {})
    evidence.update(
        {
            "verification": "TaShuo mac-ios-app stage-draft verified the input box before stage-only audit.",
            "input_method": "harness_stage_draft",
            "harness_runtime": "mac_ios_app",
            "stage_attempt_status": harness_payload.get("stage_attempt_status"),
            "staged_text_verification_status": staged_text_verification.get("status"),
            "screen_exact_text_ocr_verified": staged_text_verification.get("screen_exact_text_ocr_verified") is True,
            "exact_text_ocr_verified": staged_text_verification.get("exact_text_ocr_verified") is True,
            "exact_text_ax_verified": staged_text_verification.get("exact_text_ax_verified") is True,
        }
    )
    if screenshot_ref:
        evidence["screenshot_ref"] = screenshot_ref
    verification["evidence"] = evidence
    return verification


def _stage_result_from_verification(work_item: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    staged_text_verified = verification.get("staged_text_verified")
    evidence = {
        "verification": "Stage mode verified the payload text in the input box and did not send.",
        "sent": False,
    }
    if isinstance(verification.get("evidence"), dict):
        evidence.update(verification["evidence"])
        evidence["sent"] = False
    stage_result = {
        "schema_version": 1,
        "action_request_id": work_item.get("action_request_id"),
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "result_status": "succeeded",
        "staged_text_verified": staged_text_verified if isinstance(staged_text_verified, bool) else True,
        "staged_text_verification": verification.get("staged_text_verification") or verification,
        "evidence": evidence,
    }
    for key in ("stage_attempt_status", "screenshot_ref"):
        if verification.get(key) is not None:
            stage_result[key] = verification[key]
    return stage_result


def _action_result_template(work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_request_id": work_item.get("action_request_id"),
        "action": "send_message",
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": "",
        "result_status": "unknown",
        "evidence": {
            "verification": "Fill only after a fresh post-send observation confirms the sent bubble.",
        },
    }


def _action_result_fixture(work_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_request_id": work_item.get("action_request_id"),
        "action": "send_message",
        "target_match_id": work_item.get("match_id"),
        "payload_hash": work_item.get("payload_hash"),
        "precondition_hash": work_item.get("precondition_hash"),
        "autonomous_audit_binding": work_item.get("autonomous_audit_binding"),
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": f"{work_item.get('pre_action_observation_id')}_sent",
        "result_status": "succeeded",
        "evidence": {
            "post_send_visible_text": work_item.get("payload_text"),
            "staged_text_verified": True,
        },
    }


def _validate_staged_verification(payload: dict[str, Any], work_item: dict[str, Any]) -> dict[str, Any]:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        return {"status": "blocked", "reason": "staged verification action_request_id mismatch"}
    if payload.get("expected_payload_hash") != work_item.get("payload_hash"):
        return {"status": "blocked", "reason": "staged verification payload_hash mismatch"}
    if payload.get("result_status") != "succeeded":
        return {"status": "blocked", "reason": "staged text was not verified as succeeded"}
    if payload.get("staged_text") != _work_item_payload_text(work_item):
        return {"status": "blocked", "reason": "staged text does not match payload_text"}
    result = {
        "status": "ok",
        "action_request_id": payload.get("action_request_id"),
        "payload_hash": payload.get("expected_payload_hash"),
    }
    for key in (
        "evidence",
        "stage_attempt_status",
        "staged_text_verified",
        "staged_text_verification",
        "screenshot_ref",
    ):
        if key in payload:
            result[key] = payload[key]
    return result


def _validate_action_result(payload: dict[str, Any], work_item: dict[str, Any]) -> None:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        raise HostLoopError("action_result action_request_id mismatch")
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        raise HostLoopError("action_result payload_hash mismatch")
    if payload.get("target_match_id") != work_item.get("match_id"):
        raise HostLoopError("action_result target_match_id mismatch")


def _session_hint(work_item: dict[str, Any]) -> str:
    value = str(work_item.get("work_item_id") or "host_loop")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"session_host_loop_{digest}"


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "unknown"


def _same_work_item(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_id = left.get("work_item_id")
    right_id = right.get("work_item_id")
    if left_id and right_id:
        return left_id == right_id
    left_action = left.get("action_request_id")
    right_action = right.get("action_request_id")
    return bool(left_action and right_action and left_action == right_action)


def _template_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.template{path.suffix}")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HostLoopError(f"{key} is required")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise HostLoopError(f"expected JSON object in {path}")
    return data


def _try_read_json_object(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _redacted_managed_send_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "status",
        "reason",
        "app_id",
        "action",
        "mode",
        "draft_fingerprint",
        "draft_character_count",
        "staged_text_verification",
        "post_send_verification",
        "post_action_observation_id",
        "evidence",
        "clipboard_restored",
        "next_host_action",
        "visual_verification_request",
        "current_thread_visual_anchor",
        "message_sequence_index",
        "message_sequence_count",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _redacted_stage_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "status",
        "reason",
        "app_id",
        "action",
        "harness_backend",
        "stage_attempt_status",
        "staged_text_verified",
        "staged_text_verification",
        "next_host_action",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _managed_gui_send_normalized_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(evidence)
    normalized["staged_exact_text_verified"] = bool(
        evidence.get("staged_exact_text_verified")
        or evidence.get("staged_exact_text_ax_verified")
        or evidence.get("staged_exact_text_ocr_verified")
    )
    normalized["outbound_exact_text_verified"] = bool(
        evidence.get("outbound_exact_text_verified")
        or evidence.get("outbound_exact_text_ax_verified")
        or evidence.get("outbound_exact_text_ocr_verified")
    )
    return normalized


def _managed_gui_send_message_evidence(evidence: dict[str, Any]) -> dict[str, bool]:
    return {
        "staged_text_verified": bool(evidence.get("staged_text_verified")),
        "staged_exact_text_verified": bool(evidence.get("staged_exact_text_verified")),
        "input_cleared_after_send": bool(evidence.get("input_cleared_after_send")),
        "post_action_screen_captured": bool(evidence.get("post_action_screen_captured")),
        "outbound_message_verified": bool(evidence.get("outbound_message_verified")),
        "outbound_exact_text_verified": bool(evidence.get("outbound_exact_text_verified")),
    }


def _managed_gui_send_message_result(message: dict[str, Any], harness_payload: dict[str, Any]) -> dict[str, Any]:
    evidence = _managed_gui_send_normalized_evidence(
        harness_payload.get("evidence") if isinstance(harness_payload.get("evidence"), dict) else {}
    )
    result = {
        "index": int(message.get("index") or 0),
        "message_hash": str(message.get("message_hash") or ""),
        "character_count": int(message.get("character_count") or 0),
        "post_action_observation_id": harness_payload.get("post_action_observation_id"),
        "status": harness_payload.get("status"),
        "evidence": _managed_gui_send_message_evidence(evidence),
    }
    if harness_payload.get("already_sent") is True:
        result["already_sent"] = True
    if harness_payload.get("reason"):
        result["reason"] = harness_payload.get("reason")
    return result


def _managed_gui_send_required_evidence_for_payload(
    required_evidence: tuple[str, ...],
    harness_payload: dict[str, Any],
) -> tuple[str, ...]:
    if harness_payload.get("already_sent") is not True:
        return required_evidence
    return tuple(
        key
        for key in required_evidence
        if key not in {"staged_text_verified", "staged_exact_text_verified", "staged_exact_text_ocr_verified"}
    )


def _managed_gui_send_refreshed_target_binding(
    target_binding: dict[str, Any] | None,
    harness_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(target_binding, dict):
        return target_binding
    anchor = harness_payload.get("current_thread_visual_anchor")
    if not isinstance(anchor, dict) or anchor.get("status") != "ok":
        return target_binding
    visual_hash = str(anchor.get("visual_anchor_hash") or "").strip()
    if not visual_hash:
        return target_binding

    refreshed = dict(target_binding)
    thread_evidence = (
        dict(refreshed.get("thread_evidence"))
        if isinstance(refreshed.get("thread_evidence"), dict)
        else {}
    )
    thread_evidence["visual_anchor_hash"] = visual_hash
    if isinstance(anchor.get("visual_anchor_region"), dict):
        thread_evidence["visual_anchor_region"] = anchor.get("visual_anchor_region")
    thread_evidence["screen_state"] = str(anchor.get("screen_state") or thread_evidence.get("screen_state") or "tashuo_conversation")
    if harness_payload.get("post_action_observation_id"):
        thread_evidence["observation_id"] = harness_payload.get("post_action_observation_id")
    refreshed["thread_evidence"] = thread_evidence
    return refreshed


def _managed_sequence_progress_path(work_dir: Path, work_item: dict[str, Any]) -> Path:
    return work_dir / f"managed_sequence_progress.{_safe_name(str(work_item.get('work_item_id') or 'send'))}.json"


def _managed_sequence_visual_confirmation_path(work_dir: Path, work_item: dict[str, Any], message_index: int) -> Path:
    safe_work_id = _safe_name(str(work_item.get("work_item_id") or "send"))
    return work_dir / f"managed_sequence_visual_verification.{safe_work_id}.{int(message_index):02d}.json"


def _managed_sequence_pending_visual_result(message_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for result in message_results:
        if isinstance(result, dict) and result.get("status") == "visual_verification_pending":
            return result
    return None


def _managed_sequence_message_by_index(messages: list[dict[str, Any]], message_index: int) -> dict[str, Any] | None:
    for message in messages:
        if int(message.get("index") or 0) == int(message_index):
            return message
    return None


def _managed_sequence_visual_confirmation_template(
    work_item: dict[str, Any],
    message: dict[str, Any],
    pending_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_request_id": work_item.get("action_request_id"),
        "payload_hash": work_item.get("payload_hash"),
        "message_index": int(message.get("index") or 0),
        "message_hash": message.get("message_hash"),
        "post_action_observation_id": pending_result.get("post_action_observation_id") or "",
        "result_status": "unknown",
        "post_send_visible_text": "",
        "evidence": {
            "verification": "Set result_status to succeeded only after a fresh visual post-send observation confirms this exact outbound bubble and an empty input box.",
            "host_visual_outbound_exact_text_verified": False,
            "input_cleared_after_send": False,
            "post_action_screen_captured": False,
        },
    }


def _validate_managed_sequence_visual_confirmation(
    payload: dict[str, Any],
    work_item: dict[str, Any],
    message: dict[str, Any],
) -> str | None:
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        return "managed_sequence_visual_confirmation_action_request_id_mismatch"
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        return "managed_sequence_visual_confirmation_payload_hash_mismatch"
    if int(payload.get("message_index") or 0) != int(message.get("index") or 0):
        return "managed_sequence_visual_confirmation_message_index_mismatch"
    if payload.get("message_hash") != message.get("message_hash"):
        return "managed_sequence_visual_confirmation_message_hash_mismatch"
    if payload.get("result_status") != "succeeded":
        return "managed_sequence_visual_confirmation_not_succeeded"
    visible_text = payload.get("post_send_visible_text")
    if not isinstance(visible_text, str) or not visible_text.strip():
        return "managed_sequence_visual_confirmation_visible_text_missing"
    if visible_text != message.get("text"):
        return "managed_sequence_visual_confirmation_visible_text_mismatch"
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return "managed_sequence_visual_confirmation_evidence_missing"
    outbound_verified = bool(
        evidence.get("outbound_exact_text_verified")
        or evidence.get("host_visual_outbound_exact_text_verified")
        or evidence.get("outbound_exact_text_visual_verified_by_host")
    )
    if not outbound_verified:
        return "managed_sequence_visual_confirmation_outbound_exact_text_missing"
    if evidence.get("input_cleared_after_send") is not True:
        return "managed_sequence_visual_confirmation_input_cleared_missing"
    if evidence.get("post_action_screen_captured") is not True:
        return "managed_sequence_visual_confirmation_post_screen_missing"
    return None


def _managed_sequence_visual_confirmation_evidence(
    confirmation: dict[str, Any],
    pending_result: dict[str, Any],
) -> dict[str, Any]:
    pending_evidence = pending_result.get("evidence") if isinstance(pending_result.get("evidence"), dict) else {}
    confirmation_evidence = confirmation.get("evidence") if isinstance(confirmation.get("evidence"), dict) else {}
    merged = {**pending_evidence, **confirmation_evidence}
    if (
        confirmation_evidence.get("host_visual_outbound_exact_text_verified")
        or confirmation_evidence.get("outbound_exact_text_visual_verified_by_host")
    ):
        merged["outbound_message_verified"] = True
        merged["outbound_exact_text_verified"] = True
    return _managed_gui_send_normalized_evidence(merged)


def _managed_sequence_window_seconds(message_count: int) -> int:
    return max(1, int(message_count or 1)) * MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE


def _parse_iso_datetime_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _managed_sequence_elapsed_seconds(started_at: Any, *, now_iso: str | None = None) -> float | None:
    started = _parse_iso_datetime_utc(started_at)
    now = _parse_iso_datetime_utc(now_iso or _now_iso())
    if started is None or now is None:
        return None
    return max(0.0, (now - started).total_seconds())


def _managed_sequence_expiry(started_at: Any, *, window_seconds: int) -> dict[str, Any] | None:
    elapsed_seconds = _managed_sequence_elapsed_seconds(started_at)
    if elapsed_seconds is None or elapsed_seconds <= window_seconds:
        return None
    return {
        "message_sequence_started_at": started_at,
        "message_sequence_window_seconds": window_seconds,
        "message_sequence_elapsed_seconds": elapsed_seconds,
    }


def _managed_sequence_remaining_seconds(started_at: Any, *, window_seconds: int) -> float | None:
    elapsed_seconds = _managed_sequence_elapsed_seconds(started_at)
    if elapsed_seconds is None:
        return None
    return max(0.0, float(window_seconds) - elapsed_seconds)


def _managed_sequence_progress_load(path: Path, work_item: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError, HostLoopError):
        return {}
    if payload.get("action_request_id") != work_item.get("action_request_id"):
        return {}
    if payload.get("payload_hash") != work_item.get("payload_hash"):
        return {}
    raw_results = payload.get("message_results")
    message_results = [result for result in raw_results if isinstance(result, dict)] if isinstance(raw_results, list) else []
    progress: dict[str, Any] = {"message_results": message_results}
    if isinstance(payload.get("sequence_started_at"), str):
        progress["sequence_started_at"] = payload["sequence_started_at"]
    if isinstance(payload.get("last_message_sent_at"), str):
        progress["last_message_sent_at"] = payload["last_message_sent_at"]
    if isinstance(payload.get("target_binding"), dict):
        progress["target_binding"] = payload["target_binding"]
    return progress


def _managed_sequence_progress_save(
    path: Path,
    work_item: dict[str, Any],
    *,
    message_results: list[dict[str, Any]],
    target_binding: dict[str, Any] | None,
    sequence_started_at: str | None,
    last_message_sent_at: str | None,
    message_sequence_window_seconds: int,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "action_request_id": work_item.get("action_request_id"),
        "work_item_id": work_item.get("work_item_id"),
        "payload_hash": work_item.get("payload_hash"),
        "completed_message_count": sum(1 for result in message_results if result.get("status") == "ok"),
        "sequence_started_at": sequence_started_at,
        "last_message_sent_at": last_message_sent_at,
        "message_sequence_window_seconds": message_sequence_window_seconds,
        "message_results": message_results,
    }
    if isinstance(target_binding, dict):
        payload["target_binding"] = target_binding
    _write_json(path, payload)


def _work_item_payload_messages(work_item: dict[str, Any]) -> list[dict[str, Any]]:
    raw_messages = work_item.get("payload_messages")
    if work_item.get("payload_format") == "message_sequence" and isinstance(raw_messages, list):
        messages = []
        for expected_index, item in enumerate(raw_messages, start=1):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            message_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            messages.append(
                {
                    "index": int(item.get("index") or expected_index),
                    "text": text,
                    "message_hash": str(item.get("message_hash") or message_hash),
                    "character_count": int(item.get("character_count") or len(text)),
                }
            )
        if messages:
            return messages
    text = str(work_item.get("payload_text") or "")
    return [
        {
            "index": 1,
            "text": text,
            "message_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "character_count": len(text),
        }
    ]


def _work_item_payload_text(work_item: dict[str, Any]) -> str:
    return "\n".join(message["text"] for message in _work_item_payload_messages(work_item))


def _single_message_work_item(work_item: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    text = str(message["text"])
    message_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    single = dict(work_item)
    single["action_request_id"] = f"{work_item.get('action_request_id')}.{int(message['index']):02d}"
    single["payload_text"] = text
    single["payload_hash"] = message_hash
    single["payload_format"] = "single_message"
    single["payload_messages"] = [
        {
            "index": 1,
            "text": text,
            "message_hash": message_hash,
            "character_count": len(text),
        }
    ]
    single["message_count"] = 1
    binding = single.get("autonomous_audit_binding")
    if isinstance(binding, dict):
        updated_binding = dict(binding)
        updated_binding["payload_hash"] = message_hash
        single["autonomous_audit_binding"] = updated_binding
    return single


def _managed_gui_send_required_evidence(app_id: str, runtime: str | None = None) -> tuple[str, ...]:
    manifest = manifest_for_app(app_id)
    runtime_key = _normalized_harness_runtime(str(runtime or ""))
    if runtime_key and runtime_key != "default":
        runtime_profile = manifest.runtime_profiles.get(runtime_key)
        requirements = (
            runtime_profile.get("live_send_requirements")
            if isinstance(runtime_profile, dict) and isinstance(runtime_profile.get("live_send_requirements"), dict)
            else {}
        )
        evidence = requirements.get("required_evidence")
        if isinstance(evidence, list) and evidence:
            return tuple(str(item) for item in evidence)
    return manifest.required_send_evidence


def _target_binding_for_work_item(work_item: dict[str, Any], pending_scan_batch: dict[str, Any] | None) -> dict[str, Any]:
    existing = work_item.get("target_binding")
    if isinstance(existing, dict):
        binding = dict(existing)
    else:
        binding = {}
    binding.setdefault("target_match_id", work_item.get("match_id"))
    binding.setdefault("candidate_key", work_item.get("candidate_key"))
    required = list(binding.get("required_visible_text") or []) if isinstance(binding.get("required_visible_text"), list) else []

    thread = _thread_observation_for_work_item(work_item, pending_scan_batch)
    entry = _message_list_entry_for_work_item(work_item, pending_scan_batch)
    thread_observation = thread.get("observation") if isinstance(thread, dict) else None
    thread_hints = thread_observation.get("match_identity_hints") if isinstance(thread_observation, dict) else None
    entry_hints = entry.get("match_identity_hints") if isinstance(entry, dict) else None
    visible_name = (
        _stripped_or_none(binding.get("visible_name"))
        or _stripped_or_none(thread_hints.get("visible_name") if isinstance(thread_hints, dict) else None)
        or _stripped_or_none(entry_hints.get("visible_name") if isinstance(entry_hints, dict) else None)
        or _stripped_or_none(entry.get("visible_name") if isinstance(entry, dict) else None)
    )
    fingerprint = (
        _stripped_or_none(binding.get("conversation_fingerprint"))
        or _stripped_or_none(thread_hints.get("conversation_fingerprint") if isinstance(thread_hints, dict) else None)
        or _stripped_or_none(entry_hints.get("conversation_fingerprint") if isinstance(entry_hints, dict) else None)
    )
    if visible_name:
        binding.setdefault("visible_name", visible_name)
        required.append(str(binding.get("visible_name") or visible_name).strip())
    if fingerprint:
        binding.setdefault("conversation_fingerprint", fingerprint)
    if isinstance(entry, dict):
        for evidence_key in ("message_list_evidence", "selection_evidence"):
            evidence = entry.get(evidence_key)
            if isinstance(evidence, dict) and evidence_key not in binding:
                binding[evidence_key] = dict(evidence)
    if isinstance(thread, dict):
        thread_binding = thread.get("target_binding")
        if isinstance(thread_binding, dict):
            for key, value in thread_binding.items():
                if key == "thread_evidence" and isinstance(value, dict):
                    existing_evidence = (
                        dict(binding.get("thread_evidence"))
                        if isinstance(binding.get("thread_evidence"), dict)
                        else {}
                    )
                    existing_evidence.update(value)
                    binding["thread_evidence"] = existing_evidence
                else:
                    binding.setdefault(key, value)
        if not target_binding_structural_evidence_present("tashuo", binding):
            derived_binding = _derive_tashuo_current_thread_target_binding(thread, binding)
            if isinstance(derived_binding, dict):
                for key, value in derived_binding.items():
                    if key == "thread_evidence" and isinstance(value, dict):
                        existing_evidence = (
                            dict(binding.get("thread_evidence"))
                            if isinstance(binding.get("thread_evidence"), dict)
                            else {}
                        )
                        existing_evidence.update(value)
                        binding["thread_evidence"] = existing_evidence
                    else:
                        binding.setdefault(key, value)

    unique_required: list[str] = []
    for item in required:
        text = str(item).strip()
        if text and text not in unique_required:
            unique_required.append(text)
    binding["required_visible_text"] = unique_required
    return binding


def _derive_tashuo_current_thread_target_binding(
    thread: dict[str, Any],
    binding: dict[str, Any],
) -> dict[str, Any] | None:
    observation = thread.get("observation")
    if not isinstance(observation, dict) or observation.get("app_id") != "tashuo":
        return None
    hints = observation.get("match_identity_hints")
    if not isinstance(hints, dict):
        hints = {}
    visible_name = _stripped_or_none(binding.get("visible_name")) or _stripped_or_none(hints.get("visible_name"))
    fingerprint = (
        _stripped_or_none(binding.get("conversation_fingerprint"))
        or _stripped_or_none(hints.get("conversation_fingerprint"))
    )
    assessment = thread.get("assessment")
    latest_inbound_fingerprint = (
        _stripped_or_none(assessment.get("latest_inbound_fingerprint"))
        if isinstance(assessment, dict)
        else None
    )
    observation_id = _stripped_or_none(observation.get("observation_id"))
    screenshot_path = _thread_screenshot_path(thread, observation)
    if not (visible_name and fingerprint and latest_inbound_fingerprint and observation_id and screenshot_path):
        return None
    if not screenshot_path.exists():
        return None
    try:
        from dating_boost.apps.tashuo.native import (
            TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION,
            _tashuo_visual_anchor_hash_for_path,
        )
    except Exception:
        return None
    anchor_region = dict(TASHUO_CURRENT_THREAD_VISUAL_ANCHOR_REGION)
    anchor = _tashuo_visual_anchor_hash_for_path(screenshot_path, region=anchor_region)
    visual_anchor_hash = _stripped_or_none(anchor.get("visual_anchor_hash")) if isinstance(anchor, dict) else None
    if not visual_anchor_hash:
        return None
    return {
        "binding_type": "current_thread_visual_identity",
        "visible_name": visible_name,
        "conversation_fingerprint": fingerprint,
        "thread_evidence": {
            "observation_id": observation_id,
            "screen_state": "tashuo_conversation",
            "latest_inbound_fingerprint": latest_inbound_fingerprint,
            "visual_anchor_hash": visual_anchor_hash,
            "visual_anchor_region": anchor_region,
        },
    }


def _thread_screenshot_path(thread: dict[str, Any], observation: dict[str, Any]) -> Path | None:
    for value in (thread.get("screenshot_ref"), observation.get("raw_ref")):
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value.strip())
        return path if path.is_absolute() else ROOT / path
    return None


def _target_profile_ready_for_work_item(work_item: dict[str, Any], pending_scan_batch: dict[str, Any] | None) -> bool:
    profile_payload = _target_profile_payload_for_work_item(work_item, pending_scan_batch)
    if not isinstance(profile_payload, dict):
        return False
    profile = ProfileObservation.from_dict(profile_payload)
    return bool(
        profile.review_status == "observed"
        and (
            profile.profile_text.strip()
            or any(str(item).strip() for item in profile.photo_cues)
            or any(str(item).strip() for item in profile.hook_candidates)
        )
    )


def _target_profile_payload_for_work_item(
    work_item: dict[str, Any],
    pending_scan_batch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    embedded = work_item.get("target_profile_observation")
    if isinstance(embedded, dict):
        return embedded
    legacy = work_item.get("profile_observation")
    if isinstance(legacy, dict):
        return legacy
    thread = _thread_observation_for_work_item(work_item, pending_scan_batch)
    observation = thread.get("observation") if isinstance(thread, dict) else None
    profile = observation.get("profile_observation") if isinstance(observation, dict) else None
    return profile if isinstance(profile, dict) else None


def _scan_batch_from_consumed_observations(work_dir: Path, work_item: dict[str, Any]) -> dict[str, Any] | None:
    consumed_dir = work_dir / "consumed"
    if not consumed_dir.exists():
        return None
    candidate_key = str(work_item.get("candidate_key") or "")
    entry: dict[str, Any] | None = None
    thread: dict[str, Any] | None = None
    for path in sorted(consumed_dir.glob("*.json"), reverse=True):
        try:
            payload = _read_json(path)
        except HostLoopError:
            continue
        observation_type = str(payload.get("observation_type") or "")
        if observation_type == "thread" and thread is None and str(payload.get("candidate_key") or "") == candidate_key:
            thread = payload
            continue
        if observation_type != "message_list" or entry is not None:
            continue
        snapshot = payload.get("message_list_snapshot")
        entries = snapshot.get("entries", []) if isinstance(snapshot, dict) else []
        for item in entries:
            if isinstance(item, dict) and str(item.get("candidate_key") or "") == candidate_key:
                entry = item
                break
        if entry is not None and thread is not None:
            break
    if entry is None and thread is None:
        return None
    return {
        "schema_version": 1,
        "message_list_snapshot": {"entries": [entry] if entry is not None else []},
        "thread_observations": [thread] if thread is not None else [],
    }


def _thread_observation_for_work_item(
    work_item: dict[str, Any],
    pending_scan_batch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(pending_scan_batch, dict):
        return None
    candidate_key = str(work_item.get("candidate_key") or "")
    for item in pending_scan_batch.get("thread_observations", []):
        if isinstance(item, dict) and str(item.get("candidate_key") or "") == candidate_key:
            return item
    return None


def _message_list_entry_for_work_item(
    work_item: dict[str, Any],
    pending_scan_batch: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(pending_scan_batch, dict):
        return None
    candidate_key = str(work_item.get("candidate_key") or "")
    snapshot = pending_scan_batch.get("message_list_snapshot")
    entries = snapshot.get("entries", []) if isinstance(snapshot, dict) else []
    for item in entries:
        if isinstance(item, dict) and str(item.get("candidate_key") or "") == candidate_key:
            return item
    return None


def _stripped_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _data_dir_path(data_dir: Path, value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(data_dir / path)


def _host_loop_relationship_report_paths(data_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized["human_report_path"] = _data_dir_path(data_dir, normalized.get("human_report_path"))
    normalized["machine_report_path"] = _data_dir_path(data_dir, normalized.get("machine_report_path"))
    return normalized


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_app_profile(app_id: str) -> dict[str, Any]:
    if app_id not in set(supported_app_ids()):
        raise HostLoopError(f"unsupported app profile: {app_id}")
    path = ROOT / "app_profiles" / f"{_safe_name(app_id)}.json"
    if not path.exists():
        raise HostLoopError(f"unsupported app profile: {app_id}")
    profile = _read_json(path)
    profile["_path"] = str(path)
    return profile


def _host_instructions(profile: dict[str, Any], work_item_type: str) -> dict[str, Any]:
    key = {
        "scan_message_list": "message_list_observation",
        "observe_current_thread": "thread_observation",
        "open_thread": "thread_observation",
        "send_message": "stage_send_verification",
    }.get(work_item_type, "known_gui_pitfalls")
    native = profile.get("native_gui_harness")
    native_blocked_actions = native.get("blocked_actions", []) if isinstance(native, dict) else []
    native_live_send = native.get("live_send") if isinstance(native, dict) else None
    return {
        "app_id": profile.get("app_id"),
        "display_name": profile.get("display_name"),
        "support_level": profile.get("support_level"),
        "host_loop_supported": profile.get("host_loop_supported"),
        "host_loop_send_modes": profile.get("host_loop_send_modes", []),
        "instructions": profile.get(key, []),
        "known_gui_pitfalls": profile.get("known_gui_pitfalls", []),
        "unsupported_actions": profile.get("unsupported_actions", []),
        "native_blocked_actions": native_blocked_actions,
        "native_live_send": native_live_send,
    }


def _message_list_evidence(profile: dict[str, Any]) -> str:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    backend = _native_backend(profile)
    if backend == "iphone_mirroring_macos":
        return f"{display_name} message list observed through iPhone Mirroring."
    if backend == "macos_wechat_desktop":
        return f"{display_name} chat list observed from the macOS desktop window."
    return f"{display_name} visible message list observed by the host agent."


def _thread_identity_evidence(profile: dict[str, Any]) -> str:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    return f"Visible {display_name} chat header and messages."


def _thread_provenance_evidence(profile: dict[str, Any]) -> str:
    app_id = str(profile.get("app_id") or "unknown")
    display_name = str(profile.get("display_name") or app_id)
    backend = _native_backend(profile)
    if backend == "iphone_mirroring_macos":
        return f"Host-agent screen read from iPhone Mirroring for {display_name}."
    if backend == "macos_wechat_desktop":
        return f"Host-agent screen read from the macOS {display_name} desktop window."
    return f"Host-agent screen read from visible {display_name} UI."


def _native_backend(profile: dict[str, Any]) -> str:
    native = profile.get("native_gui_harness")
    if not isinstance(native, dict):
        return ""
    backend = native.get("backend")
    return str(backend) if backend is not None else ""


def _normalized_harness_runtime(value: str) -> str:
    return value.strip().replace("-", "_")


def _next_host_action(status: str, work_item: dict[str, Any] | None, send_mode: str, *, reason: str | None = None) -> str:
    reason_action = _next_host_action_for_block_reason(reason)
    if reason_action is not None:
        return reason_action
    if not isinstance(work_item, dict):
        if status in {"blocked", "error"}:
            return "inspect_error_and_fix_configuration"
        return "run_or_resume_host_loop"
    work_type = str(work_item.get("work_item_type") or "")
    if status == "staged_waiting_user_confirmation":
        return "review_staged_text_and_confirm_or_cancel"
    if work_type == "scan_message_list":
        return "open_app_message_list_and_write_message_list_observation"
    if work_type == "open_thread":
        return "open_requested_thread_and_write_thread_observation"
    if work_type == "send_message":
        if send_mode == "stage":
            return "paste_payload_text_and_verify_staged_text"
        return "paste_verify_send_then_record_action_result"
    if work_type == "handoff":
        return "user_takeover_required"
    if work_type in {"wait", "scheduled_wait"}:
        return "wait_or_resume_later"
    return "inspect_current_work_item"


def _next_host_action_for_block_reason(reason: str | None) -> str | None:
    if reason == "target_profile_required":
        return "open_target_profile_and_ingest_memory"
    if reason == "target_binding_structural_evidence_required":
        return "provide_structural_target_binding_evidence"
    if reason == "target_binding_lost_current_thread":
        return "stop_do_not_send_recover_current_thread_binding"
    if reason == "staged_text_requires_visual_verification":
        return "visually_verify_staged_text_before_live_send"
    if reason == "outbound_message_requires_visual_verification":
        return "visually_verify_outbound_message_after_live_send_and_write_action_result"
    if isinstance(reason, str) and reason.startswith("runtime_live_send_not_supported:"):
        return "choose_supported_runtime_or_stage_only"
    return None


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _print_human(payload: dict[str, Any]) -> None:
    print(f"status: {payload.get('status')}")
    print(f"reason: {payload.get('stop_reason')}")
    print(f"work_dir: {payload.get('work_dir')}")
    if payload.get("current_work_item"):
        print(f"current_work_item: {payload['current_work_item'].get('work_item_type')}")


if __name__ == "__main__":
    raise SystemExit(main())
