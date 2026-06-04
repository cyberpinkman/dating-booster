import json
import hashlib
import os
import subprocess
import sys
import tempfile
import argparse
import unittest
from unittest.mock import patch
from pathlib import Path

from dating_boost.cli import main
from dating_boost.host_loop import HostLoopCommandError, HostLoopSupervisor, _target_binding_for_work_item


FIXTURE_DIR = Path("tests/fixtures/host_loop/tinder")


class OperatorHostLoopTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._env["DATING_BOOST_NOW"] = "2026-05-26T00:00:00Z"

    def test_capabilities_expose_tinder_host_loop_without_live_gui_harness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "capabilities",
                "--json",
                "--data-dir",
                str(Path(temp_dir) / "data"),
            ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["agent_native_capabilities"]["host_loop_supervisor"])
            self.assertTrue(payload["agent_native_capabilities"]["tinder_host_loop"])
            self.assertEqual(payload["agent_native_capabilities"]["host_loop_command"], "dating-boost-host-loop")
            self.assertFalse(payload["agent_native_capabilities"]["live_gui_harness"])

    def test_wechat_host_loop_init_writes_wechat_authorization_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "init",
                "--app-id",
                "wechat",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            auth_template = json.loads((data_dir / "automation" / "auth.template.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(auth_template["app_id"], "wechat")
            self.assertTrue((work_dir / "current_work_item.json").exists())

    def test_contract_only_app_blocks_host_loop_doctor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/operator_host_loop.py",
                    "doctor",
                    "--app-id",
                    "bumble",
                    "--data-dir",
                    str(Path(temp_dir) / "data"),
                    "--work-dir",
                    str(Path(temp_dir) / "work"),
                    "--json",
                ],
                cwd=Path.cwd(),
                env=self._env,
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["next_host_action"], "choose_supported_host_loop_app")
            self.assertEqual(payload["details"]["app_profile"]["support_level"], "contract_only")

    def test_wechat_waiting_template_uses_wechat_desktop_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "wechat_auth.json"
            auth = json.loads((FIXTURE_DIR / "auth.json").read_text(encoding="utf-8"))
            auth["app_id"] = "wechat"
            self._write_json(auth_path, auth)
            self._bootstrap_data_dir(data_dir)

            payload = self._run_script(
                "run",
                "--app-id",
                "wechat",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--goal",
                str(FIXTURE_DIR / "goal.json"),
                "--availability",
                str(FIXTURE_DIR / "availability.json"),
                "--work-dir",
                str(work_dir),
                "--once",
                "--json",
            )
            work_item_id = payload["current_work_item"]["work_item_id"]
            template = json.loads(
                (work_dir / f"message_list_observation.{work_item_id}.template.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(payload["status"], "waiting_for_host")
            self.assertIn("send", payload["app_profile"]["native_blocked_actions"])
            self.assertEqual(template["app_id"], "wechat")
            self.assertIn("WeChat chat list", template["provenance"]["evidence"])
            self.assertNotIn("Tinder", json.dumps(template, ensure_ascii=False))

    def test_wechat_target_binding_falls_back_to_message_list_identity_hints(self):
        binding = _target_binding_for_work_item(
            {"match_id": "match_wechat", "candidate_key": "wechat_ada"},
            {
                "schema_version": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "wechat_ada",
                            "visible_name": "Ada",
                            "match_identity_hints": {
                                "visible_name": "Ada",
                                "conversation_fingerprint": "Ada dinner thread",
                            },
                        }
                    ]
                },
                "thread_observations": [
                    {
                        "candidate_key": "wechat_ada",
                        "observation": {"match_identity_hints": {}},
                    }
                ],
            },
        )

        self.assertEqual(binding["target_match_id"], "match_wechat")
        self.assertEqual(binding["candidate_key"], "wechat_ada")
        self.assertEqual(binding["visible_name"], "Ada")
        self.assertEqual(binding["required_visible_text"], ["Ada"])
        self.assertEqual(binding["conversation_fingerprint"], "Ada dinner thread")

    def test_fixture_host_loop_stage_mode_stages_message_without_recording_send_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
            self.assertEqual(payload["send_mode"], "stage")
            self.assertTrue((work_dir / "current_work_item.json").exists())
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertTrue((work_dir / f"staged_verification.{work_item_id}.json").exists())
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())
            self.assertIn("stage mode does not record action result", payload["stop_reason"])

    def test_confirm_staged_cancel_clears_pending_send_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item_id = staged_payload["current_work_item"]["work_item_id"]

            cancel_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--cancel",
                "--json",
            )
            status_payload = self._run_script(
                "status",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            self.assertEqual(cancel_payload["status"], "staged_cancelled")
            self.assertEqual(status_payload["status"], "idle")
            self.assertFalse((work_dir / "current_work_item.json").exists())
            self.assertFalse((data_dir / "operator" / "current_work_item.json").exists())
            self.assertFalse((work_dir / f"staged_verification.{work_item_id}.json").exists())

    def test_confirm_staged_action_result_is_idempotent_and_clears_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item = staged_payload["current_work_item"]
            action_result_path = Path(temp_dir) / "action_result.json"
            self._write_json(action_result_path, _action_result_for_work_item(work_item))

            first_confirm = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--action-result",
                str(action_result_path),
                "--json",
            )
            status_payload = self._run_script(
                "status",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            second_confirm = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--action-result",
                str(action_result_path),
                "--json",
            )
            audit_events = [
                json.loads(line)
                for line in (data_dir / "audit" / "action_results.jsonl").read_text(encoding="utf-8").splitlines()
            ]

            self.assertEqual(first_confirm["status"], "confirmed")
            self.assertEqual(status_payload["status"], "idle")
            self.assertEqual(second_confirm["status"], "blocked")
            self.assertEqual(second_confirm["stop_reason"], "no_staged_send_work_item")
            self.assertEqual(len(audit_events), 1)
            self.assertFalse((work_dir / "current_work_item.json").exists())
            self.assertFalse((data_dir / "operator" / "current_work_item.json").exists())

    def test_confirm_staged_requires_valid_staged_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            staged_payload = self._run_script(
                "run",
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "stage",
                "--max-steps",
                "8",
                "--json",
            )
            work_item = staged_payload["current_work_item"]
            staged_path = work_dir / f"staged_verification.{work_item['work_item_id']}.json"
            staged_path.unlink()

            missing_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            bad_staged = {
                "schema_version": 1,
                "verification_type": "staged_text",
                "action_request_id": work_item["action_request_id"],
                "match_id": work_item["match_id"],
                "candidate_key": work_item["candidate_key"],
                "expected_payload_hash": work_item["payload_hash"],
                "expected_payload_text": work_item["payload_text"],
                "result_status": "failed",
                "staged_text": work_item["payload_text"],
            }
            self._write_json(staged_path, bad_staged)
            failed_payload = self._run_script(
                "confirm-staged",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )

            self.assertEqual(missing_payload["status"], "blocked")
            self.assertEqual(missing_payload["stop_reason"], "staged_verification_required_before_confirmation")
            self.assertEqual(failed_payload["status"], "blocked")
            self.assertEqual(failed_payload["stop_reason"], "staged text was not verified as succeeded")
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_fixture_host_loop_live_mode_requires_staged_verification_before_recording_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertIn(payload["status"], {"completed", "waiting", "wait"})
            audit_path = data_dir / "audit" / "action_results.jsonl"
            self.assertTrue(audit_path.exists())
            events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["result_status"], "succeeded")
            self.assertTrue(payload["staged_verifications"])
            self.assertTrue(payload["action_results_recorded"])
            self.assertFalse(any(path.name.startswith("staged_verification.") for path in work_dir.glob("*.json")))
            self.assertTrue(any("staged_verification" in path.name for path in (work_dir / "consumed").iterdir()))
            self.assertIn("machine_report_path", payload)
            self.assertTrue(Path(payload["machine_report_path"]).exists())
            self.assertIn("human_report_path", payload)
            self.assertTrue(Path(payload["human_report_path"]).exists())

    def test_live_mode_blocks_when_safety_is_paused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._run_cli(["safety", "pause", "--data-dir", str(data_dir), "--reason", "manual-stop", "--json"])

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["stop_reason"], "safety_paused")
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_live_mode_requires_explicit_live_send_authorization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            auth_path = Path(temp_dir) / "auth_without_live.json"
            auth = json.loads((FIXTURE_DIR / "auth.json").read_text(encoding="utf-8"))
            auth.pop("live_send", None)
            self._write_json(auth_path, auth)

            payload = self._run_script(
                "--fixture-host",
                str(FIXTURE_DIR),
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
                "--work-dir",
                str(work_dir),
                "--send-mode",
                "live",
                "--max-steps",
                "8",
                "--json",
            )

            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["stop_reason"], "live_send_authorization_required")
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())

    def test_managed_wechat_live_send_runs_harness_with_text_file_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
                "expires_at": "2026-06-05T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = {
                "schema_version": 1,
                "work_item_id": "work_wechat_send",
                "work_item_type": "send_message",
                "action_request_id": "act_wechat_send",
                "match_id": "match_wechat",
                "candidate_key": "wechat_ada",
                "payload_text": payload_text,
                "payload_hash": payload_hash,
                "precondition_hash": "pre_hash",
                "autonomous_audit_binding": "audit_binding",
                "pre_action_observation_id": "obs_before",
                "policy": {"allowed": True},
                "requires_post_action_verification": True,
                "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
            }
            captured_commands: list[tuple[str, ...]] = []
            recorded_result: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False) -> dict[str, object]:
                captured_commands.append(args)
                if args[:3] == ("harness", "wechat", "send-message"):
                    self.assertIn("--text-file", args)
                    self.assertIn("--action-request", args)
                    self.assertNotIn(payload_text, args)
                    text_path = Path(args[args.index("--text-file") + 1])
                    action_path = Path(args[args.index("--action-request") + 1])
                    self.assertEqual(text_path.read_text(encoding="utf-8"), payload_text)
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    self.assertEqual(action_request["payload_hash"], payload_hash)
                    self.assertEqual(action_request["target_binding"]["required_visible_text"], ["Ada"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "draft_fingerprint": payload_hash,
                        "draft_character_count": len(payload_text),
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    result_path = Path(args[args.index("--input") + 1])
                    recorded_result.update(json.loads(result_path.read_text(encoding="utf-8")))
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(recorded_result["result_status"], "succeeded")
        self.assertEqual(recorded_result["post_action_observation_id"], "gui_post_send_1234")
        self.assertTrue(recorded_result["evidence"]["managed_gui_send"])
        self.assertTrue(supervisor.staged_verifications)
        self.assertTrue(supervisor.action_results_recorded)
        self.assertFalse(any(path.name.startswith("managed_payload.") for path in work_dir.glob("*.txt")))
        self.assertFalse(any(path.name.startswith("managed_action_request.") for path in work_dir.glob("*.json")))
        self.assertTrue(any(args[:3] == ("harness", "wechat", "send-message") for args in captured_commands))

    def test_managed_wechat_live_send_derives_target_binding_from_pending_thread_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
                "expires_at": "2026-06-05T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            (data_dir / "operator").mkdir(parents=True, exist_ok=True)
            self._write_json(data_dir / "operator" / "pending_scan_batch.json", {
                "schema_version": 1,
                "session_id": "session_wechat",
                "app_id": "wechat",
                "thread_observations": [
                    {
                        "candidate_key": "wechat_ada",
                        "observation": {
                            "match_identity_hints": {
                                "visible_name": "Ada",
                                "conversation_fingerprint": "Ada latest dinner thread",
                            }
                        },
                    }
                ],
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)
            work_item.pop("target_binding")
            observed_binding: dict[str, object] = {}

            def fake_run_cli_json(*args: str, allow_error: bool = False) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    action_path = Path(args[args.index("--action-request") + 1])
                    action_request = json.loads(action_path.read_text(encoding="utf-8"))
                    observed_binding.update(action_request["target_binding"])
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                            "outbound_message_verified": True,
                        },
                    }
                if args[:2] == ("operator", "record-action-result"):
                    return {"schema_version": 1, "status": "ok", "recorded": True}
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertIsNone(result)
        self.assertEqual(observed_binding["target_match_id"], "match_wechat")
        self.assertEqual(observed_binding["candidate_key"], "wechat_ada")
        self.assertEqual(observed_binding["visible_name"], "Ada")
        self.assertEqual(observed_binding["required_visible_text"], ["Ada"])
        self.assertEqual(observed_binding["conversation_fingerprint"], "Ada latest dinner thread")

    def test_managed_wechat_live_send_blocks_when_outbound_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            work_dir = root / "work"
            auth_path = root / "wechat_auth.json"
            payload_text = "今晚可以聊十分钟吗？"
            payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
            self._write_json(auth_path, {
                "schema_version": 1,
                "authorization_id": "auth_wechat_live",
                "scope": "send_chat_messages",
                "app_id": "wechat",
                "expires_at": "2026-06-05T00:00:00Z",
                "allowed_actions": ["send_message"],
                "autonomous_send": True,
                "live_send": True,
                "requires_post_action_verification": True,
                "revoked_at": None,
            })
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=data_dir,
                    authorization=auth_path,
                    goal=None,
                    availability=None,
                    app_id="wechat",
                    send_mode="live",
                    managed_gui_send=True,
                    work_dir=work_dir,
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )
            work_dir.mkdir(parents=True, exist_ok=True)
            work_item = _wechat_managed_work_item(payload_text, payload_hash)

            def fake_run_cli_json(*args: str, allow_error: bool = False) -> dict[str, object]:
                if args[:3] == ("harness", "wechat", "send-message"):
                    return {
                        "schema_version": 1,
                        "status": "ok",
                        "app_id": "wechat",
                        "action": "send_message",
                        "post_action_observation_id": "gui_post_send_1234",
                        "evidence": {
                            "staged_text_verified": True,
                            "input_cleared_after_send": True,
                            "post_action_screen_captured": True,
                        },
                    }
                raise AssertionError(args)

            with patch.object(supervisor, "_run_cli_json", fake_run_cli_json):
                result = supervisor._handle_managed_gui_send(work_item)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["stop_reason"], "managed_gui_send_verification_incomplete")
        self.assertFalse(supervisor.action_results_recorded)

    def test_once_mode_writes_template_and_waits_for_host_without_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._bootstrap_data_dir(data_dir)

            payload = self._run_script(
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth.json"),
                "--goal",
                str(FIXTURE_DIR / "goal.json"),
                "--availability",
                str(FIXTURE_DIR / "availability.json"),
                "--work-dir",
                str(work_dir),
                "--once",
                "--json",
            )

            self.assertEqual(payload["status"], "waiting_for_host")
            self.assertEqual(payload["current_work_item"]["work_item_type"], "scan_message_list")
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertEqual(
                Path(payload["expected_input"]).resolve(),
                (work_dir / f"message_list_observation.{work_item_id}.json").resolve(),
            )
            self.assertTrue((work_dir / f"message_list_observation.{work_item_id}.template.json").exists())

    def test_supervisor_does_not_inject_fixed_clock_without_fixture_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=Path(temp_dir) / "data",
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    work_dir=Path(temp_dir) / "work",
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )

            def fake_run(command, cwd, check, capture_output, text, env):
                self.assertNotIn("DATING_BOOST_NOW", env)
                return subprocess.CompletedProcess(command, 0, stdout='{"schema_version": 1, "status": "ok"}', stderr="")

            with patch.dict(os.environ, {}, clear=True), patch("dating_boost.host_loop.subprocess.run", fake_run):
                payload = supervisor._run_cli_json("capabilities", "--json")

        self.assertEqual(payload["status"], "ok")

    def test_supervisor_preserves_structured_cli_error_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            supervisor = HostLoopSupervisor(
                argparse.Namespace(
                    data_dir=Path(temp_dir) / "data",
                    authorization=None,
                    goal=None,
                    availability=None,
                    app_id="tinder",
                    send_mode="stage",
                    work_dir=Path(temp_dir) / "work",
                    max_steps=1,
                    once=False,
                    json=True,
                    fixture_host=None,
                    wait_timeout=None,
                    poll_interval=1.0,
                    skill_package=None,
                )
            )

            def fake_run(command, cwd, check, capture_output, text, env):
                return subprocess.CompletedProcess(
                    command,
                    2,
                    stdout='{"schema_version": 1, "status": "error", "reason": "authorization_expired"}',
                    stderr="",
                )

            with patch("dating_boost.host_loop.subprocess.run", fake_run):
                with self.assertRaises(HostLoopCommandError) as raised:
                    supervisor._run_cli_json("operator", "session", "start")

        self.assertEqual(raised.exception.payload["reason"], "authorization_expired")

    def _bootstrap_data_dir(self, data_dir: Path) -> None:
        for argv in (
            [
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_profile.json"),
            ],
            [
                "user",
                "ingest-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_dating_profile.json"),
            ],
            [
                "user",
                "ingest-interview",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "user_self_interview.json"),
            ],
        ):
            exit_code, _payload = self._run_cli(argv)
            self.assertEqual(exit_code, 0)

    def _run_cli(self, argv):
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())

    def _run_script(self, *args: str) -> dict:
        result = subprocess.run(
            [sys.executable, "scripts/operator_host_loop.py", *args],
            cwd=Path.cwd(),
            env=self._env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def _write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _action_result_for_work_item(work_item: dict) -> dict:
    return {
        "action_request_id": work_item["action_request_id"],
        "action": "send_message",
        "target_match_id": work_item["match_id"],
        "payload_hash": work_item["payload_hash"],
        "precondition_hash": work_item["precondition_hash"],
        "autonomous_audit_binding": work_item["autonomous_audit_binding"],
        "pre_action_observation_id": work_item.get("pre_action_observation_id"),
        "post_action_observation_id": f"{work_item.get('pre_action_observation_id')}_sent",
        "result_status": "succeeded",
        "evidence": {
            "post_send_visible_text": work_item["payload_text"],
            "staged_text_verified": True,
        },
    }


def _wechat_managed_work_item(payload_text: str, payload_hash: str) -> dict:
    return {
        "schema_version": 1,
        "work_item_id": "work_wechat_send",
        "work_item_type": "send_message",
        "action_request_id": "act_wechat_send",
        "match_id": "match_wechat",
        "candidate_key": "wechat_ada",
        "payload_text": payload_text,
        "payload_hash": payload_hash,
        "precondition_hash": "pre_hash",
        "autonomous_audit_binding": "audit_binding",
        "pre_action_observation_id": "obs_before",
        "requires_post_action_verification": True,
        "policy": {"allowed": True},
        "target_binding": {"required_visible_text": ["Ada"], "target_match_id": "match_wechat"},
    }


if __name__ == "__main__":
    unittest.main()
