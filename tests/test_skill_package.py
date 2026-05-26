import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost import __version__
from dating_boost.cli import main


SKILL_DIR = Path("skills/dating-booster-codex")


class SkillPackageTests(unittest.TestCase):
    def test_skill_package_metadata_is_compatible_with_capabilities(self):
        package_path = SKILL_DIR / "skill-package.json"
        metadata = json.loads(package_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["capabilities", "--json", "--data-dir", temp_dir])

        capabilities = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(metadata["package_name"], "dating-booster-codex-skill")
        self.assertEqual(metadata["target_host"], "codex")
        self.assertEqual(metadata["package_version"], "0.1.3")
        self.assertEqual(metadata["dating_boost_min_version"], "0.1.3")
        self.assertLessEqual(_version_tuple(metadata["dating_boost_min_version"]), _version_tuple(__version__))
        self.assertTrue(set(metadata["required_commands"]).issubset(set(capabilities["supported_commands"])))
        self.assertEqual(metadata["required_schema_versions"]["reply_draft"], 2)
        self.assertEqual(metadata["required_schema_versions"]["workflow_result"], 1)
        self.assertEqual(metadata["required_schema_versions"]["automation_session"], 1)
        self.assertEqual(metadata["required_schema_versions"]["appointment_ledger"], 1)
        self.assertEqual(metadata["required_schema_versions"]["progress_report"], 1)
        for schema_name, schema_version in metadata["required_schema_versions"].items():
            self.assertEqual(capabilities["schema_versions"][schema_name], schema_version)
        for spec_path in metadata["source_specs"]:
            self.assertTrue(Path(spec_path).exists(), spec_path)
        for reference_path in metadata["references"]:
            self.assertTrue((SKILL_DIR / reference_path).exists(), reference_path)
        self.assertIn("references/drafting-framework.md", metadata["references"])
        self.assertIn("references/naturalness-checklist.md", metadata["references"])

    def test_skill_markdown_contains_required_operational_guards(self):
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()

        self.assertIn("dating-boost capabilities --json --data-dir", skill_text)
        self.assertIn("skill-package.json", skill_text)
        self.assertIn("dating_boost_min_version", skill_text)
        self.assertIn("required_schema_versions", skill_text)
        self.assertIn("required_commands", skill_text)
        self.assertIn("source_spec_commit", skill_text)
        self.assertIn("warning", skill_text)
        self.assertIn("stop", skill_text)
        self.assertIn("privacy", skill_text)
        self.assertIn("visible dating app content", skill_text)
        self.assertIn("high-risk", skill_text)
        self.assertIn("post-action verification", skill_text)
        self.assertIn("record-result", skill_text)
        self.assertIn("automation session", skill_text)
        self.assertIn("host agent", skill_text)
        self.assertIn("drafting-framework.md", skill_text)
        self.assertIn("naturalness-checklist.md", skill_text)

    def test_skill_reference_files_describe_reusable_workflows_and_contracts(self):
        workflows_text = (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8").lower()
        contracts_text = (SKILL_DIR / "references" / "contracts.md").read_text(encoding="utf-8").lower()
        drafting_text = (SKILL_DIR / "references" / "drafting-framework.md").read_text(
            encoding="utf-8"
        ).lower()
        checklist_text = (SKILL_DIR / "references" / "naturalness-checklist.md").read_text(
            encoding="utf-8"
        ).lower()

        for workflow_name in ("draft", "profile refresh", "send", "feedback"):
            self.assertIn(workflow_name, workflows_text)
        for command in (
            "memory ingest-observation",
            "context build",
            "policy check-draft",
            "policy check-action",
            "action record-result",
            "feedback record",
            "workflow draft",
            "automation session start",
            "automation session step",
            "automation session stop",
            "automation report latest",
        ):
            self.assertIn(command, workflows_text)
        for field_name in (
            "observation_id",
            "match_identity_hints",
            "profile_observation",
            "conversation_observation",
            "best_reply",
            "situation_read",
            "conversation_move",
            "hook_source",
            "naturalness_notes",
            "followup_if_match_replies",
            "payload_hash",
            "result_status",
            "evidence",
            "scan_batch",
            "action_request_id",
            "machine_report",
        ):
            self.assertIn(field_name, contracts_text)
        for phrase in (
            "对方投入度",
            "最后一句",
            "连续输出",
            "未知细节",
            "question is optional",
            "answer_or_riff",
            "take_the_lead",
            "do not force a question",
            "对方把选择权交给你",
            "不要继续反问",
            "一句为主",
        ):
            self.assertIn(phrase, drafting_text)
        for phrase in (
            "偏 a 还是 b",
            "a 还是 b 还是 c",
            "标签堆叠",
            "抽象词",
            "已知标签",
            "强行提问",
            "继续反问",
            "都行",
            "看情况",
        ):
            self.assertIn(phrase, checklist_text)

    def test_naturalness_check_is_internal_by_default(self):
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()
        workflows_text = (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8").lower()
        checklist_text = (SKILL_DIR / "references" / "naturalness-checklist.md").read_text(
            encoding="utf-8"
        ).lower()

        for text in (skill_text, workflows_text, checklist_text):
            self.assertIn("internal", text)
            self.assertIn("do not show", text)
            self.assertIn("explicitly asks", text)
            self.assertIn("debug", text)

        self.assertIn("show only the final draft", skill_text)
        self.assertIn("do not list checklist results", workflows_text)
        self.assertIn("not a default user-facing output format", checklist_text)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


if __name__ == "__main__":
    unittest.main()
