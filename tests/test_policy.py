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

    def test_autonomous_switch_allows_high_risk_actions(self):
        decision = authorize_action(Action.SEND_MESSAGE, autonomous=True)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.autonomous)
        self.assertIn("explicit switch", decision.reason)

    def test_cli_autonomous_switch_allows_message_sending(self):
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["send_message", "--autonomous"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"allowed": true', output.getvalue())
        self.assertIn('"autonomous": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
