import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.cli_memory import _handle_action_record_result
from dating_boost.cli_sessions import _record_feedback
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.models import EvidenceRef, MemoryEvent, MemoryEventType, MemoryScope
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.models import ReplyMode
from dating_boost.core.repositories import JsonMemoryRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.perception.fixture_loader import load_observation


NOW = "2026-11-07T12:00:00Z"
LEGACY_TIME = "2026-05-25T00:00:00Z"


class MemoryReplayOrderTests(unittest.TestCase):
    def setUp(self):
        self.key_provider = patch.dict("os.environ", {"DATING_BOOST_KEY_PROVIDER": "local"})
        self.key_provider.start()
        self.addCleanup(self.key_provider.stop)

    def _seed(self, root, backend="sqlite"):
        if backend == "legacy":
            (root / "matches").mkdir()
            (root / "matches/index.json").write_text(
                json.dumps({"schema_version": 1, "matches": []}), encoding="utf-8"
            )
        observation = replace(
            load_observation(Path("tests/fixtures/intelligence/app_observation_chat.json")),
            captured_at=NOW,
        )
        match_id = store_observation_with_memory(root, observation)["match_id"]
        repo = MemoryRepository(root)
        fact = next(f for f in repo.load_projection(match_id).facts if f.predicate == "profile_text")
        return repo, match_id, observation, fact

    def _event(self, match_id, event_id, event_type, payload, created_at=LEGACY_TIME):
        return MemoryEvent(
            event_id=event_id, event_type=event_type, match_id=match_id,
            scope=MemoryScope.MATCH_PROFILE, created_at=created_at, payload=payload,
            evidence=EvidenceRef(source_type="user_feedback"),
        )

    def test_feedback_records_current_time_in_both_streams(self):
        with tempfile.TemporaryDirectory() as temp, patch("dating_boost.cli_sessions._now_iso", return_value=NOW):
            root = Path(temp)
            _record_feedback(data_dir=root, match_id="match_test", draft_id="draft_1",
                             mode=ReplyMode.ADAPTIVE, label="too_flirty")
            self.assertEqual(JsonMemoryRepository(root).load_feedback_events("match_test")[0]["created_at"], NOW)
            self.assertEqual(MemoryRepository(root).load_events("match_test")[0].created_at, NOW)

    def test_action_result_uses_current_clock(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch("dating_boost.cli_memory._now_iso", return_value=NOW), \
                patch("dating_boost.cli_memory._read_json_object", return_value={}), \
                patch("dating_boost.cli_memory.ActionAuditRepository") as audit, \
                patch("dating_boost.cli_memory.AutomationRepository"), redirect_stdout(StringIO()):
            audit.return_value.append_action_result.return_value = {"event_id": "event", "result_status": "unknown"}
            self.assertEqual(_handle_action_record_result(SimpleNamespace(data_dir=Path(temp), input=Path("unused"))), 0)
            audit.return_value.append_action_result.assert_called_once_with({}, created_at=NOW)

    def test_feedback_retry_keeps_first_time_and_counts_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch("dating_boost.cli_sessions._now_iso", return_value=NOW):
                _record_feedback(data_dir=root, match_id="match_test", draft_id="draft_1",
                                 mode=ReplyMode.ADAPTIVE, label="too_flirty")
            with patch("dating_boost.cli_sessions._now_iso", return_value="2026-11-08T00:00:00Z"):
                _record_feedback(data_dir=root, match_id="match_test", draft_id="draft_1",
                                 mode=ReplyMode.ADAPTIVE, label="too_flirty")
            feedback = JsonMemoryRepository(root).load_feedback_events("match_test")
            events = MemoryRepository(root).load_events("match_test")
            self.assertEqual(len(feedback), 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(feedback[0], events[0].payload)
            self.assertEqual(feedback[0]["created_at"], NOW)
            projection = MemoryRepository(root).load_projection("match_test")
            self.assertEqual(projection.feedback_preferences["adaptive"]["labels"]["too_flirty"], 1)

    def test_legacy_rejection_survives_rebuild_without_changing_timestamps(self):
        for backend in ("sqlite", "legacy"):
            for already_reordered in (False, True):
                with self.subTest(backend=backend, already_reordered=already_reordered), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    repo, match_id, observation, fact = self._seed(root, backend)
                    feedback = self._event(match_id, "feedback_legacy", MemoryEventType.FEEDBACK_RECORDED, {
                        "mode": "adaptive", "label": "wrong_assumption", "referenced_memory_ids": [fact.fact_id],
                    })
                    repo.append_event(match_id, feedback)
                    if already_reordered:
                        # Emulate an earlier version's persisted, timestamp-sorted rebuild.
                        JsonStorage(root).write_jsonl(Path("matches") / match_id / "memory_events.jsonl", [
                            event.to_dict() for event in sorted(repo.load_events(match_id), key=lambda item: (item.created_at, item.event_id))
                        ])
                    first = repo.rebuild_projection_from_observations(match_id, [observation])
                    first_events = [event.to_dict() for event in repo.load_events(match_id)]
                    second = repo.rebuild_projection_from_observations(match_id, [observation])
                    self.assertEqual(next(f.status.value for f in first.facts if f.fact_id == fact.fact_id), "rejected")
                    self.assertEqual(first.updated_at, NOW)
                    self.assertEqual(first.to_dict(), second.to_dict())
                    self.assertEqual(first_events, [event.to_dict() for event in repo.load_events(match_id)])
                    self.assertEqual(next(event.created_at for event in repo.load_events(match_id) if event.event_id == feedback.event_id), LEGACY_TIME)

    def test_same_timestamp_correction_and_disposition_keep_dependency_order(self):
        for disposition, expected in ((MemoryEventType.FACT_REJECTED, "rejected"), (MemoryEventType.FACT_ARCHIVED, "archived")):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                repo, match_id, observation, fact = self._seed(root)
                corrected = replace(fact, fact_id="corrected_fact", value="Corrected profile", normalized_value=None, supersedes=[fact.fact_id])
                correction = self._event(match_id, "z_correction", MemoryEventType.FACT_CORRECTED,
                                         {"target_fact_id": fact.fact_id, "fact": corrected.to_dict()}, created_at=NOW)
                rejection = self._event(match_id, "a_disposition", disposition,
                                        {"target_fact_id": corrected.fact_id}, created_at=NOW)
                repo.append_event(match_id, correction)
                repo.append_event(match_id, rejection)
                before = repo.rebuild_projection(match_id)
                rebuilt = repo.rebuild_projection_from_observations(match_id, [observation])
                states = {f.fact_id: f.status.value for f in rebuilt.facts}
                self.assertEqual(states[fact.fact_id], "archived")
                self.assertEqual(states[corrected.fact_id], expected)
                self.assertEqual(before.to_dict(), rebuilt.to_dict())
                self.assertEqual(rebuilt.to_dict(), repo.rebuild_projection_from_observations(match_id, [observation]).to_dict())

    def test_rebuild_preserves_observations_before_and_after_feedback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, match_id, observation, fact = self._seed(root)
            second = replace(observation, observation_id="second")
            store_observation_with_memory(root, second)
            repo.append_event(match_id, self._event(match_id, "feedback", MemoryEventType.FEEDBACK_RECORDED, {
                "mode": "adaptive", "label": "wrong_assumption", "referenced_memory_ids": [fact.fact_id],
            }))
            rejected = repo.rebuild_projection_from_observations(match_id, [observation, second])
            self.assertEqual(next(f.status.value for f in rejected.facts if f.fact_id == fact.fact_id), "rejected")
            later = replace(observation, observation_id="later", captured_at="2026-11-08T00:00:00Z")
            store_observation_with_memory(root, later)
            before = repo.load_projection(match_id).to_dict()
            before_events = [event.to_dict() for event in repo.load_events(match_id)]
            after = repo.rebuild_projection_from_observations(match_id, [observation, second, later])
            self.assertEqual(after.to_dict(), before)
            self.assertEqual([event.to_dict() for event in repo.load_events(match_id)], before_events)

    def test_ambiguous_legacy_reference_returns_cli_error_without_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, match_id, observation, fact = self._seed(root)
            store_observation_with_memory(root, replace(observation, observation_id="second"))
            repo.append_event(match_id, self._event(match_id, "feedback", MemoryEventType.FEEDBACK_RECORDED, {
                "mode": "adaptive", "label": "wrong_assumption", "referenced_memory_ids": [fact.fact_id],
            }))
            before_projection = repo.rebuild_projection(match_id).to_dict()
            reordered = [event.to_dict() for event in sorted(repo.load_events(match_id), key=lambda item: (item.created_at, item.event_id))]
            JsonStorage(root).write_jsonl(Path("matches") / match_id / "memory_events.jsonl", reordered)
            output = StringIO()
            with redirect_stdout(output):
                code = main(["memory", "rebuild", "--data-dir", str(root), "--match-id", match_id])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["reason"], "memory_fact_reference_order_ambiguous")
            self.assertEqual([event.to_dict() for event in repo.load_events(match_id)], reordered)
            self.assertEqual(repo.load_projection(match_id).to_dict(), before_projection)

    def test_cyclic_fact_dependencies_leave_original_events_and_projection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo, match_id, observation, fact = self._seed(root)
            for fact_id, target_id in (("cycle_a", "cycle_b"), ("cycle_b", "cycle_a")):
                repo.append_event(match_id, self._event(match_id, fact_id, MemoryEventType.FACT_CORRECTED, {
                    "target_fact_id": target_id, "fact": replace(fact, fact_id=fact_id, value=fact_id, normalized_value=None).to_dict(),
                }))
            before_projection = repo.load_projection(match_id).to_dict()
            before_events = [event.to_dict() for event in repo.load_events(match_id)]
            with self.assertRaisesRegex(ValueError, "memory_fact_dependency_cycle"):
                repo.rebuild_projection_from_observations(match_id, [observation])
            self.assertEqual([event.to_dict() for event in repo.load_events(match_id)], before_events)
            self.assertEqual(repo.load_projection(match_id).to_dict(), before_projection)

    def test_legacy_rejection_with_multiple_possible_fact_creators_is_ambiguous(self):
        for same_id in (False, True):
            with self.subTest(same_id=same_id), tempfile.TemporaryDirectory() as temp:
                self._assert_ambiguous_corrected_reference(Path(temp), same_id)

    def _assert_ambiguous_corrected_reference(self, root, same_id):
        repo, match_id, observation, fact = self._seed(root)
        corrected = replace(fact, fact_id=fact.fact_id if same_id else "corrected", value="New profile", normalized_value=None)
        corrected_payload = corrected.to_dict()
        # Legacy facts may omit derived normalization fields; the reducer computes them.
        corrected_payload.pop("normalized_key")
        corrected_payload.pop("normalized_value")
        repo.append_event(match_id, self._event(match_id, "correction", MemoryEventType.FACT_CORRECTED, {
            "target_fact_id": fact.fact_id, "fact": corrected_payload,
        }, created_at=NOW))
        second = replace(observation, observation_id="second", captured_at="2026-11-08T00:00:00Z",
                         profile_observation=replace(observation.profile_observation, profile_text="New profile"))
        observations = [observation]
        if not same_id:
            store_observation_with_memory(root, second)
            observations.append(second)
        repo.append_event(match_id, self._event(match_id, "feedback", MemoryEventType.FEEDBACK_RECORDED, {
            "mode": "adaptive", "label": "wrong_assumption", "referenced_memory_ids": [corrected.fact_id],
        }))
        before_projection = repo.rebuild_projection(match_id).to_dict()
        self.assertEqual(next(f["status"] for f in before_projection["facts"] if f["fact_id"] == corrected.fact_id), "rejected")
        reordered = [event.to_dict() for event in sorted(repo.load_events(match_id), key=lambda item: (item.created_at, item.event_id))]
        JsonStorage(root).write_jsonl(Path("matches") / match_id / "memory_events.jsonl", reordered)
        with self.assertRaisesRegex(ValueError, "memory_fact_reference_order_ambiguous"):
            repo.rebuild_projection_from_observations(match_id, observations)
        self.assertEqual([event.to_dict() for event in repo.load_events(match_id)], reordered)
        self.assertEqual(repo.load_projection(match_id).to_dict(), before_projection)

if __name__ == "__main__":
    unittest.main()
