from __future__ import annotations

import json
import os
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
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with temp_path.open("r+", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        self._fsync_directory(path.parent)

    def append_jsonl(self, relative_path: Path, data: dict[str, Any]) -> None:
        path = self._resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

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
