"""Backend interfaces for model-powered intelligence features."""

from __future__ import annotations

import json
from copy import deepcopy
from collections.abc import Collection, Mapping
from enum import Enum
from typing import Any, Protocol


class BackendCapability(str, Enum):
    """Capabilities that model backends can advertise."""

    GENERATE_STRUCTURED = "generate_structured"


class ModelBackend(Protocol):
    """Protocol implemented by model backends."""

    @property
    def capabilities(self) -> Collection[BackendCapability]:
        """Capabilities supported by this backend."""

    def generate_structured(self, system_prompt: str, user_prompt: str, schema: Mapping[str, object]) -> dict[str, object]:
        """Generate a structured response matching the provided JSON schema."""


class ScriptedBackend:
    """Deterministic backend for tests and local scripted flows."""

    def __init__(self, payload: Mapping[str, object]):
        self._payload = deepcopy(dict(payload))

    @property
    def capabilities(self) -> Collection[BackendCapability]:
        return frozenset({BackendCapability.GENERATE_STRUCTURED})

    def generate_structured(self, system_prompt: str, user_prompt: str, schema: Mapping[str, object]) -> dict[str, object]:
        return deepcopy(self._payload)


class OpenAIBackend:
    """OpenAI Responses API backend for structured model output."""

    def __init__(self, model: str = "gpt-4.1-mini", **client_kwargs: object):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAIBackend requires the optional OpenAI SDK. Install with "
                "`pip install 'dating-booster[openai]'` or `pip install 'openai>=2,<3'`."
            ) from exc

        self._client = OpenAI(**client_kwargs)
        self._model = model

    @property
    def capabilities(self) -> Collection[BackendCapability]:
        return frozenset({BackendCapability.GENERATE_STRUCTURED})

    def generate_structured(self, system_prompt: str, user_prompt: str, schema: Mapping[str, object]) -> dict[str, object]:
        response = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "structured_response",
                    "schema": dict(schema),
                    "strict": True,
                }
            },
        )

        parsed = _extract_parsed_response(response)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"OpenAI structured response was not a JSON object: {type(parsed).__name__}")
        return parsed


def _extract_parsed_response(response: object) -> dict[str, object]:
    output_parsed = getattr(response, "output_parsed", None)
    if output_parsed is not None:
        return _coerce_to_dict(output_parsed)

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return _load_json_object(output_text)

    output = getattr(response, "output", None)
    if output is not None:
        for item in output:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, Mapping):
                content = item.get("content")
            if content is None:
                continue

            for part in content:
                parsed = getattr(part, "parsed", None)
                if parsed is None and isinstance(part, Mapping):
                    parsed = part.get("parsed")
                if parsed is not None:
                    return _coerce_to_dict(parsed)

                text = getattr(part, "text", None)
                if text is None and isinstance(part, Mapping):
                    text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return _load_json_object(text)

    raise RuntimeError("OpenAI response did not contain parsed structured output.")


def _coerce_to_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return dumped

    raise RuntimeError(f"OpenAI structured response could not be parsed as a JSON object: {type(value).__name__}")


def _load_json_object(text: str) -> dict[str, object]:
    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI structured response was not valid JSON.") from exc

    return _coerce_to_dict(value)
