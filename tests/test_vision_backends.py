from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dating_boost.intelligence.vision_backend_factory import create_vision_backend
from dating_boost.intelligence.vision_backends import MiniMaxVisionBackend


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
