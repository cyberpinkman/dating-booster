import unittest
from pathlib import Path


class CiConfigTests(unittest.TestCase):
    def test_github_actions_runs_supported_python_matrix_pytest_diff_check_and_smoke(self):
        workflow = Path(".github/workflows/ci.yml")
        text = workflow.read_text(encoding="utf-8")

        for version in ("3.11", "3.12", "3.13"):
            self.assertIn(version, text)
        self.assertIn("ubuntu-latest", text)
        self.assertIn("macos-latest", text)
        self.assertIn("DATING_BOOST_KEY_PROVIDER", text)
        self.assertIn("pip install -e .[test]", text)
        self.assertIn("python -m pytest", text)
        self.assertIn("git diff --check", text)
        self.assertIn("scripts/agent_native_smoke.py", text)
        self.assertIn("python -m build", text)

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


if __name__ == "__main__":
    unittest.main()
