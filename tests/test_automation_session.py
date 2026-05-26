import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


FIXTURE_DIR = Path("tests/fixtures/automation")


class AutomationSessionTests(unittest.TestCase):
    def test_capabilities_expose_automation_session_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload, _ = self._run([
                "capabilities",
                "--json",
                "--data-dir",
                str(Path(temp_dir) / "data"),
            ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["schema_versions"]["scan_batch"], 1)
            self.assertEqual(payload["schema_versions"]["automation_state"], 1)
            self.assertEqual(payload["schema_versions"]["appointment_ledger"], 1)
            self.assertEqual(payload["schema_versions"]["progress_report"], 1)
            self.assertIn("automation session start", payload["supported_commands"])
            self.assertIn("automation session step", payload["supported_commands"])
            self.assertIn("automation report latest", payload["supported_commands"])
            self.assertTrue(payload["agent_native_capabilities"]["automation_session"])
            self.assertTrue(payload["agent_native_capabilities"]["appointment_ledger"])

    def test_session_step_processes_scan_batch_and_prevents_duplicate_sends(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "goal",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "goal_meet.json"),
            ])
            self._run([
                "automation",
                "availability",
                "set",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "availability_weekend.json"),
            ])
            start_exit, start_payload, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            repeat_exit, repeat_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])

            self.assertEqual(start_exit, 0)
            self.assertEqual(start_payload["status"], "active")
            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["status"], "ok")
            self.assertEqual(step_payload["scan_budget"], 5)
            self.assertEqual(step_payload["processed_entry_count"], 5)
            self.assertEqual(len(step_payload["action_requests"]), 1)
            action_request = step_payload["action_requests"][0]
            self.assertEqual(action_request["action"], "send_message")
            self.assertEqual(action_request["pre_action_observation_id"], "obs_ada_001")
            self.assertTrue(action_request["requires_post_action_verification"])
            self.assertIn("欠你一顿好吃的", action_request["payload_text"])
            self.assertEqual(len(step_payload["handoffs"]), 2)
            self.assertEqual(step_payload["handoffs"][0]["reason"], "appointment_details_requested")
            self.assertTrue(step_payload["handoffs"][1]["slot_conflict"])
            self.assertIn("row_cora", [item["candidate_key"] for item in step_payload["scan_requests"]])
            self.assertIn("row_faye", [item["candidate_key"] for item in step_payload["scheduled_actions"]])

            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(states_exit, 0)
            states_by_candidate = {
                state["candidate_key"]: state["state"]
                for state in states_payload["states"]
                if state.get("candidate_key")
            }
            self.assertEqual(states_by_candidate["row_ada"], "send_requested")
            self.assertEqual(states_by_candidate["row_cora"], "needs_thread_scan")
            self.assertEqual(states_by_candidate["row_bea"], "appointment_handoff")

            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["action_requests"], [])
            self.assertIn("duplicate_send_request_suppressed", repeat_payload["warnings"])

            action_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            action_result["action_request_id"] = action_request["action_request_id"]
            action_result["target_match_id"] = action_request["match_id"]
            action_result["payload_hash"] = action_request["payload_hash"]
            action_result_path = Path(temp_dir) / "action_result.json"
            action_result_path.write_text(json.dumps(action_result, ensure_ascii=False), encoding="utf-8")
            result_exit, result_payload, _ = self._run([
                "action",
                "record-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(action_result_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(result_exit, 0)
            self.assertEqual(result_payload["action_request_id"], action_request["action_request_id"])
            state_by_match = {state["match_id"]: state for state in states_payload["states"]}
            self.assertEqual(state_by_match[action_request["match_id"]]["state"], "sent_waiting")

            post_result_repeat_exit, post_result_repeat_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            self.assertEqual(post_result_repeat_exit, 0)
            self.assertEqual(post_result_repeat_payload["action_requests"], [])
            self.assertIn("duplicate_send_request_suppressed", post_result_repeat_payload["warnings"])

    def test_session_stop_report_and_resume(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            stop_exit, stop_payload, _ = self._run([
                "automation",
                "session",
                "stop",
                "--data-dir",
                str(data_dir),
            ])
            latest_exit, latest_payload, _ = self._run([
                "automation",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
            ])
            restart_exit, restart_payload, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])

            self.assertEqual(stop_exit, 0)
            self.assertEqual(stop_payload["status"], "stopped")
            self.assertTrue((data_dir / stop_payload["machine_report_path"]).exists())
            self.assertTrue((data_dir / stop_payload["human_report_path"]).exists())
            self.assertGreaterEqual(stop_payload["summary"]["new_match_count"], 3)
            self.assertEqual(stop_payload["summary"]["action_request_count"], 1)
            self.assertGreaterEqual(stop_payload["summary"]["handoff_count"], 2)
            self.assertEqual(latest_exit, 0)
            self.assertEqual(latest_payload["status"], "ok")
            self.assertEqual(latest_payload["machine_report"]["session_id"], stop_payload["session_id"])
            self.assertEqual(restart_exit, 0)
            self.assertEqual(restart_payload["resumed_from_report"], stop_payload["machine_report_path"])

    def test_pause_and_resume_gate_session_steps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            pause_exit, pause_payload, _ = self._run([
                "automation",
                "pause",
                "--data-dir",
                str(data_dir),
            ])
            blocked_exit, blocked_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            resume_exit, resume_payload, _ = self._run([
                "automation",
                "resume",
                "--data-dir",
                str(data_dir),
            ])
            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])

            self.assertEqual(pause_exit, 0)
            self.assertTrue(pause_payload["paused"])
            self.assertEqual(blocked_exit, 0)
            self.assertEqual(blocked_payload["status"], "blocked")
            self.assertEqual(blocked_payload["reason"], "session_paused")
            self.assertEqual(resume_exit, 0)
            self.assertFalse(resume_payload["paused"])
            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["status"], "ok")

    def test_revoked_or_expired_authorization_blocks_automatic_send(self):
        for auth_file in ("auth_revoked.json", "auth_expired.json"):
            with self.subTest(auth_file=auth_file):
                with tempfile.TemporaryDirectory() as temp_dir:
                    data_dir = Path(temp_dir) / "data"
                    self._init_profile(data_dir)
                    self._run([
                        "automation",
                        "session",
                        "start",
                        "--data-dir",
                        str(data_dir),
                        "--authorization",
                        str(FIXTURE_DIR / auth_file),
                    ])

                    step_exit, step_payload, _ = self._run([
                        "automation",
                        "session",
                        "step",
                        "--data-dir",
                        str(data_dir),
                        "--scan-batch",
                        str(FIXTURE_DIR / "scan_batch_initial.json"),
                    ])

                    self.assertEqual(step_exit, 0)
                    self.assertEqual(step_payload["status"], "blocked")
                    self.assertEqual(step_payload["reason"], "authorization_expired_or_revoked")
                    self.assertEqual(step_payload["action_requests"], [])
                    self.assertIn("authorization_expired_or_revoked", step_payload["warnings"])

    def test_same_inbound_is_nudged_only_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])

            first_exit, first_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            repeat_exit, repeat_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["state_updates"][0]["state"], "nudge_scheduled")
            self.assertEqual(first_payload["scheduled_actions"][0]["type"], "nudge_later")
            self.assertEqual(first_payload["scheduled_actions"][0]["candidate_key"], "row_gia")
            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["state_updates"][0]["state"], "waiting_for_match")
            self.assertEqual(repeat_payload["scheduled_actions"], [])
            self.assertEqual(states_exit, 0)
            state = states_payload["states"][0]
            self.assertEqual(state["last_nudged_inbound_fingerprint"], "gia:in:absurd-comedy")
            self.assertEqual(state["nudge_count_since_inbound"], 1)

    def _init_profile(self, data_dir):
        self._run([
            "init-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_profile.json",
        ])

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


if __name__ == "__main__":
    unittest.main()
