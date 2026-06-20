from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol


class StandaloneObservationProvider(Protocol):
    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        raise NotImplementedError

    def observe_current_thread(self, *, app_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        raise NotImplementedError


class FixtureObservationProvider:
    def __init__(self, fixture_dir: Path):
        self.fixture_dir = fixture_dir

    def observe_message_list(self, *, app_id: str, scan_cursor: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(scan_cursor, dict):
            raise ValueError("scan_cursor must be a JSON object")
        payload = copy.deepcopy(self._read("message_list.json"))
        payload.setdefault("schema_version", 1)
        payload["observation_type"] = "message_list"
        payload["app_id"] = app_id
        payload.setdefault("scan_cursor", dict(scan_cursor))
        return payload

    def observe_thread(self, *, app_id: str, candidate_key: str) -> dict[str, Any]:
        payload = copy.deepcopy(self._read(_thread_fixture_name(candidate_key)))
        payload.setdefault("schema_version", 1)
        payload["observation_type"] = "thread"
        payload["app_id"] = app_id
        payload["candidate_key"] = candidate_key
        return payload

    def observe_current_thread(self, *, app_id: str) -> dict[str, Any]:
        payload = copy.deepcopy(self._read("current_thread.json"))
        payload.setdefault("schema_version", 1)
        payload["observation_type"] = "thread"
        payload["app_id"] = app_id
        payload.setdefault("candidate_key", "current_thread")
        return payload

    def precheck_payload(self, *, app_id: str) -> dict[str, Any]:
        path = self.fixture_dir / "precheck.json"
        if path.exists():
            payload = copy.deepcopy(self._read("precheck.json"))
        else:
            payload = {"schema_version": 1, "status": "ok", "screen_state": "fixture_ready"}
        payload["app_id"] = app_id
        return payload

    def _read(self, name: str) -> dict[str, Any]:
        path = self.fixture_dir / name
        if not path.exists():
            raise FileNotFoundError(f"fixture observation missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"fixture observation must be a JSON object: {path}")
        return value


class FixturePrecheckHarness:
    def __init__(self, provider: StandaloneObservationProvider, *, app_id: str, runtime: str | None):
        self.provider = provider
        self.app_id = app_id
        self.runtime = runtime

    def observe(self) -> dict[str, Any]:
        payload = self.provider.precheck_payload(app_id=self.app_id)
        if self.runtime is not None:
            payload["runtime"] = self.runtime
        return payload


def fixture_harness_factory(provider: FixtureObservationProvider):
    def _factory(app_id: str, runtime: str | None = None) -> FixturePrecheckHarness:
        return FixturePrecheckHarness(provider, app_id=app_id, runtime=runtime)

    return _factory


def _thread_fixture_name(candidate_key: str) -> str:
    if not isinstance(candidate_key, str) or not candidate_key:
        raise ValueError("candidate_key must be a non-empty string")
    if all(ch.isalnum() or ch in {"-", "_"} for ch in candidate_key):
        return f"thread_{candidate_key}.json"
    safe_prefix = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in candidate_key).strip("_")
    if not safe_prefix:
        safe_prefix = "candidate"
    digest = hashlib.sha256(candidate_key.encode("utf-8")).hexdigest()[:12]
    return f"thread_{safe_prefix}_{digest}.json"
