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
        self.assertLessEqual(_version_tuple(metadata["dating_boost_min_version"]), _version_tuple(__version__))
        self.assertTrue(set(metadata["required_commands"]).issubset(set(capabilities["supported_commands"])))
        for schema_name, schema_version in metadata["required_schema_versions"].items():
            self.assertEqual(capabilities["schema_versions"][schema_name], schema_version)
        for spec_path in metadata["source_specs"]:
            self.assertTrue(Path(spec_path).exists(), spec_path)

    def test_skill_markdown_contains_required_operational_guards(self):
        skill_text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()

        self.assertIn("dating-boost capabilities --json", skill_text)
        self.assertIn("stop", skill_text)
        self.assertIn("privacy", skill_text)
        self.assertIn("visible dating app content", skill_text)
        self.assertIn("high-risk", skill_text)
        self.assertIn("post-action verification", skill_text)
        self.assertIn("record-result", skill_text)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


if __name__ == "__main__":
    unittest.main()
