from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.daemon import DaemonRepository
from dating_boost.core.production_store import DIAGNOSTIC_BUNDLE_SCHEMA_VERSION, ProductionDataStore


SENSITIVE_KEYS = {
    "display_name",
    "profile_text",
    "bio",
    "message_text",
    "text",
    "payload_text",
    "staged_text",
    "best_reply",
    "safer_reply",
    "bolder_reply",
    "blocked_draft_text",
    "ciphertext",
    "local_key_material",
    "key_id",
}


class DiagnosticsRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def doctor(self) -> dict[str, Any]:
        return {
            "schema_version": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
            "status": "ok",
            "data_doctor": _redact(ProductionDataStore(self.root).doctor()),
            "daemon": _redact(DaemonRepository(self.root).status()),
            "capabilities": _redact(build_capabilities(self.root)),
        }

    def bundle(self, output: Path) -> dict[str, Any]:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
            "status": "ok",
            "redacted": True,
            "contains_chat_text": False,
            "contains_profile_text": False,
            "contains_screenshots": False,
        }
        payloads = {
            "manifest.json": manifest,
            "capabilities.redacted.json": _redact(build_capabilities(self.root)),
            "data_doctor.redacted.json": _redact(ProductionDataStore(self.root).doctor()),
            "daemon_status.redacted.json": _redact(DaemonRepository(self.root).status()),
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in payloads.items():
                archive.writestr(name, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return {
            "schema_version": DIAGNOSTIC_BUNDLE_SCHEMA_VERSION,
            "status": "ok",
            "output": str(output),
            "redacted": True,
            "files": sorted(payloads),
        }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in SENSITIVE_KEYS:
                result[key] = "[redacted]"
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
