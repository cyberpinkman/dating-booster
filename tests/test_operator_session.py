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
            self.assertIn("operator record-stage-result", payload["supported_commands"])
            self.assertTrue(payload["agent_native_capabilities"]["operator_session"])
            self.assertTrue(payload["agent_native_capabilities"]["goal_oriented_operator"])
            self.assertTrue(payload["agent_native_capabilities"]["stage_only_audit"])

    def test_operator_start_persists_management_config_and_scan_work_budgets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            start_exit, start_payload, _ = self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
                "--management-mode",
                "high-throughput",
                "--max-threads-per-cycle",
                "7",
                "--max-pages-per-cycle",
                "2",
                "--cycle-send-limit",
                "3",
            ])
            next_exit, next_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(start_payload["status"], "active")
        self.assertEqual(start_payload["management_mode"], "high-throughput")
        work_item = next_payload["work_item"]
        self.assertEqual(next_exit, 0)
        self.assertEqual(work_item["work_item_type"], "scan_message_list")
        self.assertEqual(work_item["management_mode"], "high-throughput")
        self.assertEqual(work_item["page_budget_remaining"], 2)
        self.assertEqual(work_item["thread_budget_remaining"], 7)
        self.assertEqual(work_item["scan_cursor"], {"current": None, "next": None, "exhausted": False})

    def test_operator_continues_message_list_scan_when_cursor_not_exhausted(self):
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
                "--max-pages-per-cycle",
                "2",
            ])
            first_next_exit, first_next, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])
            self.assertEqual(first_next_exit, 0)
            self.assertEqual(first_next["work_item"]["work_item_type"], "scan_message_list")
            list_path = Path(temp_dir) / "empty_page.json"
            self._write_json(
                list_path,
                {
                    "schema_version": 1,
                    "observation_type": "message_list",
                    "session_id": "session_cursor",
                    "app_id": "tinder",
                    "captured_at": "2026-05-26T00:00:00Z",
                    "scan_cursor": {"current": "page_1", "next": "page_2", "exhausted": False},
                    "scan_budget": 5,
                    "provenance": {"author": "host_agent", "evidence": "Empty first page."},
                    "message_list_snapshot": {"entries": []},
                },
            )
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(list_path),
            ])

            next_exit, next_payload, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])

        self.assertEqual(next_exit, 0)
        work_item = next_payload["work_item"]
        self.assertEqual(work_item["work_item_type"], "scan_message_list")
        self.assertEqual(work_item["reason"], "scan_page_continuation_required")
        self.assertEqual(work_item["scan_cursor"]["current"], "page_2")
        self.assertEqual(work_item["page_budget_remaining"], 1)

    def test_high_throughput_scans_page_budget_before_processing_first_page_work(self):
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
                "--management-mode",
                "high-throughput",
                "--max-pages-per-cycle",
                "2",
            ])
            self._run(["operator", "next", "--data-dir", str(data_dir)])
            first_page = _single_candidate_message_list_observation("row_ada")
            first_page["scan_cursor"] = {"current": "page_1", "next": "page_2", "exhausted": False}
            first_page["scan_budget"] = 5
            first_path = Path(temp_dir) / "first_page.json"
            self._write_json(first_path, first_page)
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(first_path),
            ])

            continuation_exit, continuation_payload, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])
            second_page = _message_list_observation()
            second_page["scan_cursor"] = {"current": "page_2", "next": None, "exhausted": True}
            second_page["message_list_snapshot"]["entries"] = []
            second_path = Path(temp_dir) / "second_page.json"
            self._write_json(second_path, second_page)
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(second_path),
            ])
            open_exit, open_payload, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])

        self.assertEqual(continuation_exit, 0)
        self.assertEqual(continuation_payload["work_item"]["work_item_type"], "scan_message_list")
        self.assertEqual(continuation_payload["work_item"]["reason"], "scan_page_continuation_required")
        self.assertEqual(continuation_payload["work_item"]["scan_cursor"]["current"], "page_2")
        self.assertEqual(open_exit, 0)
        self.assertEqual(open_payload["work_item"]["work_item_type"], "open_thread")
        self.assertEqual(open_payload["work_item"]["candidate_key"], "row_ada")

    def test_operator_start_warns_for_old_memory_review_without_blocking(self):
        from dating_boost.core.memory.review_queue import ReviewItem, ReviewQueueRepository

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            ReviewQueueRepository(data_dir).enqueue(
                ReviewItem(
                    review_item_id="rev_old_session",
                    session_id="session_old",
                    match_id="match_old",
                    observation_id="obs_old",
                    proposal={
                        "predicate": "thread_cue",
                        "value": "ordinary conversation page",
                        "subject": "Old Match",
                        "scope": "conversation",
                        "fact_type": "visible_fact",
                        "confidence": "medium",
                        "evidence_text": "Old session suggestion.",
                    },
                    status="pending",
                    created_at="2026-05-25T00:00:00Z",
                    reported_at=None,
                    reviewed_at=None,
                    dedupe_key="old_session_ui_cue",
                    source="deterministic",
                    risk="low",
                )
            )

            start_exit, start_payload, _ = self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
                "--initial-surface",
                "current-thread",
            ])

            self.assertEqual(start_exit, 0)
            self.assertEqual(start_payload["status"], "active")
            self.assertIn("pending_memory_suggestions_require_review", start_payload["warnings"])
            self.assertEqual(start_payload["memory_review"]["pending_count"], 1)
            self.assertEqual(start_payload["initial_surface"], "current-thread")

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
            action_result["precondition_hash"] = send_payload["work_item"]["precondition_hash"]
            action_result["autonomous_audit_binding"] = send_payload["work_item"]["autonomous_audit_binding"]
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

    def test_current_thread_session_ingests_thread_without_message_list_and_records_stage_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            start_exit, start_payload, _ = self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
                "--initial-surface",
                "current-thread",
            ])
            first_next_exit, first_next, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            thread_path = Path(temp_dir) / "current_thread.json"
            thread_payload = _thread_observation("row_ada")
            thread_payload.pop("candidate_key")
            self._write_json(thread_path, thread_payload)
            ingest_exit, ingest_payload, _ = self._run([
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
            self.assertEqual(start_payload["initial_surface"], "current-thread")
            self.assertEqual(first_next_exit, 0)
            self.assertEqual(first_next["work_item"]["work_item_type"], "observe_current_thread")
            self.assertEqual(ingest_exit, 0)
            self.assertEqual(ingest_payload["status"], "ok")
            self.assertTrue(ingest_payload["candidate_key"].startswith("current_thread_"))
            self.assertEqual(send_exit, 0)
            self.assertEqual(send_payload["work_item"]["work_item_type"], "send_message")
            self.assertNotEqual(send_payload["work_item"].get("candidate_key"), "row_ada")
            self.assertEqual(repeat_exit, 0)
            self.assertEqual(repeat_payload["work_item"]["work_item_type"], "send_message")
            scan_batch = json.loads((data_dir / "operator" / "pending_scan_batch.json").read_text(encoding="utf-8"))
            current_entry = scan_batch["message_list_snapshot"]["entries"][0]
            self.assertEqual(current_entry["timestamp_cue"], "current_thread")
            self.assertNotIn("position", current_entry)

            work_item = send_payload["work_item"]
            stage_result_path = Path(temp_dir) / "stage_result.json"
            self._write_json(
                stage_result_path,
                {
                    "action_request_id": work_item["action_request_id"],
                    "target_match_id": work_item["match_id"],
                    "payload_hash": work_item["payload_hash"],
                    "pre_action_observation_id": work_item["pre_action_observation_id"],
                    "result_status": "succeeded",
                    "stage_attempt_status": "completed",
                    "staged_text_verification": {
                        "status": "verified",
                        "evidence": {"method": "fixture staged text exact match"},
                    },
                    "evidence": {"stage_mode": True, "user_must_review_before_send": True},
                },
            )
            stage_exit, stage_payload, _ = self._run([
                "operator",
                "record-stage-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(stage_result_path),
            ])
            states_exit, states_payload, _ = self._run([
                "operator",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(stage_exit, 0)
            self.assertEqual(stage_payload["status"], "ok")
            self.assertEqual(stage_payload["path"], "audit/stage_results.jsonl")
            self.assertTrue((data_dir / "audit" / "stage_results.jsonl").exists())
            self.assertFalse((data_dir / "audit" / "action_results.jsonl").exists())
            self.assertEqual(states_exit, 0)
            states = states_payload["automation"]["states"]
            self.assertEqual(states[0]["state"], "staged_pending_user")
            self.assertEqual(states[0]["last_stage_result_event_id"], stage_payload["event_id"])

    def test_current_thread_target_profile_supplement_does_not_require_message_list(self):
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
                "--initial-surface",
                "current-thread",
            ])
            self._run(["operator", "next", "--data-dir", str(data_dir)])
            missing_profile = _thread_observation("row_ada")
            missing_profile["candidate_key"] = "current_ada"
            missing_profile["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before drafting.",
            }
            missing_path = Path(temp_dir) / "missing_profile_thread.json"
            self._write_json(missing_path, missing_profile)
            self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(missing_path),
            ])

            blocked_exit, blocked_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])
            supplemented = _thread_observation("row_ada")
            supplemented["candidate_key"] = "current_ada"
            supplement_path = Path(temp_dir) / "supplemented_thread.json"
            self._write_json(supplement_path, supplemented)
            ingest_exit, ingest_payload, _ = self._run([
                "operator",
                "ingest-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(supplement_path),
            ])
            send_exit, send_payload, _ = self._run([
                "operator",
                "next",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(blocked_exit, 0)
            self.assertEqual(blocked_payload["work_item"]["work_item_type"], "blocked")
            self.assertEqual(blocked_payload["work_item"]["reason"], "target_profile_required")
            self.assertEqual(ingest_exit, 0)
            self.assertEqual(ingest_payload["status"], "ok")
            self.assertEqual(send_exit, 0)
            self.assertEqual(send_payload["work_item"]["work_item_type"], "send_message")
            self.assertEqual(send_payload["work_item"]["candidate_key"], "current_ada")

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
                "--cycle-send-limit",
                "2",
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

    def test_operator_cycle_send_limit_defers_remaining_send_work(self):
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
                "--cycle-send-limit",
                "1",
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

            first_exit, first_payload, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])
            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["work_item"]["work_item_type"], "send_message")
            self._record_operator_success(data_dir, temp_dir, first_payload["work_item"])

            limited_exit, limited_payload, _ = self._run(["operator", "next", "--data-dir", str(data_dir)])
            state_exit, state_payload, _ = self._run(["operator", "get-state", "--data-dir", str(data_dir)])

        self.assertEqual(limited_exit, 0)
        self.assertEqual(limited_payload["work_item"]["work_item_type"], "scheduled_wait")
        self.assertEqual(limited_payload["work_item"]["reason"], "cycle_send_limit_reached")
        self.assertEqual(state_exit, 0)
        self.assertEqual(state_payload["work_queue"][0]["candidate_key"], "row_zara")

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

    def test_operator_report_latest_works_for_active_session_before_stop(self):
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
                "--initial-surface",
                "current-thread",
            ])

            report_exit, report_payload, _ = self._run([
                "operator",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
            ])

            self.assertEqual(report_exit, 0)
            self.assertEqual(report_payload["status"], "ok")
            self.assertEqual(report_payload["operator_session"]["status"], "active")
            self.assertEqual(report_payload["automation_report"]["report_status"], "active")

    def test_operator_human_report_renders_memory_suggestions_for_users(self):
        from dating_boost.core.memory.review_queue import ReviewItem, ReviewQueueRepository

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            start_exit, start_payload, _ = self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            self.assertEqual(start_exit, 0)
            ReviewQueueRepository(data_dir).enqueue(
                ReviewItem(
                    review_item_id="rev_low_investment_001",
                    session_id=start_payload["session_id"],
                    match_id="match_ada",
                    observation_id="obs_ada",
                    proposal={
                        "predicate": "thread_cue",
                        "value": "match_latest_reply_low_investment",
                        "subject": "Ada",
                        "scope": "conversation",
                        "fact_type": "inference",
                        "confidence": "medium",
                        "evidence_text": "Latest reply was short.",
                    },
                    status="pending",
                    created_at="2026-06-07T00:00:00Z",
                    reported_at=None,
                    reviewed_at=None,
                    dedupe_key="dedupe_low_investment_001",
                    source="deterministic",
                    risk="low",
                )
            )

            output = StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "operator",
                    "report",
                    "latest",
                    "--data-dir",
                    str(data_dir),
                    "--format",
                    "md",
                ])
            report_text = output.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("对方最近回复信息量低", report_text)
            self.assertIn("rev_low_investment_001", report_text)
            self.assertIn("记住这条", report_text)
            self.assertNotIn("match_latest_reply_low_investment", report_text)
            self.assertNotIn("predicate", report_text)

    def test_operator_report_latest_json_flag_and_md_regenerate_legacy_memory_display(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            report_dir = data_dir / "automation" / "reports"
            report_dir.mkdir(parents=True)
            machine_report = {
                "schema_version": 1,
                "session_id": "session_legacy",
                "authorization_id": "auth_legacy",
                "started_at": "2026-06-07T00:00:00Z",
                "stopped_at": "2026-06-07T00:10:00Z",
                "summary": {
                    "match_count": 0,
                    "new_match_count": 0,
                    "action_request_count": 0,
                    "waiting_count": 0,
                    "nudge_count": 0,
                    "handoff_count": 0,
                    "slot_conflict_count": 0,
                    "slot_count": 0,
                    "user_profile_ready": True,
                    "disclosure_usage_count": 0,
                    "low_investment_repair_count": 0,
                    "paused_due_to_low_reciprocity": 0,
                },
                "user_profile_readiness": {},
                "memory_review": {
                    "required": True,
                    "pending_count": 1,
                    "items": [
                        {
                            "review_item_id": "rev_legacy_ui_cue",
                            "session_id": "session_legacy",
                            "match_id": "match_ada",
                            "observation_id": "obs_ada",
                            "proposal": {
                                "predicate": "thread_cue",
                                "value": "ordinary conversation page",
                                "subject": "Ada",
                                "scope": "conversation",
                                "fact_type": "visible_fact",
                                "confidence": "medium",
                                "evidence_text": "Legacy report item.",
                            },
                            "status": "pending",
                            "created_at": "2026-06-07T00:00:00Z",
                            "reported_at": None,
                            "reviewed_at": None,
                            "dedupe_key": "legacy_ui_cue",
                            "source": "deterministic",
                            "risk": "low",
                        }
                    ],
                    "accept_command_template": "memory review decide --data-dir DIR --accept {review_item_id}",
                    "reject_command_template": "memory review decide --data-dir DIR --reject {review_item_id}",
                },
                "states": [],
                "conversation_plans": [],
                "appointment_ledger": [],
                "next_priority_queue": [],
            }
            (report_dir / "machine_latest.json").write_text(json.dumps(machine_report), encoding="utf-8")
            (report_dir / "human_latest.md").write_text(
                "## Memory Suggestions\n- id=rev_legacy_ui_cue predicate=thread_cue value=ordinary conversation page\n",
                encoding="utf-8",
            )

            json_exit, json_payload, _ = self._run([
                "operator",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
                "--json",
            ])
            output = StringIO()
            with redirect_stdout(output):
                md_exit = main([
                    "operator",
                    "report",
                    "latest",
                    "--data-dir",
                    str(data_dir),
                    "--format",
                    "md",
                ])
            md_text = output.getvalue()

            self.assertEqual(json_exit, 0)
            item = json_payload["automation_report"]["memory_review"]["items"][0]
            self.assertIn("display", item)
            self.assertEqual(item["display"]["summary"], "当前是普通聊天页，不是飞行页或问答决策页。")
            self.assertEqual(md_exit, 0)
            self.assertIn("当前是普通聊天页", md_text)
            self.assertIn("rev_legacy_ui_cue", md_text)
            self.assertNotIn("predicate=thread_cue", md_text)
            self.assertNotIn("ordinary conversation page", md_text)

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
        action_result["precondition_hash"] = work_item["precondition_hash"]
        action_result["autonomous_audit_binding"] = work_item["autonomous_audit_binding"]
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
