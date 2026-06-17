import unittest

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.models import ReplyMode


class ContextPackTests(unittest.TestCase):
    def test_context_pack_prioritizes_boundaries_and_latest_message(self):
        pack = build_context_pack(
            user_profile={
                "boundaries": [{"content": {"text": "Do not claim overseas study"}}],
                "facts": [{"content": {"education": "Chinese university graduate"}}],
                "style_examples": ["short dry humor"],
            },
            match_profile={
                "possible_interests": [{"label": "live music", "confidence": "high"}],
                "conversation_hooks": ["Ask about recent concert"],
            },
            conversation_memory={
                "recent_messages": [
                    {"sender": "match", "text": "What are you up to this weekend?"}
                ],
                "open_threads": ["weekend plan question"],
                "commitments": [],
                "running_summary": "They discussed concerts.",
            },
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=6,
        )

        labels = [item["label"] for item in pack["items"]]

        self.assertLess(labels.index("user_boundaries"), labels.index("match_hooks"))
        self.assertLess(labels.index("latest_message"), labels.index("conversation_summary"))
        self.assertEqual(pack["reply_mode"], "adaptive")

    def test_context_pack_prioritizes_latest_inbound_turn_boundary(self):
        pack = build_context_pack(
            user_profile={},
            match_profile={"conversation_hooks": ["cat names"]},
            conversation_memory={
                "recent_messages": [
                    {"sender": "match", "text": "还有个猫猫大君"},
                    {"sender": "user", "text": "大左这个名字有点好笑..."},
                    {"sender": "match", "text": "还好呀"},
                    {"sender": "match", "text": "都没什么脾气我家的猫"},
                ],
                "latest_inbound_messages": [
                    {"sender": "match", "text": "还好呀"},
                    {"sender": "match", "text": "都没什么脾气我家的猫"},
                ],
                "open_threads": [],
                "commitments": [],
                "running_summary": "They discussed cats.",
            },
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
        )

        labels = [item["label"] for item in pack["items"]]

        self.assertLess(labels.index("latest_inbound_messages"), labels.index("latest_message"))
        self.assertLess(labels.index("turn_boundary"), labels.index("recent_messages"))
        self.assertEqual(
            pack["items"][labels.index("latest_inbound_messages")]["content"][-1]["text"],
            "都没什么脾气我家的猫",
        )

    def test_context_pack_includes_safety_constraints_for_facts_and_history(self):
        pack = build_context_pack(
            user_profile={},
            match_profile={},
            conversation_memory={},
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
        )

        self.assertIn(
            "Do not invent or contradict hard facts.", pack["safety_constraints"]
        )
        self.assertIn(
            "Do not rewrite historical events, past messages, or existing commitments.",
            pack["safety_constraints"],
        )

    def test_context_pack_includes_safety_constraints_for_persona_modulation(self):
        pack = build_context_pack(
            user_profile={},
            match_profile={},
            conversation_memory={},
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
        )

        self.assertIn(
            (
                "Persona and stance may be modulated, but must not be presented as "
                "past fact, identity change, or contradiction of user boundaries."
            ),
            pack["safety_constraints"],
        )
        self.assertIn(
            (
                "Medium or high persona/stance divergence must be labeled and "
                "explainable for downstream policy and generation."
            ),
            pack["safety_constraints"],
        )

    def test_context_pack_includes_send_time_context_when_provided(self):
        pack = build_context_pack(
            user_profile={},
            match_profile={},
            conversation_memory={},
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
            current_time_iso="2026-06-15T17:00:00Z",
        )

        items = {item["label"]: item["content"] for item in pack["items"]}

        self.assertEqual(items["send_time_context"]["local_timezone"], "Asia/Shanghai")
        self.assertEqual(items["send_time_context"]["current_local"], "2026-06-16T01:00:00+08:00")
        self.assertEqual(items["send_time_context"]["local_hour"], 1)
        self.assertNotIn("is_daytime_work_context", items["send_time_context"])

    def test_context_pack_item_content_is_a_snapshot(self):
        user_profile = {
            "boundaries": [{"content": {"text": "Do not claim overseas study"}}]
        }

        pack = build_context_pack(
            user_profile=user_profile,
            match_profile={},
            conversation_memory={},
            reply_mode=ReplyMode.ADAPTIVE,
            max_items=None,
        )

        user_profile["boundaries"][0]["content"]["text"] = "Changed later"

        self.assertEqual(
            pack["items"][0]["content"][0]["content"]["text"],
            "Do not claim overseas study",
        )


if __name__ == "__main__":
    unittest.main()
