from __future__ import annotations

import fcntl
import os
import signal
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from dating_boost.apps.tashuo.standalone_production_artifacts import QualificationPaths
from dating_boost.apps.tashuo.standalone_production_ledger import (
    LedgerConflict,
    ProductionQualificationLedger,
)
from dating_boost.core.gui_runtime_lock import (
    GUI_RUNTIME_LOCK_PROTOCOL_VERSION,
    GuiRuntimeLock,
    ProcessPort,
    RuntimeLockHandle,
    SystemProcessPort,
    boot_session_id,
    current_process_identity,
    process_identity,
)


LOCAL_LOCK_SCHEMA_VERSION = 1
LOCAL_LOCK_PROTOCOL_VERSION = 1
LOCAL_LEASE_PATH = "standalone_production/locks/runner.json"
LEASE_SECONDS = 300
MAX_HEARTBEAT_AGE_SECONDS = 90
WORKER_RECORD_PREFIX = "standalone_production/workers/"


class ProductionLockError(RuntimeError):
    pass


class ProductionLockConflict(ProductionLockError):
    pass


class WorkerIdentityConflict(ProductionLockError):
    pass


class WorkerProcessRegistry:
    def __init__(self, ledger: ProductionQualificationLedger):
        self.ledger = ledger

    def register(
        self,
        *,
        context_id: str,
        worker_kind: str,
        pid: int,
        pgid: int,
        worker_nonce: str,
        identity: Mapping[str, Any],
    ) -> dict[str, Any]:
        if (
            not _identifier(context_id)
            or worker_kind not in {"selection_probe", "attempt", "recovery"}
            or not _positive_process_id(pid)
            or not _positive_process_id(pgid)
            or not _identifier(worker_nonce)
            or identity.get("pid") != pid
            or not _identifier(identity.get("process_start_time"))
            or not _identifier(identity.get("executable_path"))
            or not _identifier(identity.get("executable_digest"))
        ):
            raise WorkerIdentityConflict("worker_identity_invalid")
        record = {
            "schema_version": 1,
            "context_id": context_id,
            "worker_kind": worker_kind,
            "status": "registered_waiting_barrier",
            "pid": pid,
            "pgid": pgid,
            "process_start_time": identity.get("process_start_time"),
            "executable_path": identity.get("executable_path"),
            "executable_digest": identity.get("executable_digest"),
            "worker_nonce": worker_nonce,
            "registered_monotonic_ns": time.monotonic_ns(),
            "heartbeat_monotonic_ns": None,
            "exit_code": None,
        }
        return self.ledger.create_versioned(self._path(context_id), record)

    def mark_child_ready(self, *, context_id: str, worker_nonce: str, pid: int) -> dict[str, Any]:
        record = self.read(context_id)
        if (
            record.get("worker_nonce") != worker_nonce
            or record.get("pid") != pid
            or record.get("status") != "registered_waiting_barrier"
        ):
            raise WorkerIdentityConflict("worker_registration_binding_mismatch")
        return self.ledger.compare_and_swap(
            self._path(context_id),
            expected_version=record["ledger_version"],
            changes={"status": "running", "heartbeat_monotonic_ns": time.monotonic_ns()},
        )

    def heartbeat(self, *, context_id: str, worker_nonce: str) -> dict[str, Any]:
        record = self.read(context_id)
        if record.get("worker_nonce") != worker_nonce or record.get("status") != "running":
            raise WorkerIdentityConflict("worker_heartbeat_binding_mismatch")
        return self.ledger.compare_and_swap(
            self._path(context_id),
            expected_version=record["ledger_version"],
            changes={"heartbeat_monotonic_ns": time.monotonic_ns()},
        )

    def mark_terminal(self, *, context_id: str, worker_nonce: str, exit_code: int) -> dict[str, Any]:
        record = self.read(context_id)
        if record.get("worker_nonce") != worker_nonce:
            raise WorkerIdentityConflict("worker_terminal_binding_mismatch")
        if record.get("status") == "terminal":
            if record.get("exit_code") != exit_code:
                raise WorkerIdentityConflict("worker_terminal_conflict")
            return record
        return self.ledger.compare_and_swap(
            self._path(context_id),
            expected_version=record["ledger_version"],
            changes={
                "status": "terminal",
                "exit_code": int(exit_code),
                "terminal_monotonic_ns": time.monotonic_ns(),
            },
        )

    def mark_disappeared(self, *, context_id: str, worker_nonce: str) -> dict[str, Any]:
        record = self.read(context_id)
        if record.get("worker_nonce") != worker_nonce:
            raise WorkerIdentityConflict("worker_terminal_binding_mismatch")
        if record.get("status") == "disappeared":
            return record
        if record.get("status") == "terminal":
            return record
        return self.ledger.compare_and_swap(
            self._path(context_id),
            expected_version=record["ledger_version"],
            changes={
                "status": "disappeared",
                "terminal_monotonic_ns": time.monotonic_ns(),
            },
        )

    def verify_live_identity(self, context_id: str) -> dict[str, Any]:
        record = self.read(context_id)
        if record.get("status") not in {"registered_waiting_barrier", "running"}:
            return {"status": "not_alive", "reason": "worker_not_active"}
        current = process_identity(int(record.get("pid") or 0))
        if current is None:
            return {"status": "not_alive", "reason": "worker_not_alive"}
        for key in ("pid", "process_start_time", "executable_path", "executable_digest"):
            if current.get(key) != record.get(key):
                return {"status": "blocked", "reason": "worker_identity_mismatch", "field": key}
        try:
            current_pgid = os.getpgid(int(record["pid"]))
        except OSError:
            return {"status": "not_alive", "reason": "worker_not_alive"}
        if current_pgid != record.get("pgid"):
            return {"status": "blocked", "reason": "worker_process_group_mismatch"}
        return {"status": "ok", "reason": "worker_identity_verified", "record": record}

    def signal_verified_group(self, context_id: str, *, sig: signal.Signals) -> dict[str, Any]:
        verified = self.verify_live_identity(context_id)
        if verified.get("status") != "ok":
            return verified
        record = verified["record"]
        try:
            os.killpg(int(record["pgid"]), sig)
        except ProcessLookupError:
            return {"status": "not_alive", "reason": "worker_not_alive"}
        return {"status": "signaled", "signal": int(sig), "context_id": context_id}

    def reconcile_orphan(
        self,
        context_id: str,
        *,
        grace_seconds: float = 3.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        record = self.read(context_id)
        worker_nonce = str(record.get("worker_nonce") or "")
        if record.get("status") not in {"registered_waiting_barrier", "running"}:
            return {"status": "already_terminal", "context_id": context_id}
        verified = self.verify_live_identity(context_id)
        if verified.get("status") == "blocked":
            raise WorkerIdentityConflict(str(verified.get("reason") or "worker_identity_mismatch"))
        if verified.get("status") == "not_alive":
            self.mark_disappeared(context_id=context_id, worker_nonce=worker_nonce)
            return {"status": "disappeared", "context_id": context_id}
        signaled = self.signal_verified_group(context_id, sig=signal.SIGTERM)
        if signaled.get("status") not in {"signaled", "not_alive"}:
            raise WorkerIdentityConflict(str(signaled.get("reason") or "worker_identity_mismatch"))
        deadline = monotonic() + grace_seconds
        while monotonic() < deadline:
            if not _process_group_alive(int(record["pgid"])):
                self.mark_disappeared(context_id=context_id, worker_nonce=worker_nonce)
                return {"status": "terminated", "context_id": context_id, "signal": int(signal.SIGTERM)}
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        verified = self.verify_live_identity(context_id)
        if verified.get("status") != "ok":
            raise WorkerIdentityConflict(str(verified.get("reason") or "worker_identity_mismatch"))
        signaled = self.signal_verified_group(context_id, sig=signal.SIGKILL)
        if signaled.get("status") != "signaled":
            raise WorkerIdentityConflict(str(signaled.get("reason") or "worker_identity_mismatch"))
        deadline = monotonic() + grace_seconds
        while monotonic() < deadline:
            if not _process_group_alive(int(record["pgid"])):
                self.mark_disappeared(context_id=context_id, worker_nonce=worker_nonce)
                return {"status": "terminated", "context_id": context_id, "signal": int(signal.SIGKILL)}
            sleep(min(0.05, max(0.0, deadline - monotonic())))
        raise WorkerIdentityConflict("worker_termination_unverified")

    def read(self, context_id: str) -> dict[str, Any]:
        return self.ledger.read_record(self._path(context_id))

    @staticmethod
    def _path(context_id: str) -> str:
        if not _identifier(context_id):
            raise WorkerIdentityConflict("worker_context_id_invalid")
        return f"{WORKER_RECORD_PREFIX}{context_id}.json"


@dataclass(slots=True)
class QualificationLocalLockHandle:
    _coordinator: QualificationLocalLock
    file_descriptor: int
    owner_id: str
    owner_nonce: str
    parent_identity: dict[str, Any]
    local_fencing_token: int
    lease_version: int
    record_version: int
    _released: bool = False

    def renew(self, *, expected_lease_version: int, expected_fencing_token: int) -> dict[str, Any]:
        lease = self._coordinator._renew(
            owner_id=self.owner_id,
            owner_nonce=self.owner_nonce,
            expected_lease_version=expected_lease_version,
            expected_fencing_token=expected_fencing_token,
            expected_record_version=self.record_version,
        )
        self.lease_version = lease["lease_version"]
        self.record_version = lease["ledger_version"]
        return lease

    def delegated_capability(self) -> dict[str, Any]:
        return {
            "schema_version": LOCAL_LOCK_SCHEMA_VERSION,
            "protocol_version": LOCAL_LOCK_PROTOCOL_VERSION,
            "qualification_id": self._coordinator.paths.qualification_id,
            "owner_id": self.owner_id,
            "owner_nonce": self.owner_nonce,
            "parent_identity": dict(self.parent_identity),
            "local_fencing_token": self.local_fencing_token,
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


class QualificationLocalLock:
    def __init__(
        self,
        paths: QualificationPaths,
        ledger: ProductionQualificationLedger,
        *,
        process_port: ProcessPort | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_time: Callable[[], datetime] | None = None,
    ):
        self.paths = paths
        self.ledger = ledger
        self._process_port = process_port or SystemProcessPort()
        self._monotonic_ns = monotonic_ns
        self._wall_time = wall_time or (lambda: datetime.now(UTC))

    def acquire(
        self,
        *,
        owner_id: str,
        owner_nonce: str,
        takeover: bool = False,
    ) -> QualificationLocalLockHandle:
        if not _identifier(owner_id) or not _identifier(owner_nonce):
            raise ProductionLockConflict("qualification_owner_invalid")
        descriptor = os.open(self.paths.runner_lock, os.O_RDWR | os.O_CREAT, 0o600)
        os.set_inheritable(descriptor, False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise ProductionLockConflict("qualification_os_lock_held") from exc
        try:
            previous = self._read_lease_or_none()
            if previous and previous.get("status") == "active":
                if self._process_port.identity_is_alive(previous.get("parent_identity") or {}):
                    raise ProductionLockConflict("qualification_previous_parent_alive")
                if not takeover:
                    raise ProductionLockConflict("qualification_takeover_required")
            heartbeat = self._monotonic_ns()
            identity = current_process_identity()
            payload = {
                "schema_version": LOCAL_LOCK_SCHEMA_VERSION,
                "protocol_version": LOCAL_LOCK_PROTOCOL_VERSION,
                "qualification_id": self.paths.qualification_id,
                "status": "active",
                "owner_id": owner_id,
                "owner_nonce": owner_nonce,
                "parent_identity": identity,
                "fencing_token": int(previous.get("fencing_token", 0) if previous else 0) + 1,
                "lease_version": int(previous.get("lease_version", 0) if previous else 0) + 1,
                "boot_session_id": boot_session_id(),
                "heartbeat_monotonic_ns": heartbeat,
                "lease_expires_monotonic_ns": heartbeat + LEASE_SECONDS * 1_000_000_000,
                "acquired_at": _iso(self._wall_time()),
                "released_at": None,
            }
            if previous is None:
                lease = self.ledger.create_versioned(LOCAL_LEASE_PATH, payload)
            else:
                lease = self.ledger.compare_and_swap(
                    LOCAL_LEASE_PATH,
                    expected_version=previous["ledger_version"],
                    changes=payload,
                )
            return QualificationLocalLockHandle(
                _coordinator=self,
                file_descriptor=descriptor,
                owner_id=owner_id,
                owner_nonce=owner_nonce,
                parent_identity=identity,
                local_fencing_token=lease["fencing_token"],
                lease_version=lease["lease_version"],
                record_version=lease["ledger_version"],
            )
        except Exception:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            raise

    def validate_delegated_capability(self, capability: Mapping[str, Any]) -> dict[str, Any]:
        lease = self._read_lease_or_none()
        if not lease or lease.get("status") != "active":
            return _blocked("qualification_lease_inactive")
        if capability.get("qualification_id") != self.paths.qualification_id:
            return _blocked("qualification_scope_mismatch")
        if capability.get("local_fencing_token") != lease.get("fencing_token"):
            return _blocked("qualification_fencing_mismatch")
        if capability.get("owner_id") != lease.get("owner_id") or capability.get("owner_nonce") != lease.get("owner_nonce"):
            return _blocked("qualification_owner_mismatch")
        if capability.get("parent_identity") != lease.get("parent_identity"):
            return _blocked("qualification_parent_identity_mismatch")
        if capability.get("protocol_version") != LOCAL_LOCK_PROTOCOL_VERSION:
            return _blocked("qualification_lock_protocol_mismatch")
        capability_lease_version = capability.get("lease_version")
        current_lease_version = lease.get("lease_version")
        if (
            not isinstance(capability_lease_version, int)
            or isinstance(capability_lease_version, bool)
            or not isinstance(current_lease_version, int)
            or capability_lease_version < 1
            or capability_lease_version > current_lease_version
        ):
            return _blocked("qualification_lease_version_conflict")
        if lease.get("boot_session_id") != boot_session_id():
            return _blocked("qualification_boot_session_changed")
        if not self._process_port.identity_is_alive(lease.get("parent_identity") or {}):
            return _blocked("qualification_parent_dead")
        heartbeat = lease.get("heartbeat_monotonic_ns")
        if not isinstance(heartbeat, int) or isinstance(heartbeat, bool):
            return _blocked("qualification_heartbeat_invalid")
        age = self._monotonic_ns() - heartbeat
        if age < 0 or age > MAX_HEARTBEAT_AGE_SECONDS * 1_000_000_000:
            return _blocked("qualification_heartbeat_stale")
        return {
            "schema_version": LOCAL_LOCK_SCHEMA_VERSION,
            "status": "ok",
            "reason": "qualification_delegated_capability_valid",
            "local_fencing_token": lease["fencing_token"],
            "lease_version": lease["lease_version"],
        }

    def _renew(
        self,
        *,
        owner_id: str,
        owner_nonce: str,
        expected_lease_version: int,
        expected_fencing_token: int,
        expected_record_version: int,
    ) -> dict[str, Any]:
        lease = self._read_lease_or_none()
        if not lease or lease.get("status") != "active":
            raise ProductionLockConflict("qualification_lease_inactive")
        if lease.get("owner_id") != owner_id or lease.get("owner_nonce") != owner_nonce:
            raise ProductionLockConflict("qualification_owner_mismatch")
        if lease.get("fencing_token") != expected_fencing_token:
            raise ProductionLockConflict("qualification_fencing_mismatch")
        if lease.get("lease_version") != expected_lease_version:
            raise ProductionLockConflict("qualification_lease_version_conflict")
        heartbeat = self._monotonic_ns()
        try:
            return self.ledger.compare_and_swap(
                LOCAL_LEASE_PATH,
                expected_version=expected_record_version,
                changes={
                    "lease_version": expected_lease_version + 1,
                    "heartbeat_monotonic_ns": heartbeat,
                    "lease_expires_monotonic_ns": heartbeat + LEASE_SECONDS * 1_000_000_000,
                },
            )
        except LedgerConflict as exc:
            raise ProductionLockConflict("qualification_lease_cas_conflict") from exc

    def _release(self, handle: QualificationLocalLockHandle) -> None:
        try:
            lease = self._read_lease_or_none()
            if (
                lease
                and lease.get("status") == "active"
                and lease.get("owner_id") == handle.owner_id
                and lease.get("owner_nonce") == handle.owner_nonce
                and lease.get("fencing_token") == handle.local_fencing_token
            ):
                try:
                    self.ledger.compare_and_swap(
                        LOCAL_LEASE_PATH,
                        expected_version=lease["ledger_version"],
                        changes={
                            "status": "released",
                            "lease_version": int(lease["lease_version"]) + 1,
                            "released_at": _iso(self._wall_time()),
                        },
                    )
                except LedgerConflict as exc:
                    raise ProductionLockConflict("qualification_release_cas_conflict") from exc
        finally:
            if handle.file_descriptor >= 0:
                fcntl.flock(handle.file_descriptor, fcntl.LOCK_UN)
                os.close(handle.file_descriptor)
                handle.file_descriptor = -1

    def _read_lease_or_none(self) -> dict[str, Any] | None:
        try:
            return self.ledger.read_record(LOCAL_LEASE_PATH)
        except FileNotFoundError:
            return None


@dataclass(slots=True)
class ProductionLockSetHandle:
    local: QualificationLocalLockHandle
    runtime: RuntimeLockHandle
    _released: bool = False

    def delegated_capability(self) -> dict[str, Any]:
        local = self.local.delegated_capability()
        runtime = self.runtime.delegated_capability()
        return {
            "schema_version": 1,
            "qualification_id": local["qualification_id"],
            "owner_id": local["owner_id"],
            "owner_nonce": local["owner_nonce"],
            "local_fencing_token": local["local_fencing_token"],
            "runtime_fencing_token": runtime["runtime_fencing_token"],
            "local_capability": local,
            "runtime_capability": runtime,
        }

    def release(self) -> None:
        if self._released:
            return
        try:
            self.runtime.release()
        finally:
            self.local.release()
            self._released = True

    def __enter__(self) -> ProductionLockSetHandle:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


class ProductionLockSet:
    def __init__(
        self,
        paths: QualificationPaths,
        *,
        runtime_lock: GuiRuntimeLock | None = None,
        process_port: ProcessPort | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ):
        self.paths = paths
        self.ledger = ProductionQualificationLedger(paths.data_dir)
        self.local_lock = QualificationLocalLock(
            paths,
            self.ledger,
            process_port=process_port,
            monotonic_ns=monotonic_ns,
        )
        self.runtime_lock = runtime_lock or GuiRuntimeLock(process_port=process_port, monotonic_ns=monotonic_ns)

    def acquire(self, *, owner_id: str, owner_nonce: str, takeover: bool = False) -> ProductionLockSetHandle:
        local = self.local_lock.acquire(owner_id=owner_id, owner_nonce=owner_nonce, takeover=takeover)
        try:
            runtime = self.runtime_lock.acquire(owner_id=owner_id, owner_nonce=owner_nonce, takeover=takeover)
        except Exception:
            local.release()
            raise
        return ProductionLockSetHandle(local=local, runtime=runtime)

    def validate_delegated_capability(self, capability: Mapping[str, Any]) -> dict[str, Any]:
        local_raw = capability.get("local_capability")
        runtime_raw = capability.get("runtime_capability")
        if not isinstance(local_raw, Mapping) or not isinstance(runtime_raw, Mapping):
            return _blocked("dual_lock_capability_missing")
        if capability.get("local_fencing_token") != local_raw.get("local_fencing_token"):
            return _blocked("qualification_fencing_mismatch")
        if capability.get("runtime_fencing_token") != runtime_raw.get("runtime_fencing_token"):
            return _blocked("runtime_fencing_mismatch")
        local_result = self.local_lock.validate_delegated_capability(local_raw)
        if local_result.get("status") != "ok":
            return local_result
        runtime_result = self.runtime_lock.validate_delegated_capability(runtime_raw)
        if runtime_result.get("status") != "ok":
            return runtime_result
        return {
            "schema_version": 1,
            "status": "ok",
            "reason": "dual_fencing_capability_valid",
            "local_fencing_token": local_result["local_fencing_token"],
            "runtime_fencing_token": runtime_result["runtime_fencing_token"],
            "runtime_lock_protocol_version": GUI_RUNTIME_LOCK_PROTOCOL_VERSION,
        }


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value


def _positive_process_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
