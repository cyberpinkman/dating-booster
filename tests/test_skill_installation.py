import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main


SKILL_DIR = Path("skills/dating-booster-codex")
SKILL_PACKAGE = SKILL_DIR / "skill-package.json"


class SkillInstallationTests(unittest.TestCase):
    def test_cli_skill_doctor_reports_ok_for_current_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run([
                "skill",
                "doctor",
                "--package",
                str(SKILL_PACKAGE),
                "--data-dir",
                temp_dir,
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["skill_version"], "0.1.6")
        self.assertTrue(payload["cli_found"])
        self.assertEqual(payload["cli_version"], "0.1.6")
        self.assertTrue(payload["capabilities_ok"])
        self.assertEqual(payload["missing_commands"], [])
        self.assertEqual(payload["schema_mismatches"], [])
        self.assertEqual(payload["warnings"], [])
        self.assertEqual(payload["next_action"], "ready")

    def test_cli_skill_doctor_reports_incompatible_missing_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            package_path = Path(temp_dir) / "skill-package.json"
            package = json.loads(SKILL_PACKAGE.read_text(encoding="utf-8"))
            package["required_commands"] = [*package["required_commands"], "missing command"]
            package_path.write_text(json.dumps(package), encoding="utf-8")

            exit_code, payload = self._run([
                "skill",
                "doctor",
                "--package",
                str(package_path),
                "--data-dir",
                temp_dir,
                "--json",
            ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "incompatible")
        self.assertIn("missing command", payload["missing_commands"])
        self.assertEqual(payload["next_action"], "stop")

    def test_skill_scripts_exist_and_compile(self):
        self.assertTrue((SKILL_DIR / "scripts" / "doctor.py").exists())
        self.assertTrue((SKILL_DIR / "scripts" / "bootstrap_cli.py").exists())

    def test_skill_doctor_script_reports_needs_bootstrap_when_cli_command_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_DIR / "scripts" / "doctor.py"),
                    "--json",
                    "--data-dir",
                    temp_dir,
                ],
                check=False,
                capture_output=True,
                env={**os.environ, "PATH": temp_dir},
                text=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(payload["status"], "needs_bootstrap")
        self.assertFalse(payload["cli_found"])
        self.assertEqual(payload["next_action"], "bootstrap_cli")

    def test_bootstrap_script_dry_run_uses_fixed_github_ref(self):
        metadata = json.loads(SKILL_PACKAGE.read_text(encoding="utf-8"))
        result = subprocess.run(
            [
                sys.executable,
                str(SKILL_DIR / "scripts" / "bootstrap_cli.py"),
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["status"], "dry_run")
        self.assertIn(
            f"git+https://github.com/cyberpinkman/dating-booster.git@{metadata['source_ref']}",
            payload["install_command"],
        )

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())


if __name__ == "__main__":
    unittest.main()
