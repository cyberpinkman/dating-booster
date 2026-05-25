import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


class CliMvpTests(unittest.TestCase):
    def test_init_profile_import_observation_and_draft_with_scripted_backend(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            import_output = StringIO()
            data_dir = Path(temp_dir)

            with redirect_stdout(output):
                init_exit = main([
                    "init-profile",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    "tests/fixtures/intelligence/user_profile.json",
                ])
            with redirect_stdout(import_output):
                import_exit = main([
                    "import-observation",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    "tests/fixtures/intelligence/app_observation_chat.json",
                ])
            import_payload = json.loads(import_output.getvalue())
            match_id = import_payload["match_id"]
            observation_path = (
                data_dir / "matches" / match_id / "observations" / "obs_chat_001.json"
            )

            with redirect_stdout(output):
                draft_exit = main([
                    "draft",
                    "--data-dir",
                    str(data_dir),
                    "--match-id",
                    match_id,
                    "--mode",
                    "adaptive",
                    "--scripted-backend-output",
                    "tests/fixtures/intelligence/scripted_reply.json",
                ])

            self.assertEqual(init_exit, 0)
            self.assertEqual(import_exit, 0)
            self.assertEqual(draft_exit, 0)
            self.assertIn("Sounds fun", output.getvalue())
            self.assertIn("What are you up to this weekend?", output.getvalue())
            self.assertIn("Ask about live music", output.getvalue())
            self.assertTrue((data_dir / "user_profile.json").exists())
            self.assertTrue(observation_path.exists())

    def test_authorize_subcommand_matches_legacy_action_gate(self):
        output = StringIO()

        with redirect_stdout(output):
            exit_code = main(["authorize", "send_message", "--autonomous"])

        payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["allowed"])
        self.assertTrue(payload["autonomous"])

    def test_feedback_command_appends_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            exit_code = main([
                "feedback",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_alex",
                "--draft-id",
                "draft_1",
                "--mode",
                "adaptive",
                "--label",
                "accepted",
            ])

            events_path = data_dir / "matches" / "match_alex" / "feedback_events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]

            self.assertEqual(exit_code, 0)
            self.assertEqual(events[0]["label"], "accepted")


if __name__ == "__main__":
    unittest.main()
