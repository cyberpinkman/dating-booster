from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["_json_or_empty", "_read_json_file", "_truncate"]

def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None

def _json_or_empty(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _truncate(value: Any, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
