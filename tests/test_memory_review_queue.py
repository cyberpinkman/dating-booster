from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dating_boost.core.memory.review_queue import ReviewItem, ReviewQueueRepository, build_dedupe_key
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.storage import JsonStorage


def _make_item(**overrides):
    defaults = {
        "review_item_id": "rev_test_001",
        "session_id": "session_test",
        "match_id": "match_alex",
        "observation_id": "obs_001",
        "proposal": {"predicate": "profile_cue", "value": "likes jazz"},
        "status": "pending",
        "created_at": "2026-06-07T00:00:00Z",
        "reported_at": None,
        "reviewed_at": None,
        "dedupe_key": "dedupe_test_001",
        "source": "deterministic",
        "risk": "low",
    }
    defaults.update(overrides)
    return ReviewItem(**defaults)


class ReviewItemSerializationTests(unittest.TestCase):
    def test_round_trip_dict(self):
        original = _make_item()
        restored = ReviewItem.from_dict(original.to_dict())
        self.assertEqual(original.review_item_id, restored.review_item_id)
        self.assertEqual(original.session_id, restored.session_id)
        self.assertEqual(original.match_id, restored.match_id)
        self.assertEqual(original.observation_id, restored.observation_id)
        self.assertEqual(original.proposal, restored.proposal)
        self.assertEqual(original.status, restored.status)
        self.assertEqual(original.created_at, restored.created_at)
        self.assertEqual(original.reported_at, restored.reported_at)
        self.assertEqual(original.reviewed_at, restored.reviewed_at)
        self.assertEqual(original.dedupe_key, restored.dedupe_key)
        self.assertEqual(original.source, restored.source)
        self.assertEqual(original.risk, restored.risk)

    def test_to_dict_adds_user_readable_display_for_known_thread_cues(self):
        cases = {
            "tashuo_permanent_chat_enabled": "她说已开启永久聊天，之后可以继续正常聊天。",
            "match_latest_reply_low_investment": "对方最近回复信息量低，后续适合先轻松承接，不要马上推进邀约。",
            "early_thread": "这段对话还在开场早期，适合先建立自然来回。",
            "question gate skipped": "对方已跳过她说问答考验，可以直接正常开场聊天。",
            "notification banner visible but not blocking input": "她说通知提示没有挡住输入框，可以继续正常回复。",
            "bottom input toolbar present": "当前聊天输入区可用，可以继续起草回复。",
            "message_input_present": "当前聊天输入区可用，可以继续起草回复。",
            "ordinary conversation page": "当前是普通聊天页，不是飞行页或问答决策页。",
            "ordinary_chat_thread": "当前是普通聊天页，不是飞行页或问答决策页。",
        }

        for value, summary in cases.items():
            with self.subTest(value=value):
                item = _make_item(proposal={"predicate": "thread_cue", "value": value})
                display = item.to_dict()["display"]
                self.assertEqual(display["summary"], summary)
                self.assertEqual(display["accept_label"], "记住这条")
                self.assertEqual(display["reject_label"], "不要记住")
                self.assertNotIn("thread_cue", display["summary"])

    def test_to_dict_unknown_display_fallback_does_not_expose_predicate_value_pair(self):
        item = _make_item(
            proposal={
                "predicate": "custom_internal_predicate",
                "subject": "Ada",
                "value": "likes late coffee",
            }
        )
        display = item.to_dict()["display"]

        self.assertEqual(display["title"], "是否记入长期记忆：Ada")
        self.assertIn("Ada", display["summary"])
        self.assertIn("likes late coffee", display["summary"])
        self.assertNotIn("custom_internal_predicate=likes late coffee", display["summary"])

    def test_from_dict_handles_none_fields(self):
        data = _make_item().to_dict()
        data["observation_id"] = None
        data["reported_at"] = None
        data["reviewed_at"] = None
        item = ReviewItem.from_dict(data)
        self.assertIsNone(item.observation_id)
        self.assertIsNone(item.reported_at)
        self.assertIsNone(item.reviewed_at)

    def test_blank_session_id_defaults_to_manual(self):
        item = _make_item(session_id="")
        restored = ReviewItem.from_dict(item.to_dict())

        self.assertEqual(item.session_id, "manual")
        self.assertEqual(restored.session_id, "manual")

    def test_null_or_missing_session_id_defaults_to_manual(self):
        null_session_data = _make_item().to_dict()
        null_session_data["session_id"] = None
        missing_session_data = _make_item().to_dict()
        del missing_session_data["session_id"]

        self.assertEqual(ReviewItem.from_dict(null_session_data).session_id, "manual")
        self.assertEqual(ReviewItem.from_dict(missing_session_data).session_id, "manual")


class ReviewQueueRepositoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)
        self.repo = ReviewQueueRepository(self.root)

    def test_enqueue_returns_item(self):
        item = _make_item()
        result = self.repo.enqueue(item)
        self.assertEqual(result.review_item_id, item.review_item_id)
        self.assertEqual(result.match_id, item.match_id)

    def test_enqueue_deduplicates_pending(self):
        item_a = _make_item(dedupe_key="dup_1")
        item_b = _make_item(dedupe_key="dup_1")
        self.repo.enqueue(item_a)
        result = self.repo.enqueue(item_b)
        all_items = self.repo.load_items()
        self.assertEqual(len(all_items), 1)
        self.assertEqual(result.review_item_id, item_a.review_item_id)

    def test_load_items_filters_by_status(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", status="pending", dedupe_key="dk_1"))
        self.repo.enqueue(_make_item(review_item_id="rev_2", status="accepted", dedupe_key="dk_2"))
        pending = self.repo.load_items(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].review_item_id, "rev_1")

    def test_load_items_filters_by_match_id(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", match_id="match_alex", dedupe_key="dk_1"))
        self.repo.enqueue(_make_item(review_item_id="rev_2", match_id="match_sam", dedupe_key="dk_2"))
        items = self.repo.load_items(match_id="match_alex")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].match_id, "match_alex")

    def test_load_items_filters_by_session_id(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", session_id="sess_a", dedupe_key="dk_1"))
        self.repo.enqueue(_make_item(review_item_id="rev_2", session_id="sess_b", dedupe_key="dk_2"))
        items = self.repo.load_items(session_id="sess_a")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].session_id, "sess_a")

    def test_update_status_changes_status_and_sets_reviewed_at(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", dedupe_key="dk_1"))
        updated = self.repo.update_status("rev_1", "accepted")
        self.assertEqual(updated.status, "accepted")
        self.assertIsNotNone(updated.reviewed_at)

    def test_update_status_raises_for_unknown_id(self):
        with self.assertRaises(ValueError):
            self.repo.update_status("nonexistent_id", "accepted")

    def test_pending_count(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", status="pending", dedupe_key="dk_1"))
        self.repo.enqueue(_make_item(review_item_id="rev_2", status="accepted", dedupe_key="dk_2"))
        self.repo.enqueue(_make_item(review_item_id="rev_3", status="pending", dedupe_key="dk_3"))
        self.assertEqual(self.repo.pending_count(), 2)

    def test_has_pending(self):
        self.assertFalse(self.repo.has_pending())
        self.repo.enqueue(_make_item(dedupe_key="dk_1"))
        self.assertTrue(self.repo.has_pending())

    def test_delete_items_for_match(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", match_id="match_alex", dedupe_key="dk_1"))
        self.repo.enqueue(_make_item(review_item_id="rev_2", match_id="match_sam", dedupe_key="dk_2"))
        self.repo.delete_items_for_match("match_alex")
        remaining = self.repo.load_items()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].match_id, "match_sam")

    def test_reject_dedupe_key_exists(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", dedupe_key="dk_reject"))
        self.repo.update_status("rev_1", "rejected")
        self.assertTrue(self.repo.reject_dedupe_key_exists("dk_reject"))

    def test_reject_dedupe_key_not_exists_for_non_rejected(self):
        self.repo.enqueue(_make_item(review_item_id="rev_1", dedupe_key="dk_pending"))
        self.assertFalse(self.repo.reject_dedupe_key_exists("dk_pending"))


class BuildDedupeKeyTests(unittest.TestCase):
    def test_deterministic_key(self):
        key_a = build_dedupe_key("match_alex", "profile_cue", "hobby", "jazz", "obs_1")
        key_b = build_dedupe_key("match_alex", "profile_cue", "hobby", "jazz", "obs_1")
        self.assertEqual(key_a, key_b)

    def test_different_inputs_produce_different_keys(self):
        key_a = build_dedupe_key("match_alex", "profile_cue", "hobby", "jazz", "obs_1")
        key_b = build_dedupe_key("match_alex", "profile_cue", "hobby", "rock", "obs_1")
        self.assertNotEqual(key_a, key_b)


class ReviewQueueProposalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.root = Path(self._tmpdir.name)

    def test_delete_match_also_deletes_review_items(self):
        match_id = "match_alex"
        storage = JsonStorage(self.root)
        match_dir = self.root / "matches" / match_id
        match_dir.mkdir(parents=True, exist_ok=True)
        (match_dir / "observations.json").write_text(
            '{"schema_version": 1, "observations": []}',
            encoding="utf-8",
        )
        storage.write_json(
            Path("matches") / "index.json",
            {"schema_version": 1, "matches": [{"match_id": match_id}]},
        )
        queue_repo = ReviewQueueRepository(self.root)
        queue_repo.enqueue(_make_item(review_item_id="rev_1", match_id=match_id, dedupe_key="dk_1"))
        queue_repo.enqueue(_make_item(review_item_id="rev_2", match_id="match_sam", dedupe_key="dk_2"))
        mem_repo = MemoryRepository(self.root)
        mem_repo.delete_match_documents(match_id)
        remaining = queue_repo.load_items()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].match_id, "match_sam")
