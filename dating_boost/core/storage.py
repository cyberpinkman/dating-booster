from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from dating_boost.core.production_store_common import PRODUCTION_DB_NAME, _is_managed_state_path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback uses the process-local lock.
    fcntl = None  # type: ignore[assignment]


class StorageError(RuntimeError):
    pass


class StorageCorruptionError(StorageError):
    pass


class SchemaVersionError(StorageError):
    pass


class InvalidStoragePathError(StorageError):
    pass


_LOCK_REGISTRY_GUARD = threading.Lock()
_ROOT_LOCKS: dict[Path, threading.RLock] = {}


class JsonStorage:
    """Repository storage API backed by encrypted SQLite after initialization.

    Plain JSON/JSONL is read and written only for an existing pre-migration data
    directory. A clean directory becomes an encrypted SQLite store on its first
    write, so runtime repositories never create a plaintext mirror by default.
    """

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
        store = self._sqlite_store()
        if store is not None:
            data = store.get_document(relative_path.as_posix())
            if data is None:
                raise FileNotFoundError(path)
        else:
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
        with self._write_lock():
            store = self._sqlite_store_for_write()
            if store is not None:
                store.upsert_document(relative_path.as_posix(), data)
                self._remove_legacy_path(path)
                return
            self._write_text_atomically(path, json.dumps(data, indent=2, sort_keys=True) + "\n")

    def append_jsonl(self, relative_path: Path, data: dict[str, Any]) -> None:
        path = self._resolve_path(relative_path)
        with self._write_lock():
            store = self._sqlite_store_for_write()
            if store is not None:
                store.append_audit_event(relative_path.as_posix(), data)
                self._remove_legacy_path(path)
                return
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            self._write_text_atomically(path, existing + json.dumps(data, sort_keys=True) + "\n")

    def write_jsonl(self, relative_path: Path, items: list[dict[str, Any]]) -> None:
        path = self._resolve_path(relative_path)
        with self._write_lock():
            store = self._sqlite_store_for_write()
            if store is not None:
                store.replace_audit_stream(relative_path.as_posix(), items)
                self._remove_legacy_path(path)
                return
            content = "".join(json.dumps(item, sort_keys=True) + "\n" for item in items)
            self._write_text_atomically(path, content)

    def read_jsonl(self, relative_path: Path) -> list[dict[str, Any]]:
        path = self._resolve_path(relative_path)
        store = self._sqlite_store()
        if store is not None:
            return [dict(item["payload"]) for item in store.list_audit_events(stream=relative_path.as_posix())]
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

    def exists(self, relative_path: Path) -> bool:
        path = self._resolve_path(relative_path)
        store = self._sqlite_store()
        if store is not None:
            if relative_path.suffix == ".jsonl":
                return store.audit_stream_exists(relative_path.as_posix())
            return store.document_exists(relative_path.as_posix())
        return path.exists()

    def delete_json(self, relative_path: Path) -> bool:
        path = self._resolve_path(relative_path)
        with self._write_lock():
            store = self._sqlite_store()
            deleted = store.delete_document(relative_path.as_posix()) > 0 if store is not None else False
            return self._remove_legacy_path(path) or deleted

    def delete_jsonl(self, relative_path: Path) -> bool:
        path = self._resolve_path(relative_path)
        with self._write_lock():
            store = self._sqlite_store()
            deleted = store.delete_audit_stream(relative_path.as_posix()) > 0 if store is not None else False
            return self._remove_legacy_path(path) or deleted

    def _sqlite_store(self):
        if not self._sqlite_db_exists():
            return None
        from dating_boost.core.production_store import ProductionDataStore

        return ProductionDataStore(self.root)

    def _sqlite_store_for_write(self):
        store = self._sqlite_store()
        if store is not None:
            return store
        if self._has_legacy_sources():
            return None
        from dating_boost.core.production_store import ProductionDataStore

        store = ProductionDataStore(self.root)
        store.initialize_empty()
        return store

    def _sqlite_db_exists(self) -> bool:
        return (self.root / PRODUCTION_DB_NAME).exists()

    def _has_legacy_sources(self) -> bool:
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
                continue
            relative_parts = path.relative_to(self.root).parts
            if relative_parts and relative_parts[0] != "backups" and _is_managed_state_path(Path(*relative_parts)):
                return True
        return False

    def _write_text_atomically(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        descriptor = -1
        try:
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            self._fsync_directory(path.parent)
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _remove_legacy_path(self, path: Path) -> bool:
        if not path.exists():
            return False
        path.unlink()
        self._fsync_directory(path.parent)
        return True

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        with _LOCK_REGISTRY_GUARD:
            thread_lock = _ROOT_LOCKS.setdefault(self.root, threading.RLock())
        with thread_lock:
            lock_path = self.root / ".dating_boost_storage.lock"
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
