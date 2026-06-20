from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dating_boost.apps.registry import supported_app_ids
from dating_boost.core.storage import JsonStorage


STANDALONE_SESSION_SCHEMA_VERSION = 1
STANDALONE_EVENT_SCHEMA_VERSION = 1
STANDALONE_SESSION_PATH = Path("standalone_session") / "session.json"
STANDALONE_EVENTS_PATH = Path("standalone_session") / "events.jsonl"
SUPPORTED_SEND_MODES = {"stage", "live"}


class StandaloneSessionRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def start(
        self,
        *,
        app_id: str,
        runtime: str | None,
        send_mode: str,
        observation_source: dict[str, Any],
        backend: dict[str, Any],
        scan_interval_seconds: int,
        managed_gui_send: bool = False,
    ) -> dict[str, Any]:
        if app_id not in set(supported_app_ids()):
            return _payload("blocked", reason=f"unsupported_app:{app_id}")
        if send_mode not in SUPPORTED_SEND_MODES:
            return _payload("blocked", reason="unsupported_send_mode")
        if send_mode == "live" and not managed_gui_send:
            return _payload("blocked", reason="managed_gui_send_required_for_live_mode")

        current = self.status()
        if current.get("status") == "active":
            return _payload("blocked", reason="standalone_session_already_active", session=current["session"])

        now = _now_iso()
        session = {
            "schema_version": STANDALONE_SESSION_SCHEMA_VERSION,
            "session_id": f"standalone_{_digest({'pid': os.getpid(), 'now': now, 'nonce': uuid.uuid4().hex})[:16]}",
            "status": "active",
            "app_id": app_id,
            "runtime": runtime,
            "send_mode": send_mode,
            "managed_gui_send": bool(managed_gui_send),
            "observation_source": dict(observation_source),
            "backend": dict(backend),
            "scan_interval_seconds": max(1, int(scan_interval_seconds)),
            "started_at": now,
            "updated_at": now,
            "stopped_at": None,
            "stop_reason": None,
            "last_tick": None,
        }
        self._storage.write_json(STANDALONE_SESSION_PATH, session)
        self._append_event("start", {"session_id": session["session_id"], "app_id": app_id})
        return _payload("active", session=session)

    def status(self) -> dict[str, Any]:
        try:
            session = self._storage.read_json(
                STANDALONE_SESSION_PATH,
                expected_schema_version=STANDALONE_SESSION_SCHEMA_VERSION,
            )
        except FileNotFoundError:
            return _payload("not_found", reason="standalone_session_not_started")
        return _payload(str(session.get("status") or "unknown"), session=session)

    def stop(self, *, reason: str) -> dict[str, Any]:
        payload = self.status()
        if payload.get("status") == "not_found":
            return _payload("stopped", reason=reason)

        session = dict(payload["session"])
        stopped_at = _now_iso()
        session["status"] = "stopped"
        session["stopped_at"] = stopped_at
        session["updated_at"] = stopped_at
        session["stop_reason"] = reason
        self._storage.write_json(STANDALONE_SESSION_PATH, session)
        self._append_event("stop", {"session_id": session["session_id"], "reason": reason})
        return _payload("stopped", session=session, reason=reason)

    def record_tick(self, tick: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(tick, dict):
            return _payload("blocked", reason="invalid_tick_payload")

        payload = self.status()
        if payload.get("status") != "active":
            return payload

        session = dict(payload["session"])
        session["last_tick"] = dict(tick)
        session["updated_at"] = _now_iso()
        self._storage.write_json(STANDALONE_SESSION_PATH, session)
        self._append_event("tick", {"session_id": session["session_id"], "tick": tick})
        return _payload("ok", session=session)

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._storage.append_jsonl(
            STANDALONE_EVENTS_PATH,
            {
                "schema_version": STANDALONE_EVENT_SCHEMA_VERSION,
                "event_type": event_type,
                "created_at": _now_iso(),
                "payload": payload,
            },
        )


def _payload(status: str, **kwargs: Any) -> dict[str, Any]:
    return {"schema_version": STANDALONE_SESSION_SCHEMA_VERSION, "status": status, **kwargs}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
