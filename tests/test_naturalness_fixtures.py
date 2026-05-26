import json
import unittest
from pathlib import Path


class NaturalnessFixtureTests(unittest.TestCase):
    def test_chinese_naturalness_seed_case_contains_a_case_bad_better_pairs(self):
        fixture_path = Path("tests/fixtures/evals/chinese_naturalness_cases.json")
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], 1)
        cases = payload["cases"]
        case = next(item for item in cases if item["case_id"] == "zh_a_low_investment_night_owl")

        self.assertIn("挺不错的", case["context"]["latest_message"])
        self.assertGreaterEqual(len(case["bad_examples"]), 2)
        self.assertGreaterEqual(len(case["better_examples"]), 3)

        bad_text = "\n".join(example["reply"] for example in case["bad_examples"])
        self.assertIn("你平时放松更偏咖啡、电影还是听歌？", bad_text)
        self.assertIn("ESFP夜猫子的放松路线", bad_text)

        for example in case["bad_examples"]:
            self.assertTrue(example["issues"])
        for example in case["better_examples"]:
            self.assertTrue(example["strategy_reason"])
            self.assertIn(example["conversation_move"], {"deepen_hook", "bridge_from_latest"})


if __name__ == "__main__":
    unittest.main()
