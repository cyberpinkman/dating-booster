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


if __name__ == "__main__":
    unittest.main()
