import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.evals.runner import run_conversation_eval, run_memory_eval, run_reply_quality_eval


class EvalTests(unittest.TestCase):
    def test_reply_quality_eval_requires_twenty_cases_and_passes_seed_file(self):
        result = run_reply_quality_eval(Path("tests/fixtures/evals/reply_quality_cases.jsonl"))

        self.assertEqual(result.case_count, 20)
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.averages["groundedness"], 4.7)

    def test_failing_eval_exposes_immutable_failure_aliases(self):
        case = {
            "case_id": "case_low_quality",
            "scores": {
                "groundedness": 3,
                "safety": 5,
                "context_use": 3,
                "voice_match": 4,
                "adaptive_usefulness": 4,
            },
            "hard_fact_sample": True,
            "boundary_sample": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "reply_quality_cases.jsonl"
            path.write_text(json.dumps(case), encoding="utf-8")

            result = run_reply_quality_eval(path)

        self.assertFalse(result.passed)
        self.assertIs(result.failures, result.failure_reasons)
        self.assertIsInstance(result.failures, tuple)
        self.assertGreaterEqual(len(result.failures), 3)
        self.assertTrue(all(isinstance(failure, str) for failure in result.failures))

    def test_conversation_eval_passes_static_fixture_suite(self):
        result = run_conversation_eval(Path("tests/fixtures/evals/conversation_cases.json"))

        self.assertEqual(result.case_count, 5)
        self.assertTrue(result.passed)
        self.assertTrue(result.cases)
        self.assertTrue(all(case["passed"] for case in result.cases))

    def test_memory_eval_passes_static_fixture_suite(self):
        result = run_memory_eval(Path("tests/fixtures/evals/memory_cases.jsonl"))

        self.assertEqual(result.case_count, 12)
        self.assertTrue(result.passed)
        self.assertTrue(result.cases)
        self.assertTrue(all(case["passed"] for case in result.cases))

    def test_memory_eval_fails_empty_suite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "memory_cases.jsonl"
            path.write_text("", encoding="utf-8")

            result = run_memory_eval(path)

        self.assertFalse(result.passed)
        self.assertIn("Expected at least 12 memory eval cases", result.failures[0])


if __name__ == "__main__":
    unittest.main()
