import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import JsonStorage


class ProductionDataCliTests(unittest.TestCase):
    def test_data_migrate_backs_up_json_creates_sqlite_and_export_redacts_blocked_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            match_dir = data_dir / "matches" / "match_ada"
            match_dir.mkdir(parents=True)
            self._write_json(
                match_dir / "match.json",
                {
                    "schema_version": 1,
                    "match_id": "match_ada",
                    "display_name": "Ada",
                    "observation_ids": ["obs_ada_001"],
                },
            )
            self._write_json(
                data_dir / "policy" / "blocked_draft.json",
                {
                    "schema_version": 1,
                    "status": "blocked",
                    "blocked_draft_text": "I studied overseas too. London was incredible.",
                    "policy": {"allowed": False},
                },
            )
            audit_dir = data_dir / "audit"
            audit_dir.mkdir()
            audit_dir.joinpath("action_results.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event_id": "event_ada",
                        "action": "send_message",
                        "target_match_id": "match_ada",
                        "payload_hash": "hash_ada",
                        "result_status": "unknown",
                        "created_at": "2026-05-26T00:00:00Z",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            migrate_exit, migrate_payload, _ = self._run(
                ["data", "migrate", "--data-dir", str(data_dir), "--json"]
            )
            doctor_exit, doctor_payload, _ = self._run(
                ["data", "doctor", "--data-dir", str(data_dir), "--json"]
            )
            caps_exit, caps_payload, _ = self._run(
                ["capabilities", "--json", "--data-dir", str(data_dir)]
            )
            export_path = root / "export.json"
            export_exit, export_payload, export_text = self._run(
                ["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"]
            )

            self.assertEqual(migrate_exit, 0)
            self.assertEqual(migrate_payload["status"], "ok")
            self.assertEqual(migrate_payload["storage_backend"], "sqlite")
            self.assertTrue((data_dir / "dating_boost.sqlite3").exists())
            self.assertTrue(migrate_payload["backup_dir"].startswith(str((data_dir / "backups").resolve())))
            self.assertFalse((match_dir / "match.json").exists())
            self.assertTrue((Path(migrate_payload["backup_dir"]) / "dating_boost.sqlite3").exists())
            self.assertGreaterEqual(migrate_payload["migrated_documents"], 2)
            self.assertGreaterEqual(migrate_payload["migrated_events"], 1)

            self.assertEqual(doctor_exit, 0)
            self.assertEqual(doctor_payload["status"], "ok")
            self.assertEqual(doctor_payload["storage_backend"], "sqlite")
            self.assertEqual(doctor_payload["schema_versions"]["data_store"], 2)
            self.assertEqual(caps_exit, 0)
            self.assertEqual(caps_payload["storage_capabilities"]["storage_backend"], "sqlite")
            self.assertTrue(caps_payload["storage_capabilities"]["sqlite"])

            self.assertEqual(export_exit, 0)
            self.assertEqual(export_payload["status"], "ok")
            self.assertTrue(export_path.exists())
            exported = json.loads(export_path.read_text(encoding="utf-8"))
            exported_paths = {item["path"] for item in exported["documents"]}
            self.assertIn("matches/match_ada/match.json", exported_paths)
            self.assertEqual(exported["audit_stream"][0]["event_id"], "event_ada")
            self.assertNotIn("I studied overseas too", export_text)
            self.assertNotIn("blocked_draft_text", export_path.read_text(encoding="utf-8"))

    def test_data_migrate_removes_plaintext_sources_and_keeps_only_encrypted_sqlite_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            source_path = data_dir / "matches" / "match_ada" / "observations.json"
            self._write_json(
                source_path,
                {
                    "schema_version": 1,
                    "match_id": "match_ada",
                    "raw_chat": "migration plaintext sentinel",
                },
            )

            exit_code, payload, _ = self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertFalse(source_path.exists())
            backup_dir = Path(payload["backup_dir"])
            self.assertTrue((backup_dir / "dating_boost.sqlite3").exists())
            plaintext_files = [
                path
                for path in data_dir.rglob("*")
                if path.is_file() and path.suffix in {".json", ".jsonl"}
            ]
            self.assertEqual(plaintext_files, [])
            all_bytes = b"".join(path.read_bytes() for path in data_dir.rglob("*") if path.is_file())
            self.assertNotIn(b"migration plaintext sentinel", all_bytes)

    def test_data_doctor_blocks_plaintext_residue_after_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            self._write_json(
                data_dir / "matches" / "match_leak" / "observations.json",
                {"schema_version": 1, "raw_chat": "unexpected plaintext residue"},
            )

            exit_code, payload, _ = self._run(["data", "doctor", "--data-dir", str(data_dir), "--json"])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "plaintext_legacy_residue")
            self.assertFalse(payload["checks"]["plaintext_legacy_files_absent"])

    def test_data_migrate_blocks_corrupt_json_after_backup_without_deleting_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            corrupt_path = data_dir / "matches" / "match_bad" / "corrupt.json"
            corrupt_path.parent.mkdir(parents=True)
            corrupt_path.write_text("{not json", encoding="utf-8")

            exit_code, payload, _ = self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "corrupt_json")
            self.assertTrue(corrupt_path.exists())
            self.assertFalse((data_dir / "dating_boost.sqlite3").exists())
            self.assertTrue(list((data_dir / "backups").glob("*")))

    def test_data_export_blocks_unmigrated_json_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            match_dir = data_dir / "matches" / "match_ada"
            match_dir.mkdir(parents=True)
            self._write_json(match_dir / "match.json", {"schema_version": 1, "match_id": "match_ada"})
            export_path = Path(temp_dir) / "export.json"

            exit_code, payload, _ = self._run(
                ["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"]
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "needs_migration")
            self.assertFalse(export_path.exists())

    def test_data_delete_requires_confirm_token_and_deletes_match_scope(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            for match_id in ("match_ada", "match_bea"):
                match_dir = data_dir / "matches" / match_id
                match_dir.mkdir(parents=True, exist_ok=True)
                self._write_json(
                    match_dir / "match.json",
                    {"schema_version": 1, "match_id": match_id, "display_name": match_id},
                )

            migrate_exit, _, _ = self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            wrong_exit, wrong_payload, _ = self._run(
                [
                    "data",
                    "delete",
                    "--data-dir",
                    str(data_dir),
                    "--scope",
                    "match",
                    "--match-id",
                    "match_ada",
                    "--confirm",
                    "wrong",
                    "--json",
                ]
            )
            delete_exit, delete_payload, _ = self._run(
                [
                    "data",
                    "delete",
                    "--data-dir",
                    str(data_dir),
                    "--scope",
                    "match",
                    "--match-id",
                    "match_ada",
                    "--confirm",
                    "delete:match:match_ada",
                    "--json",
                ]
            )
            export_path = Path(temp_dir) / "export_after_delete.json"
            _, _, _ = self._run(
                ["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"]
            )
            exported_text = export_path.read_text(encoding="utf-8")

            self.assertEqual(migrate_exit, 0)
            self.assertEqual(wrong_exit, 2)
            self.assertEqual(wrong_payload["status"], "blocked")
            self.assertEqual(wrong_payload["required_confirm_token"], "delete:match:match_ada")
            self.assertEqual(delete_exit, 0)
            self.assertEqual(delete_payload["status"], "ok")
            self.assertGreaterEqual(delete_payload["deleted_documents"], 1)
            self.assertNotIn("match_ada", exported_text)
            self.assertIn("match_bea", exported_text)

    def test_data_delete_match_removes_json_audit_state_and_backup_residue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            for match_id in ("match_ada", "match_bea"):
                match_dir = data_dir / "matches" / match_id
                match_dir.mkdir(parents=True, exist_ok=True)
                self._write_json(
                    match_dir / "match.json",
                    {"schema_version": 1, "match_id": match_id, "display_name": match_id},
                )
            self._write_json(
                data_dir / "automation" / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {"match_id": "match_ada", "candidate_key": "row_ada"},
                        {"match_id": "match_bea", "candidate_key": "row_bea"},
                    ],
                },
            )
            audit_path = data_dir / "audit" / "action_results.jsonl"
            audit_path.parent.mkdir(parents=True)
            audit_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event_id": "event_ada",
                        "target_match_id": "match_ada",
                        "payload_hash": "hash_ada",
                    },
                    sort_keys=True,
                )
                + "\n"
                + json.dumps(
                    {
                        "schema_version": 1,
                        "event_id": "event_bea",
                        "target_match_id": "match_bea",
                        "payload_hash": "hash_bea",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            delete_exit, delete_payload, _ = self._run(
                [
                    "data",
                    "delete",
                    "--data-dir",
                    str(data_dir),
                    "--scope",
                    "match",
                    "--match-id",
                    "match_ada",
                    "--confirm",
                    "delete:match:match_ada",
                    "--json",
                ]
            )
            store = ProductionDataStore(data_dir)
            remaining_events = store.list_audit_events(stream="audit/action_results.jsonl")

            self.assertEqual(delete_exit, 0)
            self.assertEqual(delete_payload["status"], "ok")
            self.assertIsNone(store.get_document("matches/match_ada/match.json"))
            self.assertIsNotNone(store.get_document("matches/match_bea/match.json"))
            self.assertEqual([event["target_match_id"] for event in remaining_events], ["match_bea"])

    def test_data_delete_match_does_not_delete_prefix_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            for match_id in ("match_1", "match_10"):
                match_dir = data_dir / "matches" / match_id
                match_dir.mkdir(parents=True, exist_ok=True)
                self._write_json(
                    match_dir / "match.json",
                    {"schema_version": 1, "match_id": match_id, "display_name": match_id},
                )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            delete_exit, delete_payload, _ = self._run(
                [
                    "data",
                    "delete",
                    "--data-dir",
                    str(data_dir),
                    "--scope",
                    "match",
                    "--match-id",
                    "match_1",
                    "--confirm",
                    "delete:match:match_1",
                    "--json",
                ]
            )
            export_path = Path(temp_dir) / "export_after_collision_delete.json"
            self._run(["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"])
            exported = json.loads(export_path.read_text(encoding="utf-8"))
            exported_paths = {item["path"] for item in exported["documents"]}

            self.assertEqual(delete_exit, 0)
            self.assertEqual(delete_payload["status"], "ok")
            self.assertFalse((data_dir / "matches" / "match_1").exists())
            self.assertFalse((data_dir / "matches" / "match_10" / "match.json").exists())
            self.assertNotIn("matches/match_1/match.json", exported_paths)
            self.assertIn("matches/match_10/match.json", exported_paths)

    def test_data_delete_match_updates_shared_sqlite_documents_instead_of_deleting_them(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            for match_id in ("match_1", "match_10"):
                match_dir = data_dir / "matches" / match_id
                match_dir.mkdir(parents=True, exist_ok=True)
                self._write_json(
                    match_dir / "match.json",
                    {"schema_version": 1, "match_id": match_id, "display_name": match_id},
                )
            self._write_json(
                data_dir / "automation" / "states.json",
                {
                    "schema_version": 1,
                    "states": [
                        {"match_id": "match_1", "candidate_key": "row_1"},
                        {"match_id": "match_10", "candidate_key": "row_10"},
                    ],
                },
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            delete_exit, delete_payload, _ = self._run(
                [
                    "data",
                    "delete",
                    "--data-dir",
                    str(data_dir),
                    "--scope",
                    "match",
                    "--match-id",
                    "match_1",
                    "--confirm",
                    "delete:match:match_1",
                    "--json",
                ]
            )
            export_path = Path(temp_dir) / "export_after_shared_delete.json"
            self._run(["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"])
            exported = json.loads(export_path.read_text(encoding="utf-8"))
            documents = {item["path"]: item["payload"] for item in exported["documents"]}

            self.assertEqual(delete_exit, 0)
            self.assertEqual(delete_payload["status"], "ok")
            self.assertIn("automation/states.json", documents)
            self.assertEqual(
                documents["automation/states.json"]["states"],
                [{"candidate_key": "row_10", "match_id": "match_10"}],
            )

    def test_data_delete_all_removes_backups_and_sqlite_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            match_dir = data_dir / "matches" / "match_ada"
            match_dir.mkdir(parents=True)
            self._write_json(match_dir / "match.json", {"schema_version": 1, "match_id": "match_ada"})
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            exit_code, payload, _ = self._run(
                [
                    "data",
                    "delete",
                    "--data-dir",
                    str(data_dir),
                    "--scope",
                    "all",
                    "--confirm",
                    "delete:all",
                    "--json",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertFalse((data_dir / "backups").exists())
            self.assertFalse((data_dir / "dating_boost.sqlite3").exists())

    def test_data_migrate_blocks_unknown_schema_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            unknown_path = data_dir / "user" / "unknown.json"
            self._write_json(unknown_path, {"schema_version": 999, "value": "bad"})

            exit_code, payload, _ = self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "unknown_schema_version")
            self.assertTrue(unknown_path.exists())

    def test_json_storage_writes_are_mirrored_to_sqlite_after_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            profile_path = Path(temp_dir) / "profile.json"
            self._write_json(
                profile_path,
                {
                    "schema_version": 1,
                    "user_id": "user_local",
                    "facts": [],
                    "preferences": [],
                    "boundaries": [],
                    "style_examples": [],
                    "goals": [],
                    "persona_baseline": "reserved",
                    "persona_range": [],
                    "stance_range": [],
                    "updated_at": "2026-05-26T00:00:00Z",
                    "default_reply_mode": "adaptive",
                },
            )
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            self._run(["init-profile", "--data-dir", str(data_dir), "--input", str(profile_path)])
            export_path = Path(temp_dir) / "export.json"

            export_exit, _, _ = self._run(
                ["data", "export", "--data-dir", str(data_dir), "--output", str(export_path), "--json"]
            )
            exported = json.loads(export_path.read_text(encoding="utf-8"))

            self.assertEqual(export_exit, 0)
            exported_paths = {item["path"] for item in exported["documents"]}
            self.assertIn("user_profile.json", exported_paths)

    def test_sqlite_mirror_failure_blocks_json_write_after_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            self._run(["data", "migrate", "--data-dir", str(data_dir), "--json"])
            storage = JsonStorage(data_dir)

            with patch(
                "dating_boost.core.production_store.ProductionDataStore.upsert_document",
                side_effect=RuntimeError("sqlite unavailable"),
            ):
                with self.assertRaises(RuntimeError):
                    storage.write_json(Path("unsafe.json"), {"schema_version": 1, "value": "must_not_split"})

            self.assertFalse((data_dir / "unsafe.json").exists())
            self.assertFalse((data_dir / "unsafe.json.tmp").exists())

    def test_sqlite_prefix_delete_helpers_only_delete_match_local_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            store = ProductionDataStore(data_dir)
            store.upsert_document("matches/match_ada/match_memory_projection.json", {"schema_version": 1})
            store.upsert_document("matches/match_bea/match_memory_projection.json", {"schema_version": 1})
            store.append_audit_event(
                "matches/match_ada/memory_events.jsonl",
                {"event_id": "event_ada", "target_match_id": "match_ada"},
            )
            store.append_audit_event(
                "matches/match_bea/memory_events.jsonl",
                {"event_id": "event_bea", "target_match_id": "match_bea"},
            )

            deleted_documents = store.delete_documents_with_prefix("matches/match_ada/")
            deleted_events = store.delete_audit_events_with_stream_prefix("matches/match_ada/")

            self.assertEqual(deleted_documents, 1)
            self.assertEqual(deleted_events, 1)
            self.assertEqual(store.list_documents(prefix="matches/match_ada/"), [])
            self.assertTrue(store.list_documents(prefix="matches/match_bea/"))
            self.assertEqual(store.list_audit_events(stream="matches/match_ada/memory_events.jsonl"), [])
            self.assertTrue(store.list_audit_events(stream="matches/match_bea/memory_events.jsonl"))

    def test_sqlite_prefix_delete_helpers_reject_unsafe_prefixes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProductionDataStore(Path(temp_dir) / "data")
            unsafe_prefixes = [
                "",
                ".",
                "..",
                "/matches/match_ada/",
                "matches/",
                "matches/../match_ada/",
                "profiles/user_local/",
            ]

            for prefix in unsafe_prefixes:
                with self.subTest(prefix=prefix):
                    with self.assertRaises(ValueError):
                        store.delete_documents_with_prefix(prefix)
                    with self.assertRaises(ValueError):
                        store.delete_audit_events_with_stream_prefix(prefix)

    def _run(self, argv):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(argv)
        text = output.getvalue()
        return exit_code, json.loads(text), text

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
