from __future__ import annotations

import copy
import json
import traceback
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from dating_boost.intelligence.typesafe import (
    MAX_RESPONSE_BYTES,
    TYPESAFE_ENDPOINT,
    ChoiceAnswer,
    NoulAnswer,
    TypeSafeClient,
    TypeSafeError,
    _http_transport,
    _NoRedirect,
)


pytestmark = pytest.mark.managed_critical

QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "Does the visible conversation require another ordinary reply?",
        "criteria": {"reply": "An unanswered question", "wait": "A clear closing", "uncertain": "Insufficient evidence"},
    },
    "needs_user": {"type": "noul", "instructions": "Does this require the user's personal decision?"},
}


def _response() -> dict:
    return {
        "model": "jev-test",
        "answers": {
            "route": {
                "type": "choice",
                "choice": "wait",
                "confidence": 0.93,
                "probabilities": {"reply": 0.02, "wait": 0.97, "uncertain": 0.01},
            },
            "needs_user": {"type": "noul", "noul": 0.02},
        },
        "usage": {"input_tokens": 123, "output_tokens": 45},
    }


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_UNIT_TEST_KEY", "only-a-unit-test-key")
    return "TYPESAFE_UNIT_TEST_KEY"


def _client(key, payload=None):
    transport = Mock(return_value=json.dumps(_response() if payload is None else payload).encode())
    return TypeSafeClient(api_key_env=key, transport=transport), transport


def test_evaluation_batches_typed_questions_and_retains_only_answers_and_usage(key) -> None:
    client, transport = _client(key)
    state = {"conversation": [{"sender": "match", "text": "好呀，晚点聊"}]}
    result = client.evaluate(state=state, questions=QUESTIONS)
    transport.assert_called_once()
    request, timeout = transport.call_args.args
    assert request.full_url == TYPESAFE_ENDPOINT
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer only-a-unit-test-key"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 5.0
    assert json.loads(request.data) == {"model": "jev-latest", "state": state, "questions": QUESTIONS}
    assert result.answers["route"] == ChoiceAnswer("wait", 0.93, {"reply": 0.02, "wait": 0.97, "uncertain": 0.01})
    assert result.answers["needs_user"] == NoulAnswer(0.02)
    assert result.model == "jev-test"
    assert (result.input_tokens, result.output_tokens) == (123, 45)
    assert result.duration_ms >= 0
    assert "晚点聊" not in repr(result)
    assert "only-a-unit-test-key" not in repr(client)
    with pytest.raises(TypeError):
        result.answers["route"].probabilities["wait"] = 0


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"model": ""}, "typesafe_invalid_model"),
        ({"model": None}, "typesafe_invalid_model"),
        ({"api_key_env": "../secret"}, "typesafe_invalid_api_key_env"),
        ({"api_key_env": ""}, "typesafe_invalid_api_key_env"),
        *[({"timeout_seconds": value}, "typesafe_invalid_timeout") for value in (0, -1, 31, True, "5", float("inf"), float("nan"), 10**400)],
    ],
)
def test_configuration_is_validated_before_transport(key, kwargs, reason) -> None:
    settings = {"api_key_env": key, **kwargs}
    with pytest.raises(TypeSafeError, match=f"^{reason}$"):
        TypeSafeClient(**settings)


def test_missing_key_is_reported_before_any_observation_or_network(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_TYPESAFE_UNIT_TEST_KEY", raising=False)
    transport = Mock()
    with pytest.raises(TypeSafeError, match="^typesafe_api_key_missing$"):
        TypeSafeClient(api_key_env="MISSING_TYPESAFE_UNIT_TEST_KEY", transport=transport)
    transport.assert_not_called()


def test_only_explicit_key_environment_variable_is_read(key) -> None:
    with patch("dating_boost.intelligence.typesafe.os.environ.get", return_value="unit-key") as read:
        TypeSafeClient(api_key_env=key)
    read.assert_called_once_with(key, "")


@pytest.mark.parametrize("value", ["bad\nkey", "bad\rkey", "bad key"])
def test_invalid_key_cannot_inject_http_headers(monkeypatch, key, value) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(TypeSafeError, match="^typesafe_api_key_invalid$"):
        TypeSafeClient(api_key_env=key)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("answers",), {}, "typesafe_answer_ids_mismatch"),
        (("answers", "extra"), {"type": "noul", "noul": 1}, "typesafe_answer_ids_mismatch"),
        (("answers", "route", "type"), "noul", "typesafe_answer_type_mismatch"),
        (("answers", "route", "choice"), "unknown", "typesafe_invalid_choice"),
        (("answers", "route", "choice"), ["wait"], "typesafe_invalid_choice"),
        (("answers", "route", "choice"), "reply", "typesafe_invalid_choice"),
        (("answers", "route", "probabilities"), {"wait": 1}, "typesafe_invalid_distribution"),
        (("answers", "route", "probabilities", "unknown"), 0, "typesafe_invalid_distribution"),
        (("answers", "route", "probabilities", "wait"), 0.2, "typesafe_invalid_distribution"),
        (("answers", "route", "probabilities", "wait"), "0.97", "typesafe_invalid_probability"),
        (("answers", "route", "confidence"), True, "typesafe_invalid_probability"),
        (("answers", "route", "confidence"), 1.01, "typesafe_invalid_probability"),
        (("answers", "needs_user", "noul"), -0.1, "typesafe_invalid_probability"),
        (("answers", "needs_user", "noul"), None, "typesafe_invalid_probability"),
        (("answers", "needs_user", "noul"), 10**400, "typesafe_invalid_probability"),
        (("model",), None, "typesafe_invalid_response"),
        (("model",), " ", "typesafe_invalid_response"),
        (("usage",), None, "typesafe_invalid_usage"),
        (("usage", "input_tokens"), -1, "typesafe_invalid_usage"),
        (("usage", "output_tokens"), True, "typesafe_invalid_usage"),
        (("usage", "output_tokens"), 1.2, "typesafe_invalid_usage"),
    ],
)
def test_response_contract_rejects_invalid_answers(key, path, value, reason) -> None:
    payload = _response()
    target = payload
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value
    client, _ = _client(key, payload)
    with pytest.raises(TypeSafeError, match=f"^{reason}$"):
        client.evaluate(state="private conversation", questions=QUESTIONS)


@pytest.mark.parametrize("body", [b"not json", b'{"model":"one","model":"two"}', b'{"value":NaN}', b'{"value":Infinity}', b"\xff", b"[]"])
def test_malformed_service_json_is_not_in_diagnostics(key, body) -> None:
    client = TypeSafeClient(api_key_env=key, transport=Mock(return_value=body))
    with pytest.raises(TypeSafeError, match="^typesafe_invalid_response$"):
        client.evaluate(state="private conversation", questions=QUESTIONS)


def test_non_finite_json_number_is_rejected(key) -> None:
    body = json.dumps(_response()).replace('"noul": 0.02', '"noul": 1e999').encode()
    client = TypeSafeClient(api_key_env=key, transport=Mock(return_value=body))
    with pytest.raises(TypeSafeError, match="^typesafe_invalid_probability$"):
        client.evaluate(state="private conversation", questions=QUESTIONS)


@pytest.mark.parametrize(
    ("status", "reason"),
    [(302, "typesafe_redirect_blocked"), (401, "typesafe_authentication_failed"), (422, "typesafe_request_rejected"),
     (429, "typesafe_rate_limited"), (529, "typesafe_overloaded"), (500, "typesafe_http_error")],
)
def test_http_failures_are_not_retried_or_reported_with_sensitive_details(key, status, reason) -> None:
    body = BytesIO(b"private error response body")
    transport = Mock(side_effect=HTTPError("https://private-url", status, "private error detail", {}, body))
    client = TypeSafeClient(api_key_env=key, transport=transport)
    with pytest.raises(TypeSafeError) as caught:
        client.evaluate(state="private conversation", questions=QUESTIONS)
    assert caught.value.reason == reason
    diagnostic = "".join(traceback.format_exception(caught.value))
    assert all(marker not in diagnostic for marker in ("private-url", "private error detail", "private error response body"))
    assert body.closed
    transport.assert_called_once()


@pytest.mark.parametrize(
    ("error", "reason"),
    [(TimeoutError("secret"), "typesafe_timeout"), (URLError(TimeoutError("secret")), "typesafe_timeout"),
     (URLError("secret"), "typesafe_connection_error"), (RuntimeError("secret"), "typesafe_transport_error")],
)
def test_transport_errors_are_redacted_and_never_retried(key, error, reason) -> None:
    transport = Mock(side_effect=error)
    client = TypeSafeClient(api_key_env=key, transport=transport)
    with pytest.raises(TypeSafeError) as caught:
        client.evaluate(state="private conversation", questions=QUESTIONS)
    assert str(caught.value) == reason
    assert "secret" not in "".join(traceback.format_exception(caught.value))
    transport.assert_called_once()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_handler_never_creates_a_redirected_request(status) -> None:
    request = Request(TYPESAFE_ENDPOINT, data=b"{}", headers={"Authorization": "Bearer unit-test-key"})
    assert _NoRedirect().redirect_request(request, None, status, "redirect", {}, "https://other-host.invalid") is None


def test_production_transport_uses_redirect_blocker_and_response_size_bound() -> None:
    response = Mock(status=200)
    response.read.return_value = b"{}"
    opener = Mock()
    opener.open.return_value.__enter__ = Mock(return_value=response)
    opener.open.return_value.__exit__ = Mock(return_value=False)
    request = Request(TYPESAFE_ENDPOINT)
    with patch("dating_boost.intelligence.typesafe.build_opener", return_value=opener) as build:
        assert _http_transport(request, 3.0) == b"{}"
    assert isinstance(build.call_args.args[0], _NoRedirect)
    opener.open.assert_called_once_with(request, timeout=3.0)
    response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)


def test_oversized_response_is_rejected(key) -> None:
    client = TypeSafeClient(api_key_env=key, transport=Mock(return_value=b" " * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(TypeSafeError, match="^typesafe_response_too_large$"):
        client.evaluate(state="conversation", questions=QUESTIONS)


def test_invalid_request_never_calls_transport(key) -> None:
    client, transport = _client(key)
    invalid_questions = copy.deepcopy(QUESTIONS)
    invalid_questions["route"]["criteria"]["bad"] = True
    with pytest.raises(TypeSafeError, match="^typesafe_invalid_questions$"):
        client.evaluate(state="conversation", questions=invalid_questions)
    with pytest.raises(TypeSafeError, match="^typesafe_invalid_request$"):
        client.evaluate(state={"value": float("nan")}, questions=QUESTIONS)
    with pytest.raises(TypeSafeError, match="^typesafe_invalid_state$"):
        client.evaluate(state=None, questions=QUESTIONS)
    transport.assert_not_called()


def test_missing_optional_usage_is_unavailable_not_zero(key) -> None:
    payload = _response()
    payload["usage"] = {}
    client, _ = _client(key, payload)
    result = client.evaluate(state="conversation", questions=QUESTIONS)
    assert result.input_tokens is None and result.output_tokens is None


def test_tied_highest_probability_is_a_valid_choice(key) -> None:
    payload = _response()
    payload["answers"]["route"]["probabilities"] = {"reply": 0.5, "wait": 0.5, "uncertain": 0}
    client, _ = _client(key, payload)
    assert client.evaluate(state="conversation", questions=QUESTIONS).answers["route"].choice == "wait"
