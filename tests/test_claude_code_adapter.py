import argparse
import filecmp
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost import __version__
from dating_boost.cli import main
from dating_boost.core.release import release_doctor
from dating_boost.host_loop import HostLoopSupervisor, _parse_args


ADAPTER_DIR = Path("agent_adapters/claude-code")
PACKAGED_ADAPTER_DIR = Path("dating_boost/resources/agent_adapters/claude-code")
ADAPTER_PACKAGE = ADAPTER_DIR / "adapter-package.json"
ADAPTER_SKILL = ADAPTER_DIR / "skills" / "dating-booster" / "SKILL.md"
CODEX_SKILL_DIR = Path("skills/dating-booster-codex")


class ClaudeCodeAdapterTests(unittest.TestCase):
    def test_claude_adapter_metadata_is_compatible_with_capabilities(self):
        metadata = json.loads(ADAPTER_PACKAGE.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, capabilities = self._run_cli(["capabilities", "--json", "--data-dir", temp_dir])

        self.assertEqual(exit_code, 0)
        self.assertEqual(metadata["package_name"], "dating-booster-claude-code-adapter")
        self.assertEqual(metadata["target_host"], "claude_code")
        self.assertEqual(metadata["package_version"], __version__)
        self.assertEqual(metadata["dating_boost_min_version"], __version__)
        self.assertEqual(metadata["source_repo"], "cyberpinkman/dating-booster")
        self.assertEqual(metadata["skill_path"], "agent_adapters/claude-code/skills/dating-booster")
        self.assertEqual(metadata["cli_command"], "dating-boost")
        self.assertEqual(metadata["host_loop_command"], "dating-boost-host-loop")
        self.assertEqual(metadata["source_ref"], f"v{__version__}")
        self.assertTrue(set(metadata["required_commands"]).issubset(set(capabilities["supported_commands"])))
        for schema_name, schema_version in metadata["required_schema_versions"].items():
            self.assertEqual(capabilities["schema_versions"][schema_name], schema_version)
        for reference_path in metadata["references"]:
            self.assertTrue((ADAPTER_DIR / reference_path).exists(), reference_path)

        agent_caps = capabilities["agent_native_capabilities"]
        self.assertIn("claude_code", agent_caps["host_agent_adapters"])
        self.assertTrue(agent_caps["claude_code_adapter"])

    def test_claude_code_adapter_source_and_packaged_resources_stay_in_sync(self):
        for relative_path in (
            Path("adapter-package.json"),
            Path("README.md"),
            Path("INSTALL.md"),
            Path("skills/dating-booster/SKILL.md"),
        ):
            with self.subTest(path=str(relative_path)):
                self.assertTrue(
                    filecmp.cmp(ADAPTER_DIR / relative_path, PACKAGED_ADAPTER_DIR / relative_path, shallow=False),
                    f"{relative_path} differs between source adapter and packaged resource",
                )

    def test_claude_code_adapter_tracks_all_runtime_gui_harness_apps(self):
        metadata = json.loads(ADAPTER_PACKAGE.read_text(encoding="utf-8"))
        skill_text = ADAPTER_SKILL.read_text(encoding="utf-8").lower()
        readme_text = (ADAPTER_DIR / "README.md").read_text(encoding="utf-8").lower()

        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, capabilities = self._run_cli(["capabilities", "--json", "--data-dir", temp_dir])

        self.assertEqual(exit_code, 0)
        required_commands = set(metadata["required_commands"])
        for command in capabilities["supported_commands"]:
            if command.startswith("harness ") and command not in {"harness doctor", "harness screenshot"}:
                with self.subTest(command=command):
                    self.assertIn(command, required_commands)

        for app_id in capabilities["agent_native_capabilities"]["supported_app_profiles"]:
            with self.subTest(app_id=app_id):
                self.assertIn(f"harness {app_id}", skill_text)
                self.assertIn(app_id, readme_text)

        self.assertIn("bumble iphone mirroring harness", skill_text)
        self.assertIn("opening move", skill_text)
        self.assertIn("tashuo iphone mirroring harness", skill_text)
        self.assertIn("question-gate", skill_text)

    def test_claude_code_skill_contains_complete_host_workflow(self):
        skill_text = ADAPTER_SKILL.read_text(encoding="utf-8").lower()
        readme_text = (ADAPTER_DIR / "README.md").read_text(encoding="utf-8").lower()

        for phrase in (
            "dating-boost adapter claude-code doctor",
            "dating-boost capabilities --json --data-dir",
            "dating-boost data doctor",
            "dating-boost data migrate",
            "dating-boost support session start",
            "dating-boost support bundle",
            "user readiness",
            "visible dating app content",
            "target binding",
            "post-action verification",
            "managed live-send",
            "harness tinder",
            "dismiss-subscription-paywall",
            "dismiss-feedback-survey",
            "subscription purchase",
            "plan selection is never an agent action",
            "rating_submitted",
            "target-binding",
            "harness wechat",
            "harness bumble",
            "harness tashuo",
            "opening move",
            "question-gate",
            "dating-boost-host-loop",
            "references/contracts.md",
            "references/workflows.md",
        ):
            self.assertIn(phrase, skill_text)
        self.assertNotIn("status: p1 planned adapter", readme_text)

    def test_adapter_claude_code_doctor_reports_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "adapter",
                "claude-code",
                "doctor",
                "--data-dir",
                temp_dir,
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_host"], "claude_code")
        self.assertEqual(payload["adapter_package"], str(ADAPTER_PACKAGE.resolve()))
        self.assertEqual(payload["skill_doctor"]["status"], "ok")

    def test_adapter_claude_code_install_supports_dry_run_and_project_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dry_exit, dry_payload = self._run_cli([
                "adapter",
                "claude-code",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--dry-run",
                "--json",
            ])
            target_path = root / ".claude" / "skills" / "dating-booster"
            self.assertEqual(dry_exit, 0)
            self.assertEqual(dry_payload["status"], "dry_run")
            self.assertEqual(dry_payload["target_path"], str(target_path))
            self.assertFalse(target_path.exists())

            install_exit, install_payload = self._run_cli([
                "adapter",
                "claude-code",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--json",
            ])

            self.assertEqual(install_exit, 0)
            self.assertEqual(install_payload["status"], "ok")
            self.assertEqual(install_payload["target_path"], str(target_path))
            self.assertTrue((target_path / "SKILL.md").exists())
            self.assertTrue((target_path / "adapter-package.json").exists())
            self.assertTrue((target_path / "references" / "contracts.md").exists())

    def test_installed_claude_code_skill_is_self_contained(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exit_code, _ = self._run_cli([
                "adapter",
                "claude-code",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--json",
            ])

            installed_skill = (root / ".claude" / "skills" / "dating-booster" / "SKILL.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("references/contracts.md", installed_skill)
        self.assertIn("references/workflows.md", installed_skill)
        self.assertNotIn("agent_adapters/shared/references", installed_skill)

    def test_pyproject_packages_claude_adapter_resources_for_wheel_installs(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        package_data = pyproject["tool"]["setuptools"]["package-data"]["dating_boost"]

        self.assertIn("resources/agent_adapters/claude-code/adapter-package.json", package_data)
        self.assertIn("resources/agent_adapters/claude-code/skills/dating-booster/SKILL.md", package_data)
        self.assertIn("resources/agent_adapters/claude-code/INSTALL.md", package_data)
        self.assertIn("resources/agent_adapters/shared/references/contracts.md", package_data)
        self.assertIn("resources/agent_adapters/shared/references/workflows.md", package_data)
        self.assertIn("resources/agent_adapters/codex/dating-booster-codex/SKILL.md", package_data)
        self.assertIn("resources/agent_adapters/codex/dating-booster-codex/skill-package.json", package_data)
        self.assertIn("resources/agent_adapters/codex/dating-booster-codex/scripts/doctor.py", package_data)
        self.assertIn("resources/agent_adapters/codex/dating-booster-codex/references/workflows.md", package_data)

    def test_release_workflow_builds_claude_code_adapter_artifact(self):
        workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn("dating-booster-claude-code-${GITHUB_REF_NAME#v}.tar.gz", workflow)
        self.assertIn("-C agent_adapters claude-code", workflow)

    def test_host_loop_accepts_adapter_package_alias(self):
        args = _parse_args(["doctor", "--adapter-package", str(ADAPTER_PACKAGE), "--json"])

        self.assertIsNone(args.skill_package)
        self.assertEqual(args.adapter_package, ADAPTER_PACKAGE)
        supervisor = HostLoopSupervisor(args)
        self.assertEqual(supervisor.skill_package_path, ADAPTER_PACKAGE.resolve())

    def test_release_doctor_includes_claude_code_adapter_artifact(self):
        payload = release_doctor()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["artifacts"]["claude_code_adapter"], f"dating-booster-claude-code-{__version__}.tar.gz")
        self.assertEqual(payload["artifact_sources"]["claude_code_adapter"], str(ADAPTER_PACKAGE))
        self.assertIn("claude-code/adapter-package.json", payload["source_hashes"])
        self.assertTrue(payload["release_capabilities"]["claude_code_adapter"])

    def test_readme_documents_claude_code_quickstart(self):
        readme = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("Claude Code", readme)
        self.assertIn("dating-boost adapter claude-code install", readme)
        self.assertIn(".claude/skills/dating-booster", readme)

    def test_adapter_codex_install_supports_dry_run_and_project_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dry_exit, dry_payload = self._run_cli([
                "adapter",
                "codex",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--dry-run",
                "--json",
            ])
            target_path = root / ".codex" / "skills" / "dating-booster-codex"
            self.assertEqual(dry_exit, 0)
            self.assertEqual(dry_payload["status"], "dry_run")
            self.assertEqual(dry_payload["target_path"], str(target_path))
            self.assertFalse(target_path.exists())

            install_exit, install_payload = self._run_cli([
                "adapter",
                "codex",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--json",
            ])

            self.assertEqual(install_exit, 0)
            self.assertEqual(install_payload["status"], "ok")
            self.assertEqual(install_payload["target_path"], str(target_path))
            self.assertTrue((target_path / "SKILL.md").exists())
            self.assertTrue((target_path / "skill-package.json").exists())
            self.assertTrue((target_path / "scripts" / "doctor.py").exists())
            self.assertTrue((target_path / "references" / "contracts.md").exists())
            self.assertFalse(any("__pycache__" in file_info["target"] for file_info in install_payload["files"]))

    def test_adapter_codex_doctor_reports_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "adapter",
                "codex",
                "doctor",
                "--data-dir",
                temp_dir,
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_host"], "codex")
        self.assertEqual(payload["skill_doctor"]["status"], "ok")

    def test_docs_describe_agent_clone_install_path(self):
        docs = {
            "root_readme": Path("README.md").read_text(encoding="utf-8"),
            "docs_readme": Path("docs/README.md").read_text(encoding="utf-8"),
            "claude_install": Path("agent_adapters/claude-code/INSTALL.md").read_text(encoding="utf-8"),
            "codex_install": Path("skills/dating-booster-codex/INSTALL.md").read_text(encoding="utf-8"),
        }
        combined = "\n".join(docs.values())

        self.assertIn("git clone https://github.com/cyberpinkman/dating-booster.git", combined)
        self.assertIn("python3 -m pip install --user -e .", combined)
        self.assertIn("python3 -m dating_boost.cli adapter claude-code install --scope user --json", combined)
        self.assertIn("python3 -m dating_boost.cli adapter codex install --scope user --json", combined)
        self.assertIn("agent 自己 clone", combined)
        self.assertNotIn("scripts/install-claude-code.sh", combined)
        self.assertNotIn("scripts/install-codex.sh", combined)
        self.assertNotIn("scripts/lib/install-agent-common.sh", combined)
        self.assertNotIn("curl -fsSL", combined)
        self.assertNotIn("DATING_BOOST_INSTALL_REF", combined)
        self.assertFalse(Path("skills/dating-booster-codex/INSTALL_FROM_GITHUB.md").exists())

    def _run_cli(self, argv: list[str]) -> tuple[int, dict]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        return exit_code, json.loads(output.getvalue())


if __name__ == "__main__":
    unittest.main()
