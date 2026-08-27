import re
import unittest
from pathlib import Path


CI_WORKFLOW = Path(".github/workflows/ci.yml")


def _ci_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def _job_block(text: str, job_id: str) -> str:
    _, separator, jobs = text.partition("\njobs:\n")
    if not separator:
        raise AssertionError("CI workflow has no jobs mapping")
    match = re.search(
        rf"(?ms)^  {re.escape(job_id)}:\n(?P<body>.*?)(?=^  [a-z0-9-]+:\n|\Z)",
        jobs,
    )
    if match is None:
        raise AssertionError(f"CI workflow has no {job_id!r} job")
    return match.group("body")


class CiConfigTests(unittest.TestCase):
    def test_daily_triggers_do_not_duplicate_feature_branch_push_and_pull_request(self):
        triggers = _ci_text().split("\njobs:\n", 1)[0]

        self.assertIn("branches: [main]", triggers)
        self.assertIn('tags: ["v*"]', triggers)
        self.assertNotIn('branches: ["**"]', triggers)
        self.assertIn("pull_request:", triggers)
        self.assertIn("workflow_dispatch:", triggers)
        self.assertIn("schedule:", triggers)
        self.assertIn("full_compatibility:", triggers)

    def test_managed_critical_and_pr_core_have_one_fast_canonical_owner(self):
        text = _ci_text()
        critical = _job_block(text, "managed-critical")
        pr_core = _job_block(text, "pr-core")

        self.assertIn('CANONICAL_PYTHON: "3.13"', text)
        self.assertIn("DATING_BOOST_KEY_PROVIDER: local", text)
        for job in (critical, pr_core):
            self.assertIn("runs-on: ubuntu-latest", job)
            self.assertIn("python-version: ${{ env.CANONICAL_PYTHON }}", job)
            self.assertNotIn("matrix:", job)
        self.assertEqual(text.count("python -m pytest -m managed_critical -q"), 1)
        self.assertIn("needs: managed-critical", pr_core)
        self.assertIn('python -m pytest -m "not nightly_lab" -q', pr_core)
        self.assertNotIn("--cov", pr_core)

    def test_coverage_is_single_canonical_nightly_job(self):
        text = _ci_text()
        coverage = _job_block(text, "nightly-coverage")

        self.assertIn("github.event_name == 'schedule'", coverage)
        self.assertIn("inputs.full_compatibility == true", coverage)
        self.assertIn("runs-on: ubuntu-latest", coverage)
        self.assertNotIn("matrix:", coverage)
        self.assertEqual(text.count("--cov=dating_boost"), 1)
        self.assertEqual(text.count("--cov-fail-under=60"), 1)

    def test_package_static_wheel_and_agent_smoke_have_one_owner(self):
        text = _ci_text()
        quality = _job_block(text, "quality")

        self.assertIn("runs-on: ubuntu-latest", quality)
        self.assertNotIn("matrix:", quality)
        for command in (
            "python -m build",
            "python -m ruff check dating_boost tests scripts",
            "python -m mypy",
            "git diff --check",
            "python scripts/agent_native_smoke.py",
            'python -m venv "$RUNNER_TEMP/dating-booster-wheel-smoke"',
        ):
            with self.subTest(command=command):
                self.assertEqual(text.count(command), 1)

    def test_normal_compatibility_matrix_runs_only_lightweight_contracts(self):
        text = _ci_text()
        compatibility = _job_block(text, "compatibility-contracts")

        self.assertIn("github.event_name != 'schedule'", compatibility)
        self.assertIn("inputs.full_compatibility != true", compatibility)
        self.assertIn("os: [ubuntu-latest, macos-latest]", compatibility)
        self.assertIn('python-version: ["3.11", "3.12", "3.13"]', compatibility)
        for test_path in (
            "tests/test_policy.py",
            "tests/test_confirmation_contract.py",
            "tests/test_runtime_safety_cli.py",
            "tests/test_ci_config.py",
        ):
            self.assertIn(test_path, compatibility)
        self.assertNotIn("--cov", compatibility)
        self.assertNotIn("python -m build", compatibility)
        self.assertNotIn("agent_native_smoke.py", compatibility)

    def test_full_compatibility_matrix_is_nightly_or_explicit_only(self):
        full_compatibility = _job_block(_ci_text(), "full-compatibility")

        self.assertIn("github.event_name == 'schedule'", full_compatibility)
        self.assertIn("inputs.full_compatibility == true", full_compatibility)
        self.assertIn("needs: managed-critical", full_compatibility)
        self.assertIn("os: [ubuntu-latest, macos-latest]", full_compatibility)
        self.assertIn('python-version: ["3.11", "3.12", "3.13"]', full_compatibility)
        self.assertIn("run: python -m pytest -q", full_compatibility)
        self.assertNotIn("--cov", full_compatibility)

    def test_release_workflow_uses_trusted_publishing_and_release_doctor(self):
        workflow = Path(".github/workflows/release.yml")
        text = workflow.read_text(encoding="utf-8")

        self.assertIn("id-token: write", text)
        self.assertIn("pypa/gh-action-pypi-publish", text)
        self.assertIn("dating-boost release doctor --json", text)
        self.assertIn("python -m build", text)
        self.assertIn("python -m build --outdir dist/python", text)
        self.assertIn("packages-dir: dist/python", text)
        self.assertIn("dist/skill/*", text)

    def test_ci_installs_wheel_and_runs_capabilities_outside_checkout(self):
        text = _job_block(_ci_text(), "quality")

        self.assertIn('python -m venv "$RUNNER_TEMP/dating-booster-wheel-smoke"', text)
        self.assertIn('pip install "$GITHUB_WORKSPACE"/dist/*.whl', text)
        self.assertIn('cd "$RUNNER_TEMP"', text)
        self.assertIn(
            '"$RUNNER_TEMP/dating-booster-wheel-smoke/bin/dating-boost" capabilities --json '
            '--data-dir "$RUNNER_TEMP/wheel-smoke-data"',
            text,
        )
        self.assertIn('payload["agent_native_capabilities"]["supported_app_profiles"]', text)


if __name__ == "__main__":
    unittest.main()
