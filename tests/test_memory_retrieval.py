import unittest
from pathlib import Path

from dating_boost.core.memory.models import (
    CommitmentMemory,
    EvidenceRef,
    IdentityTrustStatus,
    MatchMemoryProjection,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.core.memory.retrieval import build_memory_context
from dating_boost.core.memory.semantic import SemanticHookCandidate
from dating_boost.perception.fixture_loader import load_observation


NOW = "2026-06-06T00:00:00Z"
FIXTURE_PATH = Path("tests/fixtures/intelligence/app_observation_chat.json")


def evidence() -> EvidenceRef:
    return EvidenceRef(
        source_type="observation",
        source_observation_id="obs_1",
        evidence_text="test evidence",
        confidence="medium",
    )


def fact(
    fact_id: str,
    *,
    predicate: str,
    value: str,
    status: MemoryFactStatus = MemoryFactStatus.ACTIVE,
    valid_until: str | None = None,
    confidence: str = "medium",
) -> MemoryFact:
    return MemoryFact(
        fact_id=fact_id,
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=MemoryFactType.VISIBLE_FACT,
        subject="Alex",
        predicate=predicate,
        value=value,
        qualifiers={"app_id": "tinder"},
        confidence=confidence,
        evidence=evidence(),
        created_at=NOW,
        last_seen_at=NOW,
        valid_until=valid_until,
        status=status,
    )


def inference(fact_id: str, *, predicate: str, value: str) -> MemoryFact:
    return MemoryFact(
        fact_id=fact_id,
        scope=MemoryScope.MATCH_PROFILE,
        fact_type=MemoryFactType.INFERENCE,
        subject="Alex",
        predicate=predicate,
        value=value,
        qualifiers={"app_id": "tinder"},
        confidence="low",
        evidence=evidence(),
        created_at=NOW,
        last_seen_at=NOW,
    )


class MemoryRetrievalTests(unittest.TestCase):
    def test_projection_and_latest_observation_build_context(self):
        observation = load_observation(FIXTURE_PATH)
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            facts=[
                fact("fact_profile_text", predicate="profile_text", value="Live music, coffee."),
            ],
            inferences=[
                inference("hook_1", predicate="hook_candidate", value="Ask about live music"),
            ],
            active_commitments=[
                CommitmentMemory(
                    commitment_id="commitment_1",
                    text="Follow up about weekend availability.",
                    evidence=evidence(),
                    created_at=NOW,
                    last_seen_at=NOW,
                )
            ],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=observation,
            now=NOW,
            max_items=None,
        )

        self.assertEqual(context["match_profile"]["profile_text"], "Live music, coffee.")
        self.assertIn("Ask about live music", context["match_profile"]["conversation_hooks"])
        self.assertEqual(
            context["conversation_memory"]["latest_inbound_messages"][-1]["text"],
            "It was. What are you up to this weekend?",
        )
        self.assertEqual(
            context["conversation_memory"]["commitments"][0]["text"],
            "Follow up about weekend availability.",
        )
        labels = [item["label"] for item in context["memory_items"]]
        self.assertLess(labels.index("latest_inbound_messages"), labels.index("conversation_summary"))
        self.assertLess(labels.index("active_commitments"), labels.index("low_confidence_hypotheses"))

    def test_retrieval_excludes_conflicted_rejected_and_stale_facts(self):
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            facts=[
                fact("active", predicate="profile_cue", value="likes jazz"),
                fact("conflicted", predicate="city", value="Shanghai", status=MemoryFactStatus.CONFLICTED),
                fact("rejected", predicate="profile_cue", value="likes dogs", status=MemoryFactStatus.REJECTED),
                fact("stale", predicate="availability", value="free this weekend", valid_until="2026-06-01T00:00:00Z"),
            ],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=None,
            now=NOW,
            max_items=None,
        )

        self.assertIn("likes jazz", context["match_profile"]["conversation_hooks"])
        self.assertNotIn("Shanghai", str(context["match_profile"]))
        self.assertNotIn("likes dogs", str(context["match_profile"]))
        self.assertNotIn("free this weekend", str(context["match_profile"]))
        excluded = {item["fact_id"]: item["reason"] for item in context["excluded_memory"]}
        self.assertEqual(excluded["conflicted"], "conflicted")
        self.assertEqual(excluded["rejected"], "rejected")
        self.assertEqual(excluded["stale"], "stale")

    def test_retrieval_excludes_low_confidence_visible_facts(self):
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            facts=[
                fact("low_visible", predicate="profile_cue", value="maybe likes hiking", confidence="low"),
                fact("medium_visible", predicate="profile_cue", value="likes jazz", confidence="medium"),
            ],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=None,
            now=NOW,
            max_items=None,
        )

        self.assertIn("likes jazz", context["match_profile"]["conversation_hooks"])
        self.assertNotIn("maybe likes hiking", str(context["match_profile"]))
        excluded = {item["fact_id"]: item["reason"] for item in context["excluded_memory"]}
        self.assertEqual(excluded["low_visible"], "low_confidence")

    def test_untrusted_projection_contributes_only_identity_diagnostics(self):
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.CONFLICTED,
            trusted_for_context=False,
            trusted_for_managed_send=False,
            updated_at=NOW,
            facts=[fact("active", predicate="profile_cue", value="likes jazz")],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=None,
            now=NOW,
            max_items=None,
        )

        self.assertEqual(context["match_profile"]["conversation_hooks"], [])
        self.assertEqual(context["match_profile"]["possible_interests"], [])
        self.assertEqual(context["memory_items"][0]["label"], "identity_trust")
        self.assertEqual(context["memory_items"][0]["content"]["identity_status"], "conflicted")
        self.assertEqual(context["excluded_memory"][0]["reason"], "untrusted_identity")

    def test_context_budget_keeps_turn_boundary(self):
        observation = load_observation(FIXTURE_PATH)
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            facts=[
                fact("fact_1", predicate="profile_cue", value="likes jazz"),
                fact("fact_2", predicate="profile_cue", value="has a dog"),
            ],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=observation,
            now=NOW,
            max_items=2,
        )

        labels = [item["label"] for item in context["memory_items"]]
        self.assertEqual(len(labels), 2)
        self.assertIn("latest_inbound_messages", labels)
        self.assertIn("turn_boundary", labels)

    def test_context_budget_records_budget_exclusions_and_keeps_turn_boundary_at_one(self):
        observation = load_observation(FIXTURE_PATH)
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            facts=[
                fact("fact_1", predicate="profile_cue", value="likes jazz"),
                fact("fact_2", predicate="profile_cue", value="has a dog"),
                fact("fact_3", predicate="profile_cue", value="works in design"),
            ],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=observation,
            now=NOW,
            max_items=1,
        )

        labels = [item["label"] for item in context["memory_items"]]
        self.assertEqual(labels, ["turn_boundary"])
        self.assertLessEqual(len(labels), 1)
        self.assertIn("budget", {item["reason"] for item in context["excluded_memory"]})

    def test_mode_feedback_preferences_use_reducer_schema(self):
        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            feedback_preferences={
                "adaptive": {
                    "tone_negative": {
                        "too_flirty": 2,
                    },
                },
            },
        )

        adaptive_context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=None,
            now=NOW,
            max_items=None,
            reply_mode="adaptive",
        )
        self_context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=None,
            now=NOW,
            max_items=None,
            reply_mode="self",
        )

        adaptive_items = {item["label"]: item["content"] for item in adaptive_context["memory_items"]}
        self_labels = [item["label"] for item in self_context["memory_items"]]
        self.assertEqual(adaptive_items["mode_feedback_preferences"]["tone_negative"]["too_flirty"], 2)
        self.assertNotIn("mode_feedback_preferences", self_labels)

    def test_semantic_hook_retrieval_filters_rejected_conflicted_and_photo_cues(self):
        class FakeSemanticProvider:
            def retrieve_hooks(self, query, facts, limit):
                return [
                    SemanticHookCandidate(fact_id="rejected_hook", text="Rejected hook", score=0.99),
                    SemanticHookCandidate(fact_id="conflicted_hook", text="Conflicted hook", score=0.98),
                    SemanticHookCandidate(fact_id="photo_cue", text="Photo cue promoted", score=0.97),
                    SemanticHookCandidate(fact_id="semantic_profile", text="Semantic hook", score=0.96),
                ]

        projection = MatchMemoryProjection(
            match_id="match_alex",
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=NOW,
            facts=[
                fact("structured_hook", predicate="profile_cue", value="Structured jazz hook"),
                fact("semantic_profile", predicate="profile_text", value="Coffee profile detail"),
                fact("rejected_hook", predicate="hook_candidate", value="Rejected hook", status=MemoryFactStatus.REJECTED),
                fact("conflicted_hook", predicate="hook_candidate", value="Conflicted hook", status=MemoryFactStatus.CONFLICTED),
            ],
            inferences=[
                MemoryFact(
                    fact_id="photo_cue",
                    scope=MemoryScope.MATCH_PROFILE,
                    fact_type=MemoryFactType.PHOTO_CUE,
                    subject="Alex",
                    predicate="photo_cue",
                    value="Dog photo",
                    qualifiers={"app_id": "tinder"},
                    confidence="low",
                    evidence=evidence(),
                    created_at=NOW,
                    last_seen_at=NOW,
                )
            ],
        )

        context = build_memory_context(
            "match_alex",
            projection,
            latest_observation=None,
            now=NOW,
            max_items=None,
            semantic_hook_provider=FakeSemanticProvider(),
            semantic_query="coffee",
        )

        hooks = context["match_profile"]["conversation_hooks"]
        self.assertIn("Structured jazz hook", hooks)
        self.assertIn("Coffee profile detail", hooks)
        self.assertNotIn("Rejected hook", hooks)
        self.assertNotIn("Conflicted hook", hooks)
        self.assertNotIn("Dog photo", hooks)
        self.assertLess(hooks.index("Structured jazz hook"), hooks.index("Coffee profile detail"))


if __name__ == "__main__":
    unittest.main()
