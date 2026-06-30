import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.automation import AutomationRepository, _next_priority_queue, _prioritize_entries
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.memory.models import IdentityTrustStatus, MatchMemoryProjection
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import DraftReviewDecision, DraftReviewFinding


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

    def test_entry_priority_keeps_needs_reply_ahead_of_sent_waiting(self):
        sent_entry = {"candidate_key": "row_sent", "unread_cue": "unknown"}
        reply_entry = {"candidate_key": "row_reply", "unread_cue": "unknown"}
        ordered = _prioritize_entries(
            [sent_entry, reply_entry],
            states_by_candidate={
                "row_sent": {"state": "sent_waiting"},
                "row_reply": {"state": "needs_reply"},
            },
            thread_items={
                "row_reply": {
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                    }
                }
            },
        )

        self.assertEqual([entry["candidate_key"] for entry in ordered], ["row_reply", "row_sent"])

    def test_entry_priority_keeps_draft_ready_reply_badge_ahead_of_unsignaled_scan(self):
        draft_ready_entry = {"candidate_key": "row_draft_ready", "unread_cue": "reply_badge"}
        unsignaled_entry = {"candidate_key": "row_unsignaled", "unread_cue": "absent"}
        ordered = _prioritize_entries(
            [unsignaled_entry, draft_ready_entry],
            states_by_candidate={
                "row_draft_ready": {
                    "state": "draft_ready",
                    "candidate_type": "continuation_candidate",
                },
                "row_unsignaled": {
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                },
            },
            thread_items={},
        )

        self.assertEqual([entry["candidate_key"] for entry in ordered], ["row_draft_ready", "row_unsignaled"])

    def test_entry_priority_demotes_stale_waiting_thread_observation(self):
        sent_entry = {"candidate_key": "row_sent", "unread_cue": "unknown"}
        scan_later_entry = {"candidate_key": "row_scan_later", "unread_cue": "unknown"}
        ordered = _prioritize_entries(
            [sent_entry, scan_later_entry],
            states_by_candidate={
                "row_sent": {
                    "state": "sent_waiting",
                    "latest_inbound_fingerprint": "same_inbound",
                },
                "row_scan_later": {"state": "scan_later"},
            },
            thread_items={
                "row_sent": {
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                        "latest_inbound_fingerprint": "same_inbound",
                    }
                },
                "row_scan_later": {
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                    }
                },
            },
        )

        self.assertEqual([entry["candidate_key"] for entry in ordered], ["row_scan_later", "row_sent"])

    def test_next_priority_queue_excludes_stale_activation_candidate_without_unread(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_old",
                    "candidate_key": "row_old",
                    "state": "draft_ready",
                    "updated_at": "2026-05-01T00:00:00Z",
                    "unread_cue": "absent",
                },
                {
                    "match_id": "match_unread_old",
                    "candidate_key": "row_unread_old",
                    "state": "needs_thread_scan",
                    "updated_at": "2026-05-01T00:00:00Z",
                    "unread_cue": "present",
                    "candidate_type": "continuation_candidate",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_unread_old"])

    def test_next_priority_queue_excludes_tashuo_pending_question_gate_state(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "provisional_tashuo_visual_8181c3ffffffff80",
                    "candidate_key": "tashuo_visual_8181c3ffffffff80",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "visible_name": "Pending question avatar (illustration)",
                    "updated_at": "2026-06-29T17:34:33Z",
                },
                {
                    "match_id": "match_ordinary",
                    "candidate_key": "row_ordinary",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "visible_name": "Ada",
                    "unread_cue": "present",
                    "updated_at": "2026-06-29T17:34:33Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_ordinary"])

    def test_next_priority_queue_excludes_tashuo_structural_tab_header_state(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "provisional_tashuo_visual_000000ffffe7e7ef",
                    "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "visible_name": "Tab header: 消息 / 动态",
                    "updated_at": "2026-06-29T17:59:32Z",
                },
                {
                    "match_id": "match_ordinary",
                    "candidate_key": "row_ordinary",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "visible_name": "Ada",
                    "unread_cue": "present",
                    "updated_at": "2026-06-29T17:59:32Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_ordinary"])

    def test_next_priority_queue_excludes_tashuo_anonymous_question_card_state(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "provisional_tashuo_visual_0080c1ffffffffff",
                    "candidate_key": "tashuo_visual_0080c1ffffffffff",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "visible_name": "匿名提问卡片",
                    "updated_at": "2026-06-29T18:08:28Z",
                },
                {
                    "match_id": "match_ordinary",
                    "candidate_key": "row_ordinary",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "visible_name": "Ada",
                    "unread_cue": "present",
                    "updated_at": "2026-06-29T18:08:28Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_ordinary"])

    def test_next_priority_queue_promotes_recent_scan_later_continuation_with_inbound(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_opening",
                    "candidate_key": "row_opening",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_reply",
                    "candidate_key": "row_reply",
                    "state": "scan_later",
                    "candidate_type": "continuation_candidate",
                    "latest_inbound_fingerprint": "reply:fresh",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_reply", "row_opening"])

    def test_next_priority_queue_demotes_open_chat_behind_unseen_continuation(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_a_open",
                    "candidate_key": "row_open_chat",
                    "state": "needs_thread_scan",
                    "candidate_type": "open_chat_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_z_continuation",
                    "candidate_key": "row_continuation",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_continuation", "row_open_chat"])
        self.assertEqual(queue[0]["priority"], 4)
        self.assertEqual(queue[1]["priority"], 5)

    def test_next_priority_queue_promotes_pending_send_request(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_scan",
                    "candidate_key": "row_scan",
                    "state": "needs_thread_scan",
                    "candidate_type": "continuation_candidate",
                    "unread_cue": "present",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_send",
                    "candidate_key": "row_send",
                    "state": "send_requested",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_send", "row_scan"])
        self.assertEqual(queue[0]["priority"], 1)

    def test_next_priority_queue_promotes_draft_ready_reply_badge(self):
        queue = _next_priority_queue(
            [
                {
                    "match_id": "match_opening",
                    "candidate_key": "row_opening",
                    "state": "needs_thread_scan",
                    "candidate_type": "new_match_candidate",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
                {
                    "match_id": "match_reply",
                    "candidate_key": "row_reply",
                    "state": "draft_ready",
                    "candidate_type": "continuation_candidate",
                    "unread_cue": "reply_badge",
                    "updated_at": "2026-05-26T00:00:00Z",
                },
            ]
        )

        self.assertEqual([item["candidate_key"] for item in queue], ["row_reply", "row_opening"])
        self.assertEqual(queue[0]["priority"], 2)

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

    def test_session_step_stage_only_soft_accepts_standalone_reviewed_generation(self):
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
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["draft"]["draft_self_review_summary"]["ai_or_weird_probability"] = 55
            ada["draft"]["draft_self_review_summary"]["status"] = "needs_revision"
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_live_send": False,
                "primary_reason": "soft_accept_stage_only",
            }
            scan_path = Path(temp_dir) / "scan_stage_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
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
                str(scan_path),
            ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(len(step_payload["action_requests"]), 1)
        action_request = step_payload["action_requests"][0]
        self.assertEqual(action_request["candidate_key"], "row_ada")
        self.assertEqual(action_request["action"], "send_message")
        self.assertEqual(action_request["draft_self_review_summary"]["ai_or_weird_probability"], 55)
        self.assertEqual(action_request["draft_self_review_summary"]["status"], "stage_only_soft_accepted")
        self.assertIn("stage_only_draft_self_review_soft_accepted", step_payload["warnings"])

    def test_session_step_stage_only_soft_accepts_standalone_reviewed_policy(self):
        review = DraftReviewDecision(
            schema_version=1,
            status="needs_revision",
            allowed_for_display=True,
            allowed_for_stage=True,
            allowed_for_managed_send=False,
            requires_user_confirmation=False,
            primary_reason="draft_strategy_delta_missing",
            summary={"stage": True, "managed_live": False},
            findings=[
                DraftReviewFinding(
                    code="draft_strategy_delta_missing",
                    category="strategy",
                    severity="medium",
                    message="needs stronger managed-live strategy",
                    revision_hint="add a concrete handle",
                    blocks_display=False,
                    blocks_stage=False,
                    blocks_managed_send=True,
                )
            ],
            revision_hints=["add a concrete handle"],
            payload_hash="review_payload_hash",
            payload_format="single",
            message_count=1,
            review_id="review_stage_only_policy",
        )
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
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_managed_send": False,
                "primary_reason": "draft_strategy_delta_missing",
            }
            scan_path = Path(temp_dir) / "scan_stage_policy_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            with patch("dating_boost.core.automation.review_draft", return_value=review):
                step_exit, step_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(scan_path),
                ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(len(step_payload["action_requests"]), 1)
        action_request = step_payload["action_requests"][0]
        self.assertEqual(action_request["policy"]["allowed"], True)
        self.assertEqual(action_request["policy"]["allowed_for_stage"], True)
        self.assertEqual(action_request["policy"]["allowed_for_managed_send"], False)
        self.assertEqual(action_request["policy"]["reason"], "stage_only_draft_review_soft_accepted")
        self.assertIn("stage_only_draft_review_soft_accepted", step_payload["warnings"])

    def test_session_step_live_send_does_not_use_stage_only_soft_accept(self):
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
            auth = json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8"))
            auth["authorization_id"] = "auth_fixture_live_send"
            auth["live_send"] = True
            auth_path = Path(temp_dir) / "auth_live.json"
            self._write_json(auth_path, auth)
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["draft"]["draft_self_review_summary"]["ai_or_weird_probability"] = 55
            ada["draft"]["draft_self_review_summary"]["status"] = "needs_revision"
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_live_send": False,
                "primary_reason": "soft_accept_stage_only",
            }
            scan_path = Path(temp_dir) / "scan_live_blocks_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
            ])
            step_exit, step_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["action_requests"], [])
        self.assertIn("draft_self_review_probability_high", step_payload["warnings"])
        self.assertIn("draft_generation_required", step_payload["warnings"])
        revision_requests = [
            item
            for item in step_payload["scan_requests"]
            if item.get("candidate_key") == "row_ada" and item.get("reason") == "draft_revision_required"
        ]
        self.assertEqual(len(revision_requests), 1)
        self.assertEqual(revision_requests[0]["draft_revision_reason"], "draft_self_review_probability_high")

    def test_session_step_live_send_does_not_use_stage_only_policy_soft_accept(self):
        review = DraftReviewDecision(
            schema_version=1,
            status="needs_revision",
            allowed_for_display=True,
            allowed_for_stage=True,
            allowed_for_managed_send=False,
            requires_user_confirmation=False,
            primary_reason="draft_strategy_delta_missing",
            summary={"stage": True, "managed_live": False},
            findings=[
                DraftReviewFinding(
                    code="draft_strategy_delta_missing",
                    category="strategy",
                    severity="medium",
                    message="needs stronger managed-live strategy",
                    revision_hint="add a concrete handle",
                    blocks_display=False,
                    blocks_stage=False,
                    blocks_managed_send=True,
                )
            ],
            revision_hints=["add a concrete handle"],
            payload_hash="review_payload_hash",
            payload_format="single",
            message_count=1,
            review_id="review_live_policy",
        )
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
            auth = json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8"))
            auth["authorization_id"] = "auth_fixture_live_send"
            auth["live_send"] = True
            auth_path = Path(temp_dir) / "auth_live.json"
            self._write_json(auth_path, auth)
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            ada = scan["thread_observations"][0]
            ada["standalone_draft_review"] = {
                "schema_version": 1,
                "allowed_for_stage": True,
                "allowed_for_managed_send": False,
                "primary_reason": "draft_strategy_delta_missing",
            }
            scan_path = Path(temp_dir) / "scan_live_policy_blocks_soft_accept.json"
            self._write_json(scan_path, scan)

            start_exit, _, _ = self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(auth_path),
            ])
            with patch("dating_boost.core.automation.review_draft", return_value=review):
                step_exit, step_payload, _ = self._run([
                    "automation",
                    "session",
                    "step",
                    "--data-dir",
                    str(data_dir),
                    "--scan-batch",
                    str(scan_path),
                ])

        self.assertEqual(start_exit, 0)
        self.assertEqual(step_exit, 0)
        self.assertEqual(step_payload["action_requests"], [])
        self.assertIn("draft_strategy_delta_missing", step_payload["warnings"])
        self.assertIn("draft_revision_required", step_payload["warnings"])

    def test_failed_send_result_allows_same_payload_retry_with_new_request_id(self):
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
            first_request = step_payload["action_requests"][0]

            failed_result = dict(json.loads((FIXTURE_DIR / "action_result_ada.json").read_text()))
            failed_result["action_request_id"] = first_request["action_request_id"]
            failed_result["target_match_id"] = first_request["match_id"]
            failed_result["payload_hash"] = first_request["payload_hash"]
            failed_result["result_status"] = "failed"
            failed_result["post_action_observation_id"] = None
            failed_result["evidence"] = {
                "failure_reason": "target_binding_visual_relocation_exhausted_before_stage"
            }
            failed_path = Path(temp_dir) / "failed_action_result.json"
            self._write_json(failed_path, failed_result)

            result_exit, _, _ = self._run([
                "action",
                "record-result",
                "--data-dir",
                str(data_dir),
                "--input",
                str(failed_path),
            ])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            retry_scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            retry_scan["captured_at"] = "2026-05-26T10:01:00Z"
            retry_scan["thread_observations"][0]["observation"]["observation_id"] = "obs_ada_002"
            retry_scan_path = Path(temp_dir) / "retry_scan_batch.json"
            self._write_json(retry_scan_path, retry_scan)
            retry_exit, retry_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(retry_scan_path),
            ])

        self.assertEqual(result_exit, 0)
        self.assertEqual(states_exit, 0)
        state_by_match = {state["match_id"]: state for state in states_payload["states"]}
        failed_state = state_by_match[first_request["match_id"]]
        self.assertEqual(failed_state["state"], "draft_ready")
        self.assertNotIn("last_outbound_payload_hash", failed_state)
        self.assertEqual(failed_state["last_failed_outbound_payload_hash"], first_request["payload_hash"])
        self.assertEqual(failed_state["send_retry_count"], 1)
        self.assertEqual(retry_exit, 0)
        self.assertEqual(len(retry_payload["action_requests"]), 1)
        retry_request = retry_payload["action_requests"][0]
        self.assertEqual(retry_request["payload_hash"], first_request["payload_hash"])
        self.assertNotEqual(retry_request["action_request_id"], first_request["action_request_id"])
        self.assertTrue(retry_request["action_request_id"].endswith("_retry1"))
        self.assertNotIn("duplicate_send_request_suppressed", retry_payload["warnings"])

    def test_stale_same_payload_hash_in_non_active_state_retries_instead_of_suppressing(self):
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
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            _, first_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(FIXTURE_DIR / "scan_batch_initial.json"),
            ])
            first_request = first_payload["action_requests"][0]

            repo = AutomationRepository(data_dir)
            states = repo.load_states()
            for state in states:
                if state.get("match_id") == first_request["match_id"]:
                    state["state"] = "needs_thread_scan"
                    state["last_outbound_action_id"] = "action_result_failed_legacy"
                    state.pop("last_failed_outbound_payload_hash", None)
                    state.pop("last_failed_action_request_id", None)
                    state.pop("last_failed_action_result_event_id", None)
                    state.pop("send_retry_count", None)
            repo.save_states(states)

            retry_scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            retry_scan["captured_at"] = "2026-05-26T10:02:00Z"
            retry_scan["thread_observations"][0]["observation"]["observation_id"] = "obs_ada_legacy_retry"
            retry_scan_path = Path(temp_dir) / "retry_scan_batch.json"
            self._write_json(retry_scan_path, retry_scan)
            retry_exit, retry_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(retry_scan_path),
            ])
            retry_state = {
                state["match_id"]: state
                for state in AutomationRepository(data_dir).load_states()
            }[first_request["match_id"]]

        self.assertEqual(retry_exit, 0)
        self.assertEqual(len(retry_payload["action_requests"]), 1)
        retry_request = retry_payload["action_requests"][0]
        self.assertEqual(retry_request["payload_hash"], first_request["payload_hash"])
        self.assertNotEqual(retry_request["action_request_id"], first_request["action_request_id"])
        self.assertTrue(retry_request["action_request_id"].endswith("_retry1"))
        self.assertNotIn("duplicate_send_request_suppressed", retry_payload["warnings"])
        self.assertEqual(retry_state["state"], "send_requested")
        self.assertEqual(retry_state["send_retry_count"], 1)

    def test_session_step_blocks_send_when_target_profile_was_not_observed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
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
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            scan["scan_budget"] = 1
            first_thread = scan["thread_observations"][0]
            scan["message_list_snapshot"]["entries"] = [scan["message_list_snapshot"]["entries"][0]]
            scan["thread_observations"] = [first_thread]
            first_thread["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before drafting.",
            }
            scan_path = root / "scan_missing_target_profile.json"
            self._write_json(scan_path, scan)

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
            self.assertEqual(step_payload["action_requests"], [])
            self.assertIn("target_profile_required", step_payload["warnings"])
            states_exit, states_payload, _ = self._run([
                "automation",
                "get-state",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(states_exit, 0)
            self.assertEqual(states_payload["states"][0]["state"], "needs_target_profile")

    def test_session_step_requeues_revision_when_content_policy_blocks_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
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
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            scan["scan_budget"] = 1
            scan["message_list_snapshot"]["entries"] = [scan["message_list_snapshot"]["entries"][0]]
            first_thread = scan["thread_observations"][0]
            scan["thread_observations"] = [first_thread]
            planner = first_thread["planner_assessment"]
            planner["recommended_stage"] = "soft_invite_probe"
            planner["recommended_move"] = "soft_invite_probe"
            planner["soft_invite_allowed"] = True
            planner["scores"]["logistics_readiness"] = 55
            planner["next_milestone"] = "轻量试探见面意愿，但不能直接敲定具体时间地点"
            draft = first_thread["draft"]
            draft["conversation_move"] = "soft_invite_probe"
            draft["best_reply"] = "那明天19:30我们去三里屯喝一杯，你看这样行吗"
            draft["safer_reply"] = "那明天19:30找个地方坐坐？"
            draft["bolder_reply"] = "那明晚三里屯见，感觉可以直接兑现奖励了"
            scan_path = root / "scan_policy_blocked_draft.json"
            self._write_json(scan_path, scan)

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
        self.assertEqual(step_payload["action_requests"], [])
        self.assertIn("draft_blocked", step_payload["warnings"])
        self.assertIn("draft_revision_required", step_payload["warnings"])
        self.assertEqual(len(step_payload["scan_requests"]), 1)
        revision_request = step_payload["scan_requests"][0]
        self.assertEqual(revision_request["candidate_key"], "row_ada")
        self.assertEqual(revision_request["reason"], "draft_revision_required")
        self.assertTrue(revision_request["requires_revised_draft"])
        self.assertEqual(revision_request["draft_revision_reason"], "content_soft_invite_detail")
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_ada"]["state"], "needs_reply")
        self.assertTrue(states_by_key["row_ada"]["draft_revision_required"])
        self.assertEqual(states_by_key["row_ada"]["draft_revision_reason"], "content_soft_invite_detail")

    def test_non_nudge_send_cannot_bypass_latest_turn_by_declaring_nudge_draft_kind(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            scan = json.loads((FIXTURE_DIR / "scan_batch_initial.json").read_text(encoding="utf-8"))
            first_thread = scan["thread_observations"][0]
            first_thread["observation"]["conversation_observation"]["visible_messages"] = [
                {"sender": "user", "text": "你猜猜会有什么奖励"},
                {"sender": "user", "text": "那我来定"},
            ]
            first_thread["draft"]["draft_kind"] = "nudge"
            observation = AppObservation.from_dict(first_thread["observation"])
            repo = AutomationRepository(data_dir)
            ingest = repo._store_observation(observation)
            action_requests: list[dict] = []
            scan_requests: list[dict] = []
            warnings: list[str] = []
            state = {
                "match_id": ingest["match_id"],
                "candidate_key": "row_ada",
                "state": "needs_reply",
            }

            repo._queue_send_request(
                action_requests=action_requests,
                scan_requests=scan_requests,
                warnings=warnings,
                state=state,
                match_id=ingest["match_id"],
                candidate_key="row_ada",
                observation=observation,
                draft_payload=first_thread["draft"],
                latest_fingerprint="ada:in:reward-choice",
                is_nudge=False,
                authorization=json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8")),
            )

        self.assertEqual(action_requests, [])
        self.assertIn("latest_turn_required", warnings)
        self.assertIn("draft_evidence_required", warnings)

    def test_automation_context_uses_projection_plus_latest_observation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = AutomationRepository(data_dir)
            first_payload = json.loads(Path("tests/fixtures/intelligence/app_observation_chat.json").read_text(encoding="utf-8"))
            first_observation = AppObservation.from_dict(first_payload)
            first_ingest = repo._store_observation(first_observation)
            match_id = first_ingest["match_id"]

            second_payload = dict(first_payload)
            second_payload["observation_id"] = "obs_chat_002"
            second_payload["captured_at"] = "2026-05-26T00:00:00Z"
            second_payload["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
            }
            second_payload["conversation_observation"] = {
                "visible_messages": [
                    {"sender": "user", "text": "哈哈这个我记得"},
                    {"sender": "match", "text": "那你周末一般会去听现场吗"},
                ],
                "input_state": "empty",
                "thread_cues": ["weekend live music question"],
            }
            second_observation = AppObservation.from_dict(second_payload)
            repo._store_observation(second_observation)

            context_pack = repo._context_pack(match_id, second_observation)

            items = {item["label"]: item["content"] for item in context_pack["items"]}
            self.assertIn("match_hooks", items)
            self.assertIn("Ask about live music", items["match_hooks"])
            self.assertEqual(
                items["latest_inbound_messages"][-1]["text"],
                "那你周末一般会去听现场吗",
            )

    def test_automation_context_exposes_only_identity_diagnostic_for_untrusted_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            repo = AutomationRepository(data_dir)
            match_id = "match_untrusted"
            payload = json.loads(Path("tests/fixtures/intelligence/app_observation_chat.json").read_text(encoding="utf-8"))
            observation = AppObservation.from_dict(payload)
            MemoryRepository(data_dir).save_projection(
                match_id,
                MatchMemoryProjection(
                    match_id=match_id,
                    identity_status=IdentityTrustStatus.NEEDS_CONFIRMATION,
                    trusted_for_context=False,
                    trusted_for_managed_send=False,
                    updated_at="2026-06-06T00:00:00Z",
                ),
            )

            context_pack = repo._context_pack(match_id, observation)
            encoded_context = json.dumps(context_pack, ensure_ascii=False)
            items = {item["label"]: item["content"] for item in context_pack["items"]}

            self.assertIn("identity_trust", items)
            self.assertNotIn("latest_inbound_messages", items)
            self.assertNotIn("recent_messages", items)
            self.assertNotIn("It was. What are you up to this weekend?", encoded_context)

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
            if restart_exit != 0 and restart_payload.get("status") == "needs_memory_review":
                from dating_boost.core.memory.review_queue import ReviewQueueRepository
                review_repo = ReviewQueueRepository(data_dir)
                pending = review_repo.load_items(status="pending")
                session_id = pending[0].session_id if pending else ""
                confirm_token = f"memory-review:{session_id}"
                reject_ids = [item.review_item_id for item in pending]
                if reject_ids:
                    self._run([
                        "memory", "review", "decide",
                        "--data-dir", str(data_dir),
                        "--confirm", confirm_token,
                        "--reject", *reject_ids,
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

    def test_authorization_scope_app_allowlist_quiet_hours_and_verification_gate_send(self):
        cases = [
            ("draft_only_scope", {"scope": "draft_only"}, "authorization_scope_not_send_chat_messages"),
            ("wrong_app", {"app_id": "wechat"}, "authorization_app_mismatch"),
            (
                "match_not_allowed",
                {"allowed_match_ids": ["match_not_ada"]},
                "authorization_match_not_allowed",
            ),
            (
                "quiet_hours",
                {"quiet_hours": [{"start": "00:00", "end": "23:59"}]},
                "authorization_quiet_hours",
            ),
            (
                "missing_post_action_verification",
                {"requires_post_action_verification": False},
                "authorization_requires_post_action_verification",
            ),
        ]
        for name, overrides, warning in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    data_dir = Path(temp_dir) / "data"
                    auth_path = Path(temp_dir) / f"{name}.json"
                    auth_payload = json.loads((FIXTURE_DIR / "auth_send.json").read_text(encoding="utf-8"))
                    auth_payload.update(overrides)
                    self._write_json(auth_path, auth_payload)
                    self._init_profile(data_dir)
                    self._run([
                        "automation",
                        "session",
                        "start",
                        "--data-dir",
                        str(data_dir),
                        "--authorization",
                        str(auth_path),
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
                    self.assertEqual(step_payload["action_requests"], [])
                    self.assertIn(warning, step_payload["warnings"])

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

    def test_opportunity_priority_beats_new_unread_when_budget_is_tight(self):
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
                            "match_id": "match_due",
                            "candidate_key": "row_due",
                            "state": "nudge_scheduled",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "latest_inbound_fingerprint": "due:fp",
                            "last_nudged_inbound_fingerprint": None,
                            "next_due_at": "2026-05-26T00:00:00Z",
                            "last_session_id": "session_priority_due",
                        }
                    ],
                },
            )
            priority_scan = {
                "schema_version": 1,
                "session_id": "session_priority_due",
                "app_id": "tinder",
                "captured_at": "2026-05-26T00:01:00Z",
                "scan_cursor": {"current": "page_1", "next": "page_2", "exhausted": False},
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_new",
                            "visible_name": "New",
                            "latest_preview": "刚匹配",
                            "latest_preview_hash": "new_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_due",
                            "visible_name": "Due",
                            "latest_preview": "上次聊到这",
                            "latest_preview_hash": "due_hash",
                            "timestamp_cue": "30分钟前",
                            "unread_cue": "absent",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "priority_due_scan.json"
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
        self.assertEqual(step_payload["scan_requests"][0]["candidate_key"], "row_due")
        self.assertEqual(step_payload["scheduled_actions"][0]["type"], "scan_later")
        self.assertEqual(step_payload["scheduled_actions"][0]["candidate_key"], "row_new")
        self.assertEqual(step_payload["scheduled_actions"][0]["scan_cursor"], priority_scan["scan_cursor"])

    def test_unread_known_continuation_beats_absent_unread_stale_new_candidate_when_budget_is_tight(self):
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
                            "match_id": "match_xiaoyaowan",
                            "candidate_key": "row_xiaoyaowan",
                            "state": "needs_thread_scan",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_preview_hash": "same_waiting_reply_hash",
                            "last_session_id": "session_priority_unread_continuation",
                        }
                    ],
                },
            )
            priority_scan = {
                "schema_version": 1,
                "session_id": "session_priority_unread_continuation",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_stale_old",
                            "visible_name": "Old stale",
                            "latest_preview": "四个月前的旧反应",
                            "latest_preview_hash": "old_stale_hash",
                            "timestamp_cue": "",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_xiaoyaowan",
                            "visible_name": "小药丸儿",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "same_waiting_reply_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "priority_unread_continuation_scan.json"
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
        self.assertEqual(step_payload["scan_requests"][0]["candidate_key"], "row_xiaoyaowan")
        self.assertEqual(step_payload["scheduled_actions"][0]["candidate_key"], "row_stale_old")

    def test_session_step_skips_non_chat_message_list_gates(self):
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
                            "match_id": "provisional_tashuo_liked_you_gate_29_active",
                            "candidate_key": "tashuo_liked_you_gate_29_active",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "29人喜欢了你",
                            "latest_preview": "有人刚刚活跃，去打个招呼吧!",
                            "unread_cue": "present",
                            "last_session_id": "session_gate_filter",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_visual_8181c3ffffffff80",
                            "candidate_key": "tashuo_visual_8181c3ffffffff80",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Pending question avatar (illustration)",
                            "unread_cue": "present",
                            "last_session_id": "session_gate_filter",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_visual_000000ffffe7e7ef",
                            "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Tab header: 消息 / 动态",
                            "unread_cue": None,
                            "last_session_id": "session_gate_filter",
                        },
                        {
                            "schema_version": 1,
                            "match_id": "provisional_tashuo_visual_0080c1ffffffffff",
                            "candidate_key": "tashuo_visual_0080c1ffffffffff",
                            "state": "needs_thread_scan",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "匿名提问卡片",
                            "unread_cue": "present",
                            "last_session_id": "session_gate_filter",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_gate_filter",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 5,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "tashuo_liked_you_gate_29_active",
                            "candidate_type": "premium_or_liked_you_gate",
                            "visible_name": "29人喜欢了你",
                            "latest_preview": "有人刚刚活跃，去打个招呼吧!",
                            "latest_preview_hash": "liked_you_gate_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 1,
                        },
                        {
                            "candidate_key": "tashuo_visual_8181c3ffffffff80",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Pending question avatar (illustration)",
                            "latest_preview": "Pending question row avatar",
                            "latest_preview_hash": "pending_question_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 2,
                        },
                        {
                            "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "Tab header: 消息 / 动态",
                            "latest_preview": "Message tab header",
                            "latest_preview_hash": "tab_header_hash",
                            "timestamp_cue": "",
                            "unread_cue": "absent",
                            "position": 3,
                        },
                        {
                            "candidate_key": "tashuo_visual_0080c1ffffffffff",
                            "candidate_type": "new_match_candidate",
                            "visible_name": "匿名提问卡片",
                            "latest_preview": "待回答横向问题卡片",
                            "latest_preview_hash": "anonymous_question_card_hash",
                            "timestamp_cue": "",
                            "unread_cue": "present",
                            "position": 4,
                        },
                        {
                            "candidate_key": "row_ordinary",
                            "visible_name": "Ada",
                            "latest_preview": "刚刚问你今天忙不忙",
                            "latest_preview_hash": "ordinary_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 5,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "scan_with_gate.json"
            self._write_json(scan_path, scan)

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
        self.assertIn("non_chat_message_list_entry_skipped", step_payload["warnings"])
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_ordinary"])
        queued_keys = [item["candidate_key"] for item in step_payload["next_priority_queue"]]
        self.assertNotIn("tashuo_liked_you_gate_29_active", queued_keys)
        self.assertNotIn("tashuo_visual_8181c3ffffffff80", queued_keys)
        self.assertNotIn("tashuo_visual_000000ffffe7e7ef", queued_keys)
        self.assertNotIn("tashuo_visual_0080c1ffffffffff", queued_keys)
        self.assertIn("row_ordinary", queued_keys)

    def test_session_step_skips_tashuo_visual_rows_without_visible_name(self):
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
            scan = {
                "schema_version": 1,
                "session_id": "session_tashuo_empty_name_filter",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 2,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "tashuo_visual_0f3990839b0a",
                            "candidate_type": "continuation_candidate",
                            "latest_preview": "",
                            "latest_preview_hash": "empty_name_hash",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_ordinary",
                            "visible_name": "Ada",
                            "latest_preview": "刚刚问你忙不忙",
                            "latest_preview_hash": "ordinary_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "scan_with_empty_name_tashuo_visual_row.json"
            self._write_json(scan_path, scan)

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
        self.assertIn("non_chat_message_list_entry_skipped", step_payload["warnings"])
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_ordinary"])

    def test_session_step_queues_recent_open_chat_after_unread_continuation(self):
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
                            "match_id": "match_reply",
                            "candidate_key": "row_reply",
                            "state": "needs_thread_scan",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_preview_hash": "reply_old_hash",
                            "last_session_id": "session_open_chat_recent",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_open_chat_recent",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 2,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Newly Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "open_chat_recent_hash",
                            "timestamp_cue": "2天前",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_reply",
                            "visible_name": "小药丸儿",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "reply_new_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "recent_open_chat_scan.json"
            self._write_json(scan_path, scan)

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
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_reply", "row_open_chat"])
        self.assertNotIn("message_list_history_cutoff_reached", step_payload["warnings"])
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_open_chat"]["candidate_type"], "open_chat_candidate")
        self.assertEqual(states_by_key["row_open_chat"]["state"], "needs_thread_scan")

    def test_session_step_prioritizes_unseen_continuation_before_open_chat(self):
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
            scan = {
                "schema_version": 1,
                "session_id": "session_open_chat_after_continuation",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 3,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Newly Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "open_chat_recent_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_continuation",
                            "candidate_type": "continuation_candidate",
                            "visible_name": "小药丸儿",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "reply_new_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "absent",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "open_chat_after_continuation_scan.json"
            self._write_json(scan_path, scan)

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
        self.assertEqual(
            [item["candidate_key"] for item in step_payload["scan_requests"]],
            ["row_continuation", "row_open_chat"],
        )

    def test_session_step_history_cutoff_skips_old_open_chat_and_lower_rows(self):
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
            scan = {
                "schema_version": 1,
                "session_id": "session_history_cutoff",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_cursor": {"current": "page_1", "next": "page_2", "exhausted": False},
                "scan_budget": 5,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_recent_reply",
                            "visible_name": "Recent",
                            "latest_preview": "刚刚问你今天忙不忙",
                            "latest_preview_hash": "recent_hash",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_old_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Old Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "old_open_chat_hash",
                            "timestamp_cue": "4个月前",
                            "unread_cue": "absent",
                            "position": 2,
                        },
                        {
                            "candidate_key": "row_below_old",
                            "visible_name": "Below Old",
                            "latest_preview": "更旧的一行",
                            "latest_preview_hash": "below_old_hash",
                            "timestamp_cue": "5个月前",
                            "unread_cue": "absent",
                            "position": 3,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "history_cutoff_scan.json"
            self._write_json(scan_path, scan)

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
        self.assertTrue(step_payload["history_cutoff_reached"])
        self.assertEqual(step_payload["historical_entry_count"], 2)
        self.assertIn("message_list_history_cutoff_reached", step_payload["warnings"])
        self.assertEqual([item["candidate_key"] for item in step_payload["scan_requests"]], ["row_recent_reply"])
        self.assertEqual(
            [item["candidate_key"] for item in step_payload["scheduled_actions"] if item["type"] == "historical_thread_skipped"],
            ["row_old_open_chat", "row_below_old"],
        )
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_old_open_chat"]["state"], "historical_thread")
        self.assertEqual(states_by_key["row_below_old"]["state"], "historical_thread")
        queued_keys = [item["candidate_key"] for item in step_payload["next_priority_queue"]]
        self.assertNotIn("row_old_open_chat", queued_keys)
        self.assertNotIn("row_below_old", queued_keys)

    def test_session_step_history_cutoff_treats_reply_badge_below_old_row_as_historical(self):
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
            scan = {
                "schema_version": 1,
                "session_id": "session_history_cutoff_reply_badge",
                "app_id": "tashuo",
                "captured_at": "2026-06-17T08:52:19Z",
                "scan_cursor": {"current": "page_1", "next": None, "exhausted": True},
                "scan_budget": 5,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_old_open_chat",
                            "candidate_type": "open_chat_candidate",
                            "visible_name": "Old Open",
                            "latest_preview": "你们已经可以进行会话了，开启聊天",
                            "latest_preview_hash": "old_open_chat_hash",
                            "timestamp_cue": "4个月前",
                            "unread_cue": "absent",
                            "position": 1,
                        },
                        {
                            "candidate_key": "row_reply_below_old",
                            "candidate_type": "continuation_candidate",
                            "visible_name": "Reply Below Old",
                            "latest_preview": "我晚上上班呀",
                            "latest_preview_hash": "reply_below_old_hash",
                            "timestamp_cue": "去回复 badge",
                            "unread_cue": "reply_badge",
                            "position": 2,
                        },
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "history_cutoff_reply_badge_scan.json"
            self._write_json(scan_path, scan)

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
        self.assertTrue(step_payload["history_cutoff_reached"])
        self.assertEqual(step_payload["historical_entry_count"], 2)
        self.assertEqual(step_payload["scan_requests"], [])
        self.assertEqual(
            [item["candidate_key"] for item in step_payload["scheduled_actions"] if item["type"] == "historical_thread_skipped"],
            ["row_old_open_chat", "row_reply_below_old"],
        )
        self.assertEqual(states_exit, 0)
        states_by_key = {state["candidate_key"]: state for state in states_payload["states"]}
        self.assertEqual(states_by_key["row_old_open_chat"]["state"], "historical_thread")
        self.assertEqual(states_by_key["row_reply_below_old"]["state"], "historical_thread")
        queued_keys = [item["candidate_key"] for item in step_payload["next_priority_queue"]]
        self.assertNotIn("row_reply_below_old", queued_keys)

    def test_session_step_keeps_stable_waiting_state_without_thread_scan(self):
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
                            "match_id": "match_waiting",
                            "candidate_key": "row_waiting",
                            "state": "waiting_for_match",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "visible_name": "Waiting",
                            "last_preview_hash": "sha256:same_outbound_preview",
                            "last_session_id": "session_stable_waiting",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_stable_waiting",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_waiting",
                            "visible_name": "Waiting",
                            "latest_preview": "哈哈好的!",
                            "latest_preview_hash": "sha256:same_outbound_preview",
                            "timestamp_cue": "",
                            "unread_cue": "absent",
                            "position": 1,
                        }
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "stable_waiting_scan.json"
            self._write_json(scan_path, scan)

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
        self.assertEqual(step_payload["scan_requests"], [])
        self.assertEqual(states_exit, 0)
        self.assertEqual(states_payload["states"][0]["state"], "waiting_for_match")
        self.assertEqual(step_payload["next_priority_queue"][0]["state"], "waiting_for_match")

    def test_session_step_ignores_residual_unread_after_successful_send_when_preview_is_unchanged(self):
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
                            "match_id": "match_sent",
                            "candidate_key": "row_sent",
                            "state": "sent_waiting",
                            "candidate_type": "continuation_candidate",
                            "seen_before": True,
                            "last_preview_hash": "sha256:same_preview",
                            "last_outbound_action_id": "action_result_success",
                            "last_session_id": "session_residual_unread",
                        }
                    ],
                },
            )
            scan = {
                "schema_version": 1,
                "session_id": "session_residual_unread",
                "app_id": "tashuo",
                "captured_at": "2026-05-26T12:00:00Z",
                "scan_budget": 1,
                "message_list_snapshot": {
                    "entries": [
                        {
                            "candidate_key": "row_sent",
                            "visible_name": "Sent",
                            "latest_preview": "同一个预览",
                            "latest_preview_hash": "sha256:same_preview",
                            "timestamp_cue": "刚刚",
                            "unread_cue": "present",
                            "position": 1,
                        }
                    ]
                },
                "thread_observations": [],
            }
            scan_path = Path(temp_dir) / "residual_unread_scan.json"
            self._write_json(scan_path, scan)

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
        self.assertEqual(step_payload["scan_requests"], [])
        self.assertEqual(states_exit, 0)
        self.assertEqual(states_payload["states"][0]["state"], "sent_waiting")

    def test_handoff_opportunity_without_existing_state_beats_new_match(self):
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
            priority_scan = _contact_exchange_scan_batch()
            priority_scan["scan_budget"] = 1
            priority_scan["message_list_snapshot"]["entries"].insert(
                0,
                {
                    "candidate_key": "row_new",
                    "visible_name": "New",
                    "latest_preview": "刚匹配",
                    "latest_preview_hash": "new_hash",
                    "timestamp_cue": "刚刚",
                    "unread_cue": "present",
                    "position": 1,
                },
            )
            scan_path = Path(temp_dir) / "priority_handoff_scan.json"
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
        self.assertEqual(step_payload["handoffs"][0]["candidate_key"], "row_iris")
        self.assertEqual(step_payload["scheduled_actions"][0]["type"], "scan_later")
        self.assertEqual(step_payload["scheduled_actions"][0]["candidate_key"], "row_new")

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

    def test_due_nudge_blocks_when_target_profile_was_not_observed(self):
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
            due_scan["thread_observations"][0]["observation"]["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
                "review_status": "missing",
                "evidence": "Profile was not opened before a due nudge.",
            }
            due_scan_path = Path(temp_dir) / "due_scan_missing_profile.json"
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
                states_exit, states_payload, _ = self._run([
                    "automation",
                    "get-state",
                    "--data-dir",
                    str(data_dir),
                ])

        self.assertEqual(due_exit, 0)
        self.assertEqual(due_payload["action_requests"], [])
        self.assertIn("target_profile_required", due_payload["warnings"])
        self.assertEqual(states_exit, 0)
        self.assertEqual(states_payload["states"][0]["state"], "needs_target_profile")

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
        UserMemoryRepository(data_dir).ensure_profile_source(
            app_id="tinder",
            runtime="default",
            observed_at="2026-05-26T00:00:00Z",
        )

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
        "draft_generation_id": "draft_generation_nudge_fixture",
        "draft_self_review_summary": {
            "schema_version": 1,
            "ai_or_weird_probability": 0,
            "status": "ok",
            "source": "unit_fixture",
        },
    }


if __name__ == "__main__":
    unittest.main()
