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
from pathlib import Path
from typing import Any

from dating_boost.core.live_send_contract import validate_live_send_contract
from dating_boost.core.operator import OperatorRepository
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.safety import SafetyRepository


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(".local") / "dating-boost-host-loop"
DEFAULT_FIXTURE_NOW = "2026-05-26T00:00:00Z"
REPORT_FINAL_STATUSES = {"wait", "blocked", "handoff", "scheduled_wait", "stopped", "error"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

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
            "action_results_recorded": [],
            "next_host_action": "choose_supported_host_loop_app",
        }
        exit_code = 2
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


class HostLoopSupervisor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.fixture_host = args.fixture_host.resolve() if getattr(args, "fixture_host", None) else None
        self.data_dir = (getattr(args, "data_dir", None) or DEFAULT_DATA_DIR).resolve()
        self.work_dir = (getattr(args, "work_dir", None) or self.data_dir / "host-loop").resolve()
        self.steps: list[dict[str, Any]] = []
        self.staged_verifications: list[dict[str, Any]] = []
        self.action_results_recorded: list[dict[str, Any]] = []
        self.operator_session_active = False
        self.skill_package_path = self._resolve_skill_package_path(_explicit_adapter_package(args))
        self.app_profile = _load_app_profile(getattr(args, "app_id", "tinder"))

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
            if not resume or self._operator_session_status() != "active":
                start = self._run_cli_json(
                    "operator",
                    "session",
                    "start",
                    "--data-dir",
                    str(self.data_dir),
                    "--authorization",
                    str(self._authorization_path()),
                )
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

    def _preflight(self) -> None:
        if self.app_profile.get("host_loop_supported") is not True:
            raise HostLoopError(f"host loop is not supported for app_id={self.args.app_id}")
        send_modes = self.app_profile.get("host_loop_send_modes")
        if isinstance(send_modes, list) and send_modes and self.args.send_mode not in set(str(mode) for mode in send_modes):
            raise HostLoopError(f"send_mode {self.args.send_mode} is not supported for app_id={self.args.app_id}")
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

    def _handle_send_message(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        if self.args.send_mode == "live" and getattr(self.args, "managed_gui_send", False):
            return self._handle_managed_gui_send(work_item)
        staged_path = self._work_file(work_item, "staged_verification")
        if self.fixture_host is not None and not staged_path.exists():
            _write_json(staged_path, _staged_verification(work_item, result_status="succeeded"))
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
            return self._finish(
                "staged_waiting_user_confirmation",
                "stage mode does not record action result or click send",
                current=work_item,
                extra={"next_host_action": "review_staged_text_and_confirm_or_cancel"},
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

    def _handle_managed_gui_send(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        if self.args.app_id not in {"tinder", "wechat"}:
            return self._finish("blocked", f"managed_gui_send_not_supported_for_app:{self.args.app_id}", current=work_item)
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
            draft_text=str(work_item.get("payload_text") or ""),
            data_dir=self.data_dir,
        )
        if contract_reason is not None:
            return self._finish("blocked", contract_reason, current=work_item)
        draft_path.write_text(str(work_item.get("payload_text") or ""), encoding="utf-8")
        _write_json(action_request_path, action_request)
        try:
            harness_payload = self._run_cli_json(
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
                allow_error=True,
            )
        finally:
            if draft_path.exists():
                draft_path.unlink()
            if action_request_path.exists():
                action_request_path.unlink()

        self._append_timeline("managed_gui_send", work_item, {"harness": _redacted_managed_send_payload(harness_payload)})
        if harness_payload.get("status") != "ok":
            return self._finish(
                "blocked",
                str(harness_payload.get("reason") or "managed_gui_send_failed"),
                current=work_item,
                extra={"managed_gui_send": _redacted_managed_send_payload(harness_payload)},
            )
        harness_evidence = harness_payload.get("evidence") if isinstance(harness_payload.get("evidence"), dict) else {}
        if not harness_payload.get("post_action_observation_id"):
            return self._finish(
                "blocked",
                "post_action_observation_required",
                current=work_item,
                extra={"managed_gui_send": _redacted_managed_send_payload(harness_payload)},
            )
        required_evidence = _managed_gui_send_required_evidence(self.args.app_id)
        if any(harness_evidence.get(key) is not True for key in required_evidence):
            return self._finish(
                "blocked",
                "managed_gui_send_verification_incomplete",
                current=work_item,
                extra={"managed_gui_send": _redacted_managed_send_payload(harness_payload)},
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
            "post_action_observation_id": harness_payload.get("post_action_observation_id"),
            "result_status": "succeeded",
            "evidence": {
                "managed_gui_send": True,
                **harness_evidence,
            },
        }
        result_path = self._work_file(work_item, "action_result")
        _write_json(result_path, result_payload)
        recorded = self._run_cli_json("operator", "record-action-result", "--data-dir", str(self.data_dir), "--input", str(result_path))
        self.action_results_recorded.append(recorded)
        self._append_timeline("action_result", work_item, {"path": str(result_path), "recorded": recorded})
        self._clear_host_work_item(work_item, consume=True)
        return None

    def _live_send_contract_block_reason(self, work_item: dict[str, Any], authorization: dict[str, Any]) -> str | None:
        return validate_live_send_contract(
            authorization,
            self._live_send_action_request(work_item),
            app_id=self.args.app_id,
            draft_text=str(work_item.get("payload_text") or ""),
            data_dir=self.data_dir,
        )

    def _live_send_action_request(self, work_item: dict[str, Any]) -> dict[str, Any]:
        action_request = dict(work_item)
        action_request.setdefault("action", "send_message")
        action_request.setdefault("app_id", self.args.app_id)
        action_request["target_binding"] = _target_binding_for_work_item(work_item, self._pending_scan_batch_or_none())
        return action_request

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
            "action_results_recorded": list(self.action_results_recorded),
            "next_host_action": _next_host_action(status, current, self.args.send_mode),
        }
        if current is not None:
            payload["current_work_item"] = current
        if extra:
            payload.update(extra)
        if status in REPORT_FINAL_STATUSES and self.operator_session_active:
            try:
                operator_stop = self._run_cli_json("operator", "stop", "--data-dir", str(self.data_dir))
                self.operator_session_active = False
                payload["operator_stop"] = operator_stop
                payload["machine_report_path"] = _data_dir_path(self.data_dir, operator_stop.get("machine_report_path"))
                payload["human_report_path"] = _data_dir_path(self.data_dir, operator_stop.get("human_report_path"))
                payload["report_summary"] = operator_stop.get("summary")
            except (HostLoopError, HostLoopCommandError, RuntimeError) as exc:
                payload["report_error"] = str(exc)
        return payload

    def _write_current_work_item(self, work_item: dict[str, Any]) -> None:
        _write_json(self.work_dir / "current_work_item.json", work_item)

    def _clear_host_work_item(self, work_item: dict[str, Any], *, consume: bool = False) -> None:
        for kind in ("message_list_observation", "thread_observation", "staged_verification", "action_result"):
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
        if work_type == "open_thread":
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

    def _run_cli_json(self, *args: str, allow_error: bool = False) -> dict[str, Any]:
        env = dict(os.environ)
        if self.fixture_host is not None:
            env.setdefault("DATING_BOOST_NOW", DEFAULT_FIXTURE_NOW)
        result = subprocess.run(
            [sys.executable, "-m", "dating_boost.cli", *args],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
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
        "scan_cursor": None,
        "scan_budget": 5,
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
                    "unread_cue": "present|absent",
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
            "source_type": "manual_host_loop",
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
    payload_text = str(work_item.get("payload_text") or "")
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
    if payload.get("staged_text") != work_item.get("payload_text"):
        return {"status": "blocked", "reason": "staged text does not match payload_text"}
    return {
        "status": "ok",
        "action_request_id": payload.get("action_request_id"),
        "payload_hash": payload.get("expected_payload_hash"),
    }


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
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _managed_gui_send_required_evidence(app_id: str) -> tuple[str, ...]:
    common = (
        "staged_text_verified",
        "input_cleared_after_send",
        "post_action_screen_captured",
        "outbound_message_verified",
    )
    if app_id == "wechat":
        return (
            "staged_text_verified",
            "input_cleared_after_send",
            "post_action_screen_captured",
            "outbound_message_verified",
        )
    return common


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

    unique_required: list[str] = []
    for item in required:
        text = str(item).strip()
        if text and text not in unique_required:
            unique_required.append(text)
    binding["required_visible_text"] = unique_required
    return binding


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


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return os.environ.get("DATING_BOOST_NOW") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_app_profile(app_id: str) -> dict[str, Any]:
    path = ROOT / "app_profiles" / f"{_safe_name(app_id)}.json"
    if not path.exists():
        raise HostLoopError(f"unsupported app profile: {app_id}")
    profile = _read_json(path)
    profile["_path"] = str(path)
    return profile


def _host_instructions(profile: dict[str, Any], work_item_type: str) -> dict[str, Any]:
    key = {
        "scan_message_list": "message_list_observation",
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


def _next_host_action(status: str, work_item: dict[str, Any] | None, send_mode: str) -> str:
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
