import unittest
from pathlib import Path

from dating_boost.core.identity import IdentityConfidence, resolve_match_identity
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.taxonomy import PageType, SourceType


class IdentityTests(unittest.TestCase):
    def test_creates_new_match_when_no_candidates_exist(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(observation, existing_matches=[])

        self.assertEqual(result.confidence, IdentityConfidence.NEW)
        self.assertTrue(result.match_id.startswith("match_"))
        self.assertFalse(result.requires_user_confirmation)

    def test_low_confidence_name_only_match_requires_confirmation(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[{"match_id": "match_existing", "display_name": "Alex"}],
        )

        self.assertEqual(result.confidence, IdentityConfidence.LOW)
        self.assertTrue(result.requires_user_confirmation)

    def test_high_confidence_match_uses_profile_and_fingerprint(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[
                {
                    "match_id": "match_alex",
                    "display_name": "Alex",
                    "profile_cues": ["likes live music", "has a dog"],
                    "conversation_fingerprint": "alex-weekend-question",
                }
            ],
        )

        self.assertEqual(result.match_id, "match_alex")
        self.assertEqual(result.confidence, IdentityConfidence.HIGH)
        self.assertFalse(result.requires_user_confirmation)

    def test_low_information_new_matches_use_observation_id_to_avoid_collisions(self):
        first_observation = AppObservation.minimal(
            observation_id="obs_low_info_1",
            source_type=SourceType.USER_INPUT,
            app_id="generic",
            captured_at="2026-05-25T00:00:00Z",
            page_type=PageType.CHAT_THREAD,
        )
        second_observation = AppObservation.minimal(
            observation_id="obs_low_info_2",
            source_type=SourceType.USER_INPUT,
            app_id="generic",
            captured_at="2026-05-25T00:00:00Z",
            page_type=PageType.CHAT_THREAD,
        )

        first_result = resolve_match_identity(first_observation, existing_matches=[])
        second_result = resolve_match_identity(second_observation, existing_matches=[])

        self.assertEqual(first_result.confidence, IdentityConfidence.NEW)
        self.assertEqual(second_result.confidence, IdentityConfidence.NEW)
        self.assertNotEqual(first_result.match_id, second_result.match_id)


if __name__ == "__main__":
    unittest.main()
