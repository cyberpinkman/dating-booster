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
            self.assertTrue(payload["production_smoke"])
            self.assertEqual(payload["data_dir"], str(data_dir.resolve()))
            self.assertEqual(payload["compatibility"]["status"], "ok")
            self.assertEqual(payload["commands"]["capabilities"], 0)
            self.assertEqual(payload["commands"]["data_migrate"], 0)
            self.assertEqual(payload["commands"]["data_export"], 0)
            self.assertEqual(payload["commands"]["host_loop_fixture_stage"], 0)
            self.assertEqual(payload["commands"]["policy_check_draft"], 0)
            self.assertEqual(payload["host_loop_fixture_stage"]["status"], "staged_waiting_user_confirmation")
            self.assertTrue((data_dir / "context.json").exists())
            self.assertTrue((data_dir / "host_draft.json").exists())
            self.assertTrue((data_dir / "action_result.json").exists())
            self.assertTrue(Path(payload["artifacts"]["data_export"]).exists())
            self.assertTrue(Path(payload["host_loop_fixture_stage"]["staged_verification"]).exists())
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
            self.assertTrue(payload["production_smoke"])
            self.assertEqual(payload["data_dir"], str(data_dir.resolve()))
            self.assertTrue(Path(payload["artifacts"]["context"]).exists())
            self.assertTrue(Path(payload["artifacts"]["action_audit"]).exists())
            self.assertTrue(Path(payload["artifacts"]["host_loop_stage_export"]).exists())
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

    def test_architecture_docs_cover_future_expansion_axes(self):
        architecture_text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").lower()
        docs_readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8").lower()
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()

        for phrase in (
            "codex",
            "claude code",
            "hermes",
            "openclaw",
            "tinder",
            "wechat",
            "bumble",
            "tashuo",
            "hinge",
            "meet_in_person",
            "goal type registry",
            "memory evolution",
            "host agent adapter",
            "app support profile",
            "no duplicated domain logic",
        ):
            self.assertIn(phrase, architecture_text)
        self.assertIn("docs/architecture.md", docs_readme)
        self.assertIn("docs/architecture.md", root_readme)

    def test_agent_adapter_docs_separate_shared_and_host_specific_contracts(self):
        adapter_root = ROOT / "agent_adapters"
        shared_text = (adapter_root / "shared" / "README.md").read_text(encoding="utf-8").lower()
        codex_text = (adapter_root / "codex" / "README.md").read_text(encoding="utf-8").lower()
        claude_text = (adapter_root / "claude-code" / "README.md").read_text(encoding="utf-8").lower()

        for path in (
            adapter_root / "README.md",
            adapter_root / "shared" / "README.md",
            adapter_root / "codex" / "README.md",
            adapter_root / "claude-code" / "README.md",
        ):
            self.assertTrue(path.exists(), path)
        self.assertIn("capabilities --json", shared_text)
        self.assertIn("app profiles", shared_text)
        self.assertIn("references/contracts.md", shared_text)
        self.assertIn("references/workflows.md", shared_text)
        self.assertNotIn("skills/dating-booster-codex/references", shared_text)
        self.assertIn("not copy codex", (adapter_root / "README.md").read_text(encoding="utf-8").lower())
        self.assertIn("skills/dating-booster-codex", codex_text)
        self.assertIn("dating-boost adapter claude-code install", claude_text)
        self.assertIn(".claude/skills/dating-booster", claude_text)
        self.assertIn("agent_adapters/shared/references/contracts.md", claude_text)
        self.assertIn("agent_adapters/shared/references/workflows.md", claude_text)
        self.assertIn("reuse", claude_text)

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
