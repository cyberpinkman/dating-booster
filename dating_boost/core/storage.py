from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    pass


class StorageCorruptionError(StorageError):
    pass


class SchemaVersionError(StorageError):
    pass


class InvalidStoragePathError(StorageError):
    pass


class JsonStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, relative_path: Path) -> Path:
        path = (self.root / relative_path).resolve()
        if not path.is_relative_to(self.root):
            raise InvalidStoragePathError(f"path escapes storage root: {relative_path}")
        return path

    def _fsync_directory(self, path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def read_json(self, relative_path: Path, *, expected_schema_version: int) -> dict[str, Any]:
        path = self._resolve_path(relative_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StorageCorruptionError(f"corrupt JSON: {relative_path}") from exc
        if not isinstance(data, dict):
            raise StorageCorruptionError(f"expected JSON object: {relative_path}")
        if data.get("schema_version") != expected_schema_version:
            raise SchemaVersionError(
                f"expected schema_version {expected_schema_version} for {relative_path}, "
                f"got {data.get('schema_version')}"
            )
        return data

    def write_json(self, relative_path: Path, data: dict[str, Any]) -> None:
        path = self._resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with temp_path.open("r+", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            self._mirror_document_to_sqlite(relative_path, data)
            os.replace(temp_path, path)
            self._fsync_directory(path.parent)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def append_jsonl(self, relative_path: Path, data: dict[str, Any]) -> None:
        path = self._resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            temp_path.write_text(existing + json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")
            with temp_path.open("r+", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            self._mirror_event_to_sqlite(relative_path, data)
            os.replace(temp_path, path)
            self._fsync_directory(path.parent)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def write_jsonl(self, relative_path: Path, items: list[dict[str, Any]]) -> None:
        path = self._resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            content = "".join(json.dumps(item, sort_keys=True) + "\n" for item in items)
            temp_path.write_text(content, encoding="utf-8")
            with temp_path.open("r+", encoding="utf-8") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_event_stream_in_sqlite(relative_path, items)
            os.replace(temp_path, path)
            self._fsync_directory(path.parent)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def read_jsonl(self, relative_path: Path) -> list[dict[str, Any]]:
        path = self._resolve_path(relative_path)
        if not path.exists():
            return []

        items: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise StorageCorruptionError(f"expected JSON object in JSONL: {relative_path}")
                items.append(item)
        except json.JSONDecodeError as exc:
            raise StorageCorruptionError(f"corrupt JSONL: {relative_path}") from exc
        return items

    def _sqlite_db_exists(self) -> bool:
        return (self.root / "dating_boost.sqlite3").exists()

    def _mirror_document_to_sqlite(self, relative_path: Path, data: dict[str, Any]) -> None:
        if not self._sqlite_db_exists():
            return
        from dating_boost.core.production_store import ProductionDataStore

        ProductionDataStore(self.root).upsert_document(relative_path.as_posix(), data)

    def _mirror_event_to_sqlite(self, relative_path: Path, data: dict[str, Any]) -> None:
        if not self._sqlite_db_exists():
            return
        from dating_boost.core.production_store import ProductionDataStore

        ProductionDataStore(self.root).append_audit_event(relative_path.as_posix(), data)

    def _replace_event_stream_in_sqlite(self, relative_path: Path, items: list[dict[str, Any]]) -> None:
        if not self._sqlite_db_exists():
            return
        from dating_boost.core.production_store import ProductionDataStore

        ProductionDataStore(self.root).replace_audit_stream(relative_path.as_posix(), items)
