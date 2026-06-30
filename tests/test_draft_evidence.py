import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.draft_evidence import (
    ConversationThreadRepository,
    LatestTurnRepository,
    UserMemoryRepository,
    build_draft_evidence,
)
from dating_boost.core.memory.models import IdentityTrustStatus, MatchMemoryProjection
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.models import ReplyMode
from dating_boost.perception.observations import AppObservation


def _observation(
    *,
    observation_id: str = "obs_001",
    captured_at: str = "2026-06-18T10:00:00+08:00",
    visible_messages: list[dict[str, str]] | None = None,
    latest_inbound_messages: list[dict[str, str]] | None = None,
) -> AppObservation:
    if visible_messages is None:
        visible_messages = [
            {"sender": "user", "text": "你周末一般做什么"},
            {"sender": "match", "text": "我一般会去听现场"},
        ]
    if latest_inbound_messages is None:
        latest_inbound_messages = [
            message for message in visible_messages if message.get("sender") == "match"
        ]
    return AppObservation.from_dict(
        {
            "observation_id": observation_id,
            "source_type": "manual_fixture",
            "app_id": "tashuo",
            "adapter_id": "codex.test",
            "captured_at": captured_at,
            "page_type": "chat_thread",
            "page_confidence": "high",
            "match_identity_hints": {
                "visible_name": "Ada",
                "profile_cues": ["喜欢现场音乐"],
                "conversation_fingerprint": "thread-ada",
                "evidence": "fixture",
            },
            "profile_observation": {
                "profile_text": "Ada，喜欢现场音乐",
                "photo_cues": [],
                "hook_candidates": ["现场音乐"],
                "review_status": "observed",
                "evidence": "fixture",
            },
            "conversation_observation": {
                "visible_messages": visible_messages,
                "latest_inbound_messages": latest_inbound_messages,
                "input_state": "empty",
                "thread_cues": ["live music"],
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {"runtime": "mac-ios-app"},
            "raw_ref": None,
        }
    )


def _write_user_profile(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "user_profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "user_id": "user_local",
                "facts": [],
                "preferences": [],
                "boundaries": [],
                "style_examples": ["短一点，像真人聊天"],
                "goals": ["推进到线下见面"],
                "persona_baseline": "calm",
                "persona_range": ["warmer"],
                "stance_range": ["curious"],
                "updated_at": "2026-06-18T00:00:00Z",
                "default_reply_mode": "adaptive",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_disclosure_profile(data_dir: Path) -> None:
    user_dir = data_dir / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "disclosure_profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "user_id": "user_local",
                "hard_facts": [
                    {
                        "fact_id": "fact_degree_undergrad",
                        "text": "本科",
                        "value": "本科",
                        "source": "tashuo_self_profile_detail_observation",
                    }
                ],
                "persona_style": {
                    "baseline": "每句话不会太长，不油，偶尔有梗，会比较有边界感",
                    "allowed_modulations": ["light_polish"],
                },
                "shareable_material": [
                    {
                        "material_id": "mat_reply_rhythm_busy_batches",
                        "type": "reply_rhythm",
                        "text": "我一般会忙完了集中回信息，有时候会间隔比较长",
                        "tags": ["low_investment_repair"],
                        "risk_level": "low",
                        "usable_moves": ["low_investment_repair"],
                        "hard_fact_dependencies": [],
                        "example_phrasings": [],
                        "sensitivity": "low",
                        "source": "user_self_interview",
                    }
                ],
                "voice_samples": [],
                "boundaries": [
                    {
                        "boundary_id": "boundary_income_private",
                        "text": "收入不透露",
                        "type": "privacy",
                    }
                ],
                "simulation_policy": "material_only",
                "source_completion": {
                    "dating_profile": True,
                    "interview": True,
                },
                "updated_at": "2026-06-25T16:08:30Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_match_projection(
    data_dir: Path,
    match_id: str,
    *,
    updated_at: str = "2026-06-18T09:00:00+08:00",
    matched_at: str = "2026-06-01T09:00:00+08:00",
    profile_last_observed_at: str = "2026-06-18T09:00:00+08:00",
) -> None:
    MemoryRepository(data_dir).save_projection(
        match_id,
        MatchMemoryProjection(
            match_id=match_id,
            identity_status=IdentityTrustStatus.TRUSTED,
            trusted_for_context=True,
            trusted_for_managed_send=True,
            updated_at=updated_at,
            matched_at=matched_at,
            profile_last_observed_at=profile_last_observed_at,
            profile_source_runtime={"app_id": "tashuo", "runtime": "mac-ios-app"},
        ),
    )


class DraftEvidenceTests(unittest.TestCase):
    def test_blocks_missing_match_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _write_user_profile(data_dir)

            evidence = build_draft_evidence(
                data_dir,
                "match_ada",
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(),
            )

            self.assertEqual(evidence.status, "blocked")
            self.assertEqual(evidence.primary_reason, "match_memory_required")

    def test_blocks_missing_user_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _write_match_projection(data_dir, "match_ada")

            evidence = build_draft_evidence(
                data_dir,
                "match_ada",
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(),
            )

            self.assertEqual(evidence.status, "blocked")
            self.assertEqual(evidence.primary_reason, "user_memory_required")

    def test_blocks_empty_latest_turn_for_reply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            _write_user_profile(data_dir)
            _write_match_projection(data_dir, match_id)
            ConversationThreadRepository(data_dir).overwrite_from_observation(
                match_id,
                _observation(latest_inbound_messages=[]),
            )

            evidence = build_draft_evidence(
                data_dir,
                match_id,
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(latest_inbound_messages=[]),
            )

            self.assertEqual(evidence.status, "blocked")
            self.assertEqual(evidence.primary_reason, "latest_turn_required")

    def test_allows_new_match_opener_with_empty_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            _write_user_profile(data_dir)
            _write_match_projection(data_dir, match_id)

            evidence = build_draft_evidence(
                data_dir,
                match_id,
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(visible_messages=[], latest_inbound_messages=[]),
                draft_kind="opener",
            )

            self.assertEqual(evidence.status, "ok")
            self.assertEqual(evidence.conversation_thread["message_count"], 0)

    def test_blocks_existing_thread_without_conversation_thread_document(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            _write_user_profile(data_dir)
            _write_match_projection(data_dir, match_id)

            evidence = build_draft_evidence(
                data_dir,
                match_id,
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(),
            )

            self.assertEqual(evidence.status, "blocked")
            self.assertEqual(evidence.primary_reason, "conversation_thread_required")

    def test_reactivation_requires_profile_refresh_after_fourteen_days(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            _write_user_profile(data_dir)
            _write_match_projection(
                data_dir,
                match_id,
                updated_at="2026-05-01T09:00:00+08:00",
                profile_last_observed_at="2026-05-01T09:00:00+08:00",
            )
            ConversationThreadRepository(data_dir).overwrite_from_observation(match_id, _observation())

            evidence = build_draft_evidence(
                data_dir,
                match_id,
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(),
                user_reactivated=True,
                now="2026-06-18T10:00:00+08:00",
            )

            self.assertEqual(evidence.status, "blocked")
            self.assertEqual(evidence.primary_reason, "profile_refresh_required")

    def test_user_memory_tracks_runtime_profile_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _write_user_profile(data_dir)
            repo = UserMemoryRepository(data_dir)

            repo.ensure_profile_source(app_id="tinder", runtime="default", observed_at="2026-06-01T00:00:00Z")
            repo.ensure_profile_source(app_id="tashuo", runtime="mac-ios-app", observed_at="2026-06-18T00:00:00Z")

            projection = repo.load_projection()
            sources = {(item["app_id"], item["runtime"]) for item in projection["profile_sources"]}

            self.assertIn(("tinder", "default"), sources)
            self.assertIn(("tashuo", "mac-ios-app"), sources)

    def test_conversation_thread_merges_observations_instead_of_overwriting_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            repo = ConversationThreadRepository(data_dir)
            match_id = "match_ada"

            repo.overwrite_from_observation(
                match_id,
                _observation(
                    observation_id="obs_first",
                    visible_messages=[
                        {"sender": "user", "text": "你周末一般做什么"},
                        {"sender": "match", "text": "我一般会去听现场"},
                    ],
                ),
            )
            thread = repo.overwrite_from_observation(
                match_id,
                _observation(
                    observation_id="obs_second",
                    visible_messages=[
                        {"sender": "match", "text": "我一般会去听现场"},
                        {"sender": "user", "text": "那你喜欢哪种现场"},
                        {"sender": "match", "text": "偏小场一点的"},
                    ],
                    latest_inbound_messages=[{"sender": "match", "text": "偏小场一点的"}],
                ),
            )

            texts = [message["text"] for message in thread["messages"]]
            self.assertEqual(
                texts,
                ["你周末一般做什么", "我一般会去听现场", "那你喜欢哪种现场", "偏小场一点的"],
            )

    def test_append_confirmed_outbound_does_not_duplicate_latest_inbound_already_in_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            repo = ConversationThreadRepository(data_dir)
            observation = _observation()
            repo.overwrite_from_observation(match_id, observation)
            latest_turn = LatestTurnRepository(data_dir).overwrite_from_observation(match_id, observation)

            thread = repo.append_confirmed_outbound_turn(
                match_id,
                latest_turn=latest_turn,
                payload_messages=[{"index": 1, "text": "那你一般听哪种现场"}],
                action_request_id="action_request_fixture",
                created_at="2026-06-18T10:01:00+08:00",
            )

            inbound_texts = [
                message["text"]
                for message in thread["messages"]
                if message["sender"] == "match"
            ]
            self.assertEqual(inbound_texts.count("我一般会去听现场"), 1)

    def test_blocks_when_current_app_profile_source_has_not_been_recorded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            _write_user_profile(data_dir)
            _write_match_projection(data_dir, match_id)
            ConversationThreadRepository(data_dir).overwrite_from_observation(match_id, _observation())

            evidence = build_draft_evidence(
                data_dir,
                match_id,
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(),
                app_id="tashuo",
                runtime="mac-ios-app",
                require_user_profile_source=True,
            )

            self.assertEqual(evidence.status, "blocked")
            self.assertEqual(evidence.primary_reason, "user_profile_source_required")

    def test_uses_disclosure_profile_as_user_memory_when_legacy_profile_is_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_ada"
            _write_disclosure_profile(data_dir)
            _write_match_projection(data_dir, match_id)
            ConversationThreadRepository(data_dir).overwrite_from_observation(match_id, _observation())

            evidence = build_draft_evidence(
                data_dir,
                match_id,
                reply_mode=ReplyMode.ADAPTIVE,
                observation=_observation(),
                app_id="tashuo",
                runtime="mac-ios-app",
                require_user_profile_source=True,
            )

            self.assertEqual(evidence.status, "ok")
            self.assertIsNotNone(evidence.evidence_manifest["user_memory_hash"])
            sources = {
                (item.get("app_id"), item.get("runtime"))
                for item in evidence.user_memory.get("profile_sources", [])
                if isinstance(item, dict)
            }
            self.assertIn(("tashuo", "mac-ios-app"), sources)
            labels = [item["label"] for item in evidence.context_pack["items"]]
            self.assertIn("user_disclosure_profile", labels)


if __name__ == "__main__":
    unittest.main()
