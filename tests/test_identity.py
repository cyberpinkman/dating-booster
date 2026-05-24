import unittest
from pathlib import Path

from dating_boost.core.identity import IdentityConfidence, resolve_match_identity
from dating_boost.perception.fixture_loader import load_observation


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


if __name__ == "__main__":
    unittest.main()
