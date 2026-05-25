import json
import unittest
from pathlib import Path

from dating_boost.intelligence.backends import BackendCapability, ScriptedBackend


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

    def test_backend_declares_capabilities(self):
        backend = ScriptedBackend({"ok": True})

        self.assertIn(BackendCapability.GENERATE_STRUCTURED, backend.capabilities)


if __name__ == "__main__":
    unittest.main()
