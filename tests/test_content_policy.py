import unittest

from dating_boost.core.models import Divergence
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.policy.content import evaluate_draft_content


class ContentPolicyTests(unittest.TestCase):
    def test_blocks_hard_fact_violation(self):
        draft = DraftResponse(
            best_reply="I studied in London too.",
            safer_reply="That sounds interesting.",
            bolder_reply="London stories are always fun.",
            why_this_works="Claims shared background.",
            risk_flags=[],
            missing_info=[],
            mode_notes="",
            persona_divergence=Divergence.LOW,
            stance_divergence=Divergence.HIGH,
        )
        context_pack = {
            "items": [
                {"label": "user_hard_facts", "content": {"education": "Chinese university graduate"}},
                {"label": "user_boundaries", "content": "Do not claim overseas study"},
            ]
        }

        decision = evaluate_draft_content(draft, context_pack)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.severity, "high")

    def test_allows_labeled_stance_shift(self):
        draft = DraftResponse(
            best_reply="I am open to checking out a live show this weekend.",
            safer_reply="A live show could be fun.",
            bolder_reply="Pick a live show and I might be in.",
            why_this_works="Expresses future openness without claiming past experience.",
            risk_flags=[],
            missing_info=[],
            mode_notes="Changes stance toward live music.",
            persona_divergence=Divergence.LOW,
            stance_divergence=Divergence.MEDIUM,
        )

        decision = evaluate_draft_content(draft, {"items": []})

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.severity, "low")


if __name__ == "__main__":
    unittest.main()
