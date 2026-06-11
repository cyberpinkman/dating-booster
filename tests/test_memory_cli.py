import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from dating_boost.cli import main
from dating_boost.core.memory.models import IdentityTrustStatus
from dating_boost.core.memory.extractors import events_from_observation
from dating_boost.core.memory.ingest import store_observation_with_memory
from dating_boost.core.memory.models import MemoryEventType, MemoryFactType
from dating_boost.core.memory.repositories import MemoryRepository
from dating_boost.core.memory.review_queue import ReviewItem, ReviewQueueRepository
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.repositories import MatchRepository, ObservationRepository
from dating_boost.perception.fixture_loader import load_observation


FIXTURE_PATH = Path("tests/fixtures/intelligence/app_observation_chat.json")


class MemoryObservationExtractionTests(unittest.TestCase):
    def test_extracts_deterministic_events_without_copying_full_message_text(self):
        observation = load_observation(FIXTURE_PATH)

        events = events_from_observation("match_alex", observation, created_at="2026-06-06T00:00:00Z")
        event_types = [event.event_type for event in events]
        event_ids = [event.event_id for event in events]

        self.assertIn(MemoryEventType.OBSERVATION_INGESTED, event_types)
        self.assertIn(MemoryEventType.MATCH_IDENTITY_ASSESSED, event_types)
        self.assertIn(MemoryEventType.PROFILE_FACT_OBSERVED, event_types)
        self.assertIn(MemoryEventType.CONVERSATION_FACT_OBSERVED, event_types)
        self.assertIn(MemoryEventType.INFERENCE_RECORDED, event_types)
        self.assertEqual(event_ids, [event.event_id for event in events_from_observation("match_alex", observation, created_at="2026-06-06T00:00:00Z")])
        self.assertEqual(len(event_ids), len(set(event_ids)))

        for event in events:
            self.assertIsNotNone(event.evidence)
            self.assertEqual(event.evidence.source_observation_id, "obs_chat_001")
            encoded = json.dumps(event.to_dict(), ensure_ascii=False)
            self.assertNotIn("It was. What are you up to this weekend?", encoded)
            self.assertNotIn("That concert photo looks fun.", encoded)

        latest_event = [
            event
            for event in events
            if event.event_type == MemoryEventType.CONVERSATION_FACT_OBSERVED
        ][0]
        self.assertEqual(latest_event.payload["message_refs"][0]["sender"], "match")
        self.assertEqual(latest_event.payload["message_refs"][0]["message_index"], 1)
        self.assertEqual(
            latest_event.payload["message_refs"][0]["char_count"],
            len("It was. What are you up to this weekend?"),
        )
        self.assertIn("message_hash", latest_event.payload["message_refs"][0])

    def test_photo_cues_are_recorded_as_inferences(self):
        observation = load_observation(FIXTURE_PATH)

        events = events_from_observation("match_alex", observation, created_at="2026-06-06T00:00:00Z")
        inference_events = [
            event
            for event in events
            if event.event_type == MemoryEventType.INFERENCE_RECORDED
        ]
        fact_types = {
            event.payload["fact"]["fact_type"]
            for event in inference_events
        }

        self.assertIn(MemoryFactType.PHOTO_CUE.value, fact_types)
        self.assertNotIn(MemoryFactType.VISIBLE_FACT.value, fact_types)

    def test_shared_ingest_persists_events_and_projection(self):
        observation = load_observation(FIXTURE_PATH)
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = store_observation_with_memory(Path(temp_dir), observation)
            match_id = payload["match_id"]
            projection = MemoryRepository(Path(temp_dir)).load_projection(match_id)
            events = MemoryRepository(Path(temp_dir)).load_events(match_id)

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["observation_id"], "obs_chat_001")
            self.assertGreaterEqual(payload["memory_event_count"], 5)
            self.assertTrue(payload["projection_updated"])
            self.assertEqual(payload["identity_status"], projection.identity_status.value)
            self.assertEqual(payload["trusted_for_context"], projection.trusted_for_context)
            self.assertEqual(payload["trusted_for_managed_send"], projection.trusted_for_managed_send)
            self.assertEqual(projection.last_event_id, events[-1].event_id)

    def test_shared_ingest_rejects_invalid_observation_id_before_writing(self):
        original = load_observation(FIXTURE_PATH)
        payload = original.to_dict()
        payload["observation_id"] = "bad/id"
        observation = type(original).from_dict(payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            with self.assertRaisesRegex(ValueError, "invalid observation_id"):
                store_observation_with_memory(data_dir, observation)

            self.assertFalse((data_dir / "matches" / "index.json").exists())
            self.assertFalse((data_dir / "matches" / "identity_confirmations.jsonl").exists())
            self.assertFalse((data_dir / "matches").exists())

    def test_memory_ingest_observation_reports_invalid_source_type_as_json_error(self):
        payload = load_observation(FIXTURE_PATH).to_dict()
        payload["source_type"] = "manual_host_loop"

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            observation_path = Path(temp_dir) / "bad_source.json"
            observation_path.write_text(json.dumps(payload), encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "memory",
                    "ingest-observation",
                    "--data-dir",
                    str(data_dir),
                    "--input",
                    str(observation_path),
                ])

            result = json.loads(output.getvalue())

            self.assertNotEqual(exit_code, 0)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["reason"], "invalid_observation")
            self.assertIn("manual_host_loop", result["message"])

    def test_shared_ingest_rejects_invalid_resolved_match_id_before_memory_writes(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            matches_dir = data_dir / "matches"
            matches_dir.mkdir(parents=True)
            (matches_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "matches": [
                            {
                                "match_id": "bad/id",
                                "display_name": observation.match_identity_hints.visible_name,
                                "profile_cues": list(observation.match_identity_hints.profile_cues),
                                "conversation_fingerprint": observation.match_identity_hints.conversation_fingerprint,
                                "observation_ids": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "invalid match_id"):
                store_observation_with_memory(data_dir, observation)

            self.assertFalse((data_dir / "matches" / "bad").exists())
            self.assertFalse((data_dir / "matches" / "memory_events.jsonl").exists())
            self.assertEqual(sorted(path.name for path in matches_dir.iterdir()), ["index.json"])

    def test_shared_ingest_records_identity_conflict_event_for_duplicate_strong_matches(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            matches_dir = data_dir / "matches"
            matches_dir.mkdir(parents=True)
            duplicate_record = {
                "display_name": observation.match_identity_hints.visible_name,
                "profile_cues": list(observation.match_identity_hints.profile_cues),
                "conversation_fingerprint": observation.match_identity_hints.conversation_fingerprint,
                "observation_ids": [],
            }
            (matches_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "matches": [
                            {"match_id": "match_alex_a", **duplicate_record},
                            {"match_id": "match_alex_b", **duplicate_record},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            payload = store_observation_with_memory(data_dir, observation)
            events = MemoryRepository(data_dir).load_events(payload["match_id"])
            projection = MemoryRepository(data_dir).load_projection(payload["match_id"])

            self.assertEqual(payload["confidence"], "conflict")
            self.assertIn(MemoryEventType.MATCH_IDENTITY_CONFLICT, [event.event_type for event in events])
            self.assertEqual(projection.identity_status, IdentityTrustStatus.CONFLICTED)
            self.assertFalse(projection.trusted_for_context)

    def test_persisted_memory_files_do_not_copy_full_chat_message_text(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            payload = store_observation_with_memory(data_dir, observation)
            match_id = payload["match_id"]
            encoded_events = (data_dir / "matches" / match_id / "memory_events.jsonl").read_text(encoding="utf-8")
            encoded_projection = (data_dir / "matches" / match_id / "match_memory_projection.json").read_text(encoding="utf-8")
            encoded = encoded_events + encoded_projection

            self.assertNotIn("It was. What are you up to this weekend?", encoded)
            self.assertNotIn("That concert photo looks fun.", encoded)


class MemoryRebuildTests(unittest.TestCase):
    def test_rebuild_match_projection_from_existing_observation(self):
        observation = load_observation(FIXTURE_PATH)
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_alex"
            ObservationRepository(data_dir).save_observation(match_id, observation)
            MatchRepository(data_dir).upsert_match_from_observation(
                match_id=match_id,
                observation=observation,
                confidence="high",
                requires_user_confirmation=False,
            )

            first_exit, first_payload, _ = self._run([
                "memory",
                "rebuild",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
            ])
            second_exit, second_payload, _ = self._run([
                "memory",
                "rebuild",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
            ])
            projection = MemoryRepository(data_dir).load_projection(match_id)
            match_index = MatchRepository(data_dir).list_match_candidates()

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_payload["status"], "ok")
            self.assertEqual(second_payload["status"], "ok")
            self.assertEqual(first_payload["memory_event_count"], second_payload["memory_event_count"])
            self.assertIsNotNone(projection)
            self.assertEqual(projection.match_id, match_id)
            self.assertEqual(match_index[0]["match_id"], match_id)

    def test_rebuild_corrupt_observation_fails_without_partial_projection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_dir = data_dir / "matches" / "match_bad"
            match_dir.mkdir(parents=True)
            (match_dir / "observations.json").write_text("{broken", encoding="utf-8")

            exit_code, payload, _ = self._run([
                "memory",
                "rebuild",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_bad",
            ])

            self.assertNotEqual(exit_code, 0)
            self.assertEqual(payload["status"], "error")
            self.assertIn("corrupt", payload["reason"])
            self.assertFalse((match_dir / "match_memory_projection.json").exists())

    def test_rebuild_replaces_observation_derived_events_instead_of_retaining_stale_events(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = "match_alex"
            ObservationRepository(data_dir).save_observation(match_id, observation)
            MemoryRepository(data_dir).rebuild_projection_from_observations(match_id, [observation])

            revised_payload = observation.to_dict()
            revised_payload["profile_observation"] = {
                "profile_text": "",
                "photo_cues": [],
                "hook_candidates": [],
            }
            revised_observation = type(observation).from_dict(revised_payload)
            ObservationRepository(data_dir).save_observation(match_id, revised_observation)

            exit_code, payload, _ = self._run([
                "memory",
                "rebuild",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
            ])
            projection = MemoryRepository(data_dir).load_projection(match_id)
            values = {
                str(fact.value)
                for fact in [*projection.facts, *projection.inferences]
            }

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertNotIn("Ask about live music", values)

    def test_rebuild_preserves_low_identity_trust_gate(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            matches_dir = data_dir / "matches"
            matches_dir.mkdir(parents=True)
            (matches_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "matches": [
                            {
                                "match_id": "match_alex_existing",
                                "display_name": observation.match_identity_hints.visible_name,
                                "profile_cues": [],
                                "conversation_fingerprint": None,
                                "observation_ids": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            ingest = store_observation_with_memory(data_dir, observation)
            projection_before = MemoryRepository(data_dir).load_projection(ingest["match_id"])

            exit_code, payload, _ = self._run([
                "memory",
                "rebuild",
                "--data-dir",
                str(data_dir),
                "--match-id",
                ingest["match_id"],
            ])
            projection_after = MemoryRepository(data_dir).load_projection(ingest["match_id"])

            self.assertEqual(projection_before.identity_status.value, "needs_confirmation")
            self.assertFalse(projection_before.trusted_for_context)
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(projection_after.identity_status.value, "needs_confirmation")
            self.assertFalse(projection_after.trusted_for_context)
            self.assertFalse(projection_after.trusted_for_managed_send)

    def test_rebuild_all_rebuilds_every_match_with_observations_and_is_idempotent(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            first_observation = self._observation_variant(observation, "obs_chat_001", "Alex", "alex-thread-1")
            second_observation = self._observation_variant(observation, "obs_chat_002", "Bea", "bea-thread-2")
            for match_id, item in (
                ("match_alex", first_observation),
                ("match_bea", second_observation),
            ):
                ObservationRepository(data_dir).save_observation(match_id, item)
                MatchRepository(data_dir).upsert_match_from_observation(
                    match_id=match_id,
                    observation=item,
                    confidence="high",
                    requires_user_confirmation=False,
                )

            first_exit, first_payload, _ = self._run(["memory", "rebuild", "--data-dir", str(data_dir), "--all"])
            second_exit, second_payload, _ = self._run(["memory", "rebuild", "--data-dir", str(data_dir), "--all"])
            index_records = MatchRepository(data_dir).list_match_candidates()

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertEqual(first_payload["status"], "ok")
            self.assertEqual(first_payload["rebuilt_count"], 2)
            self.assertEqual(second_payload["rebuilt_count"], 2)
            self.assertEqual(
                {
                    item["match_id"]: item["memory_event_count"]
                    for item in first_payload["matches"]
                },
                {
                    item["match_id"]: item["memory_event_count"]
                    for item in second_payload["matches"]
                },
            )
            self.assertIsNotNone(MemoryRepository(data_dir).load_projection("match_alex"))
            self.assertIsNotNone(MemoryRepository(data_dir).load_projection("match_bea"))
            self.assertEqual([record["match_id"] for record in index_records], ["match_alex", "match_bea"])

    def test_rebuild_all_reports_corrupt_match_without_deleting_successful_projection_or_index(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            ObservationRepository(data_dir).save_observation("match_good", observation)
            MatchRepository(data_dir).upsert_match_from_observation(
                match_id="match_good",
                observation=observation,
                confidence="high",
                requires_user_confirmation=False,
            )
            bad_dir = data_dir / "matches" / "match_bad"
            bad_dir.mkdir(parents=True)
            (bad_dir / "observations.json").write_text("{broken", encoding="utf-8")
            index = {
                "schema_version": 1,
                "matches": [
                    *MatchRepository(data_dir).list_match_candidates(),
                    {"match_id": "match_bad", "display_name": "Bad", "observation_ids": ["bad"]},
                ],
            }
            (data_dir / "matches" / "index.json").write_text(json.dumps(index), encoding="utf-8")

            exit_code, payload, _ = self._run(["memory", "rebuild", "--data-dir", str(data_dir), "--all"])
            results = {item["match_id"]: item for item in payload["matches"]}
            index_records = MatchRepository(data_dir).list_match_candidates()

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "partial")
            self.assertEqual(payload["rebuilt_count"], 1)
            self.assertEqual(payload["error_count"], 1)
            self.assertEqual(results["match_good"]["status"], "ok")
            self.assertEqual(results["match_bad"]["status"], "error")
            self.assertIn("corrupt", results["match_bad"]["reason"])
            self.assertIsNotNone(MemoryRepository(data_dir).load_projection("match_good"))
            self.assertFalse((bad_dir / "match_memory_projection.json").exists())
            self.assertEqual([record["match_id"] for record in index_records], ["match_good", "match_bad"])

    def test_rebuild_all_reports_malformed_observation_without_aborting_batch(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            ObservationRepository(data_dir).save_observation("match_good", observation)
            MatchRepository(data_dir).upsert_match_from_observation(
                match_id="match_good",
                observation=observation,
                confidence="high",
                requires_user_confirmation=False,
            )
            bad_dir = data_dir / "matches" / "match_bad"
            bad_dir.mkdir(parents=True)
            (bad_dir / "observations.json").write_text(
                json.dumps({"schema_version": 1, "observations": [{}]}),
                encoding="utf-8",
            )

            exit_code, payload, text = self._run(["memory", "rebuild", "--data-dir", str(data_dir), "--all"])
            results = {item["match_id"]: item for item in payload["matches"]}

            self.assertEqual(exit_code, 2)
            self.assertTrue(text.strip().startswith("{"))
            self.assertEqual(payload["status"], "partial")
            self.assertEqual(results["match_bad"]["status"], "error")
            self.assertIn("observation_id", results["match_bad"]["reason"])
            self.assertEqual(results["match_good"]["status"], "ok")
            self.assertIsNotNone(MemoryRepository(data_dir).load_projection("match_good"))
            self.assertFalse((bad_dir / "match_memory_projection.json").exists())

    def _run(self, argv: list[str]) -> tuple[int, dict, str]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _observation_variant(self, observation, observation_id: str, visible_name: str, fingerprint: str):
        payload = observation.to_dict()
        payload["observation_id"] = observation_id
        payload["match_identity_hints"] = {
            **payload["match_identity_hints"],
            "visible_name": visible_name,
            "conversation_fingerprint": fingerprint,
        }
        return type(observation).from_dict(payload)


class MemoryUpdateMatchTests(unittest.TestCase):
    def test_update_match_confirms_identity(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            matches_dir = data_dir / "matches"
            matches_dir.mkdir(parents=True)
            (matches_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "matches": [
                            {
                                "match_id": "match_alex_existing",
                                "display_name": observation.match_identity_hints.visible_name,
                                "profile_cues": [],
                                "conversation_fingerprint": None,
                                "observation_ids": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            ingest = store_observation_with_memory(data_dir, observation)
            match_id = ingest["match_id"]
            input_path = self._write_json(
                data_dir,
                "confirm_identity.json",
                {"action": "confirm_identity", "confirmed_by": "user"},
            )

            exit_code, payload, _ = self._run([
                "memory",
                "update-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--input",
                str(input_path),
            ])
            projection = MemoryRepository(data_dir).load_projection(match_id)

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["action"], "confirm_identity")
            self.assertTrue(payload["projection_updated"])
            self.assertEqual(projection.identity_status, IdentityTrustStatus.TRUSTED)
            self.assertTrue(projection.trusted_for_managed_send)

    def test_update_match_corrects_rejects_and_resolves_commitment(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            ingest = store_observation_with_memory(data_dir, observation)
            match_id = ingest["match_id"]
            projection = MemoryRepository(data_dir).load_projection(match_id)
            target_fact = projection.facts[0]
            archived_fact_id = projection.facts[1].fact_id
            correction_input = self._write_json(
                data_dir,
                "correct_fact.json",
                {
                    "action": "correct_fact",
                    "target_fact_id": target_fact.fact_id,
                    "subject": target_fact.subject,
                    "predicate": target_fact.predicate,
                    "value": "prefers quiet coffee",
                    "qualifiers": target_fact.qualifiers,
                    "confidence": "high",
                },
            )
            reject_input = self._write_json(
                data_dir,
                "reject_fact.json",
                {"action": "reject_fact", "target_fact_id": "manual_corrected_fact"},
            )
            archive_input = self._write_json(
                data_dir,
                "archive_fact.json",
                {"action": "archive_fact", "target_fact_id": archived_fact_id},
            )
            create_commitment_input = self._write_json(
                data_dir,
                "create_commitment.json",
                {
                    "action": "create_commitment",
                    "commitment_id": "commitment_weekend",
                    "text": "Follow up about weekend plans.",
                },
            )
            resolve_commitment_input = self._write_json(
                data_dir,
                "resolve_commitment.json",
                {
                    "action": "resolve_commitment",
                    "commitment_id": "commitment_weekend",
                },
            )

            correct_exit, correct_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", match_id, "--input", str(correction_input)
            ])
            reject_exit, reject_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", match_id, "--input", str(reject_input)
            ])
            archive_exit, archive_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", match_id, "--input", str(archive_input)
            ])
            create_exit, create_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", match_id, "--input", str(create_commitment_input)
            ])
            resolve_exit, resolve_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", match_id, "--input", str(resolve_commitment_input)
            ])
            projection = MemoryRepository(data_dir).load_projection(match_id)
            facts_by_id = {fact.fact_id: fact for fact in projection.facts}

            self.assertEqual(correct_exit, 0)
            self.assertEqual(reject_exit, 0)
            self.assertEqual(archive_exit, 0)
            self.assertEqual(create_exit, 0)
            self.assertEqual(resolve_exit, 0)
            self.assertTrue(correct_payload["projection_updated"])
            self.assertEqual(correct_payload["action"], "correct_fact")
            self.assertEqual(reject_payload["action"], "reject_fact")
            self.assertEqual(archive_payload["action"], "archive_fact")
            self.assertEqual(create_payload["action"], "create_commitment")
            self.assertEqual(resolve_payload["action"], "resolve_commitment")
            self.assertEqual(facts_by_id[target_fact.fact_id].status.value, "archived")
            self.assertEqual(facts_by_id["manual_corrected_fact"].status.value, "rejected")
            self.assertEqual(facts_by_id[archived_fact_id].status.value, "archived")
            self.assertEqual(projection.active_commitments, [])
            self.assertEqual(projection.resolved_commitments[0].commitment_id, "commitment_weekend")

    def test_update_match_merge_identity_requires_exact_confirmation_and_preserves_history(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_chat_target_001"
        target_payload["match_identity_hints"] = {
            **target_payload["match_identity_hints"],
            "visible_name": "Alex verified",
            "conversation_fingerprint": "alex-verified-thread",
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]
            bad_input = self._write_json(
                data_dir,
                "merge_bad.json",
                {
                    "action": "merge_identity",
                    "source_match_id": source_match_id,
                    "target_match_id": target_match_id,
                    "confirmation_token": "merge",
                },
            )
            good_input = self._write_json(
                data_dir,
                "merge_good.json",
                {
                    "action": "merge_identity",
                    "source_match_id": source_match_id,
                    "target_match_id": target_match_id,
                    "confirmation_token": f"merge_identity:{source_match_id}:{target_match_id}",
                },
            )

            bad_exit, bad_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", target_match_id, "--input", str(bad_input)
            ])
            good_exit, good_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", target_match_id, "--input", str(good_input)
            ])
            match_records = MatchRepository(data_dir).list_match_candidates()
            target_record = [record for record in match_records if record["match_id"] == target_match_id][0]
            target_events = MemoryRepository(data_dir).load_events(target_match_id)

            self.assertNotEqual(bad_exit, 0)
            self.assertEqual(bad_payload["status"], "error")
            self.assertEqual(good_exit, 0)
            self.assertEqual(good_payload["action"], "merge_identity")
            self.assertNotIn(source_match_id, [record["match_id"] for record in match_records])
            self.assertIn(source_match_id, target_record["merged_match_ids"])
            self.assertIn("obs_chat_001", target_record["observation_ids"])
            self.assertTrue(
                any(event.payload.get("original_match_id") == source_match_id for event in target_events)
            )

    def test_rebuild_after_merge_preserves_source_event_history(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_chat_target_001"
        target_payload["match_identity_hints"] = {
            **target_payload["match_identity_hints"],
            "visible_name": "Alex verified",
            "conversation_fingerprint": "alex-verified-thread",
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]
            merge_input = self._write_json(
                data_dir,
                "merge_good.json",
                {
                    "action": "merge_identity",
                    "source_match_id": source_match_id,
                    "target_match_id": target_match_id,
                    "confirmation_token": f"merge_identity:{source_match_id}:{target_match_id}",
                },
            )
            self._run([
                "memory", "update-match", "--data-dir", str(data_dir), "--match-id", target_match_id, "--input", str(merge_input)
            ])

            rebuild_exit, rebuild_payload, _ = self._run([
                "memory",
                "rebuild",
                "--data-dir",
                str(data_dir),
                "--match-id",
                target_match_id,
            ])
            target_events = MemoryRepository(data_dir).load_events(target_match_id)

            self.assertEqual(rebuild_exit, 0)
            self.assertEqual(rebuild_payload["status"], "ok")
            self.assertTrue(
                any(event.payload.get("original_match_id") == source_match_id for event in target_events)
            )

    def test_update_match_invalid_action_returns_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            input_path = self._write_json(data_dir, "bad.json", {"action": "not_real"})

            exit_code, payload, _ = self._run([
                "memory",
                "update-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                "match_alex",
                "--input",
                str(input_path),
            ])

            self.assertNotEqual(exit_code, 0)
            self.assertEqual(payload["status"], "error")
            self.assertIn("unsupported", payload["reason"])

    def test_inherit_memory_requires_exact_confirmation_token(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_wechat_001"
        target_payload["match_identity_hints"] = {
            **target_payload["match_identity_hints"],
            "visible_name": "Alex WeChat",
            "conversation_fingerprint": "alex-wechat-thread",
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]
            bad_input = self._write_json(data_dir, "inherit_bad.json", {
                "action": "inherit_memory",
                "source_match_id": source_match_id,
                "target_match_id": target_match_id,
                "confirmation_token": "inherit_memory:wrong",
            })

            bad_exit, bad_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", target_match_id, "--input", str(bad_input),
            ])

            self.assertNotEqual(bad_exit, 0)
            self.assertEqual(bad_payload["status"], "error")
            self.assertIn("confirmation_token", bad_payload["reason"])

    def test_inherit_memory_target_must_match_match_id(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_wechat_002"
        target_payload["match_identity_hints"] = {
            **target_payload["match_identity_hints"],
            "visible_name": "Alex WeChat",
            "conversation_fingerprint": "alex-wechat-thread-2",
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]
            wrong_target_input = self._write_json(data_dir, "inherit_wrong_target.json", {
                "action": "inherit_memory",
                "source_match_id": source_match_id,
                "target_match_id": target_match_id,
                "confirmation_token": f"inherit_memory:{source_match_id}:{target_match_id}",
            })

            exit_code, payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", source_match_id, "--input", str(wrong_target_input),
            ])

            self.assertNotEqual(exit_code, 0)
            self.assertIn("target_match_id must match", payload["reason"])

    def test_inherit_memory_source_target_must_differ(self):
        source_observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            input_path = self._write_json(data_dir, "inherit_same.json", {
                "action": "inherit_memory",
                "source_match_id": match_id,
                "target_match_id": match_id,
                "confirmation_token": f"inherit_memory:{match_id}:{match_id}",
            })

            exit_code, payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", match_id, "--input", str(input_path),
            ])

            self.assertNotEqual(exit_code, 0)
            self.assertIn("must differ", payload["reason"])

    def test_inherit_memory_enriches_empty_target_with_source_facts(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_wechat_minimal"
        target_payload["app_id"] = "wechat"
        target_payload["match_identity_hints"] = {
            "visible_name": "Alex WeChat",
            "conversation_fingerprint": "alex-wechat-thread-min",
        }
        target_payload["profile_observation"] = {
            "profile_text": "",
            "photo_cues": [],
            "hook_candidates": [],
        }
        target_payload["conversation_observation"] = {
            "visible_messages": [],
            "input_state": "empty",
            "thread_cues": [],
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]

            target_projection_before = MemoryRepository(data_dir).load_projection(target_match_id)
            source_hooks_before = [
                str(f.value)
                for f in MemoryRepository(data_dir).load_projection(source_match_id).facts
                if f.predicate in {"profile_cue", "hook_candidate"}
            ]

            inherit_input = self._write_json(data_dir, "inherit_enrich.json", {
                "action": "inherit_memory",
                "source_match_id": source_match_id,
                "target_match_id": target_match_id,
                "direction": "dating_app_to_wechat",
                "confirmed_by": "user",
                "confirmation_token": f"inherit_memory:{source_match_id}:{target_match_id}",
            })

            exit_code, payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", target_match_id, "--input", str(inherit_input),
            ])

            target_events = MemoryRepository(data_dir).load_events(target_match_id)
            target_projection = MemoryRepository(data_dir).load_projection(target_match_id)
            inherited_events = [
                e for e in target_events
                if e.evidence is not None and e.evidence.source_type == "memory_inheritance"
            ]
            target_hooks = [
                str(f.value)
                for f in target_projection.facts
                if f.predicate in {"profile_cue", "hook_candidate"}
            ]

            self.assertEqual(exit_code, 0)
            self.assertGreater(payload["inherited_event_count"], 0)
            self.assertGreater(payload["skipped_non_inheritable_event_count"], 0)
            self.assertEqual(len(inherited_events), payload["inherited_event_count"])
            for event in inherited_events:
                self.assertEqual(event.match_id, target_match_id)
                self.assertEqual(event.payload.get("inheritance_type"), "dating_app_to_wechat")
                self.assertNotIn(event.event_type.value, {
                    "observation_ingested", "match_identity_assessed",
                    "match_identity_confirmed", "match_identity_conflict",
                    "projection_rebuilt",
                })
            self.assertTrue(target_projection.trusted_for_context)

            for hook in source_hooks_before:
                self.assertIn(hook, target_hooks, f"inherited hook '{hook}' should appear in target projection")

    def test_inherit_memory_source_identity_conflict_does_not_pollute_target(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_wechat_conflict_safe"
        target_payload["app_id"] = "wechat"
        target_payload["match_identity_hints"] = {
            "visible_name": "Alex WeChat",
            "conversation_fingerprint": "alex-wechat-thread-conflict",
        }
        target_payload["profile_observation"] = {
            "profile_text": "",
            "photo_cues": [],
            "hook_candidates": [],
        }
        target_payload["conversation_observation"] = {
            "visible_messages": [],
            "input_state": "empty",
            "thread_cues": [],
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]

            from dating_boost.core.memory.models import MemoryEvent, MemoryEventType, EvidenceRef, MemoryScope
            conflict_event = MemoryEvent(
                event_id="manual_conflict_001",
                event_type=MemoryEventType.MATCH_IDENTITY_CONFLICT,
                match_id=source_match_id,
                scope=MemoryScope.MATCH_PROFILE,
                created_at="2026-05-26T00:00:00Z",
                payload={"reason": "synthetic conflict for test"},
                evidence=EvidenceRef(source_type="test", evidence_text="synthetic"),
            )
            MemoryRepository(data_dir).append_event(source_match_id, conflict_event)
            MemoryRepository(data_dir).rebuild_projection(source_match_id)

            source_projection = MemoryRepository(data_dir).load_projection(source_match_id)
            self.assertEqual(source_projection.identity_status.value, "conflicted")

            target_projection_before = MemoryRepository(data_dir).load_projection(target_match_id)
            self.assertTrue(target_projection_before.trusted_for_context)

            inherit_input = self._write_json(data_dir, "inherit_no_pollute.json", {
                "action": "inherit_memory",
                "source_match_id": source_match_id,
                "target_match_id": target_match_id,
                "direction": "dating_app_to_wechat",
                "confirmed_by": "user",
                "confirmation_token": f"inherit_memory:{source_match_id}:{target_match_id}",
            })

            exit_code, payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", target_match_id, "--input", str(inherit_input),
            ])

            target_projection_after = MemoryRepository(data_dir).load_projection(target_match_id)
            target_events = MemoryRepository(data_dir).load_events(target_match_id)

            self.assertEqual(exit_code, 0)
            inherited_identity_events = [
                e for e in target_events
                if e.evidence is not None
                and e.evidence.source_type == "memory_inheritance"
                and e.event_type in {
                    MemoryEventType.MATCH_IDENTITY_ASSESSED,
                    MemoryEventType.MATCH_IDENTITY_CONFLICT,
                    MemoryEventType.MATCH_IDENTITY_CONFIRMED,
                }
            ]
            self.assertEqual(len(inherited_identity_events), 0,
                             "no identity events should be inherited to target")
            self.assertTrue(target_projection_after.trusted_for_context,
                            "target should remain trusted; source conflict must not pollute it")
            self.assertNotEqual(target_projection_after.identity_status.value, "conflicted")

    def test_inherit_memory_is_idempotent(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_wechat_004"
        target_payload["match_identity_hints"] = {
            **target_payload["match_identity_hints"],
            "visible_name": "Alex WeChat",
            "conversation_fingerprint": "alex-wechat-thread-4",
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]
            inherit_input = self._write_json(data_dir, "inherit_idem.json", {
                "action": "inherit_memory",
                "source_match_id": source_match_id,
                "target_match_id": target_match_id,
                "confirmation_token": f"inherit_memory:{source_match_id}:{target_match_id}",
            })

            first_exit, first_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", target_match_id, "--input", str(inherit_input),
            ])
            second_exit, second_payload, _ = self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", target_match_id, "--input", str(inherit_input),
            ])
            target_events = MemoryRepository(data_dir).load_events(target_match_id)
            inherited_events = [
                e for e in target_events
                if e.evidence is not None and e.evidence.source_type == "memory_inheritance"
            ]
            event_ids = [e.event_id for e in inherited_events]

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
            self.assertGreater(first_payload["inherited_event_count"], 0)
            self.assertEqual(second_payload["inherited_event_count"], 0)
            self.assertGreater(second_payload["skipped_existing_event_count"], 0)
            self.assertEqual(len(event_ids), len(set(event_ids)))

    def test_inherit_memory_survives_rebuild(self):
        source_observation = load_observation(FIXTURE_PATH)
        target_payload = source_observation.to_dict()
        target_payload["observation_id"] = "obs_wechat_005"
        target_payload["match_identity_hints"] = {
            **target_payload["match_identity_hints"],
            "visible_name": "Alex WeChat",
            "conversation_fingerprint": "alex-wechat-thread-5",
        }
        target_observation = type(source_observation).from_dict(target_payload)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            source_match_id = store_observation_with_memory(data_dir, source_observation)["match_id"]
            target_match_id = store_observation_with_memory(data_dir, target_observation)["match_id"]
            inherit_input = self._write_json(data_dir, "inherit_rebuild.json", {
                "action": "inherit_memory",
                "source_match_id": source_match_id,
                "target_match_id": target_match_id,
                "confirmation_token": f"inherit_memory:{source_match_id}:{target_match_id}",
            })

            self._run([
                "memory", "update-match", "--data-dir", str(data_dir),
                "--match-id", target_match_id, "--input", str(inherit_input),
            ])
            rebuild_exit, rebuild_payload, _ = self._run([
                "memory", "rebuild", "--data-dir", str(data_dir),
                "--match-id", target_match_id,
            ])
            target_events = MemoryRepository(data_dir).load_events(target_match_id)
            inherited_events = [
                e for e in target_events
                if e.evidence is not None and e.evidence.source_type == "memory_inheritance"
            ]

            self.assertEqual(rebuild_exit, 0)
            self.assertEqual(rebuild_payload["status"], "ok")
            self.assertTrue(len(inherited_events) > 0)

            target_projection = MemoryRepository(data_dir).load_projection(target_match_id)
            source_hooks = [
                str(f.value)
                for f in MemoryRepository(data_dir).load_projection(source_match_id).facts
                if f.predicate in {"profile_cue", "hook_candidate"}
            ]
            target_hooks = [
                str(f.value)
                for f in target_projection.facts
                if f.predicate in {"profile_cue", "hook_candidate"}
            ]
            for hook in source_hooks:
                self.assertIn(hook, target_hooks,
                              f"inherited hook '{hook}' should survive rebuild")

    def _write_json(self, directory: Path, name: str, payload: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _run(self, argv: list[str]) -> tuple[int, dict, str]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


class MemoryReviewCliTests(unittest.TestCase):
    def test_review_list_includes_display_without_breaking_machine_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            item = ReviewItem(
                review_item_id="rev_tashuo_permanent_001",
                session_id="session_tashuo",
                match_id="match_tashuo",
                observation_id="obs_tashuo_001",
                proposal={
                    "predicate": "thread_cue",
                    "value": "tashuo_permanent_chat_enabled",
                    "scope": "conversation",
                    "fact_type": "inference",
                    "confidence": "medium",
                    "evidence_text": "Visible thread cue.",
                    "subject": "她说对话",
                },
                status="pending",
                created_at="2026-06-07T00:00:00Z",
                reported_at=None,
                reviewed_at=None,
                dedupe_key="dedupe_tashuo_permanent_001",
                source="deterministic",
                risk="low",
            )
            ReviewQueueRepository(data_dir).enqueue(item)

            exit_code, payload, text = self._run([
                "memory",
                "review",
                "list",
                "--data-dir",
                str(data_dir),
                "--json",
            ])
            listed = payload["items"][0]

            self.assertEqual(exit_code, 0)
            self.assertEqual(listed["review_item_id"], "rev_tashuo_permanent_001")
            self.assertEqual(listed["proposal"]["predicate"], "thread_cue")
            self.assertEqual(listed["proposal"]["value"], "tashuo_permanent_chat_enabled")
            self.assertEqual(listed["display"]["summary"], "她说已开启永久聊天，之后可以继续正常聊天。")
            self.assertIn("display", text)

    def test_review_decide_requires_manual_confirm_for_legacy_blank_session_item(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._write_legacy_blank_session_review_item(data_dir)

            wrong_exit, wrong_payload, _ = self._run([
                "memory",
                "review",
                "decide",
                "--data-dir",
                str(data_dir),
                "--accept",
                "rev_manual_001",
                "--confirm",
                "memory-review:any-session",
            ])
            pending_after_wrong = ReviewQueueRepository(data_dir).load_items(status="pending")
            projection_after_wrong = MemoryRepository(data_dir).load_projection("match_alex")

            accept_exit, accept_payload, _ = self._run([
                "memory",
                "review",
                "decide",
                "--data-dir",
                str(data_dir),
                "--accept",
                "rev_manual_001",
                "--confirm",
                "memory-review:manual",
            ])
            accepted_item = ReviewQueueRepository(data_dir).load_items()[0]
            projection = MemoryRepository(data_dir).load_projection("match_alex")

            self.assertEqual(wrong_exit, 2)
            self.assertEqual(wrong_payload["status"], "blocked")
            self.assertEqual(wrong_payload["reason"], "confirm_token_session_mismatch")
            self.assertEqual(wrong_payload["item_session_id"], "manual")
            self.assertEqual(pending_after_wrong[0].session_id, "manual")
            self.assertIsNone(projection_after_wrong)
            self.assertEqual(accept_exit, 0)
            self.assertEqual(accept_payload["status"], "ok")
            self.assertEqual(accept_payload["accepted"], ["rev_manual_001"])
            self.assertEqual(accepted_item.status, "accepted")
            self.assertEqual(projection.facts[0].fact_id, "rev_manual_001")
            self.assertEqual(projection.facts[0].evidence.metadata["session_id"], "manual")

    def _write_legacy_blank_session_review_item(self, data_dir: Path) -> None:
        item = ReviewItem(
            review_item_id="rev_manual_001",
            session_id="manual",
            match_id="match_alex",
            observation_id="obs_manual_001",
            proposal={
                "predicate": "profile_cue",
                "value": "likes live music",
                "scope": "match_profile",
                "fact_type": "visible_fact",
                "confidence": "medium",
                "evidence_text": "Visible profile cue from review queue.",
                "subject": "Alex",
                "qualifiers": {"app_id": "fixture"},
            },
            status="pending",
            created_at="2026-06-07T00:00:00Z",
            reported_at=None,
            reviewed_at=None,
            dedupe_key="dedupe_manual_001",
            source="deterministic",
            risk="low",
        )
        item_data = item.to_dict()
        item_data["session_id"] = ""
        queue_path = data_dir / "memory" / "review_queue.jsonl"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(json.dumps(item_data, ensure_ascii=False) + "\n", encoding="utf-8")

    def _run(self, argv: list[str]) -> tuple[int, dict, str]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


class MemoryPrivacyCliTests(unittest.TestCase):
    def test_memory_export_includes_projection_events_conflicts_and_identity_without_raw_screenshots(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self._seed_needs_confirmation_match(data_dir, observation)
            ingest = store_observation_with_memory(data_dir, observation)
            match_id = ingest["match_id"]

            exit_code, payload, text = self._run([
                "memory",
                "export",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
            ])
            exported = payload["export"]

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(exported["match_id"], match_id)
            self.assertEqual(
                exported["identity_status"],
                MemoryRepository(data_dir).load_projection(match_id).identity_status.value,
            )
            self.assertIsInstance(exported["projection"], dict)
            self.assertGreater(len(exported["events"]), 0)
            self.assertIn("conflicts", exported)
            self.assertTrue(exported["observations"])
            self.assertIsNotNone(exported["match_record"])
            self.assertTrue(exported["identity_confirmations"])
            self.assertFalse(exported["raw_screenshots_included"])
            self.assertNotIn("raw_ref", text)
            self.assertNotIn("screen.png", text)

    def test_memory_delete_match_requires_exact_token_and_removes_json_sqlite_and_index(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            ProductionDataStore(data_dir).ensure_schema()
            self._seed_needs_confirmation_match(data_dir, observation)
            ingest = store_observation_with_memory(data_dir, observation)
            match_id = ingest["match_id"]
            feedback_input = self._write_json(
                data_dir,
                "feedback.json",
                {
                    "action": "create_commitment",
                    "commitment_id": "commitment_delete",
                    "text": "Follow up before delete.",
                },
            )
            self._run([
                "memory",
                "update-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--input",
                str(feedback_input),
            ])
            store = ProductionDataStore(data_dir)
            self.assertTrue(store.list_documents(prefix=f"matches/{match_id}/"))
            self.assertTrue(store.list_audit_events(stream=f"matches/{match_id}/memory_events.jsonl"))

            wrong_exit, wrong_payload, _ = self._run([
                "memory",
                "delete-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--confirm",
                "delete:match:" + match_id,
            ])
            delete_exit, delete_payload, _ = self._run([
                "memory",
                "delete-match",
                "--data-dir",
                str(data_dir),
                "--match-id",
                match_id,
                "--confirm",
                f"delete-match:{match_id}",
            ])

            self.assertEqual(wrong_exit, 2)
            self.assertEqual(wrong_payload["status"], "blocked")
            self.assertEqual(wrong_payload["required_confirm_token"], f"delete-match:{match_id}")
            self.assertEqual(delete_exit, 0)
            self.assertEqual(delete_payload["status"], "ok")
            self.assertFalse((data_dir / "matches" / match_id).exists())
            self.assertNotIn(match_id, [record["match_id"] for record in MatchRepository(data_dir).list_match_candidates()])
            self.assertEqual(store.list_documents(prefix=f"matches/{match_id}/"), [])
            self.assertEqual(store.list_audit_events(stream=f"matches/{match_id}/memory_events.jsonl"), [])
            confirmations_path = data_dir / "matches" / "identity_confirmations.jsonl"
            self.assertNotIn(match_id, confirmations_path.read_text(encoding="utf-8") if confirmations_path.exists() else "")
            self.assertEqual(store.list_audit_events(stream="matches/identity_confirmations.jsonl"), [])

    def test_memory_delete_match_does_not_delete_json_when_sqlite_cleanup_fails(self):
        observation = load_observation(FIXTURE_PATH)

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            ProductionDataStore(data_dir).ensure_schema()
            ingest = store_observation_with_memory(data_dir, observation)
            match_id = ingest["match_id"]

            original = ProductionDataStore.delete_documents_with_prefix
            try:
                def fail_delete_documents(self, prefix: str) -> int:
                    raise RuntimeError("sqlite cleanup failed")

                ProductionDataStore.delete_documents_with_prefix = fail_delete_documents
                exit_code, payload, _ = self._run([
                    "memory",
                    "delete-match",
                    "--data-dir",
                    str(data_dir),
                    "--match-id",
                    match_id,
                    "--confirm",
                    f"delete-match:{match_id}",
                ])
            finally:
                ProductionDataStore.delete_documents_with_prefix = original

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "error")
            self.assertIn("sqlite cleanup failed", payload["reason"])
            self.assertTrue((data_dir / "matches" / match_id / "memory_events.jsonl").exists())

    def _write_json(self, directory: Path, name: str, payload: dict) -> Path:
        path = directory / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _seed_needs_confirmation_match(self, data_dir: Path, observation) -> None:
        matches_dir = data_dir / "matches"
        matches_dir.mkdir(parents=True, exist_ok=True)
        (matches_dir / "index.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "matches": [
                        {
                            "match_id": "match_alex_existing",
                            "display_name": observation.match_identity_hints.visible_name,
                            "profile_cues": [],
                            "conversation_fingerprint": None,
                            "observation_ids": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _run(self, argv: list[str]) -> tuple[int, dict, str]:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text


class CodexSkillSyncTests(unittest.TestCase):
    def test_codex_skill_resource_copy_contains_inherit_memory(self):
        from pathlib import Path as P
        root = P(__file__).resolve().parent.parent
        source_skill = root / "skills" / "dating-booster-codex" / "SKILL.md"
        resource_copy = root / "dating_boost" / "resources" / "agent_adapters" / "codex" / "dating-booster-codex" / "SKILL.md"
        source_text = source_skill.read_text(encoding="utf-8")
        resource_text = resource_copy.read_text(encoding="utf-8")
        for marker in ["inherit_memory", "continuation channel"]:
            self.assertIn(marker, source_text, f"source SKILL.md missing '{marker}'")
            self.assertIn(marker, resource_text, f"resource SKILL.md missing '{marker}'")


if __name__ == "__main__":
    unittest.main()
