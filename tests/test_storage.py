import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.storage import (
    InvalidStoragePathError,
    JsonStorage,
    SchemaVersionError,
    StorageCorruptionError,
)


class StorageTests(unittest.TestCase):
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
            lines = (Path(temp_dir) / "events" / "feedback.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual(result["name"], "nested")
            self.assertEqual(json.loads(lines[0])["event_id"], "fb_nested")

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

    def test_jsonl_append_writes_one_object_per_line(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage = JsonStorage(Path(temp_dir))
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_1"})
            storage.append_jsonl(Path("feedback_events.jsonl"), {"event_id": "fb_2"})

            lines = (Path(temp_dir) / "feedback_events.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual([json.loads(line)["event_id"] for line in lines], ["fb_1", "fb_2"])


if __name__ == "__main__":
    unittest.main()
