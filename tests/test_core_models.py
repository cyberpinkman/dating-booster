import unittest

from dating_boost.core.models import (
    Confidence,
    MemoryItem,
    MemoryKind,
    MemoryStatus,
    ReplyMode,
    UserProfile,
)


class CoreModelTests(unittest.TestCase):
    def test_memory_item_round_trips_to_dict(self):
        item = MemoryItem(
            id="mem_1",
            kind=MemoryKind.FACT,
            content={"education": "Chinese university graduate"},
            source_type="user_input",
            evidence="User entered this during onboarding",
            confidence=Confidence.USER_CONFIRMED,
            created_at="2026-05-25T00:00:00Z",
            last_seen_at="2026-05-25T00:00:00Z",
        )

        encoded = item.to_dict()
        decoded = MemoryItem.from_dict(encoded)

        self.assertEqual(decoded.id, "mem_1")
        self.assertEqual(decoded.kind, MemoryKind.FACT)
        self.assertEqual(decoded.confidence, Confidence.USER_CONFIRMED)
        self.assertEqual(decoded.status, MemoryStatus.ACTIVE)

    def test_user_profile_contains_persona_and_stance_ranges(self):
        profile = UserProfile(
            schema_version=1,
            user_id="user_local",
            facts=[],
            preferences=[],
            boundaries=[],
            style_examples=["short and dry"],
            goals=["practice dating conversations"],
            persona_baseline="reserved",
            persona_range=["warmer", "more outgoing"],
            stance_range=["can express curiosity about new interests"],
            updated_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(profile.default_reply_mode, ReplyMode.ADAPTIVE)
        self.assertIn("more outgoing", profile.persona_range)
        self.assertIn("can express curiosity about new interests", profile.stance_range)


if __name__ == "__main__":
    unittest.main()
