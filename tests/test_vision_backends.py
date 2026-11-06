from pathlib import Path
import base64
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from dating_boost.intelligence.vision_backend_factory import create_vision_backend
from dating_boost.intelligence.vision_backends import MiniMaxVisionBackend, OpenAIVisionBackend, ScriptedVisionBackend


def _recording_backend(kind):
    payload = {"status": "ok", "same_thread": True}
    response = SimpleNamespace(
        model="response-model",
        system_fingerprint="revision-1",
        deployment_id="deployment-1",
        output_parsed=payload,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(name="emit_structured_response", arguments=json.dumps(payload))
                        )
                    ],
                    content=None,
                )
            )
        ],
    )
    create = Mock(return_value=response)
    endpoint = SimpleNamespace(create=create)
    if kind == "minimax":
        backend = MiniMaxVisionBackend(client=SimpleNamespace(chat=SimpleNamespace(completions=endpoint)))
    else:
        client_constructor = Mock(return_value=SimpleNamespace(responses=endpoint))
        with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=client_constructor)}):
            backend = OpenAIVisionBackend(model="configured-model")
    return backend, create


@pytest.mark.parametrize("kind", ["openai", "minimax"])
def test_multi_image_uses_one_ordered_structured_request_and_records_identity(kind, tmp_path):
    paths = [tmp_path / "before.png", tmp_path / "after.jpg", tmp_path / "detail.webp"]
    image_bytes = [b"before image", b"after image", b"detail image"]
    for path, data in zip(paths, image_bytes):
        path.write_bytes(data)
    backend, create = _recording_backend(kind)
    schema = {"type": "object", "properties": {"same_thread": {"type": "boolean"}}}

    payload = backend.analyze_images_structured("system", "compare these images in order", tuple(paths), schema)

    assert payload == {"status": "ok", "same_thread": True}
    create.assert_called_once()
    call = create.call_args.kwargs
    messages = call["input" if kind == "openai" else "messages"]
    assert messages[0] == {"role": "system", "content": "system"}
    assert messages[1]["role"] == "user"
    content = messages[1]["content"]
    assert content[0] == {
        "type": "input_text" if kind == "openai" else "text",
        "text": "compare these images in order",
    }
    assert len(content) == 4
    urls = [item["image_url"] if kind == "openai" else item["image_url"]["url"] for item in content[1:]]
    assert [url.split(";", 1)[0] for url in urls] == ["data:image/png", "data:image/jpeg", "data:image/webp"]
    assert [base64.b64decode(url.split(",", 1)[1]) for url in urls] == image_bytes
    if kind == "openai":
        assert [item["type"] for item in content[1:]] == ["input_image"] * 3
        assert call["model"] == "configured-model"
        assert call["text"]["format"] == {
            "type": "json_schema", "name": "vision_response", "schema": schema, "strict": True,
        }
    else:
        assert [item["type"] for item in content[1:]] == ["image_url"] * 3
        assert [item["image_url"]["detail"] for item in content[1:]] == ["high"] * 3
        assert call["tools"][0]["function"]["parameters"] == schema
        assert call["tool_choice"] == {"type": "function", "function": {"name": "emit_structured_response"}}
        assert call["extra_body"] == {"thinking": {"type": "disabled"}, "reasoning_split": True}
    assert backend.last_response_identity == {
        "response_model_identifier": "response-model",
        "revision_identifier": "revision-1",
        "stable_provider_identifier": "deployment-1",
    }


@pytest.mark.parametrize("kind", ["openai", "minimax"])
def test_single_image_matches_the_same_one_image_request(kind, tmp_path):
    path = tmp_path / "screen.png"
    path.write_bytes(b"synthetic image")
    backend, create = _recording_backend(kind)

    single = backend.analyze_image_structured("system", "user", path, {"type": "object"})
    multi = backend.analyze_images_structured("system", "user", [path], {"type": "object"})

    assert single == multi
    assert create.call_count == 2
    assert create.call_args_list[0] == create.call_args_list[1]


@pytest.mark.parametrize("kind", ["openai", "minimax", "scripted"])
def test_empty_images_fail_before_request_or_consuming_scripted_payload(kind):
    if kind == "scripted":
        backend, create = ScriptedVisionBackend([{"index": 1}, {"index": 2}]), None
    else:
        backend, create = _recording_backend(kind)

    with pytest.raises(ValueError, match="^vision_backend_images_required$"):
        backend.analyze_images_structured("system", "user", [], {"type": "object"})

    if create is not None:
        create.assert_not_called()
        assert backend.last_response_identity is None
    else:
        assert backend.analyze_image_structured("system", "user", Path("unused.png"), {}) == {"index": 1}


@pytest.mark.parametrize("kind", ["openai", "minimax"])
def test_multi_image_does_not_send_a_partial_request_when_a_later_image_is_missing(kind, tmp_path):
    first = tmp_path / "before.png"
    first.write_bytes(b"synthetic image")
    backend, create = _recording_backend(kind)

    with pytest.raises(FileNotFoundError):
        backend.analyze_images_structured("system", "user", [first, tmp_path / "missing.png"], {})

    create.assert_not_called()


@pytest.mark.parametrize("kind", ["openai", "minimax"])
def test_multi_image_does_not_add_application_retries(kind, tmp_path):
    path = tmp_path / "screen.png"
    path.write_bytes(b"synthetic image")
    backend, create = _recording_backend(kind)
    create.side_effect = TimeoutError("synthetic timeout")

    with pytest.raises(TimeoutError):
        backend.analyze_images_structured("system", "user", [path, path], {})

    create.assert_called_once()


def test_scripted_multi_image_consumes_one_payload_and_keeps_copies_independent():
    backend = ScriptedVisionBackend([{"values": [1]}, {"values": [2]}])
    first = backend.analyze_images_structured("system", "user", [Path("before.png"), Path("after.png")], {})
    second = backend.analyze_image_structured("system", "user", Path("next.png"), {})
    assert first == {"values": [1]}
    assert second == {"values": [2]}
    second["values"].append(3)
    assert backend.analyze_images_structured("system", "user", (Path("last.png"),), {}) == {"values": [2]}
    assert backend.last_response_identity == {"response_model_identifier": "scripted", "revision_identifier": "scripted"}


class VisionBackendFactoryTests(unittest.TestCase):
    def test_scripted_vision_backend_returns_payloads_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vision.json"
            path.write_text(
                json.dumps([{"status": "ok", "kind": "list"}, {"status": "ok", "kind": "thread"}]),
                encoding="utf-8",
            )
            backend = create_vision_backend({"type": "scripted", "path": str(path)})
            first = backend.analyze_image_structured("system", "user", Path("screen1.png"), {"type": "object"})
            second = backend.analyze_image_structured("system", "user", Path("screen2.png"), {"type": "object"})
        self.assertEqual(first["kind"], "list")
        self.assertEqual(second["kind"], "thread")

    def test_scripted_vision_backend_requires_path(self):
        with self.assertRaises(ValueError) as raised:
            create_vision_backend({"type": "scripted"})
        self.assertEqual(str(raised.exception), "scripted_vision_backend_path_required")

    def test_scripted_vision_backend_rejects_empty_payload_array(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vision.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                create_vision_backend({"type": "scripted", "path": str(path)})
        self.assertEqual(str(raised.exception), "scripted_vision_backend_output_must_be_object_or_non_empty_array")

    def test_minimax_vision_backend_uses_image_url_and_forced_tool_call(self):
        class FakeCompletions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="emit_structured_response",
                                            arguments=json.dumps({"status": "ok", "rows": []}),
                                        )
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "screen.png"
            image_path.write_bytes(b"fake png bytes")
            completions = FakeCompletions()
            fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
            schema = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}
            backend = MiniMaxVisionBackend(client=fake_client)

            payload = backend.analyze_image_structured("system", "user", image_path, schema)

        self.assertEqual(payload, {"status": "ok", "rows": []})
        call = completions.calls[0]
        self.assertEqual(call["model"], "MiniMax-M3")
        user_content = call["messages"][1]["content"]
        self.assertEqual(user_content[0], {"type": "text", "text": "user"})
        self.assertEqual(user_content[1]["type"], "image_url")
        self.assertTrue(user_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(call["tool_choice"], {"type": "function", "function": {"name": "emit_structured_response"}})
        self.assertEqual(call["extra_body"], {"thinking": {"type": "disabled"}, "reasoning_split": True})

    def test_factory_creates_minimax_vision_backend(self):
        class FakeMiniMaxVisionBackend:
            created_configs: list[dict[str, object]] = []

            def __init__(self, **kwargs):
                self.created_configs.append(dict(kwargs))

        with patch("dating_boost.intelligence.vision_backend_factory.MiniMaxVisionBackend", FakeMiniMaxVisionBackend):
            backend = create_vision_backend(
                {
                    "type": "minimax",
                    "model": "MiniMax-M3",
                    "base_url": "https://api.minimax.io/v1",
                    "api_key_env": "MINIMAX_API_KEY",
                }
            )

        self.assertIsInstance(backend, FakeMiniMaxVisionBackend)
        self.assertEqual(
            FakeMiniMaxVisionBackend.created_configs,
            [
                {
                    "model": "MiniMax-M3",
                    "base_url": "https://api.minimax.io/v1",
                    "api_key_env": "MINIMAX_API_KEY",
                }
            ],
        )

    def test_factory_creates_minimax_vision_backend_with_timeout_config(self):
        class FakeMiniMaxVisionBackend:
            created_configs: list[dict[str, object]] = []

            def __init__(self, **kwargs):
                self.created_configs.append(dict(kwargs))

        with patch("dating_boost.intelligence.vision_backend_factory.MiniMaxVisionBackend", FakeMiniMaxVisionBackend):
            backend = create_vision_backend({"type": "minimax", "timeout_seconds": 18})

        self.assertIsInstance(backend, FakeMiniMaxVisionBackend)
        self.assertEqual(FakeMiniMaxVisionBackend.created_configs[0]["timeout_seconds"], 18)

    def test_factory_creates_minimax_vision_backend_with_cn_default_base_url(self):
        class FakeMiniMaxVisionBackend:
            created_configs: list[dict[str, object]] = []

            def __init__(self, **kwargs):
                self.created_configs.append(dict(kwargs))

        with patch("dating_boost.intelligence.vision_backend_factory.MiniMaxVisionBackend", FakeMiniMaxVisionBackend):
            backend = create_vision_backend({"type": "minimax"})

        self.assertIsInstance(backend, FakeMiniMaxVisionBackend)
        self.assertEqual(
            FakeMiniMaxVisionBackend.created_configs,
            [
                {
                    "model": "MiniMax-M3",
                    "base_url": "https://api.minimaxi.com/v1",
                    "api_key_env": "MINIMAX_API_KEY",
                }
            ],
        )
