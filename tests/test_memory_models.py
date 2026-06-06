import json
import unittest

from dating_boost.core.memory.models import (
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


class MemoryModelTests(unittest.TestCase):
    def test_memory_event_round_trips_to_json_safe_dict(self):
        event = MemoryEvent(
            event_id="evt_1",
            event_type=MemoryEventType.PROFILE_FACT_OBSERVED,
            match_id="match_ada",
            scope=MemoryScope.MATCH_PROFILE,
            created_at="2026-06-06T00:00:00Z",
            payload={"fact_id": "fact_1", "value": "likes live music"},
            evidence=EvidenceRef(
                source_type="observation",
                source_observation_id="obs_1",
                evidence_text="Visible profile cue: live music.",
                confidence="medium",
            ),
        )

        encoded = event.to_dict()
        decoded = MemoryEvent.from_dict(encoded)

        json.dumps(encoded)
        self.assertEqual(encoded["event_type"], "profile_fact_observed")
        self.assertEqual(encoded["scope"], "match_profile")
        self.assertEqual(encoded["evidence"]["confidence"], "medium")
        self.assertEqual(decoded, event)

    def test_observation_evidence_requires_observation_id(self):
        with self.assertRaises(ValueError):
            EvidenceRef(source_type="observation", evidence_text="Visible cue.")

    def test_memory_fact_round_trips_status_and_stable_conflict_key(self):
        fact = MemoryFact(
            fact_id="fact_city_1",
            scope=MemoryScope.MATCH_PROFILE,
            fact_type=MemoryFactType.VISIBLE_FACT,
            subject="Ada",
            predicate="city",
            value="Shanghai",
            qualifiers={"app_id": "tinder"},
            confidence="high",
            evidence=EvidenceRef(
                source_type="observation",
                source_observation_id="obs_1",
                evidence_text="Profile says Shanghai.",
            ),
            created_at="2026-06-06T00:00:00Z",
            last_seen_at="2026-06-06T00:00:00Z",
            valid_from="2026-06-06T00:00:00Z",
            valid_until="2026-06-20T00:00:00Z",
        )

        encoded = fact.to_dict()
        decoded = MemoryFact.from_dict(encoded)

        self.assertEqual(decoded.status, MemoryFactStatus.ACTIVE)
        self.assertEqual(decoded.normalized_key, "ada|city|app_id=tinder")
        self.assertEqual(decoded.normalized_value, "shanghai")
        self.assertEqual(decoded.valid_from, "2026-06-06T00:00:00Z")
        self.assertEqual(decoded.valid_until, "2026-06-20T00:00:00Z")

    def test_memory_fact_without_subject_or_predicate_has_no_conflict_key(self):
        fact = MemoryFact(
            fact_id="fact_invalid_key",
            scope=MemoryScope.MATCH_PROFILE,
            fact_type=MemoryFactType.VISIBLE_FACT,
            subject="",
            predicate="",
            value="Shanghai",
            qualifiers={},
            confidence="medium",
            evidence=EvidenceRef(
                source_type="observation",
                source_observation_id="obs_1",
                evidence_text="Incomplete extracted fact.",
            ),
            created_at="2026-06-06T00:00:00Z",
            last_seen_at="2026-06-06T00:00:00Z",
        )

        self.assertIsNone(fact.normalized_key)
        self.assertEqual(fact.normalized_value, "shanghai")

    def test_memory_fact_from_dict_treats_null_subject_or_predicate_as_missing_key(self):
        data = {
            "fact_id": "fact_null_key",
            "scope": "match_profile",
            "fact_type": "visible_fact",
            "subject": None,
            "predicate": None,
            "value": "Shanghai",
            "qualifiers": {},
            "confidence": "medium",
            "evidence": {
                "source_type": "observation",
                "source_observation_id": "obs_1",
                "evidence_text": "Incomplete extracted fact.",
            },
            "created_at": "2026-06-06T00:00:00Z",
            "last_seen_at": "2026-06-06T00:00:00Z",
        }

        fact = MemoryFact.from_dict(data)

        self.assertEqual(fact.subject, "")
        self.assertEqual(fact.predicate, "")
        self.assertIsNone(fact.normalized_key)

    def test_memory_fact_rejects_malformed_explicit_normalized_key(self):
        with self.assertRaises(ValueError):
            MemoryFact(
                fact_id="fact_bad_key",
                scope=MemoryScope.MATCH_PROFILE,
                fact_type=MemoryFactType.VISIBLE_FACT,
                subject="Ada",
                predicate="city",
                value="Shanghai",
                qualifiers={},
                confidence="medium",
                evidence=EvidenceRef(
                    source_type="observation",
                    source_observation_id="obs_1",
                    evidence_text="Malformed key test.",
                ),
                created_at="2026-06-06T00:00:00Z",
                last_seen_at="2026-06-06T00:00:00Z",
                normalized_key="bad-key",
            )

    def test_inference_does_not_serialize_as_visible_fact(self):
        inference = MemoryFact(
            fact_id="inf_1",
            scope=MemoryScope.MATCH_PROFILE,
            fact_type=MemoryFactType.INFERENCE,
            subject="Ada",
            predicate="possible_interest",
            value="climbing",
            qualifiers={},
            confidence="low",
            evidence=EvidenceRef(
                source_type="observation",
                source_observation_id="obs_1",
                evidence_text="Photo cue looked like climbing gear.",
            ),
            created_at="2026-06-06T00:00:00Z",
            last_seen_at="2026-06-06T00:00:00Z",
        )

        self.assertEqual(inference.to_dict()["fact_type"], "inference")

    def test_projection_exposes_identity_trust_fields(self):
        projection = MatchMemoryProjection(
            match_id="match_ada",
            identity_status=IdentityTrustStatus.NEEDS_CONFIRMATION,
            trusted_for_context=False,
            trusted_for_managed_send=False,
            updated_at="2026-06-06T00:00:00Z",
        )

        encoded = projection.to_dict()
        decoded = MatchMemoryProjection.from_dict(encoded)

        self.assertEqual(encoded["schema_version"], 1)
        self.assertEqual(decoded.identity_status, IdentityTrustStatus.NEEDS_CONFIRMATION)
        self.assertFalse(decoded.trusted_for_context)
        self.assertFalse(decoded.trusted_for_managed_send)


if __name__ == "__main__":
    unittest.main()
