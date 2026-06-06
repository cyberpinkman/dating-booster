import tempfile
import unittest
from pathlib import Path

from dating_boost.core.memory.models import (
    CommitmentMemory,
    EvidenceRef,
    IdentityTrustStatus,
    MatchMemoryProjection,
    MemoryEvent,
    MemoryEventType,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.core.memory.reducers import reduce_match_memory
from dating_boost.core.memory.repositories import MemoryRepository


NOW = "2026-06-06T00:00:00Z"


def observation_evidence(observation_id: str = "obs_1") -> EvidenceRef:
    return EvidenceRef(
        source_type="observation",
        source_observation_id=observation_id,
        evidence_text="Visible test evidence.",
    )


def profile_fact(
    fact_id: str,
    *,
    subject: str = "Ada",
    predicate: str = "city",
    value: str = "Shanghai",
    fact_type: MemoryFactType = MemoryFactType.VISIBLE_FACT,
    observed_at: str = NOW,
) -> MemoryFact:
    return MemoryFact(
        fact_id=fact_id,
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=fact_type,
        subject=subject,
        predicate=predicate,
        value=value,
        qualifiers={"app_id": "tinder"},
        confidence="medium",
        evidence=observation_evidence(),
        created_at=observed_at,
        last_seen_at=observed_at,
    )


def invalid_key_fact(fact_id: str, *, value: str) -> MemoryFact:
    return MemoryFact(
        fact_id=fact_id,
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=MemoryFactType.VISIBLE_FACT,
        subject="",
        predicate="",
        value=value,
        qualifiers={},
        confidence="medium",
        evidence=observation_evidence(),
        created_at=NOW,
        last_seen_at=NOW,
    )


def event(
    event_id: str,
    event_type: MemoryEventType,
    payload: dict,
    *,
    created_at: str = NOW,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        event_type=event_type,
        match_id="match_ada",
        scope=MemoryScope.MATCH_PROFILE,
        created_at=created_at,
        payload=payload,
        evidence=observation_evidence(),
    )


class MemoryRepositoryTests(unittest.TestCase):
    def test_appends_and_loads_events_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = MemoryRepository(Path(temp_dir))
            first = event("evt_1", MemoryEventType.OBSERVATION_INGESTED, {"observation_id": "obs_1"})
            second = event("evt_2", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": profile_fact("fact_1").to_dict()})

            repo.append_event("match_ada", first)
            repo.append_event("match_ada", second)
            loaded = repo.load_events("match_ada")

            self.assertEqual([item.event_id for item in loaded], ["evt_1", "evt_2"])
            self.assertEqual(
                (Path(temp_dir) / "matches" / "match_ada" / "memory_events.jsonl").read_text(encoding="utf-8").count("\n"),
                2,
            )

    def test_duplicate_event_ids_are_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = MemoryRepository(Path(temp_dir))
            item = event("evt_1", MemoryEventType.OBSERVATION_INGESTED, {"observation_id": "obs_1"})

            repo.append_event("match_ada", item)
            repo.append_event("match_ada", item)

            self.assertEqual(len(repo.load_events("match_ada")), 1)

    def test_saves_and_loads_projection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = MemoryRepository(Path(temp_dir))
            projection = MatchMemoryProjection(
                match_id="match_ada",
                identity_status=IdentityTrustStatus.TRUSTED,
                trusted_for_context=True,
                trusted_for_managed_send=True,
                updated_at=NOW,
            )

            repo.save_projection("match_ada", projection)
            loaded = repo.load_projection("match_ada")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.identity_status, IdentityTrustStatus.TRUSTED)

    def test_rejects_unsafe_match_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = MemoryRepository(Path(temp_dir))
            item = event("evt_1", MemoryEventType.OBSERVATION_INGESTED, {"observation_id": "obs_1"})

            for match_id in ["", ".", "..", "../escape", "nested/match", "nested\\match"]:
                with self.subTest(match_id=match_id):
                    with self.assertRaises(ValueError):
                        repo.append_event(match_id, item)


class MemoryReducerTests(unittest.TestCase):
    def test_identical_observed_facts_merge_and_update_last_seen(self):
        first = profile_fact("fact_1", observed_at="2026-06-06T00:00:00Z")
        second = profile_fact("fact_2", observed_at="2026-06-07T00:00:00Z")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": first.to_dict()}),
                event("evt_2", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": second.to_dict()}, created_at="2026-06-07T00:00:00Z"),
            ],
        )

        self.assertEqual(len(projection.facts), 1)
        self.assertEqual(projection.facts[0].fact_id, "fact_1")
        self.assertEqual(projection.facts[0].last_seen_at, "2026-06-07T00:00:00Z")

    def test_conflicting_fact_marks_both_facts_conflicted(self):
        shanghai = profile_fact("fact_city_shanghai", value="Shanghai")
        beijing = profile_fact("fact_city_beijing", value="Beijing")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": shanghai.to_dict()}),
                event("evt_2", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": beijing.to_dict()}),
            ],
        )

        self.assertEqual({fact.status for fact in projection.facts}, {MemoryFactStatus.CONFLICTED})
        self.assertEqual(len(projection.conflicts), 1)
        self.assertEqual(projection.conflicts[0].normalized_key, "ada|city|app_id=tinder")

    def test_fact_correction_supersedes_old_fact(self):
        old = profile_fact("fact_old", value="Shanghai")
        corrected = profile_fact("fact_new", value="Hangzhou")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": old.to_dict()}),
                event(
                    "evt_2",
                    MemoryEventType.FACT_CORRECTED,
                    {"target_fact_id": "fact_old", "fact": corrected.to_dict()},
                ),
            ],
        )

        facts_by_id = {fact.fact_id: fact for fact in projection.facts}
        self.assertEqual(facts_by_id["fact_old"].status, MemoryFactStatus.ARCHIVED)
        self.assertEqual(facts_by_id["fact_new"].status, MemoryFactStatus.ACTIVE)
        self.assertIn("fact_old", facts_by_id["fact_new"].supersedes)

    def test_fact_rejection_marks_target_rejected(self):
        fact = profile_fact("fact_1")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": fact.to_dict()}),
                event("evt_2", MemoryEventType.FACT_REJECTED, {"target_fact_id": "fact_1"}),
            ],
        )

        self.assertEqual(projection.facts[0].status, MemoryFactStatus.REJECTED)

    def test_commitment_create_and_resolve_preserves_history(self):
        commitment = CommitmentMemory(
            commitment_id="commitment_1",
            text="Follow up about weekend plans.",
            evidence=observation_evidence(),
            created_at=NOW,
            last_seen_at=NOW,
        )

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.COMMITMENT_CREATED, {"commitment": commitment.to_dict()}),
                event(
                    "evt_2",
                    MemoryEventType.COMMITMENT_RESOLVED,
                    {"commitment_id": "commitment_1", "resolved_at": "2026-06-07T00:00:00Z"},
                    created_at="2026-06-07T00:00:00Z",
                ),
            ],
        )

        self.assertEqual(projection.active_commitments, [])
        self.assertEqual(projection.resolved_commitments[0].commitment_id, "commitment_1")
        self.assertEqual(projection.resolved_commitments[0].resolved_at, "2026-06-07T00:00:00Z")

    def test_commitment_created_appears_in_active_commitments(self):
        commitment = CommitmentMemory(
            commitment_id="commitment_1",
            text="Follow up about weekend plans.",
            evidence=observation_evidence(),
            created_at=NOW,
            last_seen_at=NOW,
        )

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.COMMITMENT_CREATED, {"commitment": commitment.to_dict()}),
            ],
        )

        self.assertEqual(len(projection.active_commitments), 1)
        self.assertEqual(projection.active_commitments[0].commitment_id, "commitment_1")
        self.assertEqual(projection.resolved_commitments, [])

    def test_feedback_updates_mode_scoped_counters_without_changing_facts(self):
        fact = profile_fact("fact_1")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": fact.to_dict()}),
                event(
                    "evt_2",
                    MemoryEventType.FEEDBACK_RECORDED,
                    {"mode": "adaptive", "label": "too_flirty"},
                ),
            ],
        )

        self.assertEqual(projection.feedback_preferences["adaptive"]["labels"]["too_flirty"], 1)
        self.assertEqual(projection.facts[0].status, MemoryFactStatus.ACTIVE)

    def test_identity_assessment_and_confirmation_update_trust(self):
        low = event(
            "evt_identity_low",
            MemoryEventType.MATCH_IDENTITY_ASSESSED,
            {"confidence": "low", "requires_user_confirmation": True},
        )
        confirmed = event(
            "evt_identity_confirmed",
            MemoryEventType.MATCH_IDENTITY_CONFIRMED,
            {"confirmed_by": "user"},
        )

        low_projection = reduce_match_memory("match_ada", [low])
        confirmed_projection = reduce_match_memory("match_ada", [low, confirmed])

        self.assertEqual(low_projection.identity_status, IdentityTrustStatus.NEEDS_CONFIRMATION)
        self.assertFalse(low_projection.trusted_for_managed_send)
        self.assertEqual(confirmed_projection.identity_status, IdentityTrustStatus.TRUSTED)
        self.assertTrue(confirmed_projection.trusted_for_context)
        self.assertTrue(confirmed_projection.trusted_for_managed_send)

    def test_identity_conflict_overrides_prior_trust(self):
        high = event(
            "evt_identity_high",
            MemoryEventType.MATCH_IDENTITY_ASSESSED,
            {"confidence": "high", "requires_user_confirmation": False},
        )
        conflict = event(
            "evt_identity_conflict",
            MemoryEventType.MATCH_IDENTITY_CONFLICT,
            {"reason": "duplicate visible name and cues"},
        )

        projection = reduce_match_memory("match_ada", [high, conflict])

        self.assertEqual(projection.identity_status, IdentityTrustStatus.CONFLICTED)
        self.assertFalse(projection.trusted_for_context)
        self.assertFalse(projection.trusted_for_managed_send)

    def test_identity_conflict_is_sticky_until_user_confirmation(self):
        conflict = event(
            "evt_identity_conflict",
            MemoryEventType.MATCH_IDENTITY_CONFLICT,
            {"reason": "duplicate visible name and cues"},
        )
        high_after_conflict = event(
            "evt_identity_high_after_conflict",
            MemoryEventType.MATCH_IDENTITY_ASSESSED,
            {"confidence": "high", "requires_user_confirmation": False},
        )
        confirmed = event(
            "evt_identity_confirmed",
            MemoryEventType.MATCH_IDENTITY_CONFIRMED,
            {"confirmed_by": "user"},
        )

        conflicted_projection = reduce_match_memory(
            "match_ada",
            [conflict, high_after_conflict],
        )
        confirmed_projection = reduce_match_memory(
            "match_ada",
            [conflict, high_after_conflict, confirmed],
        )

        self.assertEqual(conflicted_projection.identity_status, IdentityTrustStatus.CONFLICTED)
        self.assertFalse(conflicted_projection.trusted_for_context)
        self.assertFalse(conflicted_projection.trusted_for_managed_send)
        self.assertEqual(confirmed_projection.identity_status, IdentityTrustStatus.TRUSTED)
        self.assertTrue(confirmed_projection.trusted_for_context)
        self.assertTrue(confirmed_projection.trusted_for_managed_send)

    def test_post_confirmation_low_assessment_does_not_downgrade_trust(self):
        confirmed = event(
            "evt_identity_confirmed",
            MemoryEventType.MATCH_IDENTITY_CONFIRMED,
            {"confirmed_by": "user"},
        )
        low_after_confirmation = event(
            "evt_identity_low_after_confirmation",
            MemoryEventType.MATCH_IDENTITY_ASSESSED,
            {"confidence": "low", "requires_user_confirmation": True},
        )

        projection = reduce_match_memory(
            "match_ada",
            [confirmed, low_after_confirmation],
        )

        self.assertEqual(projection.identity_status, IdentityTrustStatus.TRUSTED)
        self.assertTrue(projection.trusted_for_context)
        self.assertTrue(projection.trusted_for_managed_send)

    def test_photo_cue_recorded_as_inference_not_fact(self):
        cue = profile_fact(
            "photo_cue_1",
            predicate="possible_interest",
            value="climbing",
            fact_type=MemoryFactType.PHOTO_CUE,
        )

        projection = reduce_match_memory(
            "match_ada",
            [
                event(
                    "evt_photo_cue",
                    MemoryEventType.INFERENCE_RECORDED,
                    {"fact": cue.to_dict()},
                ),
            ],
        )

        self.assertEqual(projection.facts, [])
        self.assertEqual(len(projection.inferences), 1)
        self.assertEqual(projection.inferences[0].fact_type, MemoryFactType.PHOTO_CUE)

    def test_inference_recorded_event_always_stays_in_inferences(self):
        for fact_type in [
            MemoryFactType.VISIBLE_FACT,
            MemoryFactType.USER_CONFIRMED,
            MemoryFactType.PHOTO_CUE,
            MemoryFactType.INFERENCE,
        ]:
            with self.subTest(fact_type=fact_type.value):
                fact = profile_fact(
                    f"{fact_type.value}_inference_payload",
                    predicate="possible_interest",
                    value="climbing",
                    fact_type=fact_type,
                )

                projection = reduce_match_memory(
                    "match_ada",
                    [
                        event(
                            f"evt_{fact_type.value}_inference_payload",
                            MemoryEventType.INFERENCE_RECORDED,
                            {"fact": fact.to_dict()},
                        ),
                    ],
                )

                self.assertEqual(projection.facts, [])
                self.assertEqual(len(projection.inferences), 1)
                self.assertEqual(projection.inferences[0].fact_type, fact_type)

    def test_facts_without_valid_conflict_key_do_not_conflict(self):
        first = invalid_key_fact("fact_invalid_1", value="Shanghai")
        second = invalid_key_fact("fact_invalid_2", value="Beijing")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": first.to_dict()}),
                event("evt_2", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": second.to_dict()}),
            ],
        )

        self.assertEqual(len(projection.facts), 2)
        self.assertEqual(projection.conflicts, [])
        self.assertEqual([fact.status for fact in projection.facts], [MemoryFactStatus.ACTIVE, MemoryFactStatus.ACTIVE])
        self.assertEqual([fact.normalized_key for fact in projection.facts], [None, None])

    def test_correction_after_conflict_recomputes_conflicted_status(self):
        shanghai = profile_fact("fact_city_shanghai", value="Shanghai")
        beijing = profile_fact("fact_city_beijing", value="Beijing")
        corrected = profile_fact("fact_city_corrected", value="Beijing")

        projection = reduce_match_memory(
            "match_ada",
            [
                event("evt_1", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": shanghai.to_dict()}),
                event("evt_2", MemoryEventType.PROFILE_FACT_OBSERVED, {"fact": beijing.to_dict()}),
                event(
                    "evt_3",
                    MemoryEventType.FACT_CORRECTED,
                    {"target_fact_id": "fact_city_shanghai", "fact": corrected.to_dict()},
                ),
            ],
        )

        facts_by_id = {fact.fact_id: fact for fact in projection.facts}
        self.assertEqual(facts_by_id["fact_city_shanghai"].status, MemoryFactStatus.ARCHIVED)
        self.assertEqual(facts_by_id["fact_city_beijing"].status, MemoryFactStatus.ACTIVE)
        self.assertEqual(facts_by_id["fact_city_corrected"].status, MemoryFactStatus.ACTIVE)
        self.assertEqual(projection.conflicts, [])


if __name__ == "__main__":
    unittest.main()
