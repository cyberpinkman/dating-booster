from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.vision_backends import OpenAIVisionBackend, ScriptedVisionBackend, VisionBackend


def create_vision_backend(config: dict[str, Any]) -> VisionBackend:
    backend_type = str(config.get("type") or "scripted")
    if backend_type == "scripted":
        path = config.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("scripted_vision_backend_path_required")
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return ScriptedVisionBackend(payload)
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            return ScriptedVisionBackend(payload)
        raise ValueError("scripted_vision_backend_output_must_be_object_or_array")
    if backend_type == "openai":
        return OpenAIVisionBackend(model=str(config.get("model") or "gpt-4.1-mini"))
    raise ValueError(f"unsupported_vision_backend:{backend_type}")
