import unittest
from pathlib import Path

from dating_boost.evals.runner import run_reply_quality_eval


class EvalTests(unittest.TestCase):
    def test_reply_quality_eval_requires_twenty_cases_and_passes_seed_file(self):
        result = run_reply_quality_eval(Path("tests/fixtures/evals/reply_quality_cases.jsonl"))

        self.assertEqual(result.case_count, 20)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.averages["groundedness"], 4.7)


if __name__ == "__main__":
    unittest.main()
