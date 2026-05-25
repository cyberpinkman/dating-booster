import unittest
from pathlib import Path

from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.perception.taxonomy import PageType, SourceType


class ObservationTests(unittest.TestCase):
    def test_loads_chat_observation_fixture(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        self.assertEqual(observation.source_type, SourceType.MANUAL_FIXTURE)
        self.assertEqual(observation.page_type, PageType.CHAT_THREAD)
        self.assertEqual(observation.match_identity_hints.visible_name, "Alex")
        self.assertEqual(
            observation.conversation_observation.visible_messages[-1]["text"],
            "It was. What are you up to this weekend?",
        )

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

    def test_visible_message_text_round_trip_preserves_multiple_sentences(self):
        observation = AppObservation.from_dict(
            {
                "observation_id": "obs_multi_sentence",
                "source_type": "manual_fixture",
                "app_id": "generic",
                "adapter_id": "manual.fixture.v1",
                "captured_at": "2026-05-25T00:00:00Z",
                "page_type": "chat_thread",
                "page_confidence": "high",
                "match_identity_hints": {
                    "visible_name": None,
                    "profile_cues": [],
                    "conversation_fingerprint": None,
                    "evidence": "",
                },
                "profile_observation": {
                    "profile_text": "",
                    "photo_cues": [],
                    "hook_candidates": [],
                },
                "conversation_observation": {
                    "visible_messages": [
                        {"sender": "match", "text": "It was. What are you up to this weekend?"}
                    ],
                    "input_state": "empty",
                    "thread_cues": [],
                },
                "element_observations": [],
                "exception_state": "none",
                "provenance": {},
                "raw_ref": None,
            }
        )

        decoded = AppObservation.from_dict(observation.to_dict())

        self.assertEqual(
            decoded.conversation_observation.visible_messages[0]["text"],
            "It was. What are you up to this weekend?",
        )

    def test_builds_observation_from_manual_screenshot_analysis(self):
        observation = build_observation_from_screenshot_analysis(
            screenshot_path=Path("/tmp/tinder-screen.png"),
            analysis={
                "observation_id": "obs_screen_001",
                "app_id": "tinder",
                "captured_at": "2026-05-25T00:00:00Z",
                "page_type": "chat_thread",
                "page_confidence": "medium",
                "match_identity_hints": {
                    "visible_name": "Riley",
                    "profile_cues": ["likes climbing"],
                    "conversation_fingerprint": "riley-climbing",
                    "evidence": "Manual screenshot analysis",
                },
                "profile_observation": {
                    "profile_text": "Climbing gym regular.",
                    "photo_cues": ["bouldering wall"],
                    "hook_candidates": ["Ask about climbing routes"],
                },
                "conversation_observation": {
                    "visible_messages": [{"sender": "match", "text": "Do you climb too?"}],
                    "input_state": "empty",
                    "thread_cues": ["climbing question"],
                },
            },
        )

        self.assertEqual(observation.source_type, SourceType.SCREENSHOT_FIXTURE)
        self.assertEqual(observation.raw_ref, "/tmp/tinder-screen.png")
        self.assertEqual(observation.match_identity_hints.visible_name, "Riley")


if __name__ == "__main__":
    unittest.main()
