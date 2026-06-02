import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


class UserDisclosureTests(unittest.TestCase):
    def test_user_readiness_requires_profile_and_interview_for_autonomous_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"

            missing_exit, missing_payload, _ = self._run([
                "user",
                "readiness",
                "--data-dir",
                str(data_dir),
                "--mode",
                "autonomous",
                "--json",
            ])
            self._run([
                "user",
                "ingest-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_dating_profile.json",
            ])
            profile_only_exit, profile_only_payload, _ = self._run([
                "user",
                "readiness",
                "--data-dir",
                str(data_dir),
                "--mode",
                "autonomous",
                "--json",
            ])
            self._run([
                "user",
                "ingest-interview",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_self_interview.json",
            ])
            ready_exit, ready_payload, _ = self._run([
                "user",
                "readiness",
                "--data-dir",
                str(data_dir),
                "--mode",
                "autonomous",
                "--json",
            ])

            self.assertEqual(missing_exit, 2)
            self.assertEqual(missing_payload["status"], "needs_user_profile")
            self.assertIn("dating_profile", missing_payload["missing"])
            self.assertEqual(profile_only_exit, 2)
            self.assertIn("self_interview", profile_only_payload["missing"])
            self.assertEqual(ready_exit, 0)
            self.assertTrue(ready_payload["ready"])
            self.assertEqual(ready_payload["shareable_material_count"], 5)
            self.assertEqual(ready_payload["low_risk_material_count"], 5)
            self.assertGreaterEqual(ready_payload["low_investment_repair_material_count"], 2)
            self.assertGreaterEqual(ready_payload["date_preference_material_count"], 1)

    def test_operator_start_blocks_without_disclosure_readiness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._run([
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                "tests/fixtures/intelligence/user_profile.json",
            ])

            start_exit, start_payload, _ = self._run([
                "operator",
                "session",
                "start",
                "--data-dir",
                str(data_dir),
                "--authorization",
                "tests/fixtures/automation/auth_send.json",
            ])

            self.assertEqual(start_exit, 2)
            self.assertEqual(start_payload["status"], "needs_user_profile")
            self.assertEqual(start_payload["reason"], "autonomous_requires_user_profile")
            self.assertFalse(start_payload["user_profile_readiness"]["ready"])

    def test_disclosure_profile_command_returns_merged_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
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

            exit_code, payload, _ = self._run([
                "user",
                "disclosure-profile",
                "--data-dir",
                str(data_dir),
                "--json",
            ])

            self.assertEqual(exit_code, 0)
            profile = payload["profile"]
            self.assertEqual(profile["simulation_policy"], "free_simulation_soft")
            self.assertTrue(profile["source_completion"]["dating_profile"])
            self.assertTrue(profile["source_completion"]["interview"])
            self.assertGreaterEqual(len(profile["hard_facts"]), 2)
            self.assertGreaterEqual(len(profile["shareable_material"]), 5)

    def test_autonomous_readiness_requires_usable_material_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_dir = temp_path / "data"
            empty_interview = json.loads(Path("tests/fixtures/intelligence/user_self_interview.json").read_text())
            for item in empty_interview["shareable_material"]:
                item["text"] = "   "
            interview_path = temp_path / "empty_interview.json"
            interview_path.write_text(json.dumps(empty_interview), encoding="utf-8")

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
                str(interview_path),
            ])
            exit_code, payload, _ = self._run([
                "user",
                "readiness",
                "--data-dir",
                str(data_dir),
                "--mode",
                "autonomous",
                "--json",
            ])

            self.assertEqual(exit_code, 2)
            self.assertFalse(payload["ready"])
            self.assertIn("low_risk_shareable_material", payload["missing"])
            self.assertIn("low_investment_repair_material", payload["missing"])
            self.assertIn("date_preference_material", payload["missing"])
            self.assertEqual(payload["shareable_material_count"], 5)
            self.assertEqual(payload["usable_shareable_material_count"], 0)

            draft_exit, draft_payload, _ = self._run([
                "user",
                "readiness",
                "--data-dir",
                str(data_dir),
                "--mode",
                "draft",
                "--json",
            ])
            self.assertEqual(draft_exit, 0)
            self.assertTrue(draft_payload["ready"])

    def test_interview_without_persona_style_preserves_profile_persona(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_dir = temp_path / "data"
            interview = json.loads(Path("tests/fixtures/intelligence/user_self_interview.json").read_text())
            interview.pop("persona_style")
            interview_path = temp_path / "interview_without_persona.json"
            interview_path.write_text(json.dumps(interview, ensure_ascii=False), encoding="utf-8")

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
                str(interview_path),
            ])
            _, payload, _ = self._run([
                "user",
                "disclosure-profile",
                "--data-dir",
                str(data_dir),
                "--json",
            ])

            self.assertEqual(payload["profile"]["persona_style"]["baseline"], "偏内向但可以主动一点")

    def test_autonomous_readiness_requires_phase_c_material_mix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            data_dir = temp_path / "data"
            interview = json.loads(Path("tests/fixtures/intelligence/user_self_interview.json").read_text())
            interview["shareable_material"] = interview["shareable_material"][:4]
            interview_path = temp_path / "thin_interview.json"
            interview_path.write_text(json.dumps(interview, ensure_ascii=False), encoding="utf-8")

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
                str(interview_path),
            ])

            exit_code, payload, _ = self._run([
                "user",
                "readiness",
                "--data-dir",
                str(data_dir),
                "--mode",
                "autonomous",
                "--json",
            ])

            self.assertEqual(exit_code, 2)
            self.assertFalse(payload["ready"])
            self.assertIn("low_risk_shareable_material", payload["missing"])

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


if __name__ == "__main__":
    unittest.main()
