from __future__ import annotations

import hashlib
import json
import errno
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, Mapping, Protocol, Sequence

from dating_boost.core.live_send_contract import live_send_authorization_quiet_hours_block_reason
from dating_boost.core.storage import JsonStorage

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses the process-local lease.
    fcntl = None  # type: ignore[assignment]


MANAGED_RUN_SCHEMA_VERSION = 1
MANAGED_RUN_INDEX_PATH = Path("managed_run") / "index.json"
MANAGED_RUN_EVENTS_PATH = Path("audit") / "managed_run_events.jsonl"

ACTIVE_RUN_STATUSES = {"active", "paused"}
TERMINAL_SEND_STATUSES = {"confirmed", "failed_before_click", "unknown_after_click"}
MANAGED_RUN_RECENT_STEP_LIMIT = 100
MANAGED_NUDGE_FALLBACK_RETRY_SECONDS = 30 * 60

_LEASE_REGISTRY_GUARD = threading.Lock()
_LEASE_LOCKS: dict[Path, threading.Lock] = {}
_STATE_LEASE_LOCKS: dict[Path, threading.RLock] = {}
_STATE_LEASE_LOCAL = threading.local()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ManagedAuthorization:
    authorization_id: str
    app_id: str
    scope: str = "send_chat_messages"
    allowed_actions: tuple[str, ...] = ("send_message",)
    allowed_target_ids: tuple[str, ...] = ()
    allow_all_targets: bool = False
    runtime: str | None = None
    autonomous_send: bool = True
    autonomous_nudge: bool = False
    live_send: bool = True
    requires_post_action_verification: bool = True
    revoked: bool = False
    expires_at: str | None = None
    quiet_hours: tuple[Any, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ManagedAuthorization:
        allowed_targets = payload.get("allowed_target_ids", payload.get("allowed_match_ids", ()))
        return cls(
            authorization_id=str(payload.get("authorization_id") or "").strip(),
            app_id=str(payload.get("app_id") or "").strip(),
            scope=str(payload.get("scope") or "").strip(),
            allowed_actions=tuple(str(item) for item in payload.get("allowed_actions", ("send_message",))),
            allowed_target_ids=tuple(str(item) for item in allowed_targets or ()),
            allow_all_targets=bool(payload.get("allow_all_targets", False)),
            runtime=str(payload["runtime"]).strip() if payload.get("runtime") else None,
            autonomous_send=payload.get("autonomous_send") is True,
            autonomous_nudge=payload.get("autonomous_nudge") is True,
            live_send=bool(payload.get("live_send", False)),
            requires_post_action_verification=payload.get("requires_post_action_verification") is True,
            revoked=payload.get("revoked_at") is not None or bool(payload.get("revoked", False)),
            expires_at=str(payload["expires_at"]) if payload.get("expires_at") else None,
            quiet_hours=tuple(payload.get("quiet_hours") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "app_id": self.app_id,
            "scope": self.scope,
            "allowed_actions": list(self.allowed_actions),
            "allowed_target_ids": list(self.allowed_target_ids),
            "allow_all_targets": self.allow_all_targets,
            "runtime": self.runtime,
            "autonomous_send": self.autonomous_send,
            "autonomous_nudge": self.autonomous_nudge,
            "live_send": self.live_send,
            "requires_post_action_verification": self.requires_post_action_verification,
            "revoked": self.revoked,
            "expires_at": self.expires_at,
            "quiet_hours": [dict(item) if isinstance(item, Mapping) else item for item in self.quiet_hours],
        }

    def session_block_reason(self, *, app_id: str, runtime: str, now: datetime) -> str | None:
        if not self.authorization_id:
            return "authorization_id_missing"
        if self.scope != "send_chat_messages":
            return "authorization_scope_not_send_chat_messages"
        if self.revoked:
            return "authorization_revoked"
        if self.expires_at is not None:
            try:
                if now >= _parse_iso(self.expires_at):
                    return "authorization_expired"
            except ValueError:
                return "authorization_expiry_invalid"
        if not self.autonomous_send:
            return "autonomous_send_not_authorized"
        if not self.live_send:
            return "live_send_not_authorized"
        if not self.requires_post_action_verification:
            return "post_action_verification_required"
        if self.app_id != app_id:
            return "authorization_app_mismatch"
        if self.runtime is not None and self.runtime != runtime:
            return "authorization_runtime_mismatch"
        if _quiet_hours_active(self.quiet_hours, now):
            return "authorization_quiet_hours"
        return None

    def block_reason(
        self,
        *,
        app_id: str,
        runtime: str,
        target_id: str,
        action: str,
        now: datetime,
    ) -> str | None:
        session_reason = self.session_block_reason(app_id=app_id, runtime=runtime, now=now)
        if session_reason is not None:
            return session_reason
        if action not in self.allowed_actions:
            return "action_not_authorized"
        if not self.allow_all_targets and target_id not in self.allowed_target_ids:
            return "target_not_authorized"
        return None


@dataclass(frozen=True)
class ManagedRunConfig:
    app_id: str
    runtime: str
    authorization: ManagedAuthorization
    scan_cursor: dict[str, Any] = field(default_factory=dict)
    duration_minutes: int = 120
    nudge_enabled: bool = False
    management_mode: str = "conservative"
    max_sends_per_run: int = 100

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ManagedRunConfig:
        authorization = payload.get("authorization")
        if isinstance(authorization, ManagedAuthorization):
            normalized_authorization = authorization
        elif isinstance(authorization, Mapping):
            normalized_authorization = ManagedAuthorization.from_dict(authorization)
        else:
            raise ValueError("authorization must be provided")
        cursor = payload.get("scan_cursor") or {}
        if not isinstance(cursor, dict):
            raise ValueError("scan_cursor must be an object")
        return cls(
            app_id=str(payload.get("app_id") or "").strip(),
            runtime=str(payload.get("runtime") or "").strip(),
            authorization=normalized_authorization,
            scan_cursor=dict(cursor),
            duration_minutes=max(1, int(payload.get("duration_minutes") or 120)),
            nudge_enabled=bool(payload.get("nudge_enabled", False)),
            management_mode=str(payload.get("management_mode") or "conservative"),
            max_sends_per_run=max(1, int(payload.get("max_sends_per_run") or 100)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "runtime": self.runtime,
            "authorization": self.authorization.to_dict(),
            "scan_cursor": dict(self.scan_cursor),
            "duration_minutes": self.duration_minutes,
            "nudge_enabled": self.nudge_enabled,
            "management_mode": self.management_mode,
            "max_sends_per_run": self.max_sends_per_run,
        }


@dataclass(frozen=True)
class ThreadCandidate:
    """A list-row hint, promoted with an authoritative revision after open."""

    candidate_key: str
    target_id: str
    target_binding: str
    discovery_revision: str
    inbound_revision: str | None = None
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MessageListSnapshot:
    candidates: tuple[ThreadCandidate, ...]
    captured_at: str
    next_cursor: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenThreadObservation:
    target_id: str
    target_binding: str
    captured_at: str


@dataclass(frozen=True)
class ThreadObservation:
    target_id: str
    target_binding: str
    inbound_revision: str
    captured_at: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DraftDecision:
    decision_id: str
    outcome: str
    target_id: str
    inbound_revision: str
    text: str = ""
    payload_hash: str = ""
    action: str = "send_message"
    reason_codes: tuple[str, ...] = ()

    @classmethod
    def send(
        cls,
        *,
        decision_id: str,
        target_id: str,
        inbound_revision: str,
        text: str,
        reason_codes: Sequence[str] = (),
    ) -> DraftDecision:
        return cls(
            decision_id=decision_id,
            outcome="send",
            target_id=target_id,
            inbound_revision=inbound_revision,
            text=text,
            payload_hash=_payload_hash(text),
            reason_codes=tuple(reason_codes),
        )


@dataclass(frozen=True)
class ComposerObservation:
    target_id: str
    target_binding: str
    inbound_revision: str
    text: str
    captured_at: str


@dataclass(frozen=True)
class ClickReceipt:
    receipt_id: str
    clicked_at: str


@dataclass(frozen=True)
class PostSendObservation:
    observation_id: str
    receipt_id: str
    target_id: str
    target_binding: str
    captured_at: str
    input_cleared: bool
    outbound_text: str | None


class ManagedObservationPort(Protocol):
    def scan_message_list(
        self,
        *,
        run_id: str,
        app_id: str,
        runtime: str,
        cursor: dict[str, Any],
    ) -> MessageListSnapshot:
        raise NotImplementedError

    def open_thread(self, candidate: ThreadCandidate) -> OpenThreadObservation:
        raise NotImplementedError

    def observe_thread(self, candidate: ThreadCandidate) -> ThreadObservation:
        raise NotImplementedError


class ManagedDecisionPort(Protocol):
    def prioritize(
        self,
        candidates: Sequence[ThreadCandidate],
        *,
        thread_states: Mapping[str, dict[str, Any]],
    ) -> ThreadCandidate | None:
        raise NotImplementedError

    def decide(self, observation: ThreadObservation, *, config: ManagedRunConfig) -> DraftDecision:
        raise NotImplementedError


class ManagedActionPort(Protocol):
    def observe_composer(self, candidate: ThreadCandidate) -> ComposerObservation:
        raise NotImplementedError

    def stage_text(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        raise NotImplementedError

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        raise NotImplementedError

    def observe_post_send(
        self,
        candidate: ThreadCandidate,
        receipt: ClickReceipt,
    ) -> PostSendObservation:
        raise NotImplementedError


@dataclass
class ManagedRunRecord:
    run_id: str
    config: ManagedRunConfig
    status: str
    started_at: str
    updated_at: str
    pause_reason: str | None = None
    stop_reason: str | None = None
    scan_cursor: dict[str, Any] = field(default_factory=dict)
    cycle_count: int = 0
    attempted_send_count: int = 0
    confirmed_send_count: int = 0
    thread_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    send_attempts: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MANAGED_RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "config": self.config.to_dict(),
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "pause_reason": self.pause_reason,
            "stop_reason": self.stop_reason,
            "scan_cursor": dict(self.scan_cursor),
            "cycle_count": self.cycle_count,
            "attempted_send_count": self.attempted_send_count,
            "confirmed_send_count": self.confirmed_send_count,
            "thread_states": {key: dict(value) for key, value in self.thread_states.items()},
            "send_attempts": {key: dict(value) for key, value in self.send_attempts.items()},
            "last_result": dict(self.last_result) if self.last_result is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ManagedRunRecord:
        if payload.get("schema_version") != MANAGED_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported managed run schema_version")
        return cls(
            run_id=str(payload["run_id"]),
            config=ManagedRunConfig.from_dict(payload["config"]),
            status=str(payload["status"]),
            started_at=str(payload["started_at"]),
            updated_at=str(payload["updated_at"]),
            pause_reason=str(payload["pause_reason"]) if payload.get("pause_reason") else None,
            stop_reason=str(payload["stop_reason"]) if payload.get("stop_reason") else None,
            scan_cursor=dict(payload.get("scan_cursor") or {}),
            cycle_count=int(payload.get("cycle_count") or 0),
            attempted_send_count=int(payload.get("attempted_send_count") or payload.get("confirmed_send_count") or 0),
            confirmed_send_count=int(payload.get("confirmed_send_count") or 0),
            thread_states={str(key): dict(value) for key, value in dict(payload.get("thread_states") or {}).items()},
            send_attempts={str(key): dict(value) for key, value in dict(payload.get("send_attempts") or {}).items()},
            last_result=dict(payload["last_result"]) if isinstance(payload.get("last_result"), dict) else None,
        )


class ManagedRunStore(Protocol):
    def create(self, record: ManagedRunRecord) -> None:
        raise NotImplementedError

    def load(self, run_id: str) -> ManagedRunRecord | None:
        raise NotImplementedError

    def save(self, record: ManagedRunRecord) -> None:
        raise NotImplementedError

    def current_run_id(self) -> str | None:
        raise NotImplementedError

    def append_event(self, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def events(self, run_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def execution_lease(self, run_id: str) -> ContextManager[bool]:
        raise NotImplementedError

    def state_lease(self, run_id: str) -> ContextManager[bool]:
        """Serialize lifecycle changes with durable send-state mutations."""
        raise NotImplementedError


class InMemoryManagedRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._current_run_id: str | None = None
        self._events: list[dict[str, Any]] = []
        self._lease_guard = threading.Lock()
        self._lease_locks: dict[str, threading.Lock] = {}
        self._state_locks: dict[str, threading.RLock] = {}

    def create(self, record: ManagedRunRecord) -> None:
        if record.run_id in self._runs:
            raise ValueError(f"managed run already exists: {record.run_id}")
        self._runs[record.run_id] = record.to_dict()
        self._current_run_id = record.run_id

    def load(self, run_id: str) -> ManagedRunRecord | None:
        payload = self._runs.get(run_id)
        return ManagedRunRecord.from_dict(payload) if payload is not None else None

    def save(self, record: ManagedRunRecord) -> None:
        if record.run_id not in self._runs:
            raise FileNotFoundError(record.run_id)
        self._runs[record.run_id] = record.to_dict()

    def current_run_id(self) -> str | None:
        return self._current_run_id

    def append_event(self, event: dict[str, Any]) -> None:
        self._events.append(dict(event))

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(event) for event in self._events if event.get("run_id") == run_id]

    @contextmanager
    def execution_lease(self, run_id: str) -> Iterator[bool]:
        with self._lease_guard:
            lease = self._lease_locks.setdefault(run_id, threading.Lock())
        acquired = lease.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lease.release()

    @contextmanager
    def state_lease(self, run_id: str) -> Iterator[bool]:
        with self._lease_guard:
            lease = self._state_locks.setdefault(run_id, threading.RLock())
        lease.acquire()
        try:
            yield True
        finally:
            lease.release()


class JsonManagedRunStore:
    """Durable managed-run state stored as one atomic run document.

    Thread state and send checkpoints live in that document. The JSONL stream is
    diagnostic only and is never used to decide whether a send may be retried.
    """

    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def create(self, record: ManagedRunRecord) -> None:
        path = self._run_path(record.run_id)
        if self._storage.exists(path):
            raise ValueError(f"managed run already exists: {record.run_id}")
        previous_current_run_id = self.current_run_id()
        # Publish the pointer first. A process death between these writes leaves
        # a recoverable missing pointer target, never an unindexed active run
        # that can execute alongside a later current run.
        self._storage.write_json(
            MANAGED_RUN_INDEX_PATH,
            {"schema_version": MANAGED_RUN_SCHEMA_VERSION, "current_run_id": record.run_id},
        )
        try:
            self._storage.write_json(path, record.to_dict())
        except Exception:
            # Ordinary write failures restore a usable index. A hard process
            # death is recovered by ManagedRun.start when the target is absent.
            self._storage.write_json(
                MANAGED_RUN_INDEX_PATH,
                {
                    "schema_version": MANAGED_RUN_SCHEMA_VERSION,
                    "current_run_id": previous_current_run_id,
                },
            )
            raise

    def load(self, run_id: str) -> ManagedRunRecord | None:
        try:
            payload = self._storage.read_json(
                self._run_path(run_id),
                expected_schema_version=MANAGED_RUN_SCHEMA_VERSION,
            )
        except FileNotFoundError:
            return None
        return ManagedRunRecord.from_dict(payload)

    def save(self, record: ManagedRunRecord) -> None:
        path = self._run_path(record.run_id)
        if not self._storage.exists(path):
            raise FileNotFoundError(record.run_id)
        self._storage.write_json(path, record.to_dict())

    def current_run_id(self) -> str | None:
        try:
            payload = self._storage.read_json(
                MANAGED_RUN_INDEX_PATH,
                expected_schema_version=MANAGED_RUN_SCHEMA_VERSION,
            )
        except FileNotFoundError:
            return None
        run_id = payload.get("current_run_id")
        return str(run_id) if run_id else None

    def append_event(self, event: dict[str, Any]) -> None:
        self._storage.append_jsonl(MANAGED_RUN_EVENTS_PATH, event)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [event for event in self._storage.read_jsonl(MANAGED_RUN_EVENTS_PATH) if event.get("run_id") == run_id]

    @contextmanager
    def execution_lease(self, run_id: str) -> Iterator[bool]:
        lock_path = self._lease_path(run_id)
        with _LEASE_REGISTRY_GUARD:
            process_lease = _LEASE_LOCKS.setdefault(lock_path, threading.Lock())
        acquired_in_process = process_lease.acquire(blocking=False)
        if not acquired_in_process:
            yield False
            return

        descriptor = -1
        file_lease_acquired = False
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.fchmod(descriptor, 0o600)
            if fcntl is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    file_lease_acquired = True
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    yield False
                    return
            yield True
        finally:
            if descriptor >= 0:
                if file_lease_acquired and fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            process_lease.release()

    @contextmanager
    def state_lease(self, run_id: str) -> Iterator[bool]:
        lock_path = self._state_lease_path(run_id)
        held_paths = getattr(_STATE_LEASE_LOCAL, "held_paths", set())
        if lock_path in held_paths:
            yield True
            return

        with _LEASE_REGISTRY_GUARD:
            process_lease = _STATE_LEASE_LOCKS.setdefault(lock_path, threading.RLock())
        process_lease.acquire()
        descriptor = -1
        file_lease_acquired = False
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.fchmod(descriptor, 0o600)
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                file_lease_acquired = True
            held_paths = set(held_paths)
            held_paths.add(lock_path)
            _STATE_LEASE_LOCAL.held_paths = held_paths
            yield True
        finally:
            held_paths = set(getattr(_STATE_LEASE_LOCAL, "held_paths", set()))
            held_paths.discard(lock_path)
            _STATE_LEASE_LOCAL.held_paths = held_paths
            if descriptor >= 0:
                if file_lease_acquired and fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            process_lease.release()

    @staticmethod
    def _run_path(run_id: str) -> Path:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return Path("managed_run") / "runs" / f"{digest}.json"

    def _lease_path(self, run_id: str) -> Path:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return self._storage.root / "managed_run" / "locks" / f"{digest}.lock"

    def _state_lease_path(self, run_id: str) -> Path:
        digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        return self._storage.root / "managed_run" / "locks" / f"{digest}.state.lock"


class ManagedRun:
    """One in-process full-managed loop with one durable source of truth."""

    def __init__(
        self,
        store: ManagedRunStore,
        observation: ManagedObservationPort,
        decision: ManagedDecisionPort,
        action: ManagedActionPort,
        *,
        now: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.store = store
        self.observation = observation
        self.decision = decision
        self.action = action
        self._now = now or _now_utc
        self._sleep = sleeper or time.sleep

    def start(self, config: ManagedRunConfig | Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        if not isinstance(config, ManagedRunConfig):
            config = ManagedRunConfig.from_dict(config)
        reason = self._config_block_reason(config)
        if reason is not None:
            return _result("blocked", reason=reason)
        session_reason = config.authorization.session_block_reason(
            app_id=config.app_id,
            runtime=config.runtime,
            now=self._now(),
        )
        if session_reason not in {None, "authorization_quiet_hours"}:
            return _result("blocked", reason=session_reason)
        with self.store.execution_lease("__managed_run_start__") as acquired:
            if not acquired:
                return _result("blocked", reason="managed_run_busy")
            current_id = self.store.current_run_id()
            current = self.store.load(current_id) if current_id else None
            if current is not None:
                self._reconcile_unfinished_click(current)
                current = self.store.load(current.run_id) or current
            if current is not None and current.status in ACTIVE_RUN_STATUSES:
                return _result("blocked", reason="managed_run_already_active", run_id=current.run_id)
            normalized_run_id = run_id or f"managed_{uuid.uuid4().hex}"
            now = _iso(self._now())
            record = ManagedRunRecord(
                run_id=normalized_run_id,
                config=config,
                status="active",
                started_at=now,
                updated_at=now,
                scan_cursor=dict(config.scan_cursor),
                thread_states=_inherited_unknown_thread_states(current),
            )
            self.store.create(record)
            self._event(record, "run_started")
        return _result(
            "active",
            run_id=record.run_id,
            run=record.to_dict(),
            relationship_progress_snapshot=_progress_snapshot(record),
        )

    def status(self, run_id: str | None = None) -> dict[str, Any]:
        record = self._resolve_record(run_id)
        if record is None:
            return _result("not_found", reason="managed_run_not_started")
        return _result(
            record.status,
            run_id=record.run_id,
            run=record.to_dict(),
            relationship_progress_snapshot=_progress_snapshot(record),
        )

    def current_run_id(self) -> str | None:
        return self.store.current_run_id()

    def pause(self, run_id: str | None = None, *, reason: str = "manual_pause") -> dict[str, Any]:
        normalized_run_id = run_id or self.store.current_run_id()
        if normalized_run_id is None:
            return _result("not_found", reason="managed_run_not_started")
        with self.store.state_lease(normalized_run_id):
            record = self.store.load(normalized_run_id)
            if record is None:
                return _result("not_found", reason="managed_run_not_started")
            if record.status == "stopped":
                return _result("stopped", reason=record.stop_reason or "managed_run_stopped", run_id=record.run_id)
            record.status = "paused"
            record.pause_reason = reason
            record.updated_at = _iso(self._now())
            self.store.save(record)
        self._event(record, "run_paused", reason=reason)
        return _result(
            "paused",
            reason=reason,
            run_id=record.run_id,
            run=record.to_dict(),
            relationship_progress_snapshot=_progress_snapshot(record),
        )

    def resume(self, run_id: str | None = None) -> dict[str, Any]:
        normalized_run_id = run_id or self.store.current_run_id()
        if normalized_run_id is None:
            return _result("not_found", reason="managed_run_not_started")
        with self.store.execution_lease("__managed_run_start__") as acquired:
            if not acquired:
                return _result("blocked", reason="managed_run_busy", run_id=normalized_run_id)
            current_id = self.store.current_run_id()
            if current_id and current_id != normalized_run_id:
                current = self.store.load(current_id)
                if current is not None and current.status in ACTIVE_RUN_STATUSES:
                    return _result("blocked", reason="managed_run_already_active", run_id=current.run_id)
            with self.store.state_lease(normalized_run_id):
                record = self.store.load(normalized_run_id)
                if record is None:
                    return _result("not_found", reason="managed_run_not_started")
                if record.status == "stopped":
                    return _result("stopped", reason=record.stop_reason or "managed_run_stopped", run_id=record.run_id)
                record.status = "active"
                record.pause_reason = None
                record.updated_at = _iso(self._now())
                self.store.save(record)
        self._event(record, "run_resumed")
        return _result(
            "active",
            run_id=record.run_id,
            run=record.to_dict(),
            relationship_progress_snapshot=_progress_snapshot(record),
        )

    def stop(self, run_id: str | None = None, *, reason: str = "manual_stop") -> dict[str, Any]:
        normalized_run_id = run_id or self.store.current_run_id()
        if normalized_run_id is None:
            return _result("stopped", reason=reason)
        with self.store.state_lease(normalized_run_id):
            record = self.store.load(normalized_run_id)
            if record is None:
                return _result("stopped", reason=reason)
            record.status = "stopped"
            record.stop_reason = reason
            record.pause_reason = None
            record.updated_at = _iso(self._now())
            self.store.save(record)
        self._event(record, "run_stopped", reason=reason)
        return _result(
            "stopped",
            reason=reason,
            run_id=record.run_id,
            run=record.to_dict(),
            relationship_progress_snapshot=_progress_snapshot(record),
            relationship_progress_report=_progress_report(record),
        )

    def run(
        self,
        run_id: str | None = None,
        *,
        max_steps: int = 50,
        wait: bool = False,
        poll_interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        if wait:
            return self._run_wait_loop(
                run_id,
                max_steps=max_steps,
                poll_interval_seconds=poll_interval_seconds,
            )
        results: list[dict[str, Any]] = []
        normalized_run_id = run_id or self.store.current_run_id()
        for _ in range(max(1, int(max_steps))):
            result = self.tick(normalized_run_id)
            results.append(result)
            if (
                result.get("status") == "no_work"
                and result.get("reason") == "inbound_revision_already_processed"
            ):
                continue
            if result.get("status") in {
                "no_work",
                "wait",
                "handoff",
                "paused",
                "stopped",
                "blocked",
                "not_found",
                "unknown_after_click",
            }:
                break
        final = results[-1]
        return {
            **final,
            "processed_count": sum(1 for item in results if item.get("status") in TERMINAL_SEND_STATUSES),
            "steps": results,
        }

    def _run_wait_loop(
        self,
        run_id: str | None,
        *,
        max_steps: int,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        if max_steps < 1:
            raise ValueError("max_steps_must_be_positive")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds_must_be_positive")
        normalized_run_id = run_id or self.store.current_run_id()
        # `max_steps` caps retained diagnostics, not the duration of a wait
        # run. A two-hour session should not accumulate thousands of idle
        # payloads in memory or print them all at shutdown.
        results: deque[dict[str, Any]] = deque(maxlen=MANAGED_RUN_RECENT_STEP_LIMIT)
        processed_count = 0
        poll_count = 0
        while True:
            result = self.tick(normalized_run_id)
            results.append(result)
            status = str(result.get("status") or "")
            reason = str(result.get("reason") or "")
            if status == "no_work":
                if reason == "send_budget_exhausted":
                    break
                if reason == "inbound_revision_already_processed":
                    # The latest discovery hint was just consumed and stored;
                    # immediately rescan so another visible candidate is not
                    # delayed by the normal idle poll interval.
                    continue
                poll_count += 1
                interrupted = self._wait_sleep_result(
                    normalized_run_id,
                    poll_interval_seconds,
                )
                if interrupted is not None:
                    results.append(interrupted)
                    break
                continue
            if status == "wait":
                poll_count += 1
                interrupted = self._wait_sleep_result(
                    normalized_run_id,
                    poll_interval_seconds,
                )
                if interrupted is not None:
                    results.append(interrupted)
                    break
                continue
            if status in TERMINAL_SEND_STATUSES:
                processed_count += 1
            if status in {"paused", "stopped", "blocked", "not_found", "unknown_after_click"}:
                break
        final = results[-1]
        return {
            **final,
            "processed_count": processed_count,
            "poll_count": poll_count,
            "wait": True,
            "poll_interval_seconds": poll_interval_seconds,
            "steps": list(results),
        }

    def _wait_sleep_result(
        self,
        run_id: str | None,
        poll_interval_seconds: float,
    ) -> dict[str, Any] | None:
        try:
            self._sleep(poll_interval_seconds)
        except KeyboardInterrupt:
            return self.pause(run_id, reason="managed_run_interrupted")
        except Exception as exc:  # noqa: BLE001 - an unusable wait loop must not remain active.
            return {
                **self.pause(run_id, reason="managed_run_wait_sleep_failed"),
                "error_type": type(exc).__name__,
            }
        return None

    def tick(self, run_id: str | None = None) -> dict[str, Any]:
        normalized_run_id = run_id or self.store.current_run_id()
        if normalized_run_id is None:
            return _result("not_found", reason="managed_run_not_started")
        with self.store.execution_lease(normalized_run_id) as acquired:
            if not acquired:
                return _result(
                    "blocked",
                    reason="managed_run_busy",
                    run_id=normalized_run_id,
                )
            return self._tick_with_lease(normalized_run_id)

    def _tick_with_lease(self, run_id: str) -> dict[str, Any]:
        record = self.store.load(run_id)
        if record is None:
            return _result("not_found", reason="managed_run_not_started")
        unfinished_click = self._reconcile_unfinished_click(record)
        if unfinished_click is not None:
            return unfinished_click
        if record.status != "active":
            return _result(
                record.status,
                reason=record.pause_reason or record.stop_reason or "managed_run_not_active",
                run_id=record.run_id,
            )
        elapsed_seconds = (self._now() - _parse_iso(record.started_at)).total_seconds()
        if elapsed_seconds >= record.config.duration_minutes * 60:
            return self.stop(record.run_id, reason="managed_run_duration_elapsed")
        authorization_reason = record.config.authorization.session_block_reason(
            app_id=record.config.app_id,
            runtime=record.config.runtime,
            now=self._now(),
        )
        if authorization_reason == "authorization_quiet_hours":
            return self._finish_tick(record, "no_work", reason=authorization_reason)
        if authorization_reason is not None:
            return self.stop(record.run_id, reason=authorization_reason)
        if record.attempted_send_count >= record.config.max_sends_per_run:
            return self.stop(record.run_id, reason="send_budget_exhausted")

        try:
            with self.store.state_lease(record.run_id):
                latest_before_scan = self.store.load(record.run_id) or record
                if latest_before_scan.status != "active":
                    return _result(
                        latest_before_scan.status,
                        reason=latest_before_scan.pause_reason
                        or latest_before_scan.stop_reason
                        or "managed_run_not_active",
                        run_id=latest_before_scan.run_id,
                    )
                snapshot = self.observation.scan_message_list(
                    run_id=latest_before_scan.run_id,
                    app_id=latest_before_scan.config.app_id,
                    runtime=latest_before_scan.config.runtime,
                    cursor=dict(latest_before_scan.scan_cursor),
                )
                latest_before_scan.scan_cursor = dict(snapshot.next_cursor)
                latest_before_scan.cycle_count += 1
                latest_before_scan.updated_at = _iso(self._now())
                self.store.save(latest_before_scan)
                record = latest_before_scan
        except Exception as exc:  # noqa: BLE001 - a port failure is a managed wait point.
            return self._finish_tick(record, "blocked", reason="message_list_observation_failed", error_type=type(exc).__name__)

        eligible = self._eligible_candidates(record, snapshot.candidates)
        try:
            candidate = self.decision.prioritize(eligible, thread_states=record.thread_states)
        except Exception as exc:  # noqa: BLE001 - a decision-port failure ends this runner.
            return self._finish_tick(
                record,
                "blocked",
                reason="candidate_prioritization_failed",
                error_type=type(exc).__name__,
            )
        if candidate is None:
            return self._finish_tick(record, "no_work", reason="no_eligible_thread")
        if candidate not in eligible:
            return self._finish_tick(record, "blocked", reason="prioritizer_returned_ineligible_thread")

        try:
            with self.store.state_lease(record.run_id):
                latest_before_open = self.store.load(record.run_id) or record
                if latest_before_open.status != "active":
                    return _result(
                        latest_before_open.status,
                        reason=latest_before_open.pause_reason
                        or latest_before_open.stop_reason
                        or "managed_run_not_active",
                        run_id=latest_before_open.run_id,
                    )
                opened = self.observation.open_thread(candidate)
        except Exception as exc:  # noqa: BLE001
            return self._finish_tick(record, "blocked", reason="open_thread_failed", error_type=type(exc).__name__)
        target_reason = _target_evidence_block_reason(candidate, opened.target_id, opened.target_binding)
        if target_reason is not None:
            return self._finish_candidate_tick(record, candidate, reason=target_reason)

        try:
            thread = self.observation.observe_thread(candidate)
        except Exception as exc:  # noqa: BLE001
            return self._finish_tick(record, "blocked", reason="thread_observation_failed", error_type=type(exc).__name__)
        target_reason = _target_evidence_block_reason(candidate, thread.target_id, thread.target_binding)
        if target_reason is not None:
            return self._finish_candidate_tick(record, candidate, reason=target_reason)
        # Message-list text is commonly truncated.  Its hash is only a hint that
        # tells us which row may deserve inspection; the fresh thread
        # observation owns the authoritative inbound revision used by every
        # decision, action and durable deduplication key below this boundary.
        candidate = replace(candidate, inbound_revision=thread.inbound_revision)
        if candidate not in self._eligible_candidates(record, (candidate,)):
            return self._finish_authoritative_duplicate(record, candidate)

        transaction = SendTransaction(
            store=self.store,
            action=self.action,
            now=self._now,
        )
        decision = transaction.prepared_decision(record, candidate, thread)
        if decision is None:
            try:
                decision = self.decision.decide(thread, config=record.config)
            except Exception as exc:  # noqa: BLE001
                return self._finish_tick(record, "blocked", reason="draft_decision_failed", error_type=type(exc).__name__)
        decision_reason = _decision_block_reason(decision, thread)
        if decision_reason is not None:
            return self._finish_candidate_tick(
                record,
                candidate,
                reason=decision_reason,
                decision_id=decision.decision_id,
            )
        if decision.outcome != "send":
            return self._record_non_send_decision(record, candidate, thread, decision)

        result = transaction.execute(record, candidate, thread, decision)
        latest = self.store.load(record.run_id) or record
        state = latest.thread_states.get(candidate.target_id)
        self._event(latest, "send_transaction_finished", **_event_result_fields(result))
        payload = {**result, "run_id": latest.run_id}
        if state is not None:
            payload["thread_state"] = dict(state)
        return payload

    def _record_non_send_decision(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        thread: ThreadObservation,
        decision: DraftDecision,
    ) -> dict[str, Any]:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            if latest.status != "active":
                return _result(
                    latest.status,
                    reason=latest.pause_reason or latest.stop_reason or "managed_run_not_active",
                    run_id=latest.run_id,
                )
            status = decision.outcome if decision.outcome in {"wait", "handoff"} else "blocked"
            reason = decision.reason_codes[0] if decision.reason_codes else f"decision:{decision.outcome}"
            result = _result(
                status,
                reason=reason,
                run_id=record.run_id,
                target_id=candidate.target_id,
                decision_id=decision.decision_id,
            )
            latest.updated_at = _iso(self._now())
            thread_state = _thread_state_payload(
                candidate,
                inbound_revision=thread.inbound_revision,
                decision_id=decision.decision_id,
                outcome=status,
                reason=reason,
                updated_at=latest.updated_at,
            )
            if status == "wait" and reason == "managed_nudge_not_due":
                thread_state["next_retry_at"] = _nudge_next_retry_at(thread, now=self._now())
            latest.thread_states[candidate.target_id] = thread_state
            latest.last_result = dict(result)
            self.store.save(latest)
        self._event(latest, "non_send_decision", status=status, target_id=candidate.target_id)
        return result

    def _finish_tick(self, record: ManagedRunRecord, status: str, *, reason: str, **extra: Any) -> dict[str, Any]:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            if latest.status != "active":
                effective_status = latest.status
                effective_reason = latest.pause_reason or latest.stop_reason or reason
            elif status == "blocked":
                # A blocked tick terminates the foreground wait loop. Persist a
                # matching lifecycle state so status cannot claim the run is
                # still actively managed after its runner has exited.
                latest.status = "paused"
                latest.pause_reason = reason
                effective_status = "paused"
                effective_reason = reason
            else:
                effective_status = status
                effective_reason = reason
            result = _result(effective_status, reason=effective_reason, run_id=latest.run_id, **extra)
            latest.last_result = dict(result)
            latest.updated_at = _iso(self._now())
            self.store.save(latest)
        self._event(latest, "tick_finished", status=effective_status, reason=effective_reason, **extra)
        return result

    def _finish_candidate_tick(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        *,
        reason: str,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            if latest.status != "active":
                return _result(
                    latest.status,
                    reason=latest.pause_reason or latest.stop_reason or "managed_run_not_active",
                    run_id=latest.run_id,
                )
            result = _result(
                "failed_before_click",
                reason=reason,
                run_id=latest.run_id,
                target_id=candidate.target_id,
                **({"decision_id": decision_id} if decision_id else {}),
            )
            latest.updated_at = _iso(self._now())
            existing_state = latest.thread_states.get(candidate.target_id)
            if candidate.inbound_revision is None and existing_state is not None:
                # A list/open failure has not established a new authoritative
                # inbound revision.  Preserve any previously confirmed thread
                # state and record only the new discovery failure; clearing the
                # full revision here would weaken duplicate-send suppression.
                next_state = dict(existing_state)
                next_state.update(
                    {
                        "last_discovery_revision": candidate.discovery_revision,
                        "last_discovery_outcome": "failed_before_click",
                        "last_discovery_reason": reason,
                        "updated_at": latest.updated_at,
                    }
                )
            else:
                next_state = _thread_state_payload(
                    candidate,
                    inbound_revision=candidate.inbound_revision or "",
                    decision_id=decision_id,
                    outcome="failed_before_click",
                    reason=reason,
                    updated_at=latest.updated_at,
                )
            latest.thread_states[candidate.target_id] = next_state
            latest.last_result = dict(result)
            self.store.save(latest)
        self._event(latest, "tick_finished", status="failed_before_click", reason=reason, target_id=candidate.target_id)
        return result

    def _finish_authoritative_duplicate(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
    ) -> dict[str, Any]:
        """Remember the discovery hint without replacing authoritative state."""

        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            if latest.status != "active":
                return _result(
                    latest.status,
                    reason=latest.pause_reason or latest.stop_reason or "managed_run_not_active",
                    run_id=latest.run_id,
                )
            state = latest.thread_states.get(candidate.target_id)
            if state is not None:
                state = dict(state)
                state["last_discovery_revision"] = candidate.discovery_revision
                state["last_discovery_outcome"] = state.get("last_outcome")
                state["last_discovery_reason"] = state.get("last_reason")
                state["updated_at"] = _iso(self._now())
                latest.thread_states[candidate.target_id] = state
            result = _result(
                "no_work",
                reason="inbound_revision_already_processed",
                run_id=latest.run_id,
                target_id=candidate.target_id,
            )
            latest.last_result = dict(result)
            latest.updated_at = _iso(self._now())
            self.store.save(latest)
        self._event(
            latest,
            "tick_finished",
            status="no_work",
            reason="inbound_revision_already_processed",
            target_id=candidate.target_id,
        )
        return result

    def _resolve_record(self, run_id: str | None) -> ManagedRunRecord | None:
        normalized_run_id = run_id or self.store.current_run_id()
        return self.store.load(normalized_run_id) if normalized_run_id else None

    def _reconcile_unfinished_click(self, record: ManagedRunRecord) -> dict[str, Any] | None:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            for decision_key, stored_attempt in latest.send_attempts.items():
                if stored_attempt.get("status") not in {"click_started", "click_committed"}:
                    continue
                attempt = dict(stored_attempt)
                reason = "unfinished_click_checkpoint_requires_reconciliation"
                attempt.update(
                    {
                        "status": "unknown_after_click",
                        "reason": reason,
                        "finished_at": _iso(self._now()),
                    }
                )
                latest.send_attempts[decision_key] = attempt
                if latest.status != "stopped":
                    latest.status = "paused"
                    latest.pause_reason = "unknown_after_click"
                latest.updated_at = _iso(self._now())
                target_id = str(attempt.get("target_id") or "")
                if target_id:
                    latest.thread_states[target_id] = {
                        "target_id": target_id,
                        "candidate_key": str(attempt.get("candidate_key") or target_id),
                        "target_binding": str(attempt.get("target_binding") or ""),
                        "last_discovery_revision": str(attempt.get("discovery_revision") or ""),
                        "last_discovery_outcome": "unknown_after_click",
                        "last_discovery_reason": reason,
                        "last_inbound_revision": str(attempt.get("inbound_revision") or ""),
                        "last_decision_id": str(attempt.get("decision_id") or ""),
                        "last_outcome": "unknown_after_click",
                        "last_reason": reason,
                        "updated_at": latest.updated_at,
                    }
                result = _result(
                    "unknown_after_click",
                    reason=reason,
                    run_id=latest.run_id,
                    target_id=attempt.get("target_id"),
                    decision_id=attempt.get("decision_id"),
                    decision_key=decision_key,
                )
                latest.last_result = dict(result)
                self.store.save(latest)
                break
            else:
                return None
        self._event(latest, "send_transaction_reconciled", **_event_result_fields(result))
        return result

    def _eligible_candidates(
        self,
        record: ManagedRunRecord,
        candidates: Sequence[ThreadCandidate],
    ) -> list[ThreadCandidate]:
        eligible: list[ThreadCandidate] = []
        for candidate in candidates:
            state = record.thread_states.get(candidate.target_id)
            authoritative = candidate.inbound_revision is not None
            state_revision = state.get(
                "last_inbound_revision" if authoritative else "last_discovery_revision"
            ) if state is not None else None
            candidate_revision = candidate.inbound_revision or candidate.discovery_revision
            if (
                state is not None
                and state_revision == candidate_revision
            ):
                outcome = state.get("last_outcome") if authoritative else state.get(
                    "last_discovery_outcome", state.get("last_outcome")
                )
                reason = state.get("last_reason") if authoritative else state.get(
                    "last_discovery_reason", state.get("last_reason")
                )
                if outcome == "wait" and reason == "managed_nudge_not_due":
                    if not _nudge_retry_due(state, now=self._now()):
                        continue
                    eligible.append(candidate)
                    continue
                if outcome in TERMINAL_SEND_STATUSES | {"wait", "handoff"}:
                    continue
            eligible.append(candidate)
        return eligible

    def _event(self, record: ManagedRunRecord, event_type: str, **payload: Any) -> None:
        try:
            self.store.append_event(
                {
                    "schema_version": MANAGED_RUN_SCHEMA_VERSION,
                    "event_id": f"event_{uuid.uuid4().hex}",
                    "event_type": event_type,
                    "run_id": record.run_id,
                    "created_at": _iso(self._now()),
                    **payload,
                }
            )
        except Exception:  # noqa: BLE001 - durable run state owns behavior; events are diagnostic only.
            return

    @staticmethod
    def _config_block_reason(config: ManagedRunConfig) -> str | None:
        if not config.app_id:
            return "app_id_missing"
        if not config.runtime:
            return "runtime_missing"
        if config.duration_minutes < 1:
            return "duration_minutes_invalid"
        if config.management_mode not in {"conservative", "high-throughput"}:
            return "management_mode_invalid"
        authorization = config.authorization
        quiet_hours_reason = live_send_authorization_quiet_hours_block_reason(authorization.quiet_hours)
        if quiet_hours_reason is not None:
            return quiet_hours_reason
        if authorization.app_id != config.app_id:
            return "authorization_app_mismatch"
        if authorization.runtime is not None and authorization.runtime != config.runtime:
            return "authorization_runtime_mismatch"
        if not authorization.live_send:
            return "live_send_not_authorized"
        if authorization.scope != "send_chat_messages":
            return "authorization_scope_not_send_chat_messages"
        if not authorization.autonomous_send:
            return "autonomous_send_not_authorized"
        if not authorization.requires_post_action_verification:
            return "post_action_verification_required"
        if "send_message" not in authorization.allowed_actions:
            return "send_message_not_authorized"
        if not authorization.allow_all_targets and not authorization.allowed_target_ids:
            return "authorization_has_no_targets"
        return None


class SendTransaction:
    """Atomic managed send protocol around the irreversible click boundary."""

    def __init__(
        self,
        *,
        store: ManagedRunStore,
        action: ManagedActionPort,
        now: Callable[[], datetime],
    ):
        self.store = store
        self.action = action
        self._now = now

    def prepared_decision(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        thread: ThreadObservation,
    ) -> DraftDecision | None:
        """Recover the exact durable draft before asking a model to draft again."""

        latest = self.store.load(record.run_id) or record
        for decision_key in sorted(latest.send_attempts):
            attempt = latest.send_attempts[decision_key]
            if attempt.get("status") != "prepared_to_click":
                continue
            if attempt.get("target_id") != candidate.target_id:
                continue
            if attempt.get("inbound_revision") != thread.inbound_revision:
                continue
            text = str(attempt.get("exact_text") or "")
            if not text or attempt.get("payload_hash") != _payload_hash(text):
                continue
            return DraftDecision(
                decision_id=str(attempt.get("decision_id") or ""),
                outcome="send",
                target_id=candidate.target_id,
                inbound_revision=thread.inbound_revision,
                text=text,
                payload_hash=str(attempt["payload_hash"]),
                action=str(attempt.get("action") or "send_message"),
                reason_codes=("resumed_prepared_checkpoint",),
            )
        return None

    def execute(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        thread: ThreadObservation,
        decision: DraftDecision,
    ) -> dict[str, Any]:
        decision_key = _decision_key(record.run_id, decision)
        latest = self.store.load(record.run_id) or record
        existing = latest.send_attempts.get(decision_key)
        if existing is not None:
            status = str(existing.get("status") or "")
            if status in TERMINAL_SEND_STATUSES:
                if status == "unknown_after_click":
                    latest = self._pause_for_unknown(latest)
                return _result(
                    status,
                    reason=str(existing.get("reason") or f"send_attempt_already_{status}"),
                    target_id=candidate.target_id,
                    decision_id=decision.decision_id,
                    decision_key=decision_key,
                    deduplicated=True,
                )
            if status == "prepared_to_click":
                return self._resume_prepared(latest, candidate, thread, decision, decision_key, existing)
            if status == "click_started":
                return self._unknown_after_click(
                    latest,
                    candidate,
                    decision,
                    decision_key,
                    "click_started_checkpoint_requires_reconciliation",
                )
            if status == "click_committed":
                return self._resume_committed(latest, candidate, decision, decision_key, existing)

        block_reason = self._pre_stage_block_reason(latest, candidate, thread, decision)
        if block_reason is not None:
            return self._gate_result(latest, candidate, decision, decision_key, block_reason)
        # Lifecycle changes and real GUI mutations share this lease. A pause or
        # stop either wins before staging, or returns only after staging has
        # completed and the prepared checkpoint is durable.
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or latest
            active_reason = self._active_block_reason(latest, candidate, decision)
            if active_reason is not None:
                return self._gate_result(latest, candidate, decision, decision_key, active_reason)
            try:
                staged = self.action.stage_text(candidate, decision.text)
            except Exception as exc:  # noqa: BLE001
                return self._failed_before_click(
                    latest,
                    candidate,
                    decision,
                    decision_key,
                    "staging_failed",
                    error_type=type(exc).__name__,
                )
            staged_reason = _composer_block_reason(
                candidate,
                thread,
                staged,
                expected_text=decision.text,
                not_before=thread.captured_at,
            )
            if staged_reason is not None:
                return self._failed_before_click(latest, candidate, decision, decision_key, staged_reason)

            loaded = self.store.load(record.run_id)
            if loaded is None:
                return _result("failed_before_click", reason="managed_run_missing_before_click", decision_key=decision_key)
            latest = loaded
            attempt = {
                "decision_key": decision_key,
                "decision_id": decision.decision_id,
                "candidate_key": candidate.candidate_key,
                "target_id": candidate.target_id,
                "target_binding": candidate.target_binding,
                "discovery_revision": candidate.discovery_revision,
                "inbound_revision": thread.inbound_revision,
                "action": decision.action,
                "exact_text": decision.text,
                "payload_hash": decision.payload_hash,
                "status": "prepared_to_click",
                "prepared_at": _iso(self._now()),
                "reason": None,
            }
            latest.send_attempts[decision_key] = attempt
            latest.updated_at = _iso(self._now())
            self.store.save(latest)  # Durable checkpoint must complete before the irreversible click.
            active_reason = self._active_block_reason(latest, candidate, decision)
            if active_reason is not None:
                return self._gate_result(latest, candidate, decision, decision_key, active_reason)
        return self._click_and_verify(latest, candidate, decision, decision_key, attempt)

    def _resume_prepared(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        thread: ThreadObservation,
        decision: DraftDecision,
        decision_key: str,
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        latest = self.store.load(record.run_id) or record
        active_reason = self._active_block_reason(latest, candidate, decision)
        if active_reason is not None:
            return self._gate_result(latest, candidate, decision, decision_key, active_reason)
        try:
            staged = self.action.observe_composer(candidate)
        except Exception as exc:  # noqa: BLE001
            return self._failed_before_click(
                latest,
                candidate,
                decision,
                decision_key,
                "prepared_checkpoint_composer_unknown",
                error_type=type(exc).__name__,
            )
        evidence_reason = _composer_identity_or_revision_block_reason(candidate, thread, staged)
        if evidence_reason is not None:
            return self._failed_before_click(latest, candidate, decision, decision_key, evidence_reason)
        freshness_reason = _capture_freshness_reason(
            staged.captured_at,
            not_before=thread.captured_at,
            prefix="composer",
        )
        if freshness_reason is not None:
            return self._failed_before_click(latest, candidate, decision, decision_key, freshness_reason)
        if staged.text != decision.text:
            reason = "prepared_checkpoint_input_cleared" if staged.text == "" else "prepared_checkpoint_text_changed"
            return self._failed_before_click(latest, candidate, decision, decision_key, reason)
        latest = self.store.load(record.run_id) or latest
        active_reason = self._active_block_reason(latest, candidate, decision)
        if active_reason is not None:
            return self._gate_result(latest, candidate, decision, decision_key, active_reason)
        return self._click_and_verify(latest, candidate, decision, decision_key, attempt)

    def _resume_committed(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        receipt_id = str(attempt.get("receipt_id") or "")
        clicked_at = str(attempt.get("clicked_at") or "")
        if not receipt_id or not clicked_at:
            return self._unknown_after_click(record, candidate, decision, decision_key, "click_checkpoint_incomplete")
        receipt = ClickReceipt(receipt_id=receipt_id, clicked_at=clicked_at)
        return self._verify_post_send(record, candidate, decision, decision_key, receipt)

    def _click_and_verify(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        attempt: dict[str, Any],
    ) -> dict[str, Any]:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id)
            if latest is None:
                return _result("failed_before_click", reason="managed_run_missing_before_click", decision_key=decision_key)
            active_reason = self._active_block_reason(latest, candidate, decision)
            if active_reason is not None:
                return self._gate_result(latest, candidate, decision, decision_key, active_reason)

            # `click_started` is the durable irreversible-boundary checkpoint.
            # The state lease remains held through the one irreversible port
            # call, so stop/pause cannot return and then observe a later click.
            attempt = dict(attempt)
            attempt.update({"status": "click_started", "click_started_at": _iso(self._now())})
            latest.send_attempts[decision_key] = attempt
            latest.attempted_send_count += 1
            latest.updated_at = _iso(self._now())
            self.store.save(latest)
            try:
                receipt = self.action.click_send(candidate)
            except Exception as exc:  # noqa: BLE001 - the port may have crossed the click boundary.
                current = self.store.load(record.run_id) or latest
                return self._unknown_after_click(
                    current,
                    candidate,
                    decision,
                    decision_key,
                    "click_result_unknown",
                    error_type=type(exc).__name__,
                )
            attempt.update(
                {
                    "status": "click_committed",
                    "receipt_id": receipt.receipt_id,
                    "clicked_at": receipt.clicked_at,
                }
            )
            committed = self.store.load(record.run_id) or latest
            committed.send_attempts[decision_key] = attempt
            committed.updated_at = _iso(self._now())
            self.store.save(committed)
        return self._verify_post_send(committed, candidate, decision, decision_key, receipt)

    def _verify_post_send(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        receipt: ClickReceipt,
    ) -> dict[str, Any]:
        try:
            post = self.action.observe_post_send(candidate, receipt)
        except Exception as exc:  # noqa: BLE001
            return self._unknown_after_click(record, candidate, decision, decision_key, "post_send_observation_failed", error_type=type(exc).__name__)
        reason = _post_send_unknown_reason(candidate, decision, receipt, post)
        if reason is not None:
            return self._unknown_after_click(record, candidate, decision, decision_key, reason)
        return self._finalize_attempt(
            record,
            candidate,
            decision,
            decision_key,
            status="confirmed",
            reason="fresh_outbound_exact_text_verified",
            post_observation_id=post.observation_id,
        )

    def _pre_stage_block_reason(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        thread: ThreadObservation,
        decision: DraftDecision,
    ) -> str | None:
        active_reason = self._active_block_reason(record, candidate, decision)
        if active_reason is not None:
            return active_reason
        if thread.inbound_revision != decision.inbound_revision:
            return "inbound_revision_changed"
        return None

    def _active_block_reason(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
    ) -> str | None:
        if record.status == "paused":
            return "managed_run_paused"
        if record.status == "stopped":
            return "managed_run_stopped"
        if record.status != "active":
            return "managed_run_not_active"
        if (self._now() - _parse_iso(record.started_at)).total_seconds() >= record.config.duration_minutes * 60:
            return "managed_run_duration_elapsed"
        if record.attempted_send_count >= record.config.max_sends_per_run:
            return "send_budget_exhausted"
        return record.config.authorization.block_reason(
            app_id=record.config.app_id,
            runtime=record.config.runtime,
            target_id=candidate.target_id,
            action=decision.action,
            now=self._now(),
        )

    def _gate_result(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        reason: str,
    ) -> dict[str, Any]:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            if reason == "managed_run_paused":
                result = _result(
                    "paused",
                    reason=latest.pause_reason or reason,
                    target_id=candidate.target_id,
                    decision_id=decision.decision_id,
                    decision_key=decision_key,
                )
                latest.last_result = dict(result)
                latest.updated_at = _iso(self._now())
                self.store.save(latest)
                return result
            if reason in {
                "managed_run_stopped",
                "managed_run_duration_elapsed",
                "send_budget_exhausted",
            }:
                if reason != "managed_run_stopped" and latest.status != "stopped":
                    latest.status = "stopped"
                    latest.stop_reason = reason
                    latest.pause_reason = None
                result = _result(
                    "stopped",
                    reason=latest.stop_reason or reason,
                    target_id=candidate.target_id,
                    decision_id=decision.decision_id,
                    decision_key=decision_key,
                    relationship_progress_snapshot=_progress_snapshot(latest),
                    relationship_progress_report=_progress_report(latest),
                )
                latest.last_result = dict(result)
                latest.updated_at = _iso(self._now())
                self.store.save(latest)
                return result
            if reason == "authorization_quiet_hours":
                result = _result(
                    "no_work",
                    reason=reason,
                    target_id=candidate.target_id,
                    decision_id=decision.decision_id,
                    decision_key=decision_key,
                )
                latest.last_result = dict(result)
                latest.updated_at = _iso(self._now())
                self.store.save(latest)
                return result
        return self._failed_before_click(latest, candidate, decision, decision_key, reason)

    def _failed_before_click(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        reason: str,
        **extra: Any,
    ) -> dict[str, Any]:
        return self._finalize_attempt(
            record,
            candidate,
            decision,
            decision_key,
            status="failed_before_click",
            reason=reason,
            **extra,
        )

    def _unknown_after_click(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        reason: str,
        **extra: Any,
    ) -> dict[str, Any]:
        return self._finalize_attempt(
            record,
            candidate,
            decision,
            decision_key,
            status="unknown_after_click",
            reason=reason,
            **extra,
        )

    def _pause_for_unknown(self, record: ManagedRunRecord) -> ManagedRunRecord:
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            if latest.status != "stopped":
                latest.status = "paused"
                latest.pause_reason = "unknown_after_click"
                latest.updated_at = _iso(self._now())
                self.store.save(latest)
        return latest

    def _finalize_attempt(
        self,
        record: ManagedRunRecord,
        candidate: ThreadCandidate,
        decision: DraftDecision,
        decision_key: str,
        *,
        status: str,
        reason: str,
        **extra: Any,
    ) -> dict[str, Any]:
        result = _result(
            status,
            reason=reason,
            target_id=candidate.target_id,
            decision_id=decision.decision_id,
            decision_key=decision_key,
            **extra,
        )
        with self.store.state_lease(record.run_id):
            latest = self.store.load(record.run_id) or record
            previous = latest.send_attempts.get(decision_key, {})
            previous_status = str(previous.get("status") or "")
            latest.send_attempts[decision_key] = {
                **previous,
                "decision_key": decision_key,
                "decision_id": decision.decision_id,
                "candidate_key": candidate.candidate_key,
                "target_id": candidate.target_id,
                "target_binding": candidate.target_binding,
                "discovery_revision": candidate.discovery_revision,
                "inbound_revision": decision.inbound_revision,
                "action": decision.action,
                "exact_text": decision.text,
                "payload_hash": decision.payload_hash,
                "status": status,
                "reason": reason,
                "finished_at": _iso(self._now()),
                **extra,
            }
            if status == "unknown_after_click" and latest.status != "stopped":
                latest.status = "paused"
                latest.pause_reason = "unknown_after_click"
            if status == "confirmed" and previous_status != "confirmed":
                latest.confirmed_send_count += 1
            latest.updated_at = _iso(self._now())
            latest.thread_states[candidate.target_id] = _thread_state_payload(
                candidate,
                inbound_revision=decision.inbound_revision,
                decision_id=decision.decision_id,
                outcome=status,
                reason=reason,
                updated_at=latest.updated_at,
            )
            latest.last_result = dict(result)
            self.store.save(latest)
        return result


def build_managed_run_runtime(
    data_dir: Path,
    *,
    observation: ManagedObservationPort,
    decision: ManagedDecisionPort,
    action: ManagedActionPort,
    now: Callable[[], datetime] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> ManagedRun:
    return ManagedRun(
        JsonManagedRunStore(data_dir),
        observation,
        decision,
        action,
        now=now,
        sleeper=sleeper,
    )


def _thread_state_payload(
    candidate: ThreadCandidate,
    *,
    inbound_revision: str,
    decision_id: str | None,
    outcome: str,
    reason: str,
    updated_at: str,
) -> dict[str, Any]:
    return {
        "target_id": candidate.target_id,
        "candidate_key": candidate.candidate_key,
        "target_binding": candidate.target_binding,
        "last_discovery_revision": candidate.discovery_revision,
        "last_discovery_outcome": outcome,
        "last_discovery_reason": reason,
        "last_inbound_revision": inbound_revision,
        "last_decision_id": decision_id,
        "last_outcome": outcome,
        "last_reason": reason,
        "updated_at": updated_at,
    }


def _inherited_unknown_thread_states(record: ManagedRunRecord | None) -> dict[str, dict[str, Any]]:
    if record is None:
        return {}
    inherited = {
        target_id: {**state, "inherited_from_run_id": record.run_id}
        for target_id, state in record.thread_states.items()
        if state.get("last_outcome") == "unknown_after_click"
    }
    for attempt in record.send_attempts.values():
        if attempt.get("status") != "unknown_after_click":
            continue
        target_id = str(attempt.get("target_id") or "")
        if not target_id or target_id in inherited:
            continue
        inherited[target_id] = {
            "target_id": target_id,
            "candidate_key": str(attempt.get("candidate_key") or target_id),
            "target_binding": str(attempt.get("target_binding") or ""),
            "last_discovery_revision": str(attempt.get("discovery_revision") or ""),
            "last_discovery_outcome": "unknown_after_click",
            "last_discovery_reason": str(attempt.get("reason") or "unknown_after_click"),
            "last_inbound_revision": str(attempt.get("inbound_revision") or ""),
            "last_decision_id": str(attempt.get("decision_id") or ""),
            "last_outcome": "unknown_after_click",
            "last_reason": str(attempt.get("reason") or "unknown_after_click"),
            "updated_at": str(attempt.get("finished_at") or record.updated_at),
            "inherited_from_run_id": record.run_id,
        }
    return inherited


def _nudge_next_retry_at(thread: ThreadObservation, *, now: datetime) -> str:
    raw_observation = thread.context.get("standalone_thread_observation")
    assessment = raw_observation.get("assessment") if isinstance(raw_observation, Mapping) else None
    if isinstance(assessment, Mapping):
        due_at = str(assessment.get("nudge_due_at") or assessment.get("due_at") or "").strip()
        if due_at:
            try:
                parsed_due_at = _parse_iso(due_at)
            except ValueError:
                pass
            else:
                if parsed_due_at > now:
                    return _iso(parsed_due_at)
    return _iso(now + timedelta(seconds=MANAGED_NUDGE_FALLBACK_RETRY_SECONDS))


def _nudge_retry_due(state: Mapping[str, Any], *, now: datetime) -> bool:
    retry_at = state.get("next_retry_at")
    if isinstance(retry_at, str):
        try:
            return now >= _parse_iso(retry_at)
        except ValueError:
            return False
    updated_at = state.get("updated_at")
    if not isinstance(updated_at, str):
        return False
    try:
        legacy_retry_at = _parse_iso(updated_at) + timedelta(seconds=MANAGED_NUDGE_FALLBACK_RETRY_SECONDS)
    except ValueError:
        return False
    return now >= legacy_retry_at


def _target_evidence_block_reason(candidate: ThreadCandidate, target_id: str, target_binding: str) -> str | None:
    if target_id != candidate.target_id:
        return "target_id_mismatch"
    if target_binding != candidate.target_binding:
        return "target_binding_mismatch"
    return None


def _decision_block_reason(decision: DraftDecision, thread: ThreadObservation) -> str | None:
    if not decision.decision_id:
        return "decision_id_missing"
    if decision.target_id != thread.target_id:
        return "decision_target_mismatch"
    if decision.inbound_revision != thread.inbound_revision:
        return "decision_inbound_revision_mismatch"
    if decision.outcome not in {"send", "wait", "handoff"}:
        return "unsupported_decision_outcome"
    if decision.outcome == "send":
        if decision.action != "send_message":
            return "unsupported_managed_action"
        if not decision.text:
            return "draft_text_missing"
        if decision.payload_hash != _payload_hash(decision.text):
            return "draft_payload_hash_mismatch"
    return None


def _composer_identity_or_revision_block_reason(
    candidate: ThreadCandidate,
    thread: ThreadObservation,
    composer: ComposerObservation,
) -> str | None:
    target_reason = _target_evidence_block_reason(candidate, composer.target_id, composer.target_binding)
    if target_reason is not None:
        return target_reason
    if composer.inbound_revision != thread.inbound_revision:
        return "inbound_revision_changed"
    return None


def _composer_block_reason(
    candidate: ThreadCandidate,
    thread: ThreadObservation,
    composer: ComposerObservation,
    *,
    expected_text: str,
    not_before: str,
) -> str | None:
    evidence_reason = _composer_identity_or_revision_block_reason(candidate, thread, composer)
    if evidence_reason is not None:
        return evidence_reason
    freshness_reason = _capture_freshness_reason(
        composer.captured_at,
        not_before=not_before,
        prefix="composer",
    )
    if freshness_reason is not None:
        return freshness_reason
    if composer.text != expected_text:
        return "composer_not_empty" if expected_text == "" else "staged_text_mismatch"
    return None


def _capture_freshness_reason(captured_at: str, *, not_before: str, prefix: str) -> str | None:
    try:
        if _parse_iso(captured_at) <= _parse_iso(not_before):
            return f"{prefix}_observation_not_fresh"
    except (TypeError, ValueError):
        return f"{prefix}_timestamp_invalid"
    return None


def _quiet_hours_active(windows: Sequence[Any], now: datetime) -> bool:
    if not windows:
        return False
    local_now = now.astimezone()
    current = local_now.hour * 60 + local_now.minute
    for item in windows:
        if isinstance(item, Mapping):
            start_value = item.get("start") or item.get("start_time")
            end_value = item.get("end") or item.get("end_time")
        elif isinstance(item, str) and "-" in item:
            start_value, end_value = item.split("-", 1)
        else:
            continue
        start = _clock_minutes(start_value)
        end = _clock_minutes(end_value)
        if start is None or end is None:
            continue
        if start <= end and start <= current < end:
            return True
        if start > end and (current >= start or current < end):
            return True
    return False


def _clock_minutes(value: Any) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour_text, minute_text = value.strip().split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour * 60 + minute


def _post_send_unknown_reason(
    candidate: ThreadCandidate,
    decision: DraftDecision,
    receipt: ClickReceipt,
    post: PostSendObservation,
) -> str | None:
    target_reason = _target_evidence_block_reason(candidate, post.target_id, post.target_binding)
    if target_reason is not None:
        return target_reason
    if not post.observation_id:
        return "post_send_observation_id_missing"
    if post.receipt_id != receipt.receipt_id:
        return "post_send_receipt_mismatch"
    freshness_reason = _capture_freshness_reason(
        post.captured_at,
        not_before=receipt.clicked_at,
        prefix="post_send",
    )
    if freshness_reason is not None:
        return freshness_reason
    if not post.input_cleared:
        return "composer_not_cleared_after_click"
    if post.outbound_text != decision.text:
        return "outbound_text_not_exact"
    return None


def _decision_key(run_id: str, decision: DraftDecision) -> str:
    return _stable_hash(
        {
            "run_id": run_id,
            "target_id": decision.target_id,
            "inbound_revision": decision.inbound_revision,
            "payload_hash": decision.payload_hash,
            "action": decision.action,
        }
    )


def _event_result_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in ("status", "reason", "target_id", "decision_id", "decision_key")
        if key in result
    }


def _progress_snapshot(record: ManagedRunRecord) -> dict[str, Any]:
    outcomes = [str(state.get("last_outcome") or "") for state in record.thread_states.values()]
    unknown_targets = {
        str(attempt.get("target_id") or decision_key)
        for decision_key, attempt in record.send_attempts.items()
        if attempt.get("status") == "unknown_after_click"
    }
    unknown_targets.update(
        target_id
        for target_id, state in record.thread_states.items()
        if state.get("last_outcome") == "unknown_after_click"
    )
    return {
        "schema_version": 1,
        "run_id": record.run_id,
        "status": record.status,
        "checked_threads": len(record.thread_states),
        "verified_sends": record.confirmed_send_count,
        "waiting": outcomes.count("wait"),
        "handoffs": outcomes.count("handoff"),
        "unknown_sends": len(unknown_targets),
        "send_budget_remaining": max(0, record.config.max_sends_per_run - record.attempted_send_count),
        "scan_cycles": record.cycle_count,
    }


def _progress_report(record: ManagedRunRecord) -> dict[str, Any]:
    snapshot = _progress_snapshot(record)
    return {
        **snapshot,
        "summary": (
            f"已检查 {snapshot['checked_threads']} 个对象，验证发送 {snapshot['verified_sends']} 条，"
            f"等待 {snapshot['waiting']} 个，需本人处理 {snapshot['handoffs']} 个，"
            f"发送结果未知 {snapshot['unknown_sends']} 条。"
        ),
    }


def _result(status: str, *, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema_version": MANAGED_RUN_SCHEMA_VERSION, "status": status}
    if reason is not None:
        payload["reason"] = reason
    payload.update(extra)
    return payload
