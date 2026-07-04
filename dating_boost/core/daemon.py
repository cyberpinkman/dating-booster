from __future__ import annotations

import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.core.production_store import ProductionDataStore
from dating_boost.core.storage import JsonStorage


DAEMON_STATE_SCHEMA_VERSION = 1
DAEMON_EVENT_SCHEMA_VERSION = 1
DAEMON_STATE_PATH = Path("daemon") / "state.json"
DAEMON_EVENTS_PATH = Path("daemon") / "events.jsonl"
DAEMON_STOP_PATH = Path("daemon") / "stop.json"
LAUNCHD_LABEL = "com.dating-booster.daemon"
DEFAULT_STOP_WAIT_TIMEOUT_SECONDS = 10.0
STOP_POLL_INTERVAL_SECONDS = 0.05


class DaemonRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._storage = JsonStorage(self.root)
        self._store = ProductionDataStore(self.root)

    def run(self, *, once: bool, owner: str, now: str, standalone_tick: bool = False) -> dict[str, Any]:
        run_id = f"daemon_{os.getpid()}_{int(time.time())}"
        lock = self._store.acquire_lock("daemon", owner=owner, run_id=run_id, now=now)
        if not lock.acquired:
            return {
                "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                "status": "blocked",
                "reason": "daemon_lock_active",
                "lock": lock.lock,
            }
        self._clear_stop_request()
        try:
            running = self._write_state(status="running", owner=owner, stop_reason=None, now=now, run_id=run_id)
            self._append_event("heartbeat", {"owner": owner, "once": once, "run_id": run_id}, now=now)
            if once:
                standalone_payload = _run_standalone_tick(self.root) if standalone_tick else None
                stopped = self._write_state(status="stopped", owner=owner, stop_reason="once_completed", now=now, run_id=run_id)
                return {
                    "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                    "status": "stopped",
                    "stop_reason": "once_completed",
                    "state": stopped,
                    "standalone_tick": standalone_payload,
                    "lock": self._store.release_lock("daemon", run_id=run_id),
                }
            interval = _heartbeat_interval()
            while True:
                if self._stop_requested():
                    stopped = self._write_state(
                        status="stopped",
                        owner=owner,
                        stop_reason="manual_stop",
                        now=_now_iso(),
                        run_id=run_id,
                    )
                    self._append_event("stop", {"reason": "manual_stop", "run_id": run_id}, now=_now_iso())
                    return {
                        "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                        "status": "stopped",
                        "stop_reason": "manual_stop",
                        "state": stopped,
                        "lock": self._store.release_lock("daemon", run_id=run_id),
                    }
                time.sleep(interval)
                heartbeat_at = _now_iso()
                running = self._write_state(
                    status="running",
                    owner=owner,
                    stop_reason=None,
                    now=heartbeat_at,
                    run_id=run_id,
                )
                self._append_event("heartbeat", {"owner": owner, "once": once, "run_id": run_id}, now=heartbeat_at)
        except KeyboardInterrupt:
            stopped = self._write_state(
                status="stopped",
                owner=owner,
                stop_reason="interrupted",
                now=_now_iso(),
                run_id=run_id,
            )
            return {
                "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                "status": "stopped",
                "stop_reason": "interrupted",
                "state": stopped,
                "lock": self._store.release_lock("daemon", run_id=run_id),
            }
        except Exception:
            self._store.release_lock("daemon", run_id=run_id)
            raise

    def status(self) -> dict[str, Any]:
        path = self.root / DAEMON_STATE_PATH
        state = (
            self._storage.read_json(DAEMON_STATE_PATH, expected_schema_version=DAEMON_STATE_SCHEMA_VERSION)
            if path.exists()
            else {
                "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                "status": "not_installed",
                "owner": None,
                "heartbeat_at": None,
                "stop_reason": None,
            }
        )
        return {"schema_version": DAEMON_STATE_SCHEMA_VERSION, "status": "ok", "state": state}

    def stop(self, *, now: str, wait_timeout_seconds: float | None = None) -> dict[str, Any]:
        current_state = self._read_state()
        current_lock = self._store.get_lock("daemon")
        target_run_id = _active_run_id(current_state, current_lock)
        target_pid = _active_pid(current_state)
        self._write_stop_request(now=now, target_run_id=target_run_id, target_pid=target_pid)
        self._append_event(
            "stop_requested",
            {"reason": "manual_stop", "target_run_id": target_run_id, "target_pid": target_pid},
            now=now,
        )
        if target_run_id is not None or target_pid is not None:
            wait = self._wait_for_stop_ack(
                target_run_id=target_run_id,
                target_pid=target_pid,
                timeout_seconds=_stop_wait_timeout(wait_timeout_seconds),
            )
            if wait["status"] == "acknowledged":
                return {
                    "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                    "status": "stopped",
                    "state": wait["state"],
                    "lock": wait["lock"],
                    "stop_wait_status": "acknowledged",
                }

        state = self._write_state(
            status="stopped",
            owner="manual",
            stop_reason="manual_stop",
            now=now,
            run_id=target_run_id,
        )
        self._append_event("stop", {"reason": "manual_stop", "target_run_id": target_run_id}, now=now)
        return {
            "schema_version": DAEMON_STATE_SCHEMA_VERSION,
            "status": "stopped",
            "state": state,
            "lock": self._store.force_release_lock("daemon", now=now),
            "stop_wait_status": "timeout" if target_run_id is not None or target_pid is not None else "no_active_daemon",
        }

    def install(self, *, dry_run: bool) -> dict[str, Any]:
        plist = launchd_plist(self.root)
        path = launchd_plist_path()
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(plist, encoding="utf-8")
        return {
            "schema_version": DAEMON_STATE_SCHEMA_VERSION,
            "status": "ok",
            "dry_run": dry_run,
            "plist_path": str(path),
            "plist": plist,
        }

    def uninstall(self, *, dry_run: bool) -> dict[str, Any]:
        path = launchd_plist_path()
        removed = False
        if not dry_run and path.exists():
            path.unlink()
            removed = True
        return {
            "schema_version": DAEMON_STATE_SCHEMA_VERSION,
            "status": "ok",
            "dry_run": dry_run,
            "plist_path": str(path),
            "removed": removed,
        }

    def _write_state(
        self,
        *,
        status: str,
        owner: str,
        stop_reason: str | None,
        now: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": DAEMON_STATE_SCHEMA_VERSION,
            "status": status,
            "owner": owner,
            "heartbeat_at": now,
            "stop_reason": stop_reason,
            "pid": os.getpid(),
        }
        if run_id is not None:
            payload["run_id"] = run_id
        self._storage.write_json(DAEMON_STATE_PATH, payload)
        return payload

    def _append_event(self, event_type: str, payload: dict[str, Any], *, now: str) -> None:
        self._storage.append_jsonl(
            DAEMON_EVENTS_PATH,
            {
                "schema_version": DAEMON_EVENT_SCHEMA_VERSION,
                "event_type": event_type,
                "created_at": now,
                "payload": payload,
            },
        )

    def _write_stop_request(self, *, now: str, target_run_id: str | None, target_pid: int | None) -> None:
        self._storage.write_json(
            DAEMON_STOP_PATH,
            {
                "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                "status": "stop_requested",
                "requested_at": now,
                "pid": os.getpid(),
                "target_run_id": target_run_id,
                "target_pid": target_pid,
            },
        )

    def _stop_requested(self) -> bool:
        return (self.root / DAEMON_STOP_PATH).exists()

    def _clear_stop_request(self) -> None:
        path = self.root / DAEMON_STOP_PATH
        if path.exists():
            path.unlink()

    def _read_state(self) -> dict[str, Any] | None:
        path = self.root / DAEMON_STATE_PATH
        if not path.exists():
            return None
        return self._storage.read_json(DAEMON_STATE_PATH, expected_schema_version=DAEMON_STATE_SCHEMA_VERSION)

    def _wait_for_stop_ack(
        self,
        *,
        target_run_id: str | None,
        target_pid: int | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            state = self._read_state()
            lock = self._store.get_lock("daemon")
            if _state_acknowledges_stop(state, target_run_id=target_run_id, target_pid=target_pid) and _lock_released(
                lock,
                target_run_id=target_run_id,
            ):
                return {
                    "status": "acknowledged",
                    "state": state,
                    "lock": lock
                    or {
                        "schema_version": 1,
                        "lock_name": "daemon",
                        "status": "missing",
                        "run_id": target_run_id,
                    },
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"status": "timeout", "state": state, "lock": lock}
            time.sleep(min(STOP_POLL_INTERVAL_SECONDS, remaining))


def launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def launchd_plist(data_dir: Path) -> str:
    executable = shutil.which("dating-boostd") or "dating-boostd"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{executable}</string>
    <string>run</string>
    <string>--data-dir</string>
    <string>{data_dir.resolve()}</string>
    <string>--json</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{data_dir.resolve() / "daemon" / "stdout.log"}</string>
  <key>StandardErrorPath</key>
  <string>{data_dir.resolve() / "daemon" / "stderr.log"}</string>
</dict>
</plist>
"""


def _heartbeat_interval() -> float:
    try:
        return max(0.01, float(os.environ.get("DATING_BOOST_DAEMON_HEARTBEAT_INTERVAL", "5")))
    except ValueError:
        return 5.0


def _stop_wait_timeout(value: float | None) -> float:
    if value is not None:
        return max(0.0, float(value))
    try:
        return max(0.0, float(os.environ.get("DATING_BOOST_DAEMON_STOP_TIMEOUT", DEFAULT_STOP_WAIT_TIMEOUT_SECONDS)))
    except ValueError:
        return DEFAULT_STOP_WAIT_TIMEOUT_SECONDS


def _active_run_id(state: dict[str, Any] | None, lock: dict[str, Any] | None) -> str | None:
    if isinstance(state, dict) and state.get("status") == "running":
        run_id = state.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    if isinstance(lock, dict) and lock.get("status") == "active":
        run_id = lock.get("run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


def _active_pid(state: dict[str, Any] | None) -> int | None:
    if not isinstance(state, dict) or state.get("status") != "running":
        return None
    pid = state.get("pid")
    return pid if isinstance(pid, int) and not isinstance(pid, bool) else None


def _state_acknowledges_stop(
    state: dict[str, Any] | None,
    *,
    target_run_id: str | None,
    target_pid: int | None,
) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("status") != "stopped" or state.get("stop_reason") != "manual_stop":
        return False
    if target_run_id is not None and state.get("run_id") != target_run_id:
        return False
    if target_pid is not None and state.get("pid") != target_pid:
        return False
    return True


def _lock_released(lock: dict[str, Any] | None, *, target_run_id: str | None) -> bool:
    if lock is None:
        return True
    if target_run_id is not None and lock.get("run_id") != target_run_id:
        return True
    return lock.get("status") != "active"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_standalone_tick(root: Path) -> dict[str, Any] | None:
    from dating_boost.core.standalone_provider_factory import build_standalone_runtime_ports
    from dating_boost.core.standalone_runtime import StandaloneAgentRuntime, StandaloneDraftPlanner
    from dating_boost.core.standalone_session import StandaloneSessionRepository

    repository = StandaloneSessionRepository(root)
    status = repository.status()
    if status.get("status") != "active":
        return None
    session = status.get("session") if isinstance(status.get("session"), dict) else {}
    ports = build_standalone_runtime_ports(root, session)
    if ports.get("status") != "ok":
        return ports
    try:
        tick = StandaloneAgentRuntime(
            root,
            observation_provider=ports["observation_provider"],
            harness_factory=ports["harness_factory"],
            action_executor=ports["action_executor"],
            draft_planner=StandaloneDraftPlanner(
                root,
                backend_config=session.get("backend") or {},
                allow_stage_soft_accept=str(session.get("send_mode") or "").strip() == "stage",
            ),
        ).tick()
    except Exception as exc:  # noqa: BLE001 - daemon run-once must return a structured payload.
        tick = {
            "schema_version": 1,
            "status": "blocked",
            "reason": "standalone_tick_failed",
            "error_type": type(exc).__name__,
        }
    repository.record_tick(tick)
    return tick


def daemon_entry(argv: list[str] | None = None) -> int:
    from dating_boost.cli import main

    return main(["daemon", *(sys.argv[1:] if argv is None else argv)])
