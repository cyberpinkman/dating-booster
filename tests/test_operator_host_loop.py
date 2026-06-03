import json
import os
import subprocess
import sys
import tempfile
import argparse
import unittest
from unittest.mock import patch
from pathlib import Path

from dating_boost.cli import main
from dating_boost.host_loop import HostLoopCommandError, HostLoopSupervisor


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


if __name__ == "__main__":
    unittest.main()
