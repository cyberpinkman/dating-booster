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


class AutomationSessionTests(unittest.TestCase):
    def setUp(self):
        self._clock_patch = patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T00:00:00Z"})
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()

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
            self.assertIn("disclosure_source", action_request)
            self.assertIn("used_user_material_ids", action_request)
            self.assertIn("question_debt_after", action_request)
            self.assertIn("reciprocity_balance_after", action_request)
            self.assertIn("low_investment_repair_applied", action_request)
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
            latest_md_exit, latest_md_text = self._run_text([
                "automation",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
                "--format",
                "md",
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
            self.assertEqual(latest_md_exit, 0)
            self.assertIn("Next Priority Queue", latest_md_text)
            self.assertIn("Handoffs", latest_md_text)
            self.assertNotIn("欠你一顿好吃的", latest_md_text)
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

    def test_stopped_session_blocks_step_until_restarted(self):
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
                "stop",
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
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            resumed_exit, resumed_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])

            self.assertEqual(blocked_exit, 0)
            self.assertEqual(blocked_payload["status"], "blocked")
            self.assertEqual(blocked_payload["reason"], "session_stopped")
            self.assertEqual(blocked_payload["action_requests"], [])
            self.assertEqual(resumed_exit, 0)
            self.assertEqual(resumed_payload["status"], "ok")

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

    def test_contact_exchange_handoff_has_specific_reason(self):
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
            scan_path = Path(temp_dir) / "contact_exchange_scan.json"
            self._write_json(scan_path, _contact_exchange_scan_batch())

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["handoffs"][0]["reason"], "contact_exchange")
            self.assertEqual(states_exit, 0)
            self.assertEqual(states_payload["states"][0]["handoff_reason"], "contact_exchange")

    def test_authorization_expiration_uses_current_clock(self):
        with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-28T00:00:00Z"}):
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

    def test_thread_scan_merges_provisional_state_into_resolved_match(self):
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
            list_only_scan = {
                "schema_version": 1,
                "session_id": "session_fixture_merge",
                "app_id": "tinder",
                "captured_at": "2026-05-26T09:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_cora",
                            "visible_name": "Cora",
                            "latest_preview": "新匹配",
                            "latest_preview_hash": "preview_cora",
                            "timestamp_cue": "昨天",
                            "unread_cue": "absent",
                            "position": 1,
                        }
                    ]
                },
                "thread_observations": [],
            }
            thread_scan = dict(list_only_scan)
            thread_scan["thread_observations"] = [
                {
                    "candidate_key": "row_cora",
                    "assessment": {
                        "schema_version": 1,
                        "latest_match_message": "你好",
                        "latest_inbound_fingerprint": "cora:in:hello",
                        "reply_window_status": "open",
                        "continuation_opportunity": "yes",
                        "appointment_stage": "none",
                        "recommended_next": "wait",
                        "confidence": "high",
                        "evidence": "Thread opened for Cora.",
                        "risk_flags": [],
                    },
                    "observation": {
                        "observation_id": "obs_cora_001",
                        "source_type": "manual_fixture",
                        "app_id": "tinder",
                        "adapter_id": "codex.manual.v1",
                        "captured_at": "2026-05-26T09:01:00Z",
                        "page_type": "chat_thread",
                        "page_confidence": "high",
                        "match_identity_hints": {
                            "visible_name": "Cora",
                            "profile_cues": ["音乐"],
                            "conversation_fingerprint": "cora-new-match",
                            "evidence": "Visible chat thread for Cora.",
                        },
                        "profile_observation": {
                            "profile_text": "喜欢音乐。",
                            "photo_cues": [],
                            "hook_candidates": ["music"],
                        },
                        "conversation_observation": {
                            "visible_messages": [{"sender": "match", "text": "你好"}],
                            "input_state": "empty",
                            "thread_cues": [],
                        },
                        "element_observations": [],
                        "exception_state": "none",
                        "provenance": {
                            "evidence": "Fixture thread observation.",
                            "redaction_status": "redacted",
                        },
                        "raw_ref": None,
                    },
                }
            ]
            list_scan_path = Path(temp_dir) / "list_scan.json"
            thread_scan_path = Path(temp_dir) / "thread_scan.json"
            self._write_json(list_scan_path, list_only_scan)
            self._write_json(thread_scan_path, thread_scan)

            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(list_scan_path),
            ])
            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(thread_scan_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(states_exit, 0)
            self.assertEqual(len(states_payload["states"]), 1)
            state = states_payload["states"][0]
            self.assertEqual(state["candidate_key"], "row_cora")
            self.assertFalse(state["match_id"].startswith("provisional_"))
            self.assertEqual(state["state"], "sent_waiting")

    def test_scan_budget_prioritizes_new_candidates_before_known_continuations(self):
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
            automation_dir = data_dir / "automation"
            automation_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                automation_dir / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {
                            "schema_version": 1,
                            "match_id": f"match_old_{index}",
                            "candidate_key": f"row_old_{index}",
                            "state": "sent_waiting",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_session_id": "session_fixture_priority",
                        }
                        for index in range(1, 6)
                    ],
                },
            )
            priority_scan = {
                "schema_version": 1,
                "session_id": "session_fixture_priority",
                "app_id": "tinder",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        *[
                            {
                                "candidate_key": f"row_old_{index}",
                                "visible_name": f"Old {index}",
                                "latest_preview": "旧会话",
                                "latest_preview_hash": f"old_{index}",
                                "timestamp_cue": "昨天",
                                "unread_cue": "absent",
                                "position": index,
                            }
                            for index in range(1, 6)
                        ],
                        {
                            "candidate_key": "row_new",
                            "visible_name": "New",
                            "latest_preview": "新匹配",
                            "latest_preview_hash": "new_preview",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 6,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "priority_scan.json"
            self._write_json(scan_path, priority_scan)

            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

            self.assertEqual(step_exit, 0)
            self.assertEqual(step_payload["processed_entry_count"], 1)
            self.assertEqual(step_payload["scan_requests"][0]["candidate_key"], "row_new")
            self.assertNotIn(
                "row_new",
                [item.get("candidate_key") for item in step_payload["scheduled_actions"]],
            )

    def test_mismatched_action_result_does_not_complete_pending_send(self):
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
            _, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            action_request = step_payload["action_requests"][0]
            action_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            action_result["action_request_id"] = action_request["action_request_id"]
            action_result["target_match_id"] = action_request["match_id"]
            action_result["payload_hash"] = "wrong_payload_hash"
            mismatch_path = Path(temp_dir) / "mismatch_result.json"
            self._write_json(mismatch_path, action_result)

            result_exit, _, _ = self._run([
                "action",
                "record-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(mismatch_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(result_exit, 0)
            self.assertEqual(states_exit, 0)
            state_by_match = {state["match_id"]: state for state in states_payload["states"]}
            state = state_by_match[action_request["match_id"]]
            self.assertEqual(state["state"], "send_requested")
            self.assertEqual(state["last_action_result_error"], "payload_hash_mismatch")

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
            self.assertEqual(first_payload["action_requests"], [])
            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["state_updates"][0]["state"], "nudge_scheduled")
            self.assertEqual(repeat_payload["scheduled_actions"], [])
            self.assertEqual(states_exit, 0)
            state = states_payload["states"][0]
            self.assertIsNone(state["last_nudged_inbound_fingerprint"])
            self.assertEqual(state["nudge_count_since_inbound"], 0)
            self.assertEqual(state["next_due_at"], "2026-05-26T00:30:00Z")

    def test_due_nudge_with_fresh_draft_generates_one_send_request(self):
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
                str(FIXTURE_DIR / "scan_batch_nudge.json"),
            ])
            due_scan = json.loads((FIXTURE_DIR / "scan_batch_nudge.json").read_text(encoding="utf-8"))
            due_scan["captured_at"] = "2026-05-26T01:01:00Z"
            due_scan["thread_observations"][0]["draft"] = _nudge_draft()
            due_scan_path = Path(temp_dir) / "due_scan.json"
            self._write_json(due_scan_path, due_scan)

            with patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T01:00:00Z"}):
                due_exit, due_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(due_scan_path),
                ])
                repeat_exit, repeat_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(due_scan_path),
                ])
                states_exit, states_payload, _ = self._run([
                    "automation",
                    "get-state",
                    "--data-dir",
                    str(data_dir),
                ])

        self.assertEqual(due_exit, 0)
        self.assertEqual(len(due_payload["action_requests"]), 1)
        self.assertIn("刚想起来", due_payload["action_requests"][0]["payload_text"])
        self.assertEqual(repeat_exit, 0)
        self.assertEqual(repeat_payload["action_requests"], [])
        self.assertIn("duplicate_send_request_suppressed", repeat_payload["warnings"])
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

    def _run_text(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, output.getvalue()

    def _write_json(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _contact_exchange_scan_batch():
    return {
        "schema_version": 1,
        "session_id": "session_fixture_contact_exchange",
        "app_id": "tinder",
        "captured_at": "2026-05-26T10:00:00Z",
        "scan_budget": 1,
        "message_list_snapshot": {
            "entries": [
                {
                    "candidate_key": "row_iris",
                    "visible_name": "Iris",
                    "latest_preview": "没换呢",
                    "latest_preview_hash": "preview_iris_contact",
                    "timestamp_cue": "刚刚",
                    "unread_cue": "present",
                    "position": 1,
                }
            ]
        },
        "thread_observations": [
            {
                "candidate_key": "row_iris",
                "assessment": {
                    "schema_version": 1,
                    "latest_match_message": "没换呢",
                    "latest_user_message": "你现在的 wx 是什么",
                    "latest_inbound_fingerprint": "iris:in:wx-not-changed",
                    "reply_window_status": "open",
                    "continuation_opportunity": "yes",
                    "appointment_stage": "none",
                    "recommended_next": "handoff",
                    "confidence": "high",
                    "evidence": "The thread has moved into contact exchange.",
                    "risk_flags": ["contact_exchange"],
                },
                "observation": {
                    "observation_id": "obs_iris_contact_001",
                    "source_type": "manual_fixture",
                    "app_id": "tinder",
                    "adapter_id": "codex.manual.v1",
                    "captured_at": "2026-05-26T10:00:00Z",
                    "page_type": "chat_thread",
                    "page_confidence": "high",
                    "match_identity_hints": {
                        "visible_name": "Iris",
                        "profile_cues": ["friend_test_match"],
                        "conversation_fingerprint": "iris-contact-exchange",
                        "evidence": "Visible Iris test thread.",
                    },
                    "profile_observation": {
                        "profile_text": "",
                        "photo_cues": [],
                        "hook_candidates": [],
                    },
                    "conversation_observation": {
                        "visible_messages": [
                            {"sender": "user", "text": "你现在的 wx 是什么"},
                            {"sender": "match", "text": "没换呢"},
                        ],
                        "input_state": "empty",
                        "thread_cues": ["contact_exchange"],
                    },
                    "element_observations": [],
                    "exception_state": "none",
                    "provenance": {
                        "evidence": "Fixture thread observation.",
                        "redaction_status": "redacted",
                    },
                    "raw_ref": None,
                },
            }
        ],
    }


def _nudge_draft():
    return {
        "best_reply": "刚想起来，你上次说的荒诞喜剧是哪部来着",
        "safer_reply": "刚想起来，你上次说的那种喜剧有推荐吗",
        "bolder_reply": "刚想起来，这题我还挺想抄个片单的",
        "why_this_works": "It lightly reopens the last movie thread.",
        "situation_read": "The thread was open but paused after the user replied.",
        "conversation_move": "nudge_later",
        "hook_source": "conversation_thread",
        "naturalness_notes": ["short", "keeps the old topic"],
        "followup_if_match_replies": "If she names a movie, reply around that title.",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "Adaptive mode.",
        "persona_divergence": "low",
        "stance_divergence": "low",
    }


if __name__ == "__main__":
    unittest.main()
