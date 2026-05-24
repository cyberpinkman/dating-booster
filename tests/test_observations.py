import unittest
from pathlib import Path

from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.taxonomy import PageType, SourceType


class ObservationTests(unittest.TestCase):
    def test_loads_chat_observation_fixture(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        self.assertEqual(observation.source_type, SourceType.MANUAL_FIXTURE)
        self.assertEqual(observation.page_type, PageType.CHAT_THREAD)
        self.assertEqual(observation.match_identity_hints.visible_name, "Alex")
        self.assertEqual(observation.conversation_observation.visible_messages[-1]["text"], "What are you up to this weekend?")

    def test_observation_round_trips_to_dict(self):
        observation = AppObservation.minimal(
            observation_id="obs_1",
            source_type=SourceType.USER_INPUT,
            app_id="generic",
            captured_at="2026-05-25T00:00:00Z",
            page_type=PageType.CHAT_THREAD,
        )

        decoded = AppObservation.from_dict(observation.to_dict())

        self.assertEqual(decoded.observation_id, "obs_1")
        self.assertEqual(decoded.page_type, PageType.CHAT_THREAD)


if __name__ == "__main__":
    unittest.main()
