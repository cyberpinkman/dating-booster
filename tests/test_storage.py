import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from dating_boost.core.storage import (
    InvalidStoragePathError,
    JsonStorage,
    SchemaVersionError,
    StorageCorruptionError,
)
from dating_boost.core.production_store import ProductionDataStore


class StorageTests(unittest.TestCase):
    def test_fresh_storage_uses_encrypted_sqlite_without_plaintext_document(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "command-input.json").write_text('{"schema_version": 1}', encoding="utf-8")
            relative_path = Path("matches/match_alex/observations.json")
            storage = JsonStorage(data_dir)

            storage.write_json(
                relative_path,
                {
                    "schema_version": 1,
                    "match_id": "match_alex",
                    "raw_chat": "unique plaintext that must never reach a mirror",
                },
            )

            self.assertTrue((data_dir / "dating_boost.sqlite3").exists())
            self.assertFalse((data_dir / relative_path).exists())
            self.assertEqual(storage.read_json(relative_path, expected_schema_version=1)["match_id"], "match_alex")
            with sqlite3.connect(data_dir / "dating_boost.sqlite3") as connection:
                stored = connection.execute(
                    "SELECT payload_json FROM documents WHERE path = ?",
                    (relative_path.as_posix(),),
                ).fetchone()[0]
            self.assertNotIn("unique plaintext", stored)

    def test_json_storage_writes_and_reads_document_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.write_json(Path("user_profile.json"), {"schema_version": 1, "name": "local"})

            result = storage.read_json(Path("user_profile.json"), expected_schema_version=1)

            self.assertEqual(result["name"], "local")

    def test_nested_relative_paths_work(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.write_json(Path("matches/local/user_profile.json"), {"schema_version": 1, "name": "nested"})
            storage.append_jsonl(Path("events/feedback.jsonl"), {"event_id": "fb_nested"})

            result = storage.read_json(Path("matches/local/user_profile.json"), expected_schema_version=1)
            events = storage.read_jsonl(Path("events/feedback.jsonl"))

            self.assertEqual(result["name"], "nested")
            self.assertEqual(events[0]["event_id"], "fb_nested")

    def test_write_json_rejects_parent_escape_without_creating_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            outside_path = Path(temp_dir) / "outside.json"
            storage = JsonStorage(root)

            with self.assertRaises(InvalidStoragePathError):
                storage.write_json(Path("../outside.json"), {"schema_version": 1})

            self.assertFalse(outside_path.exists())

    def test_write_json_rejects_absolute_path_without_creating_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            outside_path = Path(temp_dir) / "absolute-outside.json"
            storage = JsonStorage(root)

            with self.assertRaises(InvalidStoragePathError):
                storage.write_json(outside_path, {"schema_version": 1})

            self.assertFalse(outside_path.exists())

    def test_read_json_rejects_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            outside_path = Path(temp_dir) / "outside.json"
            outside_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
            storage = JsonStorage(root)

            with self.assertRaises(InvalidStoragePathError):
                storage.read_json(Path("../outside.json"), expected_schema_version=1)

            with self.assertRaises(InvalidStoragePathError):
                storage.read_json(outside_path, expected_schema_version=1)

    def test_append_jsonl_rejects_parent_escape_without_creating_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            outside_path = Path(temp_dir) / "outside.jsonl"
            storage = JsonStorage(root)

            with self.assertRaises(InvalidStoragePathError):
                storage.append_jsonl(Path("../outside.jsonl"), {"event_id": "fb_escape"})

            self.assertFalse(outside_path.exists())

    def test_write_jsonl_rejects_parent_escape_without_creating_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "storage"
            outside_path = Path(temp_dir) / "outside.jsonl"
            storage = JsonStorage(root)

            with self.assertRaises(InvalidStoragePathError):
                storage.write_jsonl(Path("../outside.jsonl"), [{"event_id": "fb_escape"}])

            self.assertFalse(outside_path.exists())

    def test_unknown_schema_version_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "user_profile.json"
            path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
            storage = JsonStorage(Path(temp_dir))

            with self.assertRaises(SchemaVersionError):
                storage.read_json(Path("user_profile.json"), expected_schema_version=1)

    def test_corrupt_json_raises_storage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.json"
            path.write_text("{broken", encoding="utf-8")
            storage = JsonStorage(Path(temp_dir))

            with self.assertRaises(StorageCorruptionError):
                storage.read_json(Path("broken.json"), expected_schema_version=1)

    def test_valid_json_non_object_raises_storage_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "not_an_object.json"
            path.write_text("[]", encoding="utf-8")
            storage = JsonStorage(Path(temp_dir))

            with self.assertRaises(StorageCorruptionError):
                storage.read_json(Path("not_an_object.json"), expected_schema_version=1)

    def test_jsonl_append_preserves_append_order_independent_of_event_timestamps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.append_jsonl(
                Path("feedback_events.jsonl"),
                {"event_id": "fb_1", "created_at": "2026-07-11T00:00:01Z"},
            )
            storage.append_jsonl(
                Path("feedback_events.jsonl"),
                {"event_id": "fb_2", "created_at": "2026-07-11T00:00:00Z"},
            )

            events = storage.read_jsonl(Path("feedback_events.jsonl"))

            self.assertEqual([event["event_id"] for event in events], ["fb_1", "fb_2"])

    def test_concurrent_legacy_jsonl_appends_do_not_lose_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            relative_path = Path("feedback_events.jsonl")
            event_path = data_dir / relative_path
            event_path.write_text("", encoding="utf-8")
            storage = JsonStorage(data_dir)
            original_read_text = Path.read_text

            def delayed_read_text(path: Path, *args, **kwargs):
                text = original_read_text(path, *args, **kwargs)
                if path == event_path:
                    time.sleep(0.05)
                return text

            with patch.object(Path, "read_text", delayed_read_text):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(storage.append_jsonl, relative_path, {"event_id": event_id})
                        for event_id in ("fb_concurrent_1", "fb_concurrent_2")
                    ]
                    for future in futures:
                        future.result()

            self.assertEqual(
                {event["event_id"] for event in storage.read_jsonl(relative_path)},
                {"fb_concurrent_1", "fb_concurrent_2"},
            )

    def test_jsonl_read_returns_objects_and_missing_file_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_1"})
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_2"})

            events = storage.read_jsonl(Path("feedback_events.jsonl"))
            missing_events = storage.read_jsonl(Path("missing.jsonl"))

            self.assertEqual([event["event_id"] for event in events], ["fb_1", "fb_2"])
            self.assertEqual(missing_events, [])

    def test_jsonl_write_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_old"})
            storage.write_jsonl(
                Path("feedback_events.jsonl"),
                [{"event_id": "fb_1"}, {"event_id": "fb_2"}],
            )

            events = storage.read_jsonl(Path("feedback_events.jsonl"))

            self.assertEqual([event["event_id"] for event in events], ["fb_1", "fb_2"])

    def test_jsonl_write_replaces_sqlite_mirrored_stream(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            store = ProductionDataStore(data_dir)
            store.ensure_schema()
            storage = JsonStorage(data_dir)

            storage.append_jsonl(
                Path("matches/match_alex/memory_events.jsonl"),
                {"event_id": "old", "created_at": "2026-06-01T00:00:00Z"},
            )
            storage.write_jsonl(
                Path("matches/match_alex/memory_events.jsonl"),
                [{"event_id": "new", "created_at": "2026-06-02T00:00:00Z"}],
            )

            events = store.list_audit_events(stream="matches/match_alex/memory_events.jsonl")

            self.assertEqual([event["event_id"] for event in events], ["new"])


if __name__ == "__main__":
    unittest.main()
