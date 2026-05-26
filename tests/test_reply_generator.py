import json
import unittest
from pathlib import Path

from dating_boost.core.models import ReplyMode
from dating_boost.intelligence.backends import BackendCapability, ScriptedBackend
from dating_boost.intelligence.prompts import REPLY_SCHEMA
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
        self.assertEqual(response.situation_read, "Match asked about weekend plans; user can bridge to live music.")
        self.assertEqual(response.conversation_move, "deepen_hook")
        self.assertEqual(response.hook_source, "profile_unknown_detail")
        self.assertIn("asks for a specific unknown detail", response.naturalness_notes)
        self.assertEqual(response.followup_if_match_replies, "If they name a venue, ask what kind of shows they like.")
        self.assertEqual(response.persona_divergence.value, "low")
        self.assertEqual(response.stance_divergence.value, "low")

    def test_reply_schema_requires_strategy_and_naturalness_fields(self):
        for field_name in (
            "situation_read",
            "conversation_move",
            "hook_source",
            "naturalness_notes",
            "followup_if_match_replies",
        ):
            self.assertIn(field_name, REPLY_SCHEMA["required"])
            self.assertIn(field_name, REPLY_SCHEMA["properties"])

    def test_core_prompt_includes_strategy_and_chinese_naturalness_guidance(self):
        backend = CapturingBackend(
            json.loads(Path("tests/fixtures/intelligence/scripted_reply.json").read_text(encoding="utf-8"))
        )
        context_pack = {
            "reply_mode": ReplyMode.ADAPTIVE.value,
            "language": "zh-CN",
            "items": [
                {"label": "latest_message", "content": "挺不错的"},
                {"label": "match_hooks", "content": ["电影", "唱歌", "夜猫子"]},
            ],
            "safety_constraints": ["Respect hard facts."],
        }

        generate_reply(context_pack, ReplyMode.ADAPTIVE, backend)

        system_prompt = backend.system_prompt.lower()
        for phrase in (
            "situation_read",
            "conversation_move",
            "hook_source",
            "naturalness_notes",
            "followup_if_match_replies",
            "chinese",
            "unknown details",
            "one short question",
            "question is optional",
            "answer or riff",
            "do not force a question",
            "take_the_lead",
            "delegates the choice",
            "do not ask them to decide again",
            "multi-option",
            "tag stacking",
            "hard facts",
        ):
            self.assertIn(phrase, system_prompt)
        self.assertIs(backend.schema, REPLY_SCHEMA)


class CapturingBackend:
    def __init__(self, payload):
        self._payload = dict(payload)
        self.system_prompt = ""
        self.user_prompt = ""
        self.schema = {}

    @property
    def capabilities(self):
        return frozenset({BackendCapability.GENERATE_STRUCTURED})

    def generate_structured(self, system_prompt, user_prompt, schema):
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.schema = schema
        return dict(self._payload)


if __name__ == "__main__":
    unittest.main()
