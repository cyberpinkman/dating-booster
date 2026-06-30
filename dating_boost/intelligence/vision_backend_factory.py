from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dating_boost.intelligence.backends import MINIMAX_DEFAULT_API_KEY_ENV, MINIMAX_DEFAULT_BASE_URL, MINIMAX_DEFAULT_MODEL
from dating_boost.intelligence.vision_backends import MiniMaxVisionBackend, OpenAIVisionBackend, ScriptedVisionBackend, VisionBackend


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
    if backend_type == "minimax":
        kwargs: dict[str, Any] = {
            "model": str(config.get("model") or MINIMAX_DEFAULT_MODEL),
            "base_url": str(config.get("base_url") or MINIMAX_DEFAULT_BASE_URL),
            "api_key_env": str(config.get("api_key_env") or MINIMAX_DEFAULT_API_KEY_ENV),
        }
        if "timeout_seconds" in config:
            kwargs["timeout_seconds"] = config.get("timeout_seconds")
        return MiniMaxVisionBackend(**kwargs)
    raise ValueError(f"unsupported_vision_backend:{backend_type}")
