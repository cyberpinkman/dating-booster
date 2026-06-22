import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from dating_boost.intelligence.backends import BackendCapability, MiniMaxBackend, ScriptedBackend


class BackendTests(unittest.TestCase):
    def test_scripted_backend_returns_structured_payload(self):
        payload = json.loads(Path("tests/fixtures/intelligence/scripted_reply.json").read_text(encoding="utf-8"))
        backend = ScriptedBackend(payload)

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )

        self.assertEqual(result["best_reply"], "Sounds fun. Any good live music spots you recommend?")

    def test_scripted_backend_isolated_from_original_payload_mutation(self):
        payload = {"reply": {"text": "Original"}, "risk_flags": []}
        backend = ScriptedBackend(payload)

        payload["reply"]["text"] = "Changed"
        payload["risk_flags"].append("mutated")

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )

        self.assertEqual(result["reply"]["text"], "Original")
        self.assertEqual(result["risk_flags"], [])

    def test_scripted_backend_returns_isolated_results(self):
        backend = ScriptedBackend({"reply": {"text": "Original"}, "risk_flags": []})

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )
        result["reply"]["text"] = "Changed"
        result["risk_flags"].append("mutated")

        next_result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )

        self.assertEqual(next_result["reply"]["text"], "Original")
        self.assertEqual(next_result["risk_flags"], [])

    def test_backend_declares_capabilities(self):
        backend = ScriptedBackend({"ok": True})

        self.assertIn(BackendCapability.GENERATE_STRUCTURED, backend.capabilities)

    def test_minimax_backend_uses_forced_tool_call_for_structured_output(self):
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
                                            arguments=json.dumps({"best_reply": "你好呀"}),
                                        )
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )

        completions = FakeCompletions()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        schema = {
            "type": "object",
            "required": ["best_reply"],
            "properties": {"best_reply": {"type": "string"}},
            "additionalProperties": False,
        }
        backend = MiniMaxBackend(client=fake_client)

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema=schema,
        )

        self.assertEqual(result, {"best_reply": "你好呀"})
        call = completions.calls[0]
        self.assertEqual(call["model"], "MiniMax-M3")
        self.assertEqual(call["messages"][0], {"role": "system", "content": "Return draft JSON."})
        self.assertEqual(call["messages"][1], {"role": "user", "content": "Draft a reply."})
        self.assertEqual(call["tool_choice"], {"type": "function", "function": {"name": "emit_structured_response"}})
        self.assertEqual(call["tools"][0]["function"]["parameters"], schema)
        self.assertEqual(call["extra_body"], {"thinking": {"type": "disabled"}, "reasoning_split": True})

    def test_minimax_backend_extracts_json_from_wrapped_tool_arguments(self):
        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="emit_structured_response",
                                            arguments='```json\n{"best_reply":"你好呀"}\n```',
                                        )
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        backend = MiniMaxBackend(client=fake_client)

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )

        self.assertEqual(result, {"best_reply": "你好呀"})

    def test_minimax_backend_extracts_json_from_stringified_tool_arguments(self):
        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        function=SimpleNamespace(
                                            name="emit_structured_response",
                                            arguments=json.dumps('{"best_reply":"你好呀"}'),
                                        )
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        backend = MiniMaxBackend(client=fake_client)

        result = backend.generate_structured(
            system_prompt="Return draft JSON.",
            user_prompt="Draft a reply.",
            schema={"type": "object"},
        )

        self.assertEqual(result, {"best_reply": "你好呀"})


if __name__ == "__main__":
    unittest.main()
