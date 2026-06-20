from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.backends import ModelBackend, OpenAIBackend, ScriptedBackend


def create_model_backend(config: dict[str, Any]) -> ModelBackend:
    backend_type = str(config.get("type") or "scripted")
    if backend_type == "scripted":
        path = config.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("scripted_backend_path_required")
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return ScriptedBackend(payload)
        if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
            return ScriptedBackend(payload)
        raise ValueError("scripted_backend_output_must_be_object_or_array")
    if backend_type == "openai":
        model = str(config.get("model") or "gpt-4.1-mini")
        return OpenAIBackend(model=model)
    raise ValueError(f"unsupported_model_backend:{backend_type}")
