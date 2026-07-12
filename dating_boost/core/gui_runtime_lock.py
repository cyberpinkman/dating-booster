from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


GUI_RUNTIME_LOCK_SCHEMA_VERSION = 1
GUI_RUNTIME_LOCK_PROTOCOL_VERSION = 1
RUNTIME_SCOPE_NAME = "tashuo-mac-ios-app"
LEASE_SECONDS = 300
MAX_HEARTBEAT_AGE_SECONDS = 90


class RuntimeLockError(RuntimeError):
    pass


class RuntimeLockConflict(RuntimeLockError):
    pass


class RuntimeSafetyPaused(RuntimeLockError):
    pass


class ProcessPort(Protocol):
    def identity_is_alive(self, identity: Mapping[str, Any]) -> bool: ...


class SystemProcessPort:
    def identity_is_alive(self, identity: Mapping[str, Any]) -> bool:
        pid = identity.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        current = process_identity(pid)
        if current is None:
            return False
        return all(
            current.get(key) == identity.get(key)
            for key in ("pid", "process_start_time", "executable_digest")
        )


@dataclass(slots=True)
class RuntimeLockHandle:
    _coordinator: GuiRuntimeLock
    file_descriptor: int
    owner_id: str
    owner_nonce: str
    parent_identity: dict[str, Any]
    fencing_token: int
    lease_version: int
    _released: bool = False

    def renew(self, *, expected_lease_version: int, expected_fencing_token: int) -> dict[str, Any]:
        lease = self._coordinator._renew(
            owner_id=self.owner_id,
            owner_nonce=self.owner_nonce,
            expected_lease_version=expected_lease_version,
            expected_fencing_token=expected_fencing_token,
        )
        self.lease_version = lease["lease_version"]
        return lease

    def delegated_capability(self) -> dict[str, Any]:
        return {
            "schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION,
            "protocol_version": GUI_RUNTIME_LOCK_PROTOCOL_VERSION,
            "app_id": "tashuo",
            "runtime": "mac-ios-app",
            "owner_id": self.owner_id,
            "owner_nonce": self.owner_nonce,
            "parent_identity": dict(self.parent_identity),
            "runtime_fencing_token": self.fencing_token,
            "lease_version": self.lease_version,
        }

    def release(self) -> None:
        if self._released:
            return
        try:
            self._coordinator._release(self)
        finally:
            self._released = True

    def _close_os_lock_without_releasing_lease(self) -> None:
        if self._released:
            return
        try:
            fcntl.flock(self.file_descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self.file_descriptor)
            self.file_descriptor = -1
            self._released = True

    def __enter__(self) -> RuntimeLockHandle:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


class GuiRuntimeLock:
    def __init__(
        self,
        *,
        state_root: Path | None = None,
        process_port: ProcessPort | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time: Callable[[], datetime] | None = None,
    ):
        root = state_root or (Path.home() / "Library" / "Application Support" / "Dating Booster" / "runtime-locks")
        self.state_root = root.expanduser().resolve()
        self.scope_dir = self.state_root / RUNTIME_SCOPE_NAME
        self.lock_path = self.scope_dir / "runtime.lock"
        self.lease_path = self.scope_dir / "lease.json"
        self.counter_path = self.scope_dir / "fencing.counter"
        self.pause_path = self.scope_dir / "safety-pause.json"
        self.pause_lock_path = self.scope_dir / "safety-pause.lock"
        self.scope = {"app_id": "tashuo", "runtime": "mac-ios-app"}
        self._process_port = process_port or SystemProcessPort()
        self._monotonic_ns = monotonic_ns
        self._wall_time = wall_time or (lambda: datetime.now(UTC))
        self._initialize_paths()

    def acquire(
        self,
        *,
        owner_id: str,
        owner_nonce: str,
        takeover: bool = False,
    ) -> RuntimeLockHandle:
        if not _identifier(owner_id) or not _identifier(owner_nonce):
            raise RuntimeLockConflict("runtime_owner_invalid")
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.set_inheritable(descriptor, False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise RuntimeLockConflict("runtime_os_lock_held") from exc
        try:
            pause = self._read_pause()
            if pause.get("paused") is True:
                raise RuntimeSafetyPaused("runtime_safety_paused")
            previous = self._read_json(self.lease_path)
            if previous and previous.get("status") == "active":
                alive = self._process_port.identity_is_alive(previous.get("parent_identity") or {})
                if alive:
                    raise RuntimeLockConflict("runtime_previous_parent_alive")
                if not takeover:
                    raise RuntimeLockConflict("runtime_takeover_required")
            fencing_token = self._advance_fencing_counter()
            previous_version = previous.get("lease_version", 0) if isinstance(previous, dict) else 0
            lease_version = int(previous_version) + 1
            identity = current_process_identity()
            heartbeat = self._monotonic_ns()
            lease = {
                "schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION,
                "protocol_version": GUI_RUNTIME_LOCK_PROTOCOL_VERSION,
                **self.scope,
                "status": "active",
                "owner_id": owner_id,
                "owner_nonce": owner_nonce,
                "parent_identity": identity,
                "lease_version": lease_version,
                "fencing_token": fencing_token,
                "boot_session_id": boot_session_id(),
                "heartbeat_monotonic_ns": heartbeat,
                "lease_expires_monotonic_ns": heartbeat + LEASE_SECONDS * 1_000_000_000,
                "acquired_at": _iso(self._wall_time()),
                "released_at": None,
            }
            self._write_json(self.lease_path, lease)
            return RuntimeLockHandle(
                _coordinator=self,
                file_descriptor=descriptor,
                owner_id=owner_id,
                owner_nonce=owner_nonce,
                parent_identity=identity,
                fencing_token=fencing_token,
                lease_version=lease_version,
            )
        except Exception:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            raise

    def validate_delegated_capability(self, capability: Mapping[str, Any]) -> dict[str, Any]:
        pause = self._read_pause()
        if pause.get("paused") is True:
            return _blocked("runtime_safety_paused", pause_id=pause.get("pause_id"))
        lease = self._read_json(self.lease_path)
        if not lease or lease.get("status") != "active":
            return _blocked("runtime_lease_inactive")
        if capability.get("app_id") != "tashuo" or capability.get("runtime") != "mac-ios-app":
            return _blocked("runtime_scope_mismatch")
        if capability.get("runtime_fencing_token") != lease.get("fencing_token"):
            return _blocked("runtime_fencing_mismatch")
        if capability.get("owner_id") != lease.get("owner_id") or capability.get("owner_nonce") != lease.get("owner_nonce"):
            return _blocked("runtime_owner_mismatch")
        if capability.get("parent_identity") != lease.get("parent_identity"):
            return _blocked("runtime_parent_identity_mismatch")
        if capability.get("protocol_version") != GUI_RUNTIME_LOCK_PROTOCOL_VERSION:
            return _blocked("runtime_lock_protocol_mismatch")
        capability_lease_version = capability.get("lease_version")
        current_lease_version = lease.get("lease_version")
        if (
            not isinstance(capability_lease_version, int)
            or isinstance(capability_lease_version, bool)
            or not isinstance(current_lease_version, int)
            or capability_lease_version < 1
            or capability_lease_version > current_lease_version
        ):
            return _blocked("runtime_lease_version_conflict")
        if lease.get("boot_session_id") != boot_session_id():
            return _blocked("runtime_boot_session_changed")
        if not self._process_port.identity_is_alive(lease.get("parent_identity") or {}):
            return _blocked("runtime_parent_dead")
        heartbeat = lease.get("heartbeat_monotonic_ns")
        if not isinstance(heartbeat, int) or isinstance(heartbeat, bool):
            return _blocked("runtime_heartbeat_invalid")
        age = self._monotonic_ns() - heartbeat
        if age < 0 or age > MAX_HEARTBEAT_AGE_SECONDS * 1_000_000_000:
            return _blocked("runtime_heartbeat_stale")
        return {
            "schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION,
            "status": "ok",
            "reason": "runtime_delegated_capability_valid",
            "runtime_fencing_token": lease["fencing_token"],
            "lease_version": lease["lease_version"],
        }

    def pause(self, *, reason: str) -> dict[str, Any]:
        if not _identifier(reason):
            raise RuntimeSafetyPaused("runtime_pause_reason_invalid")
        descriptor = self._pause_lock()
        try:
            existing = self._read_pause()
            if existing.get("paused") is True:
                return {"status": "paused", **existing}
            payload = {
                "schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION,
                **self.scope,
                "paused": True,
                "pause_id": f"pause_{secrets.token_hex(12)}",
                "reason": reason,
                "created_at": _iso(self._wall_time()),
                "resumed_at": None,
            }
            self._write_json(self.pause_path, payload)
            return {"status": "paused", **payload}
        finally:
            self._unlock_close(descriptor)

    def resume(self, *, pause_id: str) -> dict[str, Any]:
        descriptor = self._pause_lock()
        try:
            existing = self._read_pause()
            if existing.get("paused") is not True:
                return {"schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION, "status": "active", **self.scope}
            if existing.get("pause_id") != pause_id:
                raise RuntimeSafetyPaused("runtime_pause_id_mismatch")
            payload = {
                **existing,
                "paused": False,
                "reason": None,
                "resumed_at": _iso(self._wall_time()),
            }
            self._write_json(self.pause_path, payload)
            return {"status": "active", **payload}
        finally:
            self._unlock_close(descriptor)

    def status(self) -> dict[str, Any]:
        lease = self._read_json(self.lease_path) or {}
        pause = self._read_pause()
        safe_lease = {
            key: lease.get(key)
            for key in (
                "status",
                "owner_id",
                "lease_version",
                "fencing_token",
                "boot_session_id",
                "heartbeat_monotonic_ns",
                "lease_expires_monotonic_ns",
                "acquired_at",
                "released_at",
            )
            if key in lease
        }
        return {
            "schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION,
            **self.scope,
            "lease": safe_lease,
            "safety_pause": pause,
        }

    def _renew(
        self,
        *,
        owner_id: str,
        owner_nonce: str,
        expected_lease_version: int,
        expected_fencing_token: int,
    ) -> dict[str, Any]:
        lease = self._read_json(self.lease_path)
        if not lease or lease.get("status") != "active":
            raise RuntimeLockConflict("runtime_lease_inactive")
        if lease.get("owner_id") != owner_id or lease.get("owner_nonce") != owner_nonce:
            raise RuntimeLockConflict("runtime_owner_mismatch")
        if lease.get("fencing_token") != expected_fencing_token:
            raise RuntimeLockConflict("runtime_fencing_mismatch")
        if lease.get("lease_version") != expected_lease_version:
            raise RuntimeLockConflict("runtime_lease_version_conflict")
        heartbeat = self._monotonic_ns()
        updated = {
            **lease,
            "lease_version": expected_lease_version + 1,
            "heartbeat_monotonic_ns": heartbeat,
            "lease_expires_monotonic_ns": heartbeat + LEASE_SECONDS * 1_000_000_000,
        }
        self._write_json(self.lease_path, updated)
        return updated

    def _release(self, handle: RuntimeLockHandle) -> None:
        try:
            lease = self._read_json(self.lease_path)
            if (
                lease
                and lease.get("status") == "active"
                and lease.get("owner_id") == handle.owner_id
                and lease.get("owner_nonce") == handle.owner_nonce
                and lease.get("fencing_token") == handle.fencing_token
            ):
                released = {
                    **lease,
                    "status": "released",
                    "lease_version": int(lease["lease_version"]) + 1,
                    "released_at": _iso(self._wall_time()),
                }
                self._write_json(self.lease_path, released)
        finally:
            if handle.file_descriptor >= 0:
                fcntl.flock(handle.file_descriptor, fcntl.LOCK_UN)
                os.close(handle.file_descriptor)
                handle.file_descriptor = -1

    def _initialize_paths(self) -> None:
        self.scope_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _chmod(self.state_root, 0o700)
        _chmod(self.scope_dir, 0o700)
        for path in (self.lock_path, self.pause_lock_path):
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            os.close(descriptor)
            _chmod(path, 0o600)

    def _advance_fencing_counter(self) -> int:
        current = 0
        if self.counter_path.exists():
            try:
                current = int(self.counter_path.read_text(encoding="ascii").strip())
            except (OSError, ValueError) as exc:
                raise RuntimeLockConflict("runtime_fencing_counter_corrupt") from exc
        next_value = current + 1
        _atomic_write(self.counter_path, f"{next_value}\n", mode=0o600)
        return next_value

    def _pause_lock(self) -> int:
        descriptor = os.open(self.pause_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.set_inheritable(descriptor, False)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor

    def _unlock_close(self, descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    def _read_pause(self) -> dict[str, Any]:
        return self._read_json(self.pause_path) or {
            "schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION,
            **self.scope,
            "paused": False,
            "pause_id": None,
            "reason": None,
            "created_at": None,
            "resumed_at": None,
        }

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeLockConflict("runtime_lock_state_corrupt") from exc
        if not isinstance(payload, dict):
            raise RuntimeLockConflict("runtime_lock_state_corrupt")
        return payload

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        _atomic_write(
            path,
            json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
            mode=0o600,
        )


@lru_cache(maxsize=1)
def current_process_identity() -> dict[str, Any]:
    identity = process_identity(os.getpid())
    if identity is None:
        executable = Path(sys.executable).resolve()
        return {
            "pid": os.getpid(),
            "process_start_time": f"fallback:{time.monotonic_ns()}",
            "executable_path": str(executable),
            "executable_digest": _file_digest(executable),
        }
    return identity


def process_identity(pid: int) -> dict[str, Any] | None:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    start_time = result.stdout.strip()
    if result.returncode != 0 or not start_time:
        return None
    executable = _process_executable_path(pid)
    if executable is None or not executable.is_file():
        return None
    return {
        "pid": pid,
        "process_start_time": start_time,
        "executable_path": str(executable),
        "executable_digest": _file_digest(executable),
    }


@lru_cache(maxsize=1)
def boot_session_id() -> str:
    source = ""
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "kern.boottime"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            source = result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            source = ""
    if not source:
        try:
            source = next(
                line.split()[1]
                for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
                if line.startswith("btime ")
            )
        except (OSError, StopIteration, IndexError):
            source = f"unknown:{platform.node()}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _process_executable_path(pid: int) -> Path | None:
    if pid == os.getpid():
        return Path(sys.executable).resolve()
    if platform.system() == "Darwin":
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            buffer = ctypes.create_string_buffer(4096)
            length = libproc.proc_pidpath(pid, buffer, len(buffer))
            if length > 0:
                return Path(buffer.value.decode("utf-8")).resolve()
        except (OSError, UnicodeDecodeError):
            return None
    try:
        return Path(os.readlink(f"/proc/{pid}/exe")).resolve()
    except OSError:
        return None


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _chmod(path, mode)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp.exists():
            temp.unlink()


def _blocked(reason: str, **extras: Any) -> dict[str, Any]:
    return {"schema_version": GUI_RUNTIME_LOCK_SCHEMA_VERSION, "status": "blocked", "reason": reason, **extras}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
