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


ADAPTER_DIR = Path("agent_adapters/openclaw")
PACKAGED_ADAPTER_DIR = Path("dating_boost/resources/agent_adapters/openclaw")
ADAPTER_PACKAGE = ADAPTER_DIR / "adapter-package.json"
ADAPTER_SKILL = ADAPTER_DIR / "skills" / "dating-booster" / "SKILL.md"


class OpenClawAdapterTests(unittest.TestCase):
    def test_openclaw_adapter_metadata_is_compatible_with_capabilities(self):
        metadata = json.loads(ADAPTER_PACKAGE.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, capabilities = self._run_cli(["capabilities", "--json", "--data-dir", temp_dir])

        self.assertEqual(exit_code, 0)
        self.assertEqual(metadata["package_name"], "dating-booster-openclaw-adapter")
        self.assertEqual(metadata["target_host"], "openclaw")
        self.assertIn("hermes", metadata["compatible_hosts"])
        self.assertEqual(metadata["compatibility_mode"], "openclaw_skill")
        self.assertEqual(metadata["package_version"], __version__)
        self.assertEqual(metadata["dating_boost_min_version"], __version__)
        self.assertEqual(metadata["source_repo"], "cyberpinkman/dating-booster")
        self.assertEqual(metadata["skill_path"], "agent_adapters/openclaw/skills/dating-booster")
        self.assertEqual(metadata["cli_command"], "dating-boost")
        self.assertEqual(metadata["host_loop_command"], "dating-boost-host-loop")
        self.assertEqual(metadata["source_ref"], _expected_source_ref(__version__))
        self.assertEqual(metadata["source_spec_commit"], _expected_source_ref(__version__))
        self.assertTrue(set(metadata["required_commands"]).issubset(set(capabilities["supported_commands"])))
        for schema_name, schema_version in metadata["required_schema_versions"].items():
            self.assertEqual(capabilities["schema_versions"][schema_name], schema_version)
        for reference_path in metadata["references"]:
            self.assertTrue((ADAPTER_DIR / reference_path).exists(), reference_path)

        agent_caps = capabilities["agent_native_capabilities"]
        self.assertIn("openclaw", agent_caps["host_agent_adapters"])
        self.assertIn("hermes", agent_caps["host_agent_adapters"])
        self.assertTrue(agent_caps["openclaw_adapter"])
        self.assertTrue(agent_caps["hermes_openclaw_compatible_adapter"])

    def test_openclaw_adapter_source_and_packaged_resources_stay_in_sync(self):
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

    def test_openclaw_skill_contains_complete_host_workflow_and_hermes_boundary(self):
        skill_text = ADAPTER_SKILL.read_text(encoding="utf-8").lower()
        readme_text = (ADAPTER_DIR / "README.md").read_text(encoding="utf-8").lower()

        for phrase in (
            "dating-boost adapter openclaw doctor",
            "dating-boost adapter hermes doctor",
            "openclaw-compatible",
            "hermes",
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
            "dating-boost-host-loop",
            "references/contracts.md",
            "references/workflows.md",
            "survey-style a/b",
            "yes/no-style hypothesis",
            "prefer lifestyle or interest",
            "relationship_progress_report",
            "report file paths",
        ):
            self.assertIn(phrase, skill_text)
        self.assertNotIn("future adapter", readme_text)
        self.assertIn("hermes uses the openclaw-compatible skill contract", readme_text)

    def test_adapter_openclaw_doctor_reports_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "adapter",
                "openclaw",
                "doctor",
                "--data-dir",
                temp_dir,
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_host"], "openclaw")
        self.assertEqual(payload["compatibility_target"], "openclaw")
        self.assertEqual(payload["adapter_package"], str(ADAPTER_PACKAGE.resolve()))
        self.assertEqual(payload["skill_doctor"]["status"], "ok")
        self.assertEqual(payload["managed_live_send_guidance"]["direct_harness_scope"], "executor_internal_only")
        self.assertIn("managed_start_live", payload["managed_live_send_guidance"]["canonical_commands"])

    def test_adapter_hermes_doctor_reports_openclaw_compatible_ok(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exit_code, payload = self._run_cli([
                "adapter",
                "hermes",
                "doctor",
                "--data-dir",
                temp_dir,
                "--json",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_host"], "hermes")
        self.assertEqual(payload["compatibility_target"], "openclaw")
        self.assertEqual(payload["adapter_package"], str(ADAPTER_PACKAGE.resolve()))
        self.assertEqual(payload["skill_doctor"]["status"], "ok")

    def test_adapter_openclaw_install_supports_dry_run_and_project_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dry_exit, dry_payload = self._run_cli([
                "adapter",
                "openclaw",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--dry-run",
                "--json",
            ])
            target_path = root / ".openclaw" / "skills" / "dating-booster"
            self.assertEqual(dry_exit, 0)
            self.assertEqual(dry_payload["status"], "dry_run")
            self.assertEqual(dry_payload["target_host"], "openclaw")
            self.assertEqual(dry_payload["compatibility_target"], "openclaw")
            self.assertEqual(dry_payload["target_path"], str(target_path))
            self.assertFalse(target_path.exists())

            install_exit, install_payload = self._run_cli([
                "adapter",
                "openclaw",
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

    def test_adapter_openclaw_install_removes_stale_target_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_path = root / ".openclaw" / "skills" / "dating-booster"
            stale_file = target_path / "references" / "old-workflow.md"
            stale_file.parent.mkdir(parents=True)
            stale_file.write_text("old workflow draft path", encoding="utf-8")

            install_exit, install_payload = self._run_cli([
                "adapter",
                "openclaw",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--json",
            ])

            self.assertEqual(install_exit, 0)
            self.assertEqual(install_payload["status"], "ok")
            self.assertFalse(stale_file.exists())
            self.assertTrue((target_path / "SKILL.md").exists())

    def test_adapter_hermes_install_uses_openclaw_compatible_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exit_code, payload = self._run_cli([
                "adapter",
                "hermes",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--dry-run",
                "--json",
            ])
            target_path = root / ".openclaw" / "skills" / "dating-booster"

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual(payload["target_host"], "hermes")
        self.assertEqual(payload["compatibility_target"], "openclaw")
        self.assertEqual(payload["target_path"], str(target_path))
        self.assertIn("adapter hermes doctor", payload["next_action"])

    def test_installed_openclaw_skill_is_self_contained(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exit_code, _ = self._run_cli([
                "adapter",
                "openclaw",
                "install",
                "--scope",
                "project",
                "--target",
                str(root),
                "--json",
            ])

            installed_skill = (root / ".openclaw" / "skills" / "dating-booster" / "SKILL.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("references/contracts.md", installed_skill)
        self.assertIn("references/workflows.md", installed_skill)
        self.assertNotIn("agent_adapters/shared/references", installed_skill)

    def test_pyproject_packages_openclaw_adapter_resources_for_wheel_installs(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        package_data = pyproject["tool"]["setuptools"]["package-data"]["dating_boost"]

        self.assertIn("resources/agent_adapters/openclaw/adapter-package.json", package_data)
        self.assertIn("resources/agent_adapters/openclaw/README.md", package_data)
        self.assertIn("resources/agent_adapters/openclaw/INSTALL.md", package_data)
        self.assertIn("resources/agent_adapters/openclaw/skills/dating-booster/SKILL.md", package_data)

    def test_release_workflow_builds_openclaw_adapter_artifact(self):
        workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

        self.assertIn("dating-booster-openclaw-${GITHUB_REF_NAME#v}.tar.gz", workflow)
        self.assertIn("-C agent_adapters openclaw", workflow)

    def test_release_doctor_includes_openclaw_adapter_artifact(self):
        payload = release_doctor()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["artifacts"]["openclaw_adapter"], f"dating-booster-openclaw-{__version__}.tar.gz")
        self.assertEqual(payload["artifact_sources"]["openclaw_adapter"], str(ADAPTER_PACKAGE))
        self.assertIn("openclaw/adapter-package.json", payload["source_hashes"])
        self.assertTrue(payload["release_capabilities"]["openclaw_adapter"])
        self.assertTrue(payload["release_capabilities"]["hermes_openclaw_compatible_adapter"])

    def test_agents_doc_documents_openclaw_and_hermes_quickstart(self):
        readme = Path("AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("OpenClaw", readme)
        self.assertIn("Hermes", readme)
        self.assertIn("python3 -m dating_boost.cli adapter openclaw install", readme)
        self.assertIn("python3 -m dating_boost.cli adapter hermes doctor", readme)
        self.assertIn(".openclaw/skills/dating-booster", readme)

    def _run_cli(self, args: list[str]) -> tuple[int, dict]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(args)
        text = output.getvalue().strip()
        payload = json.loads(text) if text else {}
        return exit_code, payload


def _expected_source_ref(version: str) -> str:
    return "main" if ".dev" in version else f"v{version}"
