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


class AutomationPlannerTests(unittest.TestCase):
    def setUp(self):
        self._clock_patch = patch.dict(os.environ, {"DATING_BOOST_NOW": "2026-05-26T08:00:00Z"})
        self._clock_patch.start()

    def tearDown(self):
        self._clock_patch.stop()

    def test_session_step_updates_goal_plan_and_blocks_misaligned_draft(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            bad_scan_path = Path(temp_dir) / "misaligned_scan.json"
            good_scan_path = Path(temp_dir) / "aligned_scan.json"
            self._write_json(bad_scan_path, _planner_scan(draft_move="deepen_current"))
            self._write_json(good_scan_path, _planner_scan(draft_move="bridge_topic"))

            bad_exit, bad_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(bad_scan_path),
            ])
            good_exit, good_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(good_scan_path),
            ])

            self.assertEqual(bad_exit, 0)
            self.assertEqual(bad_payload["action_requests"], [])
            self.assertIn("planner_misaligned_draft", bad_payload["warnings"])
            match_id = bad_payload["state_updates"][0]["match_id"]
            plan_exit, plan_payload, _ = self._run([
                "planner",
                "get",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--json",
            ])
            self.assertEqual(plan_exit, 0)
            self.assertEqual(plan_payload["goal_plan"]["recommended_move"], "bridge_topic")
            self.assertEqual(good_exit, 0)
            self.assertEqual(len(good_payload["action_requests"]), 1)
            action_request = good_payload["action_requests"][0]
            self.assertEqual(action_request["conversation_move"], "bridge_topic")
            self.assertEqual(action_request["conversation_stage"], "warmup")
            self.assertEqual(action_request["planner_alignment"], "ok")
            self.assertEqual(action_request["next_milestone"], "从猫桥到她平时在家状态")

    def test_session_step_requires_planner_assessment_before_auto_send(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            scan = _planner_scan(draft_move="bridge_topic")
            scan["thread_observations"][0].pop("planner_assessment")
            scan_path = Path(temp_dir) / "no_planner_scan.json"
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
            self.assertIn("planner_assessment_required", step_payload["warnings"])
            self.assertEqual(step_payload["state_updates"][0]["state"], "needs_reply")

    def test_draft_alignment_requires_matching_move_not_explanation_substring(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            scan = _planner_scan(draft_move="deepen_current")
            scan["thread_observations"][0]["draft"]["why_this_works"] = (
                "Mentions bridge_topic, but the draft move is still deepen_current."
            )
            scan_path = Path(temp_dir) / "substring_alignment_scan.json"
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
            self.assertIn("planner_misaligned_draft", step_payload["warnings"])

    def test_planner_handoff_blocks_auto_send_even_when_assessment_says_reply(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            scan_path = Path(temp_dir) / "handoff_scan.json"
            self._write_json(
                scan_path,
                _planner_scan(
                    planner_stage="appointment_handoff",
                    planner_move="handoff",
                    draft_move="bridge_topic",
                    soft_invite_allowed=False,
                    logistics_readiness=80,
                ),
            )

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
            self.assertEqual(step_payload["handoffs"][0]["reason"], "appointment_details_requested")
            self.assertEqual(step_payload["handoffs"][0]["planner_stage"], "appointment_handoff")
            self.assertEqual(step_payload["handoffs"][0]["suggested_user_decision"], "选择具体日期、时间段、区域")

    def test_planner_handoff_reserves_appointment_slot_and_detects_conflict(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            slot = {"date": "2026-06-06", "time_window": "19:00-21:00", "area": "朝阳"}
            first_scan = _planner_scan(
                candidate_key="row_xiaoqing",
                visible_name="小青",
                conversation_fingerprint="xiaoqing-slot",
                planner_stage="appointment_handoff",
                planner_move="handoff",
                appointment_slot=slot,
            )
            second_scan = _planner_scan(
                candidate_key="row_xiaolan",
                visible_name="小蓝",
                conversation_fingerprint="xiaolan-slot",
                planner_stage="appointment_handoff",
                planner_move="handoff",
                appointment_slot=slot,
            )
            first_path = Path(temp_dir) / "first_slot_scan.json"
            second_path = Path(temp_dir) / "second_slot_scan.json"
            self._write_json(first_path, first_scan)
            self._write_json(second_path, second_scan)

            first_exit, first_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(first_path),
            ])
            second_exit, second_payload, _ = self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(second_path),
            ])

            self.assertEqual(first_exit, 0)
            self.assertFalse(first_payload["handoffs"][0]["slot_conflict"])
            self.assertEqual(second_exit, 0)
            self.assertTrue(second_payload["handoffs"][0]["slot_conflict"])
            self._run([
                "automation",
                "session",
                "stop",
                "--data-dir",
                str(data_dir),
            ])
            report_exit, report_payload, _ = self._run([
                "automation",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
            ])
            self.assertEqual(report_exit, 0)
            ledger = report_payload["machine_report"]["appointment_ledger"]
            self.assertEqual(len(ledger), 2)
            self.assertTrue(any(slot["conflict"] for slot in ledger))

    def test_planner_handoff_preserves_contact_exchange_reason(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            scan = _planner_scan(
                planner_stage="appointment_handoff",
                planner_move="handoff",
                planner_handoff_reason="contact_exchange",
            )
            scan_path = Path(temp_dir) / "planner_contact_handoff.json"
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
            self.assertEqual(step_payload["handoffs"][0]["reason"], "contact_exchange")

    def test_low_investment_repair_can_send_self_disclosure_instead_of_more_questions(self):
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
            scan_path = Path(temp_dir) / "low_repair.json"
            self._write_json(
                scan_path,
                _planner_scan(
                    planner_move="low_investment_repair",
                    draft_move="low_investment_repair",
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 3,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 2,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "high",
                        "last_user_turn_type": "question",
                    },
                    draft_overrides={
                        "best_reply": "感觉你家已经很会享受安静了，我有时候也是在家憋久了才突然想出去透口气",
                        "conversation_move": "low_investment_repair",
                        "disclosure_source": "user_material",
                        "used_user_material_ids": ["mat_home_rhythm"],
                    },
                ),
            )

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
            self.assertEqual(len(step_payload["action_requests"]), 1)
            request = step_payload["action_requests"][0]
            self.assertEqual(request["conversation_move"], "low_investment_repair")
            self.assertEqual(request["disclosure_source"], "user_material")
            self.assertEqual(request["used_user_material_ids"], ["mat_home_rhythm"])
            self.assertTrue(request["low_investment_repair_applied"])

    def test_material_only_policy_blocks_simulated_self_disclosure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._init_profile(data_dir)
            disclosure_path = data_dir / "user" / "disclosure_profile.json"
            profile = json.loads(disclosure_path.read_text(encoding="utf-8"))
            profile["simulation_policy"] = "material_only"
            disclosure_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
            self._run([
                "automation",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                str(FIXTURE_DIR / "auth_send.json"),
            ])
            scan_path = Path(temp_dir) / "simulated_disclosure.json"
            self._write_json(
                scan_path,
                _planner_scan(
                    planner_move="low_investment_repair",
                    draft_move="low_investment_repair",
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 3,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 2,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "high",
                        "last_user_turn_type": "question",
                    },
                    draft_overrides={
                        "best_reply": "我有时候也是在家待久了才突然想出门透口气",
                        "conversation_move": "low_investment_repair",
                    },
                ),
            )

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
            self.assertIn("simulated_disclosure_not_allowed", step_payload["warnings"])

    def test_low_investment_debt_blocks_bridge_question(self):
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
            scan_path = Path(temp_dir) / "bridge_question.json"
            self._write_json(
                scan_path,
                _planner_scan(
                    planner_move="bridge_topic",
                    draft_move="bridge_topic",
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 3,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 2,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "high",
                        "last_user_turn_type": "question",
                    },
                    draft_overrides={
                        "best_reply": "感觉你家小动物含量有点高，你平时是不是还挺宅的",
                        "conversation_move": "bridge_topic",
                    },
                ),
            )

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
            self.assertIn("low_investment_direct_question_blocked", step_payload["warnings"])

    def test_session_report_includes_planner_progress(self):
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
                "tests/fixtures/automation/auth_send.json",
            ])
            scan_path = Path(temp_dir) / "aligned_scan.json"
            self._write_json(scan_path, _planner_scan(draft_move="bridge_topic"))
            self._run([
                "automation",
                "session",
                "step",
                "--data-dir",
                str(data_dir),
                "--scan-batch",
                str(scan_path),
            ])
            stop_exit, stop_payload, _ = self._run([
                "automation",
                "session",
                "stop",
                "--data-dir",
                str(data_dir),
            ])
            report_exit, report_text = self._run_text([
                "automation",
                "report",
                "latest",
                "--data-dir",
                str(data_dir),
                "--format",
                "md",
            ])

            self.assertEqual(stop_exit, 0)
            self.assertEqual(report_exit, 0)
            self.assertIn("Conversation Plans", report_text)
            self.assertIn("stage=warmup", report_text)
            self.assertIn("move=bridge_topic", report_text)
            self.assertIn("milestone=从猫桥到她平时在家状态", report_text)

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


def _planner_scan(
    *,
    candidate_key="row_xiaoqing",
    visible_name="小青",
    conversation_fingerprint="xiaoqing_cats",
    planner_stage="warmup",
    planner_move="bridge_topic",
    planner_handoff_reason=None,
    draft_move="bridge_topic",
    soft_invite_allowed=False,
    logistics_readiness=15,
    appointment_slot=None,
    reciprocity=None,
    draft_overrides=None,
):
    why_this_works = (
        "It follows planner move bridge_topic and moves from cats to her home-life rhythm."
        if draft_move == "bridge_topic"
        else "It keeps asking about the current cat topic."
    )
    return {
        "schema_version": 1,
        "session_id": "session_planner_fixture",
        "app_id": "wechat",
        "captured_at": "2026-05-31T16:00:00+08:00",
        "scan_budget": 1,
        "message_list_snapshot": {
            "entries": [
                {
                    "candidate_key": candidate_key,
                    "visible_name": visible_name,
                    "latest_preview": "都没什么脾气我家的猫",
                    "latest_preview_hash": "preview_xiaoqing_cats",
                    "timestamp_cue": "刚刚",
                    "unread_cue": "present",
                    "position": 1,
                }
            ]
        },
        "thread_observations": [
            {
                "candidate_key": candidate_key,
                "assessment": {
                    "schema_version": 1,
                    "latest_match_message": "都没什么脾气我家的猫",
                    "latest_user_message": "它是最有脾气那个吗",
                    "latest_inbound_fingerprint": "xiaoqing:in:cats-calm",
                    "reply_window_status": "open",
                    "continuation_opportunity": "yes",
                    "appointment_stage": "none",
                    "recommended_next": "reply",
                    "confidence": "high",
                    "evidence": "Match answered the cat question.",
                    "risk_flags": [],
                },
                "planner_assessment": {
                    "schema_version": 1,
                    "latest_turn_summary": "对方回应猫的话题，但没有主动反问",
                    "latest_turn_type": "short_answer",
                    "inbound_intent": "answer",
                    "topic": {
                        "current_topic": "cats",
                        "topic_state": "saturating",
                        "new_information": ["家里的猫都没什么脾气"],
                        "stale_hooks": ["大君这个旧名字不能再当最新问题"],
                    },
                    "scores": {
                        "engagement": 52,
                        "warmth": 48,
                        "curiosity": 20,
                        "comfort": 40,
                        "momentum": 38,
                        "topic_saturation": 76,
                        "logistics_readiness": logistics_readiness,
                        "risk": 18,
                    },
                    "recommended_stage": planner_stage,
                    "recommended_move": planner_move,
                    "next_milestone": "从猫桥到她平时在家状态",
                    "avoid_next": ["继续问哪只猫最有脾气", "继续问猫名字"],
                    "soft_invite_allowed": soft_invite_allowed,
                    "confidence": "high",
                    "evidence": "latest_inbound_messages only answered the cat temperament question; no new strong hook.",
                    **({"reciprocity": reciprocity} if reciprocity else {}),
                    **({"handoff_reason": planner_handoff_reason} if planner_handoff_reason else {}),
                },
                **({"appointment_slot": appointment_slot} if appointment_slot else {}),
                "observation": {
                    "observation_id": "obs_xiaoqing_cats_001",
                    "source_type": "manual_fixture",
                    "app_id": "wechat",
                    "adapter_id": "codex.manual.v1",
                    "captured_at": "2026-05-31T16:00:00+08:00",
                    "page_type": "chat_thread",
                    "page_confidence": "high",
                    "match_identity_hints": {
                            "visible_name": visible_name,
                        "profile_cues": ["cats"],
                            "conversation_fingerprint": conversation_fingerprint,
                        "evidence": "Visible chat thread.",
                    },
                    "profile_observation": {
                        "profile_text": "养猫，喜欢简单真诚。",
                        "photo_cues": ["cat photo"],
                        "hook_candidates": ["cats", "home life"],
                    },
                    "conversation_observation": {
                        "visible_messages": [
                            {"sender": "user", "text": "它是最有脾气那个吗"},
                            {"sender": "match", "text": "还好呀"},
                            {"sender": "match", "text": "都没什么脾气我家的猫"},
                        ],
                        "latest_inbound_messages": [
                            {"sender": "match", "text": "还好呀"},
                            {"sender": "match", "text": "都没什么脾气我家的猫"},
                        ],
                        "input_state": "empty",
                        "thread_cues": ["cat temperament answered"],
                    },
                    "element_observations": [],
                    "exception_state": "none",
                    "provenance": {"evidence": "Fixture."},
                    "raw_ref": None,
                },
                "draft": {
                    "best_reply": "感觉你家已经是小型动物园了，你平时是在家待着就很充电的人吗",
                    "safer_reply": "感觉你家小动物含量有点高，你平时是不是还挺宅的",
                    "bolder_reply": "感觉你家猫已经把你训练得很会相处了哈哈",
                    "why_this_works": why_this_works,
                    "situation_read": "The cat topic is close to saturation, so bridge gently.",
                    "conversation_move": draft_move,
                    "hook_source": "conversation_thread",
                    "naturalness_notes": ["short", "bridges from cats to lifestyle"],
                    "followup_if_match_replies": "If she answers about home life, lightly self-disclose.",
                    "risk_flags": [],
                    "missing_info": [],
                    "mode_notes": "Adaptive mode.",
                    "persona_divergence": "low",
                    "stance_divergence": "low",
                    **(draft_overrides or {}),
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
