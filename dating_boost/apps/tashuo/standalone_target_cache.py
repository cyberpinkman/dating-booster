from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.core.storage import JsonStorage
from dating_boost.apps.tashuo.standalone_common import TARGET_CACHE_PATH, _now_iso

__all__ = ["TaShuoStandaloneTargetCache"]

class TaShuoStandaloneTargetCache:
    def __init__(self, root: Path):
        self._storage = JsonStorage(root)

    def put(self, target: dict[str, Any]) -> None:
        current = self._read()
        candidate_key = str(target.get("candidate_key") or "").strip()
        if not candidate_key:
            raise ValueError("candidate_key_required")
        current[candidate_key] = {**target, "observed_at": _now_iso()}
        self._storage.write_json(TARGET_CACHE_PATH, {"schema_version": 1, "targets": current})

    def get(self, candidate_key: str) -> dict[str, Any] | None:
        return self._read().get(candidate_key)

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            payload = self._storage.read_json(TARGET_CACHE_PATH, expected_schema_version=1)
        except FileNotFoundError:
            return {}
        targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
        return {str(key): value for key, value in targets.items() if isinstance(value, dict)}
