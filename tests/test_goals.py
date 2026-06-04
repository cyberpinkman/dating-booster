import unittest
import tempfile
from pathlib import Path

from dating_boost.core.automation import AutomationRepository
from dating_boost.core.goals import DEFAULT_GOAL_TYPE, GOAL_TYPE_REGISTRY, get_goal_type_definition


class GoalRegistryTests(unittest.TestCase):
    def test_meet_in_person_goal_type_is_registered_with_extension_contract(self):
        goal = get_goal_type_definition()
        payload = goal.to_dict()

        self.assertEqual(DEFAULT_GOAL_TYPE, "meet_in_person")
        self.assertEqual(goal.goal_type, "meet_in_person")
        self.assertIn("meet_in_person", GOAL_TYPE_REGISTRY)
        self.assertIn("soft_invite_probe", payload["milestones"])
        self.assertIn("handoff", payload["allowed_moves"])
        self.assertIn("contact_exchange", payload["handoff_rules"])
        self.assertIn("date_or_meeting_preferences", payload["required_user_context"])
        self.assertIn("no_concrete_appointment_commitment_without_user", payload["policy_constraints"])
        self.assertIn("logistics_readiness", payload["success_evidence"])

    def test_unknown_goal_type_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "unsupported goal_type"):
            get_goal_type_definition("unknown_goal")

    def test_goal_registry_contains_future_expansion_goal_types(self):
        for goal_type in (
            "meet_in_person",
            "build_rapport",
            "screen_compatibility",
            "revive_stalled_chat",
            "maintain_connection",
        ):
            goal = get_goal_type_definition(goal_type)
            self.assertEqual(goal.goal_type, goal_type)
            self.assertTrue(goal.milestones)
            self.assertTrue(goal.allowed_moves)
            self.assertTrue(goal.policy_constraints)

    def test_automation_goal_save_validates_and_normalizes_goal_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = AutomationRepository(Path(temp_dir))

            payload = repo.save_goal({
                "schema_version": 1,
                "goal_id": "goal_rapport",
                "kind": "build_rapport",
                "status": "active",
            })
            saved = repo.load_goals_payload()["goals"][0]

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["goal_type"], "build_rapport")
        self.assertEqual(saved["goal_type"], "build_rapport")
        self.assertNotIn("kind", saved)

    def test_automation_goal_save_rejects_unknown_goal_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = AutomationRepository(Path(temp_dir))

            with self.assertRaisesRegex(ValueError, "unsupported_goal_type"):
                repo.save_goal({
                    "schema_version": 1,
                    "goal_id": "goal_unknown",
                    "goal_type": "unknown_goal",
                    "status": "active",
                })


if __name__ == "__main__":
    unittest.main()
