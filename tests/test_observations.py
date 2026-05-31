import unittest
from pathlib import Path

from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.perception.taxonomy import ExceptionState, PageType, SourceType


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

    def test_latest_inbound_messages_are_derived_after_latest_user_message(self):
        observation = AppObservation.from_dict(
            {
                "observation_id": "obs_turn_boundary",
                "source_type": "manual_fixture",
                "app_id": "wechat",
                "adapter_id": "manual.fixture.v1",
                "captured_at": "2026-05-31T16:25:00+08:00",
                "page_type": "chat_thread",
                "page_confidence": "high",
                "match_identity_hints": {
                    "visible_name": "小青",
                    "profile_cues": [],
                    "conversation_fingerprint": "xiaoqing-cat-thread",
                    "evidence": "Visible chat thread.",
                },
                "profile_observation": {
                    "profile_text": "",
                    "photo_cues": [],
                    "hook_candidates": [],
                },
                "conversation_observation": {
                    "visible_messages": [
                        {"sender": "match", "text": "还有个猫猫大君"},
                        {"sender": "user", "text": "大左这个名字有点好笑...它是最有脾气那个吗"},
                        {"sender": "match", "text": "还好呀"},
                        {"sender": "match", "text": "都没什么脾气我家的猫"},
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

        self.assertEqual(
            [message["text"] for message in observation.conversation_observation.latest_inbound_messages],
            ["还好呀", "都没什么脾气我家的猫"],
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

    def test_authoring_guide_page_and_exception_values_are_supported(self):
        for page_type in (
            "home_card",
            "profile_detail",
            "match_list",
            "chat_thread",
            "new_match",
            "paywall",
            "permission",
            "error",
            "unknown",
        ):
            self.assertEqual(PageType(page_type).value, page_type)

        for exception_state in (
            "none",
            "partial_capture",
            "redacted",
            "paywall",
            "permission_blocked",
            "network_error",
            "login_required",
            "unknown",
        ):
            self.assertEqual(ExceptionState(exception_state).value, exception_state)

        observation = AppObservation.from_dict(
            {
                "observation_id": "obs_profile_detail",
                "source_type": "manual_fixture",
                "app_id": "tinder",
                "adapter_id": "codex.manual.v1",
                "captured_at": "2026-05-26T00:00:00Z",
                "page_type": "profile_detail",
                "page_confidence": "medium",
                "match_identity_hints": {
                    "visible_name": "Alex",
                    "profile_cues": ["live music"],
                    "conversation_fingerprint": "alex-profile",
                    "evidence": "Visible profile detail page.",
                },
                "profile_observation": {
                    "profile_text": "Mentions live music.",
                    "photo_cues": ["concert photo"],
                    "hook_candidates": ["Ask about recent shows"],
                },
                "conversation_observation": {
                    "visible_messages": [],
                    "input_state": "unknown",
                    "thread_cues": [],
                },
                "element_observations": [],
                "exception_state": "paywall",
                "provenance": {"redaction_status": "redacted"},
                "raw_ref": None,
            }
        )

        self.assertEqual(observation.page_type, PageType.PROFILE_DETAIL)
        self.assertEqual(observation.exception_state, ExceptionState.PAYWALL)


if __name__ == "__main__":
    unittest.main()
