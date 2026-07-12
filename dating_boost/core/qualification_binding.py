from __future__ import annotations

from typing import Any, Mapping


QUALIFICATION_BINDING_SCHEMA_VERSION = 1


def normalize_qualification_binding(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {
        "schema_version": payload.get("schema_version"),
        "qualification_id": payload.get("qualification_id"),
        "phase": payload.get("phase"),
        "cycle_index": payload.get("cycle_index"),
        "attempt_id": payload.get("attempt_id"),
        "local_fencing_token": payload.get("local_fencing_token"),
        "runtime_fencing_token": payload.get("runtime_fencing_token"),
    }
    if (
        normalized["schema_version"] != QUALIFICATION_BINDING_SCHEMA_VERSION
        or not _identifier(normalized["qualification_id"])
        or normalized["phase"] not in {"canary", "soak"}
        or not _positive_integer(normalized["cycle_index"])
        or not _identifier(normalized["attempt_id"])
        or not _positive_integer(normalized["local_fencing_token"])
        or not _positive_integer(normalized["runtime_fencing_token"])
    ):
        raise ValueError("qualification_binding_invalid")
    return normalized


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
