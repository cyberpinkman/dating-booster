"""Small, bounded TypeSafe HTTP client for typed semantic judgments.

Protocol: https://docs.typesafe.ai/api. Independent questions share one request.
Jev supplies judgments, not generated replies or permission to perform actions.
No request state, credentials, or service error bodies are logged or retained.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


TYPESAFE_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_RESPONSE_BYTES = 1024 * 1024
Transport = Callable[[Request, float], bytes]


class TypeSafeError(RuntimeError):
    """A fixed diagnostic code safe to include in local operational metrics."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


@dataclass(frozen=True)
class NoulAnswer:
    noul: float


@dataclass(frozen=True)
class EvaluationResult:
    answers: Mapping[str, ChoiceAnswer | NoulAnswer]
    model: str
    duration_ms: float
    input_tokens: int | None
    output_tokens: int | None


class _NoRedirect(HTTPRedirectHandler):
    # urllib otherwise forwards Authorization to redirected destinations.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_transport(request: Request, timeout_seconds: float) -> bytes:
    with build_opener(_NoRedirect()).open(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise TypeSafeError("typesafe_http_error")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise TypeSafeError("typesafe_response_too_large")
        return body


class TypeSafeClient:
    """One request, no automatic retries, and a configurable short socket timeout.

    A transport can be injected for offline tests; it receives a urllib Request
    and the timeout, and returns response bytes. The production endpoint is fixed
    and redirects are rejected so credentials cannot follow a service redirect.
    """

    def __init__(
        self,
        *,
        model: str = "jev-latest",
        api_key_env: str = "TYPESAFE_API_KEY",
        timeout_seconds: float = 5.0,
        transport: Transport | None = None,
    ):
        if not isinstance(model, str) or not model.strip():
            raise TypeSafeError("typesafe_invalid_model")
        if not isinstance(api_key_env, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env) is None:
            raise TypeSafeError("typesafe_invalid_api_key_env")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 30
            or not math.isfinite(timeout_seconds)
        ):
            raise TypeSafeError("typesafe_invalid_timeout")
        api_key = os.environ.get(api_key_env, "").strip()
        if not api_key:
            raise TypeSafeError("typesafe_api_key_missing")
        if any(character.isspace() for character in api_key):
            raise TypeSafeError("typesafe_api_key_invalid")
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self._api_key = api_key
        self._transport = transport if transport is not None else _http_transport

    def evaluate(self, *, state: str | dict | list, questions: Mapping[str, Any]) -> EvaluationResult:
        _validate_questions(questions)
        if not isinstance(state, (str, dict, list)):
            raise TypeSafeError("typesafe_invalid_state")
        try:
            body = json.dumps(
                {"model": self.model, "state": state, "questions": dict(questions)},
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise TypeSafeError("typesafe_invalid_request") from None
        request = Request(
            TYPESAFE_ENDPOINT,
            data=body,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            response_body = self._transport(request, self.timeout_seconds)
        except HTTPError as exc:
            reason = _http_error_reason(exc.code)
            exc.close()
            raise TypeSafeError(reason) from None
        except TimeoutError:
            raise TypeSafeError("typesafe_timeout") from None
        except URLError as exc:
            reason = "typesafe_timeout" if isinstance(exc.reason, TimeoutError) else "typesafe_connection_error"
            raise TypeSafeError(reason) from None
        except TypeSafeError:
            raise
        except Exception:
            # Transport implementations may attach request data to exceptions.
            raise TypeSafeError("typesafe_transport_error") from None
        if not isinstance(response_body, bytes):
            raise TypeSafeError("typesafe_invalid_response")
        if len(response_body) > MAX_RESPONSE_BYTES:
            raise TypeSafeError("typesafe_response_too_large")
        try:
            payload = json.loads(response_body, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise TypeSafeError("typesafe_invalid_response") from None
        return _parse_response(payload, questions, max(0.0, (time.monotonic() - started) * 1000))


def _validate_questions(questions: Mapping[str, Any]) -> None:
    if not isinstance(questions, Mapping) or not questions:
        raise TypeSafeError("typesafe_invalid_questions")
    for question_id, question in questions.items():
        if not isinstance(question_id, str) or not question_id or not isinstance(question, dict):
            raise TypeSafeError("typesafe_invalid_questions")
        if not isinstance(question.get("instructions"), (str, dict, list)) or not question["instructions"]:
            raise TypeSafeError("typesafe_invalid_questions")
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "choice":
            if not isinstance(criteria, dict) or not criteria:
                raise TypeSafeError("typesafe_invalid_questions")
            if any(not isinstance(key, str) or not key for key in criteria):
                raise TypeSafeError("typesafe_invalid_questions")
            if any(value is not None and not isinstance(value, (str, dict, list)) for value in criteria.values()):
                raise TypeSafeError("typesafe_invalid_questions")
        elif kind == "noul":
            if criteria is not None and (
                not isinstance(criteria, dict)
                or not set(criteria).issubset({"true", "false"})
                or any(not isinstance(value, (str, dict, list)) for value in criteria.values())
            ):
                raise TypeSafeError("typesafe_invalid_questions")
        else:
            raise TypeSafeError("typesafe_unsupported_question_type")


def _parse_response(payload: Any, questions: Mapping[str, Any], duration_ms: float) -> EvaluationResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str) or not payload["model"].strip():
        raise TypeSafeError("typesafe_invalid_response")
    raw_answers = payload.get("answers")
    if not isinstance(raw_answers, dict) or set(raw_answers) != set(questions):
        raise TypeSafeError("typesafe_answer_ids_mismatch")
    answers: dict[str, ChoiceAnswer | NoulAnswer] = {}
    for question_id, question in questions.items():
        raw = raw_answers[question_id]
        if not isinstance(raw, dict) or raw.get("type") != question["type"]:
            raise TypeSafeError("typesafe_answer_type_mismatch")
        if question["type"] == "noul":
            answers[question_id] = NoulAnswer(noul=_probability(raw.get("noul")))
            continue
        choice, probabilities = raw.get("choice"), raw.get("probabilities")
        if not isinstance(choice, str) or choice not in question["criteria"]:
            raise TypeSafeError("typesafe_invalid_choice")
        if not isinstance(probabilities, dict) or set(probabilities) != set(question["criteria"]):
            raise TypeSafeError("typesafe_invalid_distribution")
        distribution = {key: _probability(value) for key, value in probabilities.items()}
        if not math.isclose(math.fsum(distribution.values()), 1.0, rel_tol=0, abs_tol=1e-5):
            raise TypeSafeError("typesafe_invalid_distribution")
        if distribution[choice] < max(distribution.values()):
            raise TypeSafeError("typesafe_invalid_choice")
        answers[question_id] = ChoiceAnswer(
            choice=choice,
            confidence=_probability(raw.get("confidence")),
            probabilities=MappingProxyType(distribution),
        )
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise TypeSafeError("typesafe_invalid_usage")
    return EvaluationResult(
        answers=MappingProxyType(answers),
        model=payload["model"],
        duration_ms=duration_ms,
        input_tokens=_token_count(usage.get("input_tokens")),
        output_tokens=_token_count(usage.get("output_tokens")),
    )


def _probability(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1 or not math.isfinite(value):
        raise TypeSafeError("typesafe_invalid_probability")
    return float(value)


def _token_count(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise TypeSafeError("typesafe_invalid_usage")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite number")


def _http_error_reason(status: int) -> str:
    if 300 <= status < 400:
        return "typesafe_redirect_blocked"
    return {
        401: "typesafe_authentication_failed",
        403: "typesafe_authentication_failed",
        422: "typesafe_request_rejected",
        429: "typesafe_rate_limited",
        529: "typesafe_overloaded",
    }.get(status, "typesafe_http_error")
