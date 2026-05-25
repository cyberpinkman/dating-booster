import json
import unittest
from pathlib import Path

from dating_boost.core.models import ReplyMode
from dating_boost.intelligence.backends import ScriptedBackend
from dating_boost.intelligence.reply_generator import generate_reply


class ReplyGeneratorTests(unittest.TestCase):
    def test_generate_reply_returns_structured_drafts(self):
        backend = ScriptedBackend(
            json.loads(Path("tests/fixtures/intelligence/scripted_reply.json").read_text(encoding="utf-8"))
        )
        context_pack = {
            "reply_mode": ReplyMode.ADAPTIVE.value,
            "items": [
                {"label": "latest_message", "content": "What are you up to this weekend?"},
                {"label": "match_hooks", "content": ["live music"]},
            ],
            "safety_constraints": ["Do not invent hard facts."],
        }

        response = generate_reply(context_pack, ReplyMode.ADAPTIVE, backend)

        self.assertEqual(response.best_reply, "Sounds fun. Any good live music spots you recommend?")
        self.assertEqual(response.persona_divergence.value, "low")
        self.assertEqual(response.stance_divergence.value, "low")


if __name__ == "__main__":
    unittest.main()
