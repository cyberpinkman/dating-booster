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
            running = self._write_state(status="running", owner=owner, stop_reason=None, now=now)
            self._append_event("heartbeat", {"owner": owner, "once": once, "run_id": run_id}, now=now)
            if once:
                standalone_payload = _run_standalone_tick(self.root) if standalone_tick else None
                stopped = self._write_state(status="stopped", owner=owner, stop_reason="once_completed", now=now)
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
                    stopped = self._write_state(status="stopped", owner=owner, stop_reason="manual_stop", now=_now_iso())
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
                running = self._write_state(status="running", owner=owner, stop_reason=None, now=heartbeat_at)
                self._append_event("heartbeat", {"owner": owner, "once": once, "run_id": run_id}, now=heartbeat_at)
        except KeyboardInterrupt:
            stopped = self._write_state(status="stopped", owner=owner, stop_reason="interrupted", now=_now_iso())
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

    def stop(self, *, now: str) -> dict[str, Any]:
        self._write_stop_request(now=now)
        state = self._write_state(status="stopped", owner="manual", stop_reason="manual_stop", now=now)
        self._append_event("stop", {"reason": "manual_stop"}, now=now)
        return {
            "schema_version": DAEMON_STATE_SCHEMA_VERSION,
            "status": "stopped",
            "state": state,
            "lock": self._store.force_release_lock("daemon", now=now),
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

    def _write_state(self, *, status: str, owner: str, stop_reason: str | None, now: str) -> dict[str, Any]:
        payload = {
            "schema_version": DAEMON_STATE_SCHEMA_VERSION,
            "status": status,
            "owner": owner,
            "heartbeat_at": now,
            "stop_reason": stop_reason,
            "pid": os.getpid(),
        }
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

    def _write_stop_request(self, *, now: str) -> None:
        self._storage.write_json(
            DAEMON_STOP_PATH,
            {
                "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                "status": "stop_requested",
                "requested_at": now,
                "pid": os.getpid(),
            },
        )

    def _stop_requested(self) -> bool:
        return (self.root / DAEMON_STOP_PATH).exists()

    def _clear_stop_request(self) -> None:
        path = self.root / DAEMON_STOP_PATH
        if path.exists():
            path.unlink()


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_standalone_tick(root: Path) -> dict[str, Any] | None:
    from dating_boost.core.standalone_provider_factory import build_standalone_runtime_ports
    from dating_boost.core.standalone_runtime import StandaloneAgentRuntime
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
