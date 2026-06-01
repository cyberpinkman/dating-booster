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

        known_issues = {issue for example in case["bad_examples"] for issue in example["issues"]}
        for example in case["bad_examples"]:
            self.assertTrue(example["issues"])
        for example in case["better_examples"]:
            self.assertTrue(example["strategy_reason"])
            self.assertTrue(example["avoids_issues"])
            for avoided_issue in example["avoids_issues"]:
                self.assertIn(avoided_issue, known_issues)
            self.assertIn(example["conversation_move"], {"deepen_current", "bridge_topic"})

    def test_chinese_naturalness_seed_case_covers_answer_or_riff_without_forced_question(self):
        fixture_path = Path("tests/fixtures/evals/chinese_naturalness_cases.json")
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))

        case = next(item for item in payload["cases"] if item["case_id"] == "zh_news_riff_no_forced_question")

        self.assertIn("咋想的啊", case["context"]["latest_message"])
        self.assertIn("接梗", case["context"]["goal"])
        self.assertGreaterEqual(len(case["bad_examples"]), 2)
        self.assertGreaterEqual(len(case["better_examples"]), 3)

        known_issues = {issue for example in case["bad_examples"] for issue in example["issues"]}
        self.assertIn("forced question after the match already asked a question", known_issues)
        self.assertIn("jumps away from the live thread to profile tags", known_issues)

        better_without_question = [
            example for example in case["better_examples"] if "？" not in example["reply"] and "?" not in example["reply"]
        ]
        self.assertTrue(better_without_question)

        for example in case["better_examples"]:
            self.assertIn(example["conversation_move"], {"answer_or_riff", "bridge_topic"})
            self.assertTrue(example["avoids_issues"])
            for avoided_issue in example["avoids_issues"]:
                self.assertIn(avoided_issue, known_issues)
            self.assertTrue(example["strategy_reason"])

    def test_chinese_naturalness_seed_case_covers_take_the_lead_after_delegation(self):
        fixture_path = Path("tests/fixtures/evals/chinese_naturalness_cases.json")
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))

        case = next(item for item in payload["cases"] if item["case_id"] == "zh_reward_delegation_take_the_lead")

        self.assertEqual(case["context"]["latest_message"], "你定")
        self.assertIn("接过选择权", case["context"]["goal"])
        self.assertIn("纯爱", case["context"]["match_profile_hooks"])

        known_issues = {issue for example in case["bad_examples"] for issue in example["issues"]}
        self.assertIn("asks the match to decide after she delegated", known_issues)
        self.assertIn("too sexually forward for pure-love long-term context", known_issues)

        better_without_question = [
            example for example in case["better_examples"] if "？" not in example["reply"] and "?" not in example["reply"]
        ]
        self.assertTrue(better_without_question)

        for example in case["better_examples"]:
            self.assertIn(example["conversation_move"], {"take_the_lead", "bridge_topic"})
            self.assertTrue(example["avoids_issues"])
            for avoided_issue in example["avoids_issues"]:
                self.assertIn(avoided_issue, known_issues)
            self.assertTrue(example["strategy_reason"])


if __name__ == "__main__":
    unittest.main()
