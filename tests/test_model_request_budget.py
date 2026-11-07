"""Keep network retries visible to the managed workflow's recovery policy."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.intelligence.backends import MiniMaxBackend, OpenAIBackend
from dating_boost.intelligence.vision_backends import MiniMaxVisionBackend, OpenAIVisionBackend


@pytest.mark.parametrize("backend_type", [MiniMaxBackend, MiniMaxVisionBackend, OpenAIBackend, OpenAIVisionBackend])
def test_model_clients_bound_each_request_without_hidden_sdk_retries(backend_type, monkeypatch):
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=constructor))
    monkeypatch.delenv("DATING_BOOST_MINIMAX_REQUEST_TIMEOUT_SECONDS", raising=False)

    backend_type(api_key="synthetic-test-key")

    options = constructor.call_args.kwargs
    assert options["max_retries"] == 0
    assert options["timeout"] == 45.0


@pytest.mark.parametrize("backend_type", [MiniMaxBackend, MiniMaxVisionBackend])
def test_minimax_explicit_request_timeout_reaches_sdk(backend_type, monkeypatch):
    constructor = Mock()
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=constructor))

    backend_type(api_key="synthetic-test-key", timeout_seconds=7)

    assert constructor.call_args.kwargs["timeout"] == 7
    assert constructor.call_args.kwargs["max_retries"] == 0
