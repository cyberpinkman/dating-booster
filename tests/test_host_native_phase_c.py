import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


FIXTURE_DIR = Path("tests/fixtures/host_loop/tinder")


class HostNativePhaseCTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._env["DATING_BOOST_NOW"] = "2026-05-26T00:00:00Z"

    def test_host_loop_doctor_and_init_report_structured_readiness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            init_payload = self._run_host_loop(
                "init",
                "--data-dir",
                str(data_dir),
                "--work-dir",
                str(work_dir),
                "--json",
            )
            self.assertEqual(init_payload["status"], "ok")
            self.assertTrue((data_dir / "automation" / "auth.template.json").exists())
            self.assertTrue((work_dir / "current_work_item.json").exists())

            doctor_payload = self._run_host_loop("doctor", "--data-dir", str(data_dir), "--work-dir", str(work_dir), "--json")
            self.assertEqual(doctor_payload["status"], "needs_user_profile")
            self.assertIn("user_profile", doctor_payload["missing"])
            self.assertEqual(doctor_payload["next_host_action"], "complete_user_profile_and_interview")

    def test_host_loop_run_uses_work_item_scoped_files_and_next_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"

            payload = self._run_host_loop(
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

            self.assertEqual(payload["status"], "staged_waiting_user_confirmation")
            self.assertEqual(payload["next_host_action"], "review_staged_text_and_confirm_or_cancel")
            work_item_id = payload["current_work_item"]["work_item_id"]
            self.assertTrue((work_dir / f"staged_verification.{work_item_id}.json").exists())
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())
            timeline_path = data_dir / "host_loop" / "timeline.jsonl"
            self.assertTrue(timeline_path.exists())
            events = [json.loads(line) for line in timeline_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(event["event_type"] == "staged_verification" for event in events))

            status_payload = self._run_host_loop("status", "--data-dir", str(data_dir), "--work-dir", str(work_dir), "--json")
            self.assertEqual(status_payload["status"], "waiting_for_confirmation")
            self.assertEqual(status_payload["work_item"]["work_item_id"], work_item_id)

    def test_observation_authoring_rejects_missing_boundary_and_old_inbound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            good_thread = json.loads((FIXTURE_DIR / "threads" / "ada_1_preview_ada.json").read_text(encoding="utf-8"))
            good_thread["identity_confidence"] = "high"
            good_thread["identity_evidence"] = "Header says Ada and profile cues match."
            good_thread["turn_boundary_evidence"] = {
                "latest_user_outbound_text": "你猜猜会有什么奖励",
                "latest_user_outbound_index": 0,
                "latest_inbound_after_user": ["你定"],
            }
            good_thread["screenshot_ref"] = ""
            good_thread["observation"]["conversation_observation"]["latest_inbound_messages"][0][
                "is_after_latest_outbound"
            ] = True
            good_path = Path(temp_dir) / "good_thread.json"
            good_path.write_text(json.dumps(good_thread, ensure_ascii=False), encoding="utf-8")

            good_exit, good_payload = self._run_cli([
                "observation",
                "validate",
                "--input",
                str(good_path),
                "--json",
            ])
            self.assertEqual(good_exit, 0)
            self.assertEqual(good_payload["status"], "ok")

            bad_thread = json.loads(json.dumps(good_thread))
            bad_thread.pop("turn_boundary_evidence")
            bad_thread["observation"]["conversation_observation"]["latest_inbound_messages"][0][
                "is_after_latest_outbound"
            ] = False
            bad_path = Path(temp_dir) / "bad_thread.json"
            bad_path.write_text(json.dumps(bad_thread, ensure_ascii=False), encoding="utf-8")

            bad_exit, bad_payload = self._run_cli([
                "observation",
                "validate",
                "--input",
                str(bad_path),
                "--json",
            ])
            self.assertEqual(bad_exit, 2)
            self.assertTrue(any("turn_boundary_evidence" in error for error in bad_payload["errors"]))
            self.assertTrue(any("latest_inbound_messages" in error for error in bad_payload["errors"]))

            empty_boundary = json.loads(json.dumps(good_thread))
            empty_boundary["turn_boundary_evidence"] = {}
            empty_boundary_path = Path(temp_dir) / "empty_boundary_thread.json"
            empty_boundary_path.write_text(json.dumps(empty_boundary, ensure_ascii=False), encoding="utf-8")

            empty_exit, empty_payload = self._run_cli([
                "observation",
                "validate",
                "--input",
                str(empty_boundary_path),
                "--json",
            ])
            self.assertEqual(empty_exit, 2)
            self.assertTrue(any("turn_boundary_evidence" in error for error in empty_payload["errors"]))

    def test_conversation_eval_and_replay_cli(self):
        eval_exit, eval_payload = self._run_cli(["eval", "run", "--suite", "conversation", "--json"])
        self.assertEqual(eval_exit, 0)
        self.assertEqual(eval_payload["status"], "ok")
        self.assertTrue(eval_payload["passed"])
        self.assertGreaterEqual(eval_payload["case_count"], 5)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            work_dir = Path(temp_dir) / "work"
            self._run_host_loop(
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
            replay_exit, replay_payload = self._run_cli([
                "replay",
                "latest",
                "--data-dir",
                str(data_dir),
                "--format",
                "json",
            ])
            self.assertEqual(replay_exit, 0)
            self.assertEqual(replay_payload["status"], "ok")
            self.assertTrue(replay_payload["timeline"])

    def test_multi_app_profiles_are_available_to_capabilities(self):
        exit_code, payload = self._run_cli(["capabilities", "--json"])

        self.assertEqual(exit_code, 0)
        caps = payload["agent_native_capabilities"]
        self.assertTrue(caps["multi_app_profiles"])
        self.assertEqual(set(caps["supported_app_profiles"]), {"tinder", "wechat", "bumble", "tashuo"})
        for app_id in caps["supported_app_profiles"]:
            self.assertTrue((Path("app_profiles") / f"{app_id}.json").exists())

    def _run_cli(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())

    def _run_host_loop(self, *args: str) -> dict:
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


if __name__ == "__main__":
    unittest.main()
