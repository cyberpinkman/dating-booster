from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage


SAFETY_SCHEMA_VERSION = 1
SAFETY_PATH = Path("safety") / "status.json"


class SafetyRepository:
    def __init__(self, root: Path):
        self.root = root
        self._storage = JsonStorage(root)

    def pause(self, *, reason: str, created_at: str) -> dict[str, Any]:
        payload = {
            "schema_version": SAFETY_SCHEMA_VERSION,
            "paused": True,
            "reason": reason,
            "created_at": created_at,
            "resumed_at": None,
        }
        self._storage.write_json(SAFETY_PATH, payload)
        return {"schema_version": SAFETY_SCHEMA_VERSION, "status": "paused", **payload}

    def resume(self, *, created_at: str) -> dict[str, Any]:
        payload = {
            "schema_version": SAFETY_SCHEMA_VERSION,
            "paused": False,
            "reason": None,
            "created_at": self.status().get("created_at"),
            "resumed_at": created_at,
        }
        self._storage.write_json(SAFETY_PATH, payload)
        return {"schema_version": SAFETY_SCHEMA_VERSION, "status": "active", **payload}

    def status(self) -> dict[str, Any]:
        path = self.root / SAFETY_PATH
        if not path.exists():
            return {
                "schema_version": SAFETY_SCHEMA_VERSION,
                "paused": False,
                "reason": None,
                "created_at": None,
                "resumed_at": None,
            }
        return self._storage.read_json(SAFETY_PATH, expected_schema_version=SAFETY_SCHEMA_VERSION)

    def is_paused(self) -> bool:
        return bool(self.status().get("paused"))
