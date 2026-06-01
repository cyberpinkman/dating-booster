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


ROOT = Path(__file__).resolve().parents[1]
SKILL_PACKAGE_PATH = ROOT / "skills" / "dating-booster-codex" / "skill-package.json"
DEFAULT_DATA_DIR = ROOT / ".local" / "dating-boost-host-loop"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drive a host-executed Tinder operator loop.")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--goal", type=Path)
    parser.add_argument("--availability", type=Path)
    parser.add_argument("--app-id", default="tinder")
    parser.add_argument("--send-mode", choices=["stage", "live"], default="stage")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fixture-host", type=Path)
    parser.add_argument("--wait-timeout", type=float, default=None)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    supervisor = HostLoopSupervisor(args)
    payload, exit_code = supervisor.run()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return exit_code


class HostLoopSupervisor:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.fixture_host = args.fixture_host.resolve() if args.fixture_host else None
        self.data_dir = (args.data_dir or DEFAULT_DATA_DIR).resolve()
        self.work_dir = (args.work_dir or self.data_dir / "host-loop").resolve()
        self.steps: list[dict[str, Any]] = []
        self.staged_verifications: list[dict[str, Any]] = []
        self.action_results_recorded: list[dict[str, Any]] = []

    def run(self) -> tuple[dict[str, Any], int]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._bootstrap_fixture_profile()
            self._preflight()
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

            for _ in range(max(self.args.max_steps, 1)):
                next_payload = self._run_cli_json("operator", "next", "--data-dir", str(self.data_dir))
                work_item = next_payload.get("work_item")
                if not isinstance(work_item, dict):
                    return self._finish("error", "operator_next_returned_no_work_item", extra={"next": next_payload}), 2
                work_type = str(work_item.get("work_item_type") or "")
                self._write_current_work_item(work_item)
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
        except HostLoopError as exc:
            return self._finish("blocked", str(exc)), 0
        except RuntimeError as exc:
            return self._finish("error", str(exc)), 2

    def _preflight(self) -> None:
        capabilities = self._run_cli_json("capabilities", "--json", "--data-dir", str(self.data_dir))
        agent_caps = capabilities.get("agent_native_capabilities", {})
        if not agent_caps.get("host_loop_supervisor"):
            raise HostLoopError("capabilities missing host_loop_supervisor")
        if not agent_caps.get("tinder_host_loop"):
            raise HostLoopError("capabilities missing tinder_host_loop")
        if agent_caps.get("live_gui_harness"):
            raise HostLoopError("this supervisor expects live_gui_harness=false")

        doctor = self._run_cli_json(
            "skill",
            "doctor",
            "--package",
            str(SKILL_PACKAGE_PATH),
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
        path = self.work_dir / "message_list_observation.json"
        if self.fixture_host is not None and not path.exists():
            fixture = self.fixture_host / "message_list_observation.json"
            if fixture.exists():
                shutil.copyfile(fixture, path)
        if not path.exists():
            _write_json(_template_path(path), _message_list_template(work_item, self.args.app_id))
            waiting = self._waiting("message_list_observation", path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting
        ingest = self._run_cli_json("operator", "ingest-observation", "--data-dir", str(self.data_dir), "--input", str(path))
        self._consume(path)
        if ingest.get("status") != "ok":
            return self._finish("blocked", str(ingest.get("reason") or "message_list_ingest_failed"), current=work_item)
        return None

    def _handle_open_thread(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        candidate_key = _required_string(work_item, "candidate_key")
        path = self.work_dir / f"thread_observation_{_safe_name(candidate_key)}.json"
        if self.fixture_host is not None and not path.exists():
            fixture = self.fixture_host / "threads" / f"{candidate_key}.json"
            if fixture.exists():
                shutil.copyfile(fixture, path)
        if not path.exists():
            _write_json(_template_path(path), _thread_template(work_item, self.args.app_id))
            waiting = self._waiting("thread_observation", path, work_item)
            if waiting.get("status") != "host_input_ready":
                return waiting
        ingest = self._run_cli_json("operator", "ingest-observation", "--data-dir", str(self.data_dir), "--input", str(path))
        self._consume(path)
        if ingest.get("status") != "ok":
            return self._finish("blocked", str(ingest.get("reason") or "thread_ingest_failed"), current=work_item)
        return None

    def _handle_send_message(self, work_item: dict[str, Any]) -> dict[str, Any] | None:
        staged_path = self.work_dir / "staged_verification.json"
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
        if verification["status"] != "ok":
            return self._finish("blocked", verification["reason"], current=work_item)
        if self.args.send_mode == "stage":
            return self._finish(
                "staged_waiting_user_confirmation",
                "stage mode does not record action result or click send",
                current=work_item,
            )

        result_path = self.work_dir / "action_result.json"
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
        self._consume(result_path)
        return None

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

    def _fixture_file(self, filename: str) -> Path | None:
        if self.fixture_host is None:
            return None
        path = self.fixture_host / filename
        return path if path.exists() else None

    def _waiting(self, expected: str, path: Path, work_item: dict[str, Any]) -> dict[str, Any]:
        if self.args.once or self.args.wait_timeout == 0:
            return self._finish(
                "waiting_for_host",
                f"waiting_for_{expected}",
                current=work_item,
                extra={"expected_input": str(path)},
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
            extra={"expected_input": str(path)},
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
            "stop_reason": reason,
            "send_mode": self.args.send_mode,
            "app_id": self.args.app_id,
            "data_dir": str(self.data_dir),
            "work_dir": str(self.work_dir),
            "steps": list(self.steps),
            "staged_verifications": list(self.staged_verifications),
            "action_results_recorded": list(self.action_results_recorded),
        }
        if current is not None:
            payload["current_work_item"] = current
        if extra:
            payload.update(extra)
        return payload

    def _write_current_work_item(self, work_item: dict[str, Any]) -> None:
        _write_json(self.work_dir / "current_work_item.json", work_item)

    def _consume(self, path: Path) -> None:
        consumed_dir = self.work_dir / "consumed"
        consumed_dir.mkdir(parents=True, exist_ok=True)
        target = consumed_dir / f"{len(list(consumed_dir.iterdir())) + 1:04d}_{path.name}"
        path.replace(target)

    def _run_cli_json(self, *args: str) -> dict[str, Any]:
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
        if result.returncode != 0:
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


def _message_list_template(work_item: dict[str, Any], app_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "observation_type": "message_list",
        "session_id": _session_hint(work_item),
        "app_id": app_id,
        "captured_at": "TODO_ISO_TIMESTAMP",
        "scan_cursor": None,
        "scan_budget": 5,
        "provenance": {
            "author": "host_agent",
            "evidence": "Tinder message list observed through iPhone Mirroring.",
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
                    "match_identity_hints": {
                        "visible_name": "TODO",
                        "profile_cues": [],
                        "conversation_fingerprint": "TODO",
                    },
                    "evidence": "Visible Tinder row.",
                }
            ]
        },
    }


def _thread_template(work_item: dict[str, Any], app_id: str) -> dict[str, Any]:
    candidate_key = str(work_item.get("candidate_key") or "TODO")
    return {
        "schema_version": 1,
        "observation_type": "thread",
        "candidate_key": candidate_key,
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
                "evidence": "Visible Tinder chat header and messages.",
            },
            "profile_observation": {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
            },
            "conversation_observation": {
                "visible_messages": [],
                "latest_inbound_messages": [],
                "input_state": "empty",
                "thread_cues": [],
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {
                "evidence": "Host-agent screen read from iPhone Mirroring.",
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
