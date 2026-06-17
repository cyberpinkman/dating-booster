import unittest

from dating_boost.core.models import Divergence
from dating_boost.intelligence.reply_generator import DraftResponse
from dating_boost.policy.content import evaluate_draft_content


def _draft_response(**overrides):
    payload = {
        "best_reply": "That sounds interesting.",
        "safer_reply": "That sounds interesting.",
        "bolder_reply": "Tell me more.",
        "why_this_works": "Keeps the conversation moving.",
        "situation_read": "Policy unit test fixture.",
        "conversation_move": "deepen_current",
        "hook_source": "conversation_thread",
        "naturalness_notes": ["unit test fixture"],
        "followup_if_match_replies": "Continue the thread.",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "",
        "persona_divergence": Divergence.LOW,
        "stance_divergence": Divergence.LOW,
    }
    payload.update(overrides)
    return DraftResponse(**payload)


class ContentPolicyTests(unittest.TestCase):
    def test_blocks_hard_fact_violation(self):
        draft = _draft_response(
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

    def test_blocks_hard_facts_only_overseas_study_claim(self):
        draft = _draft_response(
            best_reply="I studied overseas too.",
            safer_reply="That sounds interesting.",
            bolder_reply="Tell me more about your school days.",
            why_this_works="Claims matching education background.",
            risk_flags=[],
            missing_info=[],
            mode_notes="",
            persona_divergence=Divergence.LOW,
            stance_divergence=Divergence.LOW,
        )
        context_pack = {
            "items": [
                {"label": "user_hard_facts", "content": {"education": "Chinese university graduate"}},
            ]
        }

        decision = evaluate_draft_content(draft, context_pack)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.severity, "high")

    def test_blocks_age_and_location_hard_fact_contradictions(self):
        context_pack = {
            "items": [
                {
                    "label": "user_hard_facts",
                    "content": {
                        "age": 30,
                        "city": "Shanghai",
                    },
                },
            ]
        }
        cases = (
            _draft_response(
                best_reply="I'm 25, so I still have time.",
                safer_reply="That sounds interesting.",
                bolder_reply="Tell me more.",
                why_this_works="Invents age.",
                risk_flags=[],
                missing_info=[],
                mode_notes="",
                persona_divergence=Divergence.LOW,
                stance_divergence=Divergence.LOW,
            ),
            _draft_response(
                best_reply="I live in London too.",
                safer_reply="That sounds interesting.",
                bolder_reply="Tell me more.",
                why_this_works="Invents location.",
                risk_flags=[],
                missing_info=[],
                mode_notes="",
                persona_divergence=Divergence.LOW,
                stance_divergence=Divergence.LOW,
            ),
        )

        for draft in cases:
            with self.subTest(reply=draft.best_reply):
                decision = evaluate_draft_content(draft, context_pack)

                self.assertFalse(decision.allowed)
                self.assertEqual(decision.severity, "high")

    def test_blocks_hard_fact_violations_from_disclosure_profile(self):
        context_pack = {
            "items": [
                {
                    "label": "user_disclosure_profile",
                    "content": {
                        "hard_facts": [
                            {"fact_id": "fact_city", "field": "city", "value": "Beijing"},
                            {
                                "fact_id": "fact_education",
                                "field": "education",
                                "value": "Chinese university graduate",
                            },
                        ],
                        "boundaries": [
                            {"boundary_id": "no_fake_study", "text": "Do not claim overseas study"}
                        ],
                    },
                },
            ]
        }
        cases = (
            _draft_response(
                best_reply="I live in London too.",
                safer_reply="That sounds interesting.",
                bolder_reply="Tell me more.",
                why_this_works="Invents location.",
            ),
            _draft_response(
                best_reply="I studied overseas too.",
                safer_reply="That sounds interesting.",
                bolder_reply="Tell me more.",
                why_this_works="Invents education.",
            ),
        )

        for draft in cases:
            with self.subTest(reply=draft.best_reply):
                decision = evaluate_draft_content(draft, context_pack)

                self.assertFalse(decision.allowed)
                self.assertEqual(decision.severity, "high")

    def test_blocks_overseas_study_synonyms_in_any_reply_variant(self):
        context_pack = {
            "items": [
                {"label": "user_boundaries", "content": "Do not claim overseas study"},
            ]
        }
        cases = (
            _draft_response(
                best_reply="That sounds interesting.",
                safer_reply="I studied overseas too.",
                bolder_reply="London stories are always fun.",
                why_this_works="Claims shared background.",
                risk_flags=[],
                missing_info=[],
                mode_notes="",
                persona_divergence=Divergence.LOW,
                stance_divergence=Divergence.LOW,
            ),
            _draft_response(
                best_reply="That sounds interesting.",
                safer_reply="London stories are always fun.",
                bolder_reply="I went to university in London.",
                why_this_works="Claims shared background.",
                risk_flags=[],
                missing_info=[],
                mode_notes="",
                persona_divergence=Divergence.LOW,
                stance_divergence=Divergence.LOW,
            ),
        )

        for draft in cases:
            with self.subTest(reply=draft):
                decision = evaluate_draft_content(draft, context_pack)

                self.assertFalse(decision.allowed)
                self.assertEqual(decision.severity, "high")

    def test_unlabeled_medium_high_divergence_requires_user_confirmation(self):
        draft = _draft_response(
            best_reply="I am open to checking out a live show this weekend.",
            safer_reply="A live show could be fun.",
            bolder_reply="Pick a live show and I might be in.",
            why_this_works="Expresses a new stance.",
            risk_flags=[],
            missing_info=[],
            mode_notes="",
            persona_divergence=Divergence.LOW,
            stance_divergence=Divergence.MEDIUM,
        )

        decision = evaluate_draft_content(draft, {"items": []})

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_user_confirmation)

    def test_allows_labeled_stance_shift(self):
        draft = _draft_response(
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

    def test_blocks_soft_invite_with_specific_time_or_contact_details(self):
        context_pack = {
            "items": [
                {
                    "label": "planner_recommendation",
                    "content": {
                        "recommended_move": "soft_invite_probe",
                        "conversation_stage": "soft_invite_probe",
                        "soft_invite_allowed": True,
                    },
                }
            ]
        }
        cases = (
            _draft_response(
                best_reply="那明晚八点在三里屯见吧",
                safer_reply="感觉这个适合当面聊。",
                bolder_reply="明晚八点见。",
                why_this_works="Incorrectly commits to logistics.",
            ),
            _draft_response(
                best_reply="那加我微信吧，聊起来方便点",
                safer_reply="感觉这个适合当面聊。",
                bolder_reply="vx发你。",
                why_this_works="Incorrectly asks for contact exchange.",
            ),
        )

        for draft in cases:
            with self.subTest(reply=draft.best_reply):
                decision = evaluate_draft_content(draft, context_pack)

                self.assertFalse(decision.allowed)
                self.assertEqual(decision.severity, "high")

    def test_allows_soft_invite_without_concrete_logistics(self):
        draft = _draft_response(
            best_reply="感觉这个还挺适合当面聊的",
            safer_reply="感觉这个还挺适合当面聊的",
            bolder_reply="这个话题当面聊应该更有意思",
            why_this_works="Low-pressure soft invite without exact logistics.",
            conversation_move="soft_invite_probe",
        )
        context_pack = {
            "items": [
                {
                    "label": "planner_recommendation",
                    "content": {
                        "recommended_move": "soft_invite_probe",
                        "conversation_stage": "soft_invite_probe",
                        "soft_invite_allowed": True,
                    },
                }
            ]
        }

        decision = evaluate_draft_content(draft, context_pack)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.severity, "low")

if __name__ == "__main__":
    unittest.main()
