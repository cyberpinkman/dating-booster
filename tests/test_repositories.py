import tempfile
import unittest
from pathlib import Path

from dating_boost.core.models import Confidence, MemoryItem, MemoryKind, ReplyMode, UserProfile
from dating_boost.core.repositories import JsonMemoryRepository


class RepositoryTests(unittest.TestCase):
    def test_saves_and_loads_user_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))
            profile = UserProfile(
                schema_version=1,
                user_id="user_local",
                facts=[],
                preferences=[],
                boundaries=[],
                style_examples=["concise"],
                goals=["practice"],
                persona_baseline="reserved",
                persona_range=["warmer"],
                stance_range=["open to new interests"],
                updated_at="2026-05-25T00:00:00Z",
            )

            repo.save_user_profile(profile)
            loaded = repo.load_user_profile()

            self.assertEqual(loaded.user_id, "user_local")
            self.assertEqual(loaded.persona_range, ["warmer"])

    def test_appends_feedback_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))

            repo.append_feedback_event("match_1", {"event_id": "fb_1", "label": "accepted"})
            repo.append_feedback_event("match_1", {"event_id": "fb_2", "label": "too_long"})
            events = repo.load_feedback_events("match_1")

            self.assertEqual([event["event_id"] for event in events], ["fb_1", "fb_2"])

    def test_rejects_unsafe_match_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))

            for match_id in ["", "../escape", "nested/match", "nested\\match"]:
                with self.subTest(match_id=match_id):
                    with self.assertRaises(ValueError):
                        repo.append_feedback_event(match_id, {"event_id": "fb_1"})
                    with self.assertRaises(ValueError):
                        repo.load_feedback_events(match_id)

    def test_user_profile_serializes_memory_items_and_reply_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))
            fact = MemoryItem(
                id="mem_1",
                kind=MemoryKind.FACT,
                content={"city": "Shanghai"},
                source_type="user_input",
                evidence="User stated this",
                confidence=Confidence.USER_CONFIRMED,
                created_at="2026-05-25T00:00:00Z",
                last_seen_at="2026-05-25T00:00:00Z",
            )
            profile = UserProfile(
                schema_version=1,
                user_id="user_local",
                facts=[fact],
                preferences=[],
                boundaries=[],
                style_examples=[],
                goals=[],
                persona_baseline="reserved",
                persona_range=[],
                stance_range=[],
                updated_at="2026-05-25T00:00:00Z",
                default_reply_mode=ReplyMode.SELF,
            )

            repo.save_user_profile(profile)
            raw_profile = Path(temp_dir, "user_profile.json").read_text(encoding="utf-8")
            loaded = repo.load_user_profile()

            self.assertIn('"default_reply_mode": "self"', raw_profile)
            self.assertEqual(loaded.default_reply_mode, ReplyMode.SELF)
            self.assertEqual(loaded.facts[0], fact)


if __name__ == "__main__":
    unittest.main()
