from __future__ import annotations

import argparse
import json
import os
import shutil
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
DEFAULT_STOP_DISCOVERY_TIMEOUT_SECONDS = 2.0
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
        state = self._read_state()
        if state is None:
            state = {
                "schema_version": DAEMON_STATE_SCHEMA_VERSION,
                "status": "not_installed",
                "owner": None,
                "heartbeat_at": None,
                "stop_reason": None,
            }
        return {"schema_version": DAEMON_STATE_SCHEMA_VERSION, "status": "ok", "state": state}

    def stop(self, *, now: str, wait_timeout_seconds: float | None = None) -> dict[str, Any]:
        current_state = self._read_state()
        current_lock = self._store.get_lock("daemon")
        target_run_id = _active_run_id(current_state, current_lock)
        target_pid = _active_pid(current_state)
        if target_run_id is None and target_pid is None:
            discovered = self._wait_for_active_target(timeout_seconds=_stop_discovery_timeout())
            current_state = discovered["state"]
            current_lock = discovered["lock"]
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
        return self._storage.exists(DAEMON_STOP_PATH)

    def _clear_stop_request(self) -> None:
        self._storage.delete_json(DAEMON_STOP_PATH)

    def _read_state(self) -> dict[str, Any] | None:
        try:
            return self._storage.read_json(DAEMON_STATE_PATH, expected_schema_version=DAEMON_STATE_SCHEMA_VERSION)
        except FileNotFoundError:
            return None

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

    def _wait_for_active_target(self, *, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            state = self._read_state()
            lock = self._store.get_lock("daemon")
            if _active_run_id(state, lock) is not None or _active_pid(state) is not None:
                return {"state": state, "lock": lock}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"state": state, "lock": lock}
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


def _stop_discovery_timeout() -> float:
    try:
        return max(
            0.0,
            float(os.environ.get("DATING_BOOST_DAEMON_STOP_DISCOVERY_TIMEOUT", DEFAULT_STOP_DISCOVERY_TIMEOUT_SECONDS)),
        )
    except ValueError:
        return DEFAULT_STOP_DISCOVERY_TIMEOUT_SECONDS


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
    parser = argparse.ArgumentParser(
        prog="dating-boostd",
        description="Dating Booster daemon supervisor.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--data-dir", required=True, type=Path)
    run_parser.add_argument("--once", action="store_true")
    run_parser.add_argument("--standalone-tick", action="store_true")
    run_parser.add_argument("--json", action="store_true")
    run_parser.set_defaults(_daemon_handler=_daemon_entry_run)

    for command, handler in (
        ("install", _daemon_entry_install),
        ("uninstall", _daemon_entry_uninstall),
        ("status", _daemon_entry_status),
        ("stop", _daemon_entry_stop),
    ):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--data-dir", required=True, type=Path)
        command_parser.add_argument("--dry-run", action="store_true")
        command_parser.add_argument("--json", action="store_true")
        command_parser.set_defaults(_daemon_handler=handler)

    argv_list = list(argv) if argv is not None else None
    if argv_list and argv_list[0] == "daemon":
        argv_list = argv_list[1:]
    args = parser.parse_args(argv_list)
    return args._daemon_handler(args)


def _daemon_entry_run(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).run(
        once=args.once,
        owner="dating-boostd",
        now=_now_iso(),
        standalone_tick=bool(args.standalone_tick),
    )
    _daemon_entry_print_json(payload)
    standalone_tick = payload.get("standalone_tick") if isinstance(payload.get("standalone_tick"), dict) else None
    if standalone_tick and standalone_tick.get("status") == "blocked":
        return 2
    return 0 if payload.get("status") != "blocked" else 2


def _daemon_entry_install(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).install(dry_run=args.dry_run)
    _daemon_entry_print_json(payload)
    return 0


def _daemon_entry_uninstall(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).uninstall(dry_run=args.dry_run)
    _daemon_entry_print_json(payload)
    return 0


def _daemon_entry_status(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).status()
    _daemon_entry_print_json(payload)
    return 0


def _daemon_entry_stop(args: argparse.Namespace) -> int:
    payload = DaemonRepository(args.data_dir).stop(now=_now_iso())
    _daemon_entry_print_json(payload)
    return 0


def _daemon_entry_print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
