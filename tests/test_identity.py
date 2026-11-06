import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from dating_boost.core.draft_evidence import build_draft_evidence
from dating_boost.core.memory.extractors import events_from_observation
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.models import MatchMemoryProjection
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.repositories import MatchRepository, ObservationRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.core.identity import IdentityConfidence, resolve_match_identity
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation, MatchIdentityHints
from dating_boost.perception.taxonomy import PageType, SourceType


class IdentityTests(unittest.TestCase):
    def test_creates_new_match_when_no_candidates_exist(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(observation, existing_matches=[])

        self.assertEqual(result.confidence, IdentityConfidence.NEW)
        self.assertTrue(result.match_id.startswith("match_"))
        self.assertFalse(result.requires_user_confirmation)

    def test_low_confidence_name_only_match_requires_confirmation(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[{"match_id": "match_existing", "app_id": observation.app_id, "display_name": "Alex"}],
        )

        self.assertEqual(result.confidence, IdentityConfidence.LOW)
        self.assertTrue(result.requires_user_confirmation)

    def test_high_confidence_match_uses_profile_and_fingerprint(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[
                {
                    "match_id": "match_alex",
                    "app_id": observation.app_id,
                    "display_name": "Alex",
                    "profile_cues": ["likes live music", "has a dog"],
                    "conversation_fingerprint": "alex-weekend-question",
                }
            ],
        )

        self.assertEqual(result.match_id, "match_alex")
        self.assertEqual(result.confidence, IdentityConfidence.HIGH)
        self.assertFalse(result.requires_user_confirmation)

    def test_unique_name_and_fingerprint_match_is_high_confidence_without_profile_cues(self):
        observation = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))

        result = resolve_match_identity(
            observation,
            existing_matches=[
                {
                    "match_id": "match_alex",
                    "app_id": observation.app_id,
                    "display_name": "Alex",
                    "profile_cues": [],
                    "conversation_fingerprint": "alex-weekend-question",
                }
            ],
        )

        self.assertEqual(result.match_id, "match_alex")
        self.assertEqual(result.confidence, IdentityConfidence.HIGH)
        self.assertFalse(result.requires_user_confirmation)

    def test_same_identity_hints_across_apps_create_independent_records(self):
        first = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))
        second = replace(first, app_id="wechat", observation_id="obs_wechat")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = store_observation_with_memory(root, first)["match_id"]
            target = store_observation_with_memory(root, second)["match_id"]
            self.assertNotEqual(source, target)
            for match_id, observation in [(source, first), (target, second)]:
                self.assertEqual(store_observation_with_memory(root, observation)["match_id"], match_id)
                self.assertEqual(ObservationRepository(root).load_observations(match_id), [observation])
            with self.assertRaisesRegex(ValueError, "app"):
                MatchRepository(root).merge_matches(source_match_id=source, target_match_id=target)

    def test_legacy_scope_reuses_only_a_complete_single_app_observation_history(self):
        obs = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))
        foreign = replace(obs, app_id="wechat", observation_id="obs_wechat")
        cases = [
            ("verified", [obs], [obs.observation_id]),
            ("mixed", [obs, foreign], [obs.observation_id, foreign.observation_id]),
            ("unknown", [obs], [obs.observation_id, "missing"]),
            ("unknown", [], []),
        ]
        for status, history, observation_ids in cases:
            with self.subTest(status=status, ids=observation_ids), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                repo, memory, storage = MatchRepository(root), MemoryRepository(root), JsonStorage(root)
                match_id = "legacy_alex"
                storage.write_json(Path("matches/index.json"), {
                    "schema_version": 1, "matches": [{
                        "match_id": match_id, "display_name": "Alex",
                        "conversation_fingerprint": obs.match_identity_hints.conversation_fingerprint,
                        "observation_ids": observation_ids,
                    }],
                })
                storage.write_json(Path("matches") / match_id / "observations.json", {
                    "schema_version": 1, "observations": [o.to_dict() for o in history],
                })
                memory.save_projection(match_id, MatchMemoryProjection(
                    match_id=match_id, identity_status="trusted", trusted_for_managed_send=True,
                ))
                record = repo.get_match_record(match_id)
                self.assertEqual(record["app_scope_status"], status)
                result = store_observation_with_memory(root, replace(obs, observation_id="obs_next"))
                if status == "verified":
                    self.assertEqual(result["match_id"], match_id)
                    raw = storage.read_json(Path("matches/index.json"), expected_schema_version=1)
                    self.assertEqual(raw["matches"][0]["app_id"], obs.app_id)
                else:
                    self.assertNotEqual(result["match_id"], match_id)
                    self.assertFalse(memory.load_projection(match_id).trusted_for_managed_send)
                    self.assertFalse(memory.rebuild_projection(match_id).trusted_for_context)
                    self.assertEqual(ObservationRepository(root).load_observations(match_id), history)
                    evidence = build_draft_evidence(root, match_id, reply_mode="adaptive")
                    self.assertEqual(evidence.primary_reason, "match_app_scope_review_required")

    def test_legacy_overwritten_observation_cannot_hide_a_foreign_native_event(self):
        first = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))
        overwritten = replace(first, app_id="wechat")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            match_id = "legacy_reused_id"
            memory, storage = MemoryRepository(root), JsonStorage(root)
            storage.write_json(Path("matches/index.json"), {
                "schema_version": 1, "matches": [{
                    "match_id": match_id, "display_name": first.match_identity_hints.visible_name,
                    "conversation_fingerprint": first.match_identity_hints.conversation_fingerprint,
                    "observation_ids": [first.observation_id],
                }],
            })
            storage.write_json(Path("matches") / match_id / "observations.json", {
                "schema_version": 1, "observations": [overwritten.to_dict()],
            })
            original = events_from_observation(match_id, first, first.captured_at)
            memory.replace_events(match_id, original)
            repo = MatchRepository(root)
            self.assertEqual(repo.get_match_record(match_id)["app_scope_status"], "mixed")
            with self.assertRaisesRegex(ValueError, "match_app_scope_review_required"):
                memory.rebuild_projection_from_observations(match_id, [overwritten])
            self.assertEqual({e.event_id for e in memory.load_events(match_id)}, {e.event_id for e in original})
            self.assertNotEqual(store_observation_with_memory(root, overwritten)["match_id"], match_id)
            inherited = [event for event in original if "fact" in event.payload]
            for event in inherited:
                event.evidence = replace(event.evidence, source_type="memory_inheritance")
            memory.replace_events(match_id, inherited)
            self.assertEqual(repo.get_match_app_id(match_id), "wechat")

    def test_unindexed_mixed_archive_blocks_direct_access_without_restoring_merged_index_entry(self):
        first = load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            match_id = "former_merge_source"
            memory, repo = MemoryRepository(root), MatchRepository(root)
            JsonStorage(root).write_json(Path("matches") / match_id / "observations.json", {
                "schema_version": 1,
                "observations": [first.to_dict(), replace(first, app_id="wechat", observation_id="we2").to_dict()],
            })
            memory.save_projection(match_id, MatchMemoryProjection(
                match_id=match_id, identity_status="trusted", trusted_for_managed_send=True,
            ))
            self.assertIsNone(repo.get_match_record(match_id))
            self.assertFalse(memory.load_projection(match_id).trusted_for_context)
            self.assertFalse(memory.load_projection(match_id).trusted_for_managed_send)
            self.assertEqual(build_draft_evidence(root, match_id, reply_mode="adaptive").primary_reason,
                             "match_app_scope_review_required")
            with self.assertRaisesRegex(ValueError, "match_app_scope_review_required"):
                memory.rebuild_projection_from_observations(match_id, [first])

    def test_replay_keeps_verified_legacy_id_without_a_visible_name(self):
        obs = AppObservation.minimal("old_anon", SourceType.USER_INPUT, "tinder", "", PageType.CHAT_THREAD)
        for fingerprint in [None, "opaque_thread"]:
            with self.subTest(fingerprint=fingerprint), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                first = replace(obs, match_identity_hints=replace(obs.match_identity_hints, conversation_fingerprint=fingerprint))
                raw_key = fingerprint or first.observation_id
                old_id = f"match_{raw_key}_{hashlib.sha256(raw_key.encode()).hexdigest()[:8]}"
                ObservationRepository(root).save_observation(old_id, first)
                JsonStorage(root).write_json(Path("matches/index.json"), {
                    "schema_version": 1, "matches": [{
                        "match_id": old_id, "display_name": None, "conversation_fingerprint": fingerprint,
                        "observation_ids": [first.observation_id],
                    }],
                })
                next_obs = replace(first, observation_id="next") if fingerprint else first
                self.assertEqual(store_observation_with_memory(root, next_obs)["match_id"], old_id)
                self.assertNotEqual(store_observation_with_memory(root, replace(next_obs, app_id="wechat"))["match_id"], old_id)

    def test_legacy_unknown_or_invalid_app_evidence_never_verifies_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage = JsonStorage(root)
            match_id = "legacy_unknown"
            storage.write_json(Path("matches/index.json"), {
                "schema_version": 1, "matches": [{"match_id": match_id, "observation_ids": ["obs"]}],
            })
            for app in ["unknown", None, []]:
                with self.subTest(app=app):
                    storage.write_json(Path("matches") / match_id / "observations.json", {
                        "schema_version": 1, "observations": [
                            {"app_id": "tinder", "observation_id": "obs"},
                            {"app_id": app, "observation_id": "obs2"},
                        ],
                    })
                    self.assertEqual(MatchRepository(root).get_match_record(match_id)["app_scope_status"], "unknown")

    def test_low_information_new_matches_use_observation_id_to_avoid_collisions(self):
        first_observation = AppObservation.minimal(
            observation_id="obs_low_info_1",
            source_type=SourceType.USER_INPUT,
            app_id="generic",
            captured_at="2026-05-25T00:00:00Z",
            page_type=PageType.CHAT_THREAD,
        )
        second_observation = AppObservation.minimal(
            observation_id="obs_low_info_2",
            source_type=SourceType.USER_INPUT,
            app_id="generic",
            captured_at="2026-05-25T00:00:00Z",
            page_type=PageType.CHAT_THREAD,
        )

        first_result = resolve_match_identity(first_observation, existing_matches=[])
        second_result = resolve_match_identity(second_observation, existing_matches=[])

        self.assertEqual(first_result.confidence, IdentityConfidence.NEW)
        self.assertEqual(second_result.confidence, IdentityConfidence.NEW)
        self.assertNotEqual(first_result.match_id, second_result.match_id)

    def test_same_name_new_matches_without_fingerprint_do_not_collide(self):
        first_observation = replace(
            AppObservation.minimal(
                observation_id="obs_same_name_1",
                source_type=SourceType.USER_INPUT,
                app_id="generic",
                captured_at="2026-05-25T00:00:00Z",
                page_type=PageType.CHAT_THREAD,
            ),
            match_identity_hints=MatchIdentityHints(
                visible_name="Alex",
                profile_cues=["ceramics class"],
                conversation_fingerprint=None,
                evidence="Visible chat header",
            ),
        )
        second_observation = replace(
            AppObservation.minimal(
                observation_id="obs_same_name_2",
                source_type=SourceType.USER_INPUT,
                app_id="generic",
                captured_at="2026-05-25T00:00:00Z",
                page_type=PageType.CHAT_THREAD,
            ),
            match_identity_hints=MatchIdentityHints(
                visible_name="Alex",
                profile_cues=["trail running"],
                conversation_fingerprint=None,
                evidence="Visible chat header",
            ),
        )

        first_result = resolve_match_identity(first_observation, existing_matches=[])
        second_result = resolve_match_identity(second_observation, existing_matches=[])

        self.assertEqual(first_result.confidence, IdentityConfidence.NEW)
        self.assertEqual(second_result.confidence, IdentityConfidence.NEW)
        self.assertNotEqual(first_result.match_id, second_result.match_id)


if __name__ == "__main__":
    unittest.main()
