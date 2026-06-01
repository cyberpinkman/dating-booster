import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main


FIXTURE_DIR = Path("tests/fixtures/automation")


class OperatorSessionTests(unittest.TestCase):
    def setUp(self):
        self._clock_patch = patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"})
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()

    def test_capabilities_expose_operator_session_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload, _ = self._run([
                "capabilities",
                "--json",
                "--data-dir",
                str(Path(temp_dir) / "data"),
            ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["schema_versions"]["operator_session"], 1)
            self.assertEqual(payload["schema_versions"]["operator_work_item"], 1)
            self.assertEqual(payload["schema_versions"]["operator_work_queue"], 1)
            self.assertIn("operator session start", payload["supported_commands"])
            self.assertIn("operator next", payload["supported_commands"])
            self.assertIn("operator ingest-observation", payload["supported_commands"])
            self.assertIn("operator record-action-result", payload["supported_commands"])
            self.assertTrue(payload["agent_native_capabilities"]["operator_session"])
            self.assertTrue(payload["agent_native_capabilities"]["goal_oriented_operator"])

    def test_operator_guides_host_from_list_scan_to_verified_send(self):
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
            start_exit, start_payload, _ = self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            first_next_exit, first_next, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            list_path = Path(temp_dir) / "operator_list.json"
            self._write_json(list_path, _single_candidate_message_list_observation("row_ada"))
            ingest_list_exit, ingest_list, _ = self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(list_path),
            ])
            open_exit, open_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            thread_path = Path(temp_dir) / "operator_thread.json"
            self._write_json(thread_path, _thread_observation("row_ada"))
            ingest_thread_exit, ingest_thread, _ = self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(thread_path),
            ])
            send_exit, send_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            repeat_exit, repeat_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(start_exit, 0)
            self.assertEqual(start_payload["status"], "active")
            self.assertEqual(first_next_exit, 0)
            self.assertEqual(first_next["work_item"]["work_item_type"], "scan_message_list")
            self.assertEqual(ingest_list_exit, 0)
            self.assertEqual(ingest_list["status"], "ok")
            self.assertEqual(open_exit, 0)
            self.assertEqual(open_payload["work_item"]["work_item_type"], "open_thread")
            self.assertEqual(open_payload["work_item"]["candidate_key"], "row_ada")
            self.assertEqual(ingest_thread_exit, 0)
            self.assertEqual(ingest_thread["status"], "ok")
            self.assertEqual(send_exit, 0)
            self.assertEqual(send_payload["work_item"]["work_item_type"], "send_message")
            self.assertEqual(send_payload["work_item"]["candidate_key"], "row_ada")
            self.assertIn("欠你一顿好吃的", send_payload["work_item"]["payload_text"])
            self.assertTrue(send_payload["work_item"]["requires_post_action_verification"])
            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["work_item"], send_payload["work_item"])

            action_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            action_result["action_request_id"] = send_payload["work_item"]["action_request_id"]
            action_result["target_match_id"] = send_payload["work_item"]["match_id"]
            action_result["payload_hash"] = send_payload["work_item"]["payload_hash"]
            result_path = Path(temp_dir) / "operator_action_result.json"
            self._write_json(result_path, action_result)
            result_exit, result_payload, _ = self._run([
                "operator",
                "record-action-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(result_path),
            ])
            states_exit, states_payload, _ = self._run([
                "operator",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(result_exit, 0)
            self.assertEqual(result_payload["status"], "ok")
            self.assertEqual(states_exit, 0)
            state_by_candidate = {
                state.get("candidate_key"): state
                for state in states_payload["automation"]["states"]
            }
            self.assertEqual(state_by_candidate["row_ada"]["state"], "sent_waiting")
            next_after_result_exit, next_after_result, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(next_after_result_exit, 0)
            self.assertEqual(next_after_result["work_item"]["work_item_type"], "scan_message_list")

    def test_operator_drains_multiple_send_requests_from_work_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            list_path = Path(temp_dir) / "two_reply_list.json"
            self._write_json(list_path, _two_reply_message_list_observation())
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(list_path),
            ])
            for candidate_key, visible_name in (("row_ada", "Ada"), ("row_zara", "Zara")):
                thread_path = Path(temp_dir) / f"{candidate_key}.json"
                self._write_json(
                    thread_path,
                    _reply_thread_observation(
                        candidate_key=candidate_key,
                        visible_name=visible_name,
                        observation_id=f"obs_{candidate_key}_001",
                        inbound_fingerprint=f"{candidate_key}:in:you-pick",
                    ),
                )
                self._run([
                    "operator",
                    "ingest-observation",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    str(thread_path),
                ])

            first_exit, first_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["work_item"]["work_item_type"], "send_message")
            self.assertEqual(first_payload["work_item"]["candidate_key"], "row_ada")
            self._record_operator_success(data_dir, temp_dir, first_payload["work_item"])

            second_exit, second_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(second_exit, 0)
            self.assertEqual(second_payload["work_item"]["work_item_type"], "send_message")
            self.assertEqual(second_payload["work_item"]["candidate_key"], "row_zara")
            self._record_operator_success(data_dir, temp_dir, second_payload["work_item"])

            final_exit, final_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(final_exit, 0)
            self.assertEqual(final_payload["work_item"]["work_item_type"], "scan_message_list")

    def test_operator_handoff_does_not_stick_as_current_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            list_path = Path(temp_dir) / "handoff_list.json"
            self._write_json(list_path, _single_candidate_message_list_observation("row_bea"))
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(list_path),
            ])
            thread_path = Path(temp_dir) / "handoff_thread.json"
            self._write_json(thread_path, _thread_observation("row_bea"))
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(thread_path),
            ])

            handoff_exit, handoff_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            repeat_exit, repeat_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(handoff_exit, 0)
            self.assertEqual(handoff_payload["work_item"]["work_item_type"], "handoff")
            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["work_item"]["work_item_type"], "scan_message_list")

    def test_operator_ingest_rejects_invalid_thread_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            list_path = Path(temp_dir) / "operator_list.json"
            self._write_json(list_path, _message_list_observation())
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(list_path),
            ])
            invalid_thread = _thread_observation("row_ada")
            invalid_thread.pop("assessment")
            invalid_path = Path(temp_dir) / "invalid_thread.json"
            self._write_json(invalid_path, invalid_thread)

            exit_code, payload, _ = self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(invalid_path),
            ])
            state_exit, state_payload, _ = self._run([
                "operator",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")
            self.assertIn("assessment", payload["reason"])
            self.assertEqual(state_exit, 0)
            self.assertEqual(state_payload["pending_scan_batch"]["thread_observations"], [])

    def test_operator_stop_writes_resume_report(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            stop_exit, stop_payload, _ = self._run([
                "operator",
                "stop",
                "--data-dir",
                str(data_dir),
            ])
            report_exit, report_payload, _ = self._run([
                "operator",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(stop_exit, 0)
            self.assertEqual(stop_payload["status"], "stopped")
            self.assertTrue((data_dir / stop_payload["machine_report_path"]).exists())
            self.assertEqual(report_exit, 0)
            self.assertEqual(report_payload["status"], "ok")
            self.assertEqual(report_payload["operator_session"]["status"], "stopped")

    def test_operator_start_clears_stale_pending_scan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            list_path = Path(temp_dir) / "operator_list.json"
            self._write_json(list_path, _message_list_observation())
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(list_path),
            ])
            self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            next_exit, next_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(next_exit, 0)
            self.assertEqual(next_payload["work_item"]["work_item_type"], "scan_message_list")

    def _init_profile(self, data_dir):
        self._run([
            "init-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_profile.json",
        ])
        self._run([
            "user",
            "ingest-profile",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_dating_profile.json",
        ])
        self._run([
            "user",
            "ingest-interview",
            "--data-dir",
            str(data_dir),
            "--input",
            "tests/fixtures/intelligence/user_self_interview.json",
        ])

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _write_json(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _record_operator_success(self, data_dir, temp_dir, work_item):
        action_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
        action_result["action_request_id"] = work_item["action_request_id"]
        action_result["target_match_id"] = work_item["match_id"]
        action_result["payload_hash"] = work_item["payload_hash"]
        action_result["pre_action_observation_id"] = work_item["pre_action_observation_id"]
        result_path = Path(temp_dir) / f"{work_item['candidate_key']}_action_result.json"
        self._write_json(result_path, action_result)
        result_exit, result_payload, _ = self._run([
            "operator",
            "record-action-result",
            "--data-dir",
            str(data_dir),
            "--input",
            str(result_path),
        ])
        self.assertEqual(result_exit, 0)
        self.assertEqual(result_payload["status"], "ok")


def _message_list_observation():
    scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "observation_type": "message_list",
        "session_id": scan["session_id"],
        "app_id": scan["app_id"],
        "captured_at": scan["captured_at"],
        "scan_cursor": scan["scan_cursor"],
        "scan_budget": scan["scan_budget"],
        "provenance": scan["provenance"],
        "message_list_snapshot": scan["message_list_snapshot"],
    }


def _thread_observation(candidate_key):
    scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
    for item in scan["thread_observations"]:
        if item["candidate_key"] == candidate_key:
            payload = dict(item)
            payload["schema_version"] = 1
            payload["observation_type"] = "thread"
            return payload
    raise AssertionError(f"missing fixture thread observation: {candidate_key}")


def _single_candidate_message_list_observation(candidate_key):
    payload = _message_list_observation()
    entries = payload["message_list_snapshot"]["entries"]
    payload["message_list_snapshot"]["entries"] = [
        entry for entry in entries if entry["candidate_key"] == candidate_key
    ]
    return payload


def _two_reply_message_list_observation():
    ada = _single_candidate_message_list_observation("row_ada")["message_list_snapshot"]["entries"][0]
    zara = dict(ada)
    zara["candidate_key"] = "row_zara"
    zara["visible_name"] = "Zara"
    zara["latest_preview_hash"] = "preview_zara"
    zara["position"] = 2
    zara["match_identity_hints"] = {
        "visible_name": "Zara",
        "profile_cues": ["日料", "纯爱"],
        "conversation_fingerprint": "zara-reward",
    }
    payload = _message_list_observation()
    payload["message_list_snapshot"]["entries"] = [ada, zara]
    payload["scan_budget"] = 2
    return payload


def _reply_thread_observation(*, candidate_key, visible_name, observation_id, inbound_fingerprint):
    payload = _thread_observation("row_ada")
    payload["candidate_key"] = candidate_key
    payload["assessment"]["latest_inbound_fingerprint"] = inbound_fingerprint
    payload["observation"]["observation_id"] = observation_id
    payload["observation"]["match_identity_hints"]["visible_name"] = visible_name
    payload["observation"]["match_identity_hints"]["conversation_fingerprint"] = f"{candidate_key}-reward"
    payload["observation"]["match_identity_hints"]["evidence"] = f"Visible chat thread for {visible_name}."
    return payload


if __name__ == "__main__":
    unittest.main()
