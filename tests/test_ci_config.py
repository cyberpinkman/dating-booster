import unittest
from pathlib import Path


class CiConfigTests(unittest.TestCase):
    def test_github_actions_runs_supported_python_matrix_pytest_diff_check_and_smoke(self):
        workflow = Path(".github/workflows/ci.yml")
        text = workflow.read_text(encoding="utf-8")

        for version in ("3.11", "3.12", "3.13"):
            self.assertIn(version, text)
        self.assertIn("pip install -e .[test]", text)
        self.assertIn("python -m pytest", text)
        self.assertIn("git diff --check", text)
        self.assertIn("scripts/agent_native_smoke.py", text)


if __name__ == "__main__":
    unittest.main()
