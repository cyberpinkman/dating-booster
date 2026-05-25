import tempfile
import unittest
from pathlib import Path

from dating_boost.core.feedback import FeedbackLabel, create_feedback_event
from dating_boost.core.models import ReplyMode
from dating_boost.core.repositories import JsonMemoryRepository


class FeedbackTests(unittest.TestCase):
    def test_feedback_event_contains_mode_and_label(self):
        event = create_feedback_event(
            event_id="fb_1",
            match_id="match_alex",
            draft_id="draft_1",
            mode="adaptive",
            label=FeedbackLabel.ACCEPTED,
            created_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(event["label"], "accepted")
        self.assertEqual(event["mode"], "adaptive")

    def test_feedback_event_accepts_valid_string_label(self):
        event = create_feedback_event(
            event_id="fb_1",
            match_id="match_alex",
            draft_id="draft_1",
            mode="adaptive",
            label="too_short",
            created_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(event["label"], "too_short")

    def test_feedback_event_rejects_invalid_string_label(self):
        with self.assertRaises(ValueError):
            create_feedback_event(
                event_id="fb_1",
                match_id="match_alex",
                draft_id="draft_1",
                mode="adaptive",
                label="not_a_real_label",
                created_at="2026-05-25T00:00:00Z",
            )

    def test_feedback_event_serializes_reply_mode_enum(self):
        event = create_feedback_event(
            event_id="fb_1",
            match_id="match_alex",
            draft_id="draft_1",
            mode=ReplyMode.RECIPIENT_OPTIMIZED,
            label=FeedbackLabel.ACCEPTED,
            created_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(event["mode"], "recipient_optimized")

    def test_feedback_event_contains_all_required_fields(self):
        event = create_feedback_event(
            event_id="fb_1",
            match_id="match_alex",
            draft_id="draft_1",
            mode="adaptive",
            label=FeedbackLabel.ACCEPTED,
            created_at="2026-05-25T00:00:00Z",
        )

        self.assertEqual(
            set(event),
            {"event_id", "match_id", "draft_id", "mode", "label", "created_at"},
        )

    def test_feedback_event_persists_through_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = JsonMemoryRepository(Path(temp_dir))
            event = create_feedback_event(
                event_id="fb_1",
                match_id="match_alex",
                draft_id="draft_1",
                mode="adaptive",
                label=FeedbackLabel.TOO_LONG,
                created_at="2026-05-25T00:00:00Z",
            )

            repo.append_feedback_event("match_alex", event)

            self.assertEqual(repo.load_feedback_events("match_alex")[0]["label"], "too_long")


if __name__ == "__main__":
    unittest.main()
