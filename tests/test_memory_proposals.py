from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dating_boost.core.memory.models import (
    EvidenceRef,
    MatchMemoryProjection,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.core.memory.proposals import classify_risk, extract_proposals
from dating_boost.core.memory.review_queue import ReviewQueueRepository
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation

FIXTURE_PATH = Path("tests/fixtures/intelligence/app_observation_chat.json")


class ClassifyRiskTests(unittest.TestCase):
    def test_low_risk_profile_cue(self):
        self.assertEqual(classify_risk("profile_cue", "likes jazz"), "low")

    def test_medium_risk_date_logistics(self):
        self.assertEqual(classify_risk("date_logistics", "Let's meet Friday"), "medium")

    def test_high_risk_phone(self):
        self.assertEqual(classify_risk("phone_number", "555-1234"), "high")

    def test_high_risk_email(self):
        self.assertEqual(classify_risk("email", "test@example.com"), "high")

    def test_high_risk_social_media(self):
        self.assertEqual(classify_risk("social_media", "instagram handle"), "high")

    def test_medium_risk_commitment(self):
        self.assertEqual(classify_risk("commitment", "promised to call"), "medium")

    def test_low_risk_default(self):
        self.assertEqual(classify_risk("hobby", "photography"), "low")


class ExtractProposalsTests(unittest.TestCase):
    def setUp(self):
        self.observation = load_observation(FIXTURE_PATH)
        self.projection = MatchMemoryProjection(match_id="match_alex")

    def test_extracts_profile_cue_proposals(self):
        proposals = extract_proposals("match_alex", self.observation, self.projection)
        self.assertGreater(len(proposals), 0)
        for item in proposals:
            self.assertEqual(item.source, "deterministic")
            self.assertEqual(item.status, "pending")

    def test_no_proposals_for_existing_facts(self):
        from dating_boost.core.memory.models import normalized_fact_key

        n_key = normalized_fact_key("Alex", "profile_cue", {"app_id": "tinder"})
        existing_fact = MemoryFact(
            fact_id="fact_existing",
            scope=MemoryScope.MATCH_PROFILE,
            fact_type=MemoryFactType.VISIBLE_FACT,
            subject="Alex",
            predicate="profile_cue",
            value="likes live music",
            qualifiers={"app_id": "tinder"},
            confidence="high",
            evidence=EvidenceRef(
                source_type="observation",
                source_observation_id="obs_prior",
                evidence_text="prior",
            ),
            created_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-01T00:00:00Z",
        )
        projection_with_fact = MatchMemoryProjection(
            match_id="match_alex",
            facts=[existing_fact],
        )
        proposals = extract_proposals("match_alex", self.observation, projection_with_fact)
        profile_proposals = [
            p for p in proposals if p.proposal.get("predicate") == "profile_cue"
        ]
        for p in profile_proposals:
            self.assertNotEqual(p.proposal.get("value"), "likes live music")

    def test_proposals_have_correct_fields(self):
        proposals = extract_proposals("match_alex", self.observation, self.projection)
        required_fields = [
            "review_item_id",
            "session_id",
            "match_id",
            "proposal",
            "status",
            "dedupe_key",
            "source",
            "risk",
        ]
        for item in proposals:
            for field_name in required_fields:
                self.assertTrue(
                    hasattr(item, field_name),
                    f"Missing field: {field_name}",
                )

    def test_proposals_are_low_risk_for_profile_cues(self):
        proposals = extract_proposals("match_alex", self.observation, self.projection)
        profile_proposals = [
            p for p in proposals if p.proposal.get("predicate") == "profile_cue"
        ]
        self.assertGreater(len(profile_proposals), 0)
        for item in profile_proposals:
            self.assertEqual(item.risk, "low")

    def test_ui_only_thread_cues_are_not_memory_suggestions(self):
        payload = self.observation.to_dict()
        payload["conversation_observation"]["thread_cues"] = [
            "ordinary conversation page",
            "bottom input toolbar present",
            "notification banner visible but not blocking input",
            "question gate skipped",
        ]
        observation = AppObservation.from_dict(payload)

        proposals = extract_proposals("match_alex", observation, self.projection)
        thread_cues = [
            item.proposal.get("value")
            for item in proposals
            if item.proposal.get("predicate") == "thread_cue"
        ]

        self.assertNotIn("ordinary conversation page", thread_cues)
        self.assertNotIn("bottom input toolbar present", thread_cues)
        self.assertNotIn("notification banner visible but not blocking input", thread_cues)
        self.assertIn("question gate skipped", thread_cues)

    def test_dedupe_key_prevents_reenqueue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = ReviewQueueRepository(Path(tmpdir))
            proposals = extract_proposals("match_alex", self.observation, self.projection)
            for item in proposals:
                repo.enqueue(item)
            for item in proposals:
                repo.enqueue(item)
            total = len(repo.load_items(match_id="match_alex", status="pending"))
            self.assertEqual(total, len(proposals))


class ExtractProposalsWithSessionTests(unittest.TestCase):
    def setUp(self):
        self.observation = load_observation(FIXTURE_PATH)
        self.projection = MatchMemoryProjection(match_id="match_alex")

    def test_proposals_carry_session_id(self):
        proposals = extract_proposals(
            "match_alex",
            self.observation,
            self.projection,
            session_id="session_abc",
        )
        self.assertGreater(len(proposals), 0)
        for item in proposals:
            self.assertEqual(item.session_id, "session_abc")

    def test_proposals_carry_observation_id(self):
        proposals = extract_proposals(
            "match_alex",
            self.observation,
            self.projection,
            observation_id="obs_123",
        )
        self.assertGreater(len(proposals), 0)
        for item in proposals:
            self.assertEqual(item.observation_id, "obs_123")


if __name__ == "__main__":
    unittest.main()
