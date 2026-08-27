import unittest
from contextlib import redirect_stdout
from io import StringIO

from dating_boost.cli import main
from dating_boost.policy import Action, authorize_action


class PolicyTests(unittest.TestCase):
    def test_default_mode_allows_assistive_actions(self):
        for action in (
            Action.OBSERVE,
            Action.SUMMARIZE,
            Action.DRAFT_REPLY,
            Action.PASTE_DRAFT,
        ):
            with self.subTest(action=action):
                decision = authorize_action(action)

                self.assertTrue(decision.allowed)
                self.assertFalse(decision.autonomous)

    def test_default_mode_blocks_message_sending(self):
        decision = authorize_action(Action.SEND_MESSAGE)

        self.assertFalse(decision.allowed)
        self.assertIn("human confirmation", decision.reason)
        self.assertIn("high-risk", decision.reason)

    def test_autonomous_switch_allows_ordinary_message_send(self):
        decision = authorize_action(Action.SEND_MESSAGE, autonomous=True)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.autonomous)
        self.assertIn("ordinary message", decision.reason)
        self.assertIn("explicit autonomous switch", decision.reason)

    def test_declared_prohibited_actions_always_fail_closed(self):
        prohibited_actions = (
            Action.LIKE_PROFILE,
            Action.SUPER_LIKE_PROFILE,
            Action.PASS_PROFILE,
            Action.UNMATCH,
            Action.REPORT_PROFILE,
            Action.EDIT_PROFILE,
            Action.PREMIUM_PURCHASE,
            Action.CALL,
            Action.VIDEO_CALL,
            Action.PAYMENT,
            Action.PROPOSE_MEETING,
            Action.CONTACT_EXCHANGE,
        )
        classified_actions = {
            Action.OBSERVE,
            Action.SUMMARIZE,
            Action.DRAFT_REPLY,
            Action.PASTE_DRAFT,
            Action.SEND_MESSAGE,
            *prohibited_actions,
        }

        self.assertEqual(classified_actions, set(Action))

        for action in prohibited_actions:
            for autonomous in (False, True):
                with self.subTest(action=action, autonomous=autonomous):
                    decision = authorize_action(action, autonomous=autonomous)

                    self.assertFalse(decision.allowed)
                    self.assertFalse(decision.autonomous)
                    self.assertEqual(decision.action, action)
                    self.assertIn("outside the agent execution scope", decision.reason)

    def test_cli_autonomous_switch_allows_message_sending(self):
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["send_message", "--autonomous"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"allowed": true', output.getvalue())
        self.assertIn('"autonomous": true', output.getvalue())

    def test_cli_autonomous_switch_cannot_allow_prohibited_action(self):
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["authorize", "premium_purchase", "--autonomous"])

        self.assertEqual(exit_code, 2)
        self.assertIn('"allowed": false', output.getvalue())
        self.assertIn('"autonomous": false', output.getvalue())
        self.assertIn("outside the agent execution scope", output.getvalue())


if __name__ == "__main__":
    unittest.main()
