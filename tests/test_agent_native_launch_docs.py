import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentNativeLaunchDocsTests(unittest.TestCase):
    def test_smoke_script_runs_complete_fixture_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "agent-native"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/agent_native_smoke.py",
                    "--data-dir",
                    str(data_dir),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["data_dir"], str(data_dir.resolve()))
            self.assertEqual(payload["compatibility"]["status"], "ok")
            self.assertEqual(payload["commands"]["capabilities"], 0)
            self.assertEqual(payload["commands"]["policy_check_draft"], 0)
            self.assertTrue((data_dir / "context.json").exists())
            self.assertTrue((data_dir / "host_draft.json").exists())
            self.assertTrue((data_dir / "action_result.json").exists())
            self.assertTrue((data_dir / "audit" / "action_results.jsonl").exists())
            self.assertTrue((data_dir / "matches" / payload["match_id"] / "feedback_events.jsonl").exists())

    def test_smoke_script_default_data_dir_keeps_artifacts_after_exit(self):
        data_dir = ROOT / ".local" / "dating-boost-smoke"
        shutil.rmtree(data_dir, ignore_errors=True)
        try:
            result = subprocess.run(
                [sys.executable, "scripts/agent_native_smoke.py"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["data_dir"], str(data_dir.resolve()))
            self.assertTrue(Path(payload["artifacts"]["context"]).exists())
            self.assertTrue(Path(payload["artifacts"]["action_audit"]).exists())
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)

    def test_installation_and_startup_docs_exist_and_are_actionable(self):
        install_text = (ROOT / "skills" / "dating-booster-codex" / "INSTALL.md").read_text(
            encoding="utf-8"
        )
        readme_text = (ROOT / "README.md").read_text(encoding="utf-8")

        required_install_phrases = (
            "CODEX_HOME",
            "skills/dating-booster-codex",
            "dating-boost capabilities --json --data-dir",
            "scripts/agent_native_smoke.py",
            "visible dating app content",
            "skill-package.json",
        )
        for phrase in required_install_phrases:
            self.assertIn(phrase, install_text)
        self.assertIn("skills/dating-booster-codex/INSTALL.md", readme_text)

    def test_observation_authoring_guide_covers_screen_to_json_rules(self):
        guide_text = (
            ROOT
            / "skills"
            / "dating-booster-codex"
            / "references"
            / "observation-authoring.md"
        ).read_text(encoding="utf-8").lower()
        metadata = json.loads(
            (ROOT / "skills" / "dating-booster-codex" / "skill-package.json").read_text(
                encoding="utf-8"
            )
        )

        for phrase in (
            "page_type",
            "page_confidence",
            "match_identity_hints",
            "profile_observation",
            "conversation_observation",
            "visible_messages",
            "photo_cues",
            "hook_candidates",
            "visible fact",
            "photo cue",
            "inference",
            "low_confidence",
            "must not be promoted to fact",
            "unknown",
            "do not infer",
            "redact",
        ):
            self.assertIn(phrase, guide_text)
        self.assertIn("references/observation-authoring.md", metadata["references"])


if __name__ == "__main__":
    unittest.main()
