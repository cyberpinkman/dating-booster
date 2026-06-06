import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path

from dating_boost.cli import main
from dating_boost.core.feedback import FeedbackLabel, create_feedback_event
from dating_boost.core.memory.models import (
    EvidenceRef,
    MemoryEvent,
    MemoryEventType,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.core.memory.reducers import reduce_match_memory
from dating_boost.core.memory.repositories import MemoryRepository
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

    def test_feedback_event_accepts_optional_memory_learning_fields(self):
        event = create_feedback_event(
            event_id="fb_1",
            match_id="match_alex",
            draft_id="draft_1",
            mode="adaptive",
            label=FeedbackLabel.ACCEPTED,
            created_at="2026-05-25T00:00:00Z",
            referenced_memory_ids=["fact_hook"],
            conversation_move="deepen_current",
            hook_source="match_hooks",
            edited_text_ref="draft_1_edited",
            user_confirmed_style_promotion=True,
        )

        self.assertEqual(event["referenced_memory_ids"], ["fact_hook"])
        self.assertEqual(event["conversation_move"], "deepen_current")
        self.assertEqual(event["hook_source"], "match_hooks")
        self.assertEqual(event["edited_text_ref"], "draft_1_edited")
        self.assertTrue(event["user_confirmed_style_promotion"])

    def test_wrong_assumption_feedback_rejects_referenced_memory(self):
        fact = _memory_fact("fact_assumption")

        projection = reduce_match_memory(
            "match_alex",
            [
                _memory_event("evt_fact", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": fact.to_dict()}),
                _memory_event(
                    "evt_feedback",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {
                        "mode": "adaptive",
                        "label": "wrong_assumption",
                        "referenced_memory_ids": ["fact_assumption"],
                    },
                ),
            ],
        )

        self.assertEqual(projection.inferences[0].status, MemoryFactStatus.REJECTED)
        self.assertEqual(
            projection.feedback_preferences["adaptive"]["labels"]["wrong_assumption"],
            1,
        )

    def test_wrong_assumption_feedback_rejects_referenced_fact_and_inference(self):
        fact = _memory_fact("fact_assumption")
        visible_fact = MemoryFact(
            fact_id="fact_visible",
            scope=MemoryScope.MATCH_PROFILE,
            fact_type=MemoryFactType.VISIBLE_FACT,
            subject="Alex",
            predicate="city",
            value="Shanghai",
            qualifiers={},
            confidence="medium",
            evidence=_evidence(),
            created_at="2026-05-25T00:00:00Z",
            last_seen_at="2026-05-25T00:00:00Z",
        )

        projection = reduce_match_memory(
            "match_alex",
            [
                _memory_event("evt_fact", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": visible_fact.to_dict()}),
                _memory_event("evt_inference", MemoryEventType.INFERENCE_RECORDED, {"fact": fact.to_dict()}),
                _memory_event(
                    "evt_feedback",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {
                        "mode": "adaptive",
                        "label": "wrong_assumption",
                        "referenced_memory_ids": ["fact_visible", "fact_assumption"],
                    },
                ),
            ],
        )

        self.assertEqual(projection.facts[0].status, MemoryFactStatus.REJECTED)
        self.assertEqual(projection.inferences[0].status, MemoryFactStatus.REJECTED)

    def test_feedback_preferences_are_scoped_by_mode_and_signal_type(self):
        projection = reduce_match_memory(
            "match_alex",
            [
                _memory_event(
                    "evt_not_like_me",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {"mode": "adaptive", "label": "not_like_me"},
                ),
                _memory_event(
                    "evt_too_flirty",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {"mode": "adaptive", "label": "too_flirty"},
                ),
                _memory_event(
                    "evt_accepted",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {
                        "mode": "adaptive",
                        "label": "accepted",
                        "conversation_move": "deepen_current",
                        "hook_source": "match_hooks",
                    },
                ),
                _memory_event(
                    "evt_edited",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {
                        "mode": "recipient_optimized",
                        "label": "edited",
                        "edited_text_ref": "draft_1_edited",
                    },
                ),
            ],
        )

        adaptive = projection.feedback_preferences["adaptive"]
        recipient = projection.feedback_preferences["recipient_optimized"]
        self.assertEqual(adaptive["style"]["not_like_me"], 1)
        self.assertEqual(adaptive["tone_negative"]["too_flirty"], 1)
        self.assertEqual(adaptive["accepted"]["conversation_moves"]["deepen_current"], 1)
        self.assertEqual(adaptive["accepted"]["hook_sources"]["match_hooks"], 1)
        self.assertEqual(recipient["edited"]["count"], 1)
        self.assertNotIn("style_promotions", recipient["edited"])

    def test_feedback_record_appends_memory_event_and_rebuilds_projection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "feedback",
                    "record",
                    "--data-dir",
                    str(data_dir),
                    "--match-id",
                    "match_alex",
                    "--draft-id",
                    "draft_1",
                    "--mode",
                    "adaptive",
                    "--label",
                    "too_flirty",
                ])
            payload = json.loads(output.getvalue())
            projection = MemoryRepository(data_dir).load_projection("match_alex")

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["projection_updated"])
            self.assertEqual(
                projection.feedback_preferences["adaptive"]["tone_negative"]["too_flirty"],
                1,
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


def _evidence() -> EvidenceRef:
    return EvidenceRef(source_type="user_input", evidence_text="test")


def _memory_fact(fact_id: str) -> MemoryFact:
    return MemoryFact(
        fact_id=fact_id,
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=MemoryFactType.INFERENCE,
        subject="Alex",
        predicate="possible_interest",
        value="climbing",
        qualifiers={},
        confidence="low",
        evidence=_evidence(),
        created_at="2026-05-25T00:00:00Z",
        last_seen_at="2026-05-25T00:00:00Z",
    )


def _memory_event(event_id: str, event_type: MemoryEventType, payload: dict) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        event_type=event_type,
        match_id="match_alex",
        scope=MemoryScope.MATCH_PROFILE,
        created_at="2026-05-25T00:00:00Z",
        payload=payload,
        evidence=_evidence(),
    )


if __name__ == "__main__":
    unittest.main()
