"""Image-backed structured intelligence backends."""

from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Protocol

from dating_boost.intelligence.backends import (
    MINIMAX_STRUCTURED_TOOL_NAME,
    MiniMaxBackend,
    _extract_minimax_tool_payload,
    _extract_parsed_response,
)


class VisionBackend(Protocol):
    """Protocol implemented by structured image-analysis backends."""

    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        """Analyze an image and return a structured response."""


class ScriptedVisionBackend:
    """Deterministic vision backend for tests and local scripted flows."""

    def __init__(self, payload: Mapping[str, object] | list[Mapping[str, object]]):
        if isinstance(payload, list):
            if not payload:
                raise ValueError("scripted_vision_backend_output_must_be_object_or_non_empty_array")
            self._payloads = [deepcopy(dict(item)) for item in payload]
        else:
            self._payloads = [deepcopy(dict(payload))]
        self._cursor = 0

    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        if self._cursor >= len(self._payloads):
            payload = self._payloads[-1]
        else:
            payload = self._payloads[self._cursor]
            self._cursor += 1
        return deepcopy(payload)


class OpenAIVisionBackend:
    """OpenAI Responses API backend for structured image analysis."""

    def __init__(self, model: str = "gpt-4.1-mini", **client_kwargs: object):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAIVisionBackend requires the optional OpenAI SDK. Install with "
                "`pip install 'dating-booster[models]'` or `pip install 'openai>=2,<3'`."
            ) from exc

        self._client = OpenAI(**client_kwargs)
        self._model = model

    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        data_url = f"{_image_mime_type(image_path)};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
        response = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "vision_response",
                    "schema": dict(schema),
                    "strict": True,
                }
            },
        )
        return _extract_parsed_response(response)


class MiniMaxVisionBackend(MiniMaxBackend):
    """MiniMax OpenAI-compatible image analysis backend."""

    def analyze_image_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        image_path: Path,
        schema: Mapping[str, object],
    ) -> dict[str, Any]:
        data_url = f"{_image_mime_type(image_path)};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": MINIMAX_STRUCTURED_TOOL_NAME,
                        "description": "Return the final structured JSON object for the Dating Booster vision workflow.",
                        "parameters": dict(schema),
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": MINIMAX_STRUCTURED_TOOL_NAME}},
            extra_body=self._extra_body(),
        )
        return _extract_minimax_tool_payload(response)


def _image_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "data:image/jpeg"
    if suffix == ".webp":
        return "data:image/webp"
    return "data:image/png"
