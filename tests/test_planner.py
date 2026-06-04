import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main
from dating_boost.core.planner import PlannerRepository
from dating_boost.perception.observations import AppObservation


NOW = "2026-05-31T16:00:00+08:00"


class PlannerCoreTests(unittest.TestCase):
    def test_update_creates_goal_plan_and_event_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            observation = _observation("obs_cat_001")
            assessment = _planner_assessment(
                recommended_move="bridge_topic",
                current_topic="cats",
                topic_state="saturating",
                topic_saturation=76,
            )

            payload = PlannerRepository(data_dir).update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=observation,
                assessment=assessment,
                now=NOW,
            )

            self.assertEqual(payload["status"], "ok")
            plan = payload["goal_plan"]
            self.assertEqual(plan["match_id"], "match_xiaoqing")
            self.assertEqual(plan["goal_type"], "meet_in_person")
            self.assertEqual(plan["stage"], "warmup")
            self.assertEqual(plan["recommended_move"], "bridge_topic")
            self.assertEqual(plan["scores"]["topic_saturation"], 76)
            self.assertEqual(plan["plan_revision"], 1)
            self.assertEqual(plan["last_observation_id"], "obs_cat_001")
            self.assertTrue((data_dir / "matches" / "match_xiaoqing" / "goal_plan.json").exists())

            events = PlannerRepository(data_dir).event_log("match_xiaoqing")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event_type"], "planner_update")
            self.assertEqual(events[0]["planner_revision"], 1)

    def test_update_accepts_explicit_goal_type_from_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            payload = PlannerRepository(data_dir).update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_rapport",
                goal_type="build_rapport",
                observation=_observation("obs_rapport_001"),
                assessment=_planner_assessment(
                    recommended_move="deepen_current",
                    current_topic="weekend",
                    topic_state="active",
                ),
                now=NOW,
            )

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["goal_plan"]["goal_type"], "build_rapport")
            self.assertEqual(payload["goal_plan"]["goal_id"], "goal_rapport")

    def test_update_rejects_unknown_goal_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unsupported goal_type"):
                PlannerRepository(Path(temp_dir)).update_plan(
                    match_id="match_xiaoqing",
                    goal_id="goal_unknown",
                    goal_type="unknown_goal",
                    observation=_observation("obs_unknown_001"),
                    assessment=_planner_assessment(),
                    now=NOW,
                )

    def test_update_increments_revision_and_topic_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))

            first = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_cat_001"),
                assessment=_planner_assessment(current_topic="cats", topic_state="active"),
                now=NOW,
            )
            second = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_cat_002"),
                assessment=_planner_assessment(current_topic="cats", topic_state="saturating"),
                now="2026-05-31T16:05:00+08:00",
            )

            self.assertEqual(first["goal_plan"]["plan_revision"], 1)
            self.assertEqual(second["goal_plan"]["plan_revision"], 2)
            self.assertEqual(second["goal_plan"]["topic_history"][0]["topic"], "cats")
            self.assertEqual(second["goal_plan"]["topic_history"][0]["turn_count"], 2)
            self.assertEqual(second["goal_plan"]["topic_history"][0]["outcome"], "saturating")

    def test_topic_saturation_blocks_shallow_deepen_but_allows_bridge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))

            blocked = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_cat_001"),
                assessment=_planner_assessment(
                    recommended_move="deepen_current",
                    current_topic="cats",
                    topic_state="saturating",
                    topic_saturation=82,
                    evidence="No new strong hook; the match only answered briefly.",
                ),
                now=NOW,
            )["recommendation"]
            allowed = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_cat_002"),
                assessment=_planner_assessment(
                    recommended_move="bridge_topic",
                    current_topic="cats",
                    topic_state="saturating",
                    topic_saturation=82,
                ),
                now="2026-05-31T16:05:00+08:00",
            )["recommendation"]

            self.assertFalse(blocked["auto_send_allowed"])
            self.assertIn("topic_saturation_requires_bridge", blocked["block_reasons"])
            self.assertTrue(allowed["auto_send_allowed"])
            self.assertEqual(allowed["recommended_move"], "bridge_topic")

    def test_low_investment_question_debt_blocks_more_questions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))

            blocked = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_low_001"),
                assessment=_planner_assessment(
                    recommended_move="deepen_current",
                    topic_saturation=40,
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 3,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 2,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "medium",
                        "last_user_turn_type": "question",
                    },
                ),
                now=NOW,
            )["recommendation"]
            repair = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_low_002"),
                assessment=_planner_assessment(
                    recommended_move="low_investment_repair",
                    topic_saturation=72,
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 3,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 2,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "high",
                        "last_user_turn_type": "question",
                    },
                ),
                now="2026-05-31T16:06:00+08:00",
            )["recommendation"]

            self.assertFalse(blocked["auto_send_allowed"])
            self.assertIn("low_investment_question_debt", blocked["block_reasons"])
            self.assertTrue(repair["auto_send_allowed"])
            self.assertEqual(repair["recommended_move"], "low_investment_repair")
            self.assertEqual(repair["low_investment_streak"], 2)

    def test_fallback_reciprocity_does_not_reset_debt_from_recommended_repair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))
            repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_low_001"),
                assessment=_planner_assessment(
                    recommended_move="deepen_current",
                    topic_saturation=40,
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 3,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 1,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "medium",
                        "last_user_turn_type": "question",
                    },
                ),
                now=NOW,
            )

            repair = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_low_002"),
                assessment=_planner_assessment(
                    recommended_move="low_investment_repair",
                    topic_saturation=72,
                ),
                now="2026-05-31T16:06:00+08:00",
            )["recommendation"]

            self.assertEqual(repair["recommended_move"], "low_investment_repair")
            self.assertEqual(repair["question_debt"], 2)
            self.assertEqual(repair["self_disclosure_debt"], 3)

    def test_slow_down_wait_pauses_auto_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))

            recommendation = repo.update_plan(
                match_id="match_xiaoqing",
                goal_id="goal_meet",
                observation=_observation("obs_wait_001"),
                assessment=_planner_assessment(
                    recommended_move="slow_down_wait",
                    topic_saturation=88,
                    reciprocity={
                        "question_debt": 2,
                        "self_disclosure_debt": 4,
                        "reciprocity_balance": "user_over_asking",
                        "low_investment_streak": 3,
                        "match_curiosity_about_user": "no",
                        "topic_exit_pressure": "high",
                        "last_user_turn_type": "question",
                    },
                ),
                now=NOW,
            )["recommendation"]

            self.assertFalse(recommendation["auto_send_allowed"])
            self.assertIn("planner_wait", recommendation["block_reasons"])
            self.assertEqual(recommendation["recommended_move"], "slow_down_wait")

    def test_soft_invite_and_handoff_recommendations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))

            soft_invite = repo.update_plan(
                match_id="match_ada",
                goal_id="goal_meet",
                observation=_observation("obs_soft_invite"),
                assessment=_planner_assessment(
                    recommended_stage="soft_invite_probe",
                    recommended_move="soft_invite_probe",
                    logistics_readiness=48,
                    soft_invite_allowed=True,
                    current_topic="japanese_food",
                    topic_saturation=35,
                ),
                now=NOW,
            )["recommendation"]
            handoff = repo.update_plan(
                match_id="match_ada",
                goal_id="goal_meet",
                observation=_observation("obs_handoff"),
                assessment=_planner_assessment(
                    recommended_stage="appointment_handoff",
                    recommended_move="handoff",
                    logistics_readiness=80,
                    soft_invite_allowed=False,
                    current_topic="meeting_details",
                    topic_saturation=20,
                ),
                now="2026-05-31T16:10:00+08:00",
            )

            self.assertTrue(soft_invite["auto_send_allowed"])
            self.assertEqual(soft_invite["recommended_move"], "soft_invite_probe")
            self.assertFalse(soft_invite["requires_handoff"])
            self.assertEqual(handoff["goal_plan"]["stage"], "appointment_handoff")
            self.assertTrue(handoff["recommendation"]["requires_handoff"])
            self.assertEqual(handoff["recommendation"]["handoff_reason"], "appointment_details_requested")

    def test_handoff_reason_can_be_contact_exchange(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = PlannerRepository(Path(temp_dir))

            payload = repo.update_plan(
                match_id="match_ada",
                goal_id="goal_meet",
                observation=_observation("obs_contact"),
                assessment=_planner_assessment(
                    recommended_stage="appointment_handoff",
                    recommended_move="handoff",
                    handoff_reason="contact_exchange",
                    logistics_readiness=80,
                    soft_invite_allowed=False,
                    current_topic="contact_exchange",
                    topic_saturation=20,
                ),
                now=NOW,
            )

            self.assertEqual(payload["goal_plan"]["handoff_reason"], "contact_exchange")
            self.assertEqual(payload["recommendation"]["handoff_reason"], "contact_exchange")

    def test_planner_cli_update_get_recommend_and_event_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            observation_path = Path(temp_dir) / "observation.json"
            assessment_path = Path(temp_dir) / "assessment.json"
            observation_path.write_text(
                json.dumps(_observation("obs_cli_001").to_dict(), ensure_ascii=False),
                encoding="utf-8",
            )
            assessment_path.write_text(
                json.dumps(
                    _planner_assessment(recommended_move="bridge_topic", topic_saturation=72),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            update_exit, update_payload, _ = self._run([
                "planner",
                "update",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_cli",
                "--goal-id",
                "goal_meet",
                "--observation",
                str(observation_path),
                "--assessment",
                str(assessment_path),
                "--json",
            ])
            get_exit, get_payload, _ = self._run([
                "planner",
                "get",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_cli",
                "--json",
            ])
            recommend_exit, recommend_payload, _ = self._run([
                "planner",
                "recommend",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_cli",
                "--json",
            ])
            log_exit, log_payload, _ = self._run([
                "planner",
                "event-log",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_cli",
                "--json",
            ])

            self.assertEqual(update_exit, 0)
            self.assertEqual(update_payload["status"], "ok")
            self.assertEqual(get_exit, 0)
            self.assertEqual(get_payload["goal_plan"]["match_id"], "match_cli")
            self.assertEqual(recommend_exit, 0)
            self.assertEqual(recommend_payload["recommendation"]["recommended_move"], "bridge_topic")
            self.assertEqual(log_exit, 0)
            self.assertEqual(log_payload["events"][0]["event_type"], "planner_update")

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


def _observation(observation_id):
    return AppObservation.from_dict(
        {
            "observation_id": observation_id,
            "source_type": "manual_fixture",
            "app_id": "wechat",
            "adapter_id": "codex.manual.v1",
            "captured_at": NOW,
            "page_type": "chat_thread",
            "page_confidence": "high",
            "match_identity_hints": {
                "visible_name": "小青",
                "profile_cues": ["cats"],
                "conversation_fingerprint": "xiaoqing-cats",
                "evidence": "Visible test chat.",
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
        }
    )


def _planner_assessment(
    *,
    recommended_stage="warmup",
    recommended_move="bridge_topic",
    current_topic="cats",
    topic_state="active",
    topic_saturation=40,
    logistics_readiness=15,
    soft_invite_allowed=False,
    handoff_reason=None,
    reciprocity=None,
    evidence="latest_inbound_messages answered the current question but did not create a deeper hook.",
):
    return {
        "schema_version": 1,
        "latest_turn_summary": "对方回应猫的话题，但没有主动反问",
        "latest_turn_type": "short_answer",
        "inbound_intent": "answer",
        "topic": {
            "current_topic": current_topic,
            "topic_state": topic_state,
            "new_information": ["家里的猫都没什么脾气"],
            "stale_hooks": ["旧猫名不能当最新问题"],
        },
        "scores": {
            "engagement": 52,
            "warmth": 48,
            "curiosity": 20,
            "comfort": 40,
            "momentum": 38,
            "topic_saturation": topic_saturation,
            "logistics_readiness": logistics_readiness,
            "risk": 18,
        },
        "recommended_stage": recommended_stage,
        "recommended_move": recommended_move,
        "next_milestone": "从猫桥到她平时在家状态",
        "avoid_next": ["继续问哪只猫最有脾气", "继续问猫名字"],
        "soft_invite_allowed": soft_invite_allowed,
        "confidence": "high",
        "evidence": evidence,
        **({"reciprocity": reciprocity} if reciprocity else {}),
        **({"handoff_reason": handoff_reason} if handoff_reason else {}),
    }


if __name__ == "__main__":
    unittest.main()
