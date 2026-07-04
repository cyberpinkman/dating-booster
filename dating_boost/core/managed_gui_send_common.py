from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


MESSAGE_SEQUENCE_SECONDS_PER_MESSAGE = 20


class ManagedGuiSendError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManagedGuiSendError(f"invalid JSON in {path}") from exc
    if not isinstance(data, dict):
        raise ManagedGuiSendError(f"expected JSON object in {path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _template_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.template{path.suffix}")


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value).strip("_") or "unknown"


def _now_iso() -> str:
    if os.environ.get("DATING_BOOST_NOW"):
        return str(os.environ["DATING_BOOST_NOW"])
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalized_harness_runtime(value: str) -> str:
    return value.strip().replace("-", "_")
