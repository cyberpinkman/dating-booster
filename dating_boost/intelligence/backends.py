"""Backend interfaces for model-powered intelligence features."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from collections.abc import Collection, Mapping
from enum import Enum
from typing import Any, Protocol


MINIMAX_DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_GLOBAL_BASE_URL = "https://api.minimax.io/v1"
MINIMAX_DEFAULT_MODEL = "MiniMax-M3"
MINIMAX_DEFAULT_API_KEY_ENV = "MINIMAX_API_KEY"
MINIMAX_STRUCTURED_TOOL_NAME = "emit_structured_response"
MINIMAX_DEFAULT_REQUEST_TIMEOUT_SECONDS = 45.0
MINIMAX_REQUEST_TIMEOUT_ENV = "DATING_BOOST_MINIMAX_REQUEST_TIMEOUT_SECONDS"


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

    def __init__(self, payload: Mapping[str, object] | list[Mapping[str, object]]):
        if isinstance(payload, list):
            self._payloads = [deepcopy(dict(item)) for item in payload]
        else:
            self._payloads = [deepcopy(dict(payload))]
        self._cursor = 0

    @property
    def capabilities(self) -> Collection[BackendCapability]:
        return frozenset({BackendCapability.GENERATE_STRUCTURED})

    def generate_structured(self, system_prompt: str, user_prompt: str, schema: Mapping[str, object]) -> dict[str, object]:
        if self._cursor >= len(self._payloads):
            if _schema_requires(schema, "ai_or_weird_probability"):
                return {
                    "ai_or_weird_probability": 0,
                    "reason": "scripted default self review pass",
                    "supplemental_prompt": "",
                }
            payload = self._payloads[-1]
        else:
            payload = self._payloads[self._cursor]
            self._cursor += 1
        if _schema_requires(schema, "ai_or_weird_probability") and "ai_or_weird_probability" not in payload:
            return {
                "ai_or_weird_probability": 0,
                "reason": "scripted default self review pass",
                "supplemental_prompt": "",
            }
        return deepcopy(payload)


class OpenAIBackend:
    """OpenAI Responses API backend for structured model output."""

    def __init__(self, model: str = "gpt-4.1-mini", **client_kwargs: object):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAIBackend requires the optional OpenAI SDK. Install with "
                "`pip install 'dating-booster[models]'` or `pip install 'openai>=2,<3'`."
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


class MiniMaxBackend:
    """MiniMax OpenAI-compatible backend for Coding/Token Plan keys.

    MiniMax M-series models do not provide a stable schema-constrained JSON
    mode across all OpenAI-compatible surfaces, so structured output is
    recovered through a forced function call whose parameters are the requested
    JSON schema.
    """

    def __init__(
        self,
        model: str = MINIMAX_DEFAULT_MODEL,
        *,
        base_url: str = MINIMAX_DEFAULT_BASE_URL,
        api_key_env: str = MINIMAX_DEFAULT_API_KEY_ENV,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        client: Any | None = None,
    ):
        self._model = model or MINIMAX_DEFAULT_MODEL
        self._base_url = base_url or MINIMAX_DEFAULT_BASE_URL
        self._api_key_env = api_key_env or MINIMAX_DEFAULT_API_KEY_ENV
        self._timeout_seconds = _request_timeout_seconds(timeout_seconds)
        if client is not None:
            self._client = client
            return

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "MiniMaxBackend requires the optional OpenAI SDK. Install with "
                "`pip install 'dating-booster[models]'` or `pip install 'openai>=2,<3'`."
            ) from exc

        resolved_api_key = api_key or os.environ.get(self._api_key_env)
        if not resolved_api_key and self._api_key_env == MINIMAX_DEFAULT_API_KEY_ENV:
            resolved_api_key = os.environ.get("MINIMAX_CN_API_KEY")
        if not resolved_api_key and self._api_key_env == MINIMAX_DEFAULT_API_KEY_ENV:
            resolved_api_key = os.environ.get("MINIMAX_SUBSCRIPTION_KEY")
        if not resolved_api_key:
            raise RuntimeError(f"MiniMaxBackend requires {self._api_key_env}, MINIMAX_CN_API_KEY, or MINIMAX_SUBSCRIPTION_KEY.")
        self._client = OpenAI(api_key=resolved_api_key, base_url=self._base_url, timeout=self._timeout_seconds)

    @property
    def capabilities(self) -> Collection[BackendCapability]:
        return frozenset({BackendCapability.GENERATE_STRUCTURED})

    def generate_structured(self, system_prompt: str, user_prompt: str, schema: Mapping[str, object]) -> dict[str, object]:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": MINIMAX_STRUCTURED_TOOL_NAME,
                        "description": "Return the final structured JSON object for the Dating Booster draft workflow.",
                        "parameters": dict(schema),
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": MINIMAX_STRUCTURED_TOOL_NAME}},
            extra_body=_minimax_extra_body(self._model),
        )
        return _extract_minimax_tool_payload(response)

    def _extra_body(self) -> dict[str, object]:
        return _minimax_extra_body(self._model)


def _minimax_extra_body(model: str) -> dict[str, object]:
    extra_body: dict[str, object] = {"thinking": {"type": "disabled"}}
    if str(model or "").strip().lower() in {"minimax-m3", "minimax/minimax-m3"}:
        extra_body["reasoning_split"] = True
    return extra_body


def _request_timeout_seconds(value: float | None) -> float:
    if value is not None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = 0.0
        if parsed > 0:
            return parsed
    raw = os.environ.get(MINIMAX_REQUEST_TIMEOUT_ENV)
    if raw:
        try:
            parsed = float(raw)
        except ValueError:
            parsed = 0.0
        if parsed > 0:
            return parsed
    return MINIMAX_DEFAULT_REQUEST_TIMEOUT_SECONDS


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


def _extract_minimax_tool_payload(response: object) -> dict[str, object]:
    choices = _value(response, "choices")
    if isinstance(choices, list) and choices:
        message = _value(choices[0], "message")
        tool_calls = _value(message, "tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                function = _value(tool_call, "function")
                if _value(function, "name") != MINIMAX_STRUCTURED_TOOL_NAME:
                    continue
                arguments = _value(function, "arguments")
                if isinstance(arguments, str) and arguments.strip():
                    return _load_minimax_json_object(arguments)

        content = _value(message, "content")
        if isinstance(content, str) and content.strip():
            return _load_minimax_json_object(_json_object_candidate(_strip_think_tags(content)))

    raise RuntimeError("MiniMax structured response did not contain a valid structured payload.")


def _value(container: object, key: str) -> Any:
    if isinstance(container, Mapping):
        return container.get(key)
    return getattr(container, key, None)


def _load_minimax_json_object(text: str) -> dict[str, object]:
    value = _load_minimax_json_value(text)
    if isinstance(value, str):
        value = _load_minimax_json_value(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"MiniMax structured response was not a JSON object: {type(value).__name__}")
    return dict(value)


def _load_minimax_json_value(text: str) -> Any:
    candidates = []
    stripped = _strip_markdown_json_fence(_strip_think_tags(text))
    for candidate in (text, stripped, _json_object_candidate(stripped)):
        cleaned = candidate.strip()
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise RuntimeError("MiniMax structured response was not valid JSON.") from last_error


def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def _json_object_candidate(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


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


def _schema_requires(schema: Mapping[str, object], field: str) -> bool:
    required = schema.get("required")
    return isinstance(required, list) and field in required
