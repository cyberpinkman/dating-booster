import tempfile
import unittest
from pathlib import Path

from dating_boost.core.draft_evidence import DraftEvidencePack
from dating_boost.intelligence.backends import ScriptedBackend
from dating_boost.intelligence.draft_generation import generate_reply_with_refinement
from dating_boost.intelligence.draft_prompt import build_draft_generation_prompt


def _reply_payload(text: str) -> dict[str, object]:
    return {
        "best_reply": text,
        "safer_reply": text,
        "bolder_reply": text,
        "why_this_works": "接住最新消息，并留一个可回复把手。",
        "situation_read": "对方刚提到现场音乐。",
        "conversation_move": "deepen_current",
        "hook_source": "latest_message",
        "naturalness_notes": ["短", "先接话"],
        "followup_if_match_replies": "继续问她喜欢的现场类型。",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "adaptive",
        "persona_divergence": "low",
        "stance_divergence": "low",
        "strategic_delta": "从现场音乐接到她喜欢的类型。",
        "selected_hook": "现场音乐",
        "question_count": 1,
    }


def _self_review(probability: int, supplemental_prompt: str = "") -> dict[str, object]:
    return {
        "ai_or_weird_probability": probability,
        "reason": "fixture",
        "supplemental_prompt": supplemental_prompt,
    }


def _evidence_pack() -> DraftEvidencePack:
    return DraftEvidencePack(
        schema_version=1,
        status="ok",
        evidence_id="draft_evidence_fixture",
        match_id="match_ada",
        reply_mode="adaptive",
        draft_kind="reply",
        primary_reason=None,
        missing_blocks=[],
        evidence_manifest={
            "latest_turn_hash": "hash_latest",
            "conversation_thread_hash": "hash_thread",
            "planner_recommendation_hash": "hash_plan",
            "match_memory_hash": "hash_match",
            "user_memory_hash": "hash_user",
        },
        latest_turn={
            "latest_turn_id": "latest_turn_fixture",
            "messages": [{"sender": "match", "text": "我一般会去听现场"}],
            "message_count": 1,
        },
        conversation_thread={
            "revision": 3,
            "messages": [
                {"sender": "user", "text": "你周末一般做什么"},
                {"sender": "match", "text": "我一般会去听现场"},
            ],
            "message_count": 2,
        },
        planner_recommendation={
            "conversation_stage": "warmup",
            "recommended_move": "deepen_current",
            "next_milestone": "找到一个可自然延展的共同兴趣",
            "auto_send_allowed": True,
        },
        match_memory={"profile": "喜欢现场音乐"},
        user_memory={"style_examples": ["短一点，像真人聊天"]},
        context_pack={"match_id": "match_ada", "items": []},
    )


class DraftPromptAndGenerationTests(unittest.TestCase):
    def test_prompt_orders_latest_turn_before_thread_strategy_and_memories(self):
        prompt = build_draft_generation_prompt(_evidence_pack())

        section_order = [
            "SECTION 1 latest_inbound_turn",
            "SECTION 2 complete_conversation_thread",
            "SECTION 3 relationship_strategy_current_stage",
            "SECTION 4 match_memory",
            "SECTION 5 user_memory",
            "SECTION 6 human_naturalness_requirements",
        ]
        positions = [prompt.user_prompt.index(section) for section in section_order]

        self.assertEqual(positions, sorted(positions))
        self.assertIn("我一般会去听现场", prompt.user_prompt)
        self.assertIn("你周末一般做什么", prompt.user_prompt)
        self.assertIn("deepen_current", prompt.user_prompt)
        self.assertIn("answerable relationship handle", prompt.user_prompt)

    def test_refinement_retries_when_probability_above_40(self):
        backend = ScriptedBackend(
            [
                _reply_payload("你这个回答有点像总结报告，那现场音乐你偏哪种？"),
                _self_review(41, "去掉总结感，先接住她的话，再轻问一个具体偏好。"),
                _reply_payload("现场听起来比歌单有意思多了。你偏小酒馆那种，还是更大的场？"),
                _self_review(30),
            ]
        )

        result = generate_reply_with_refinement(
            _evidence_pack(),
            backend=backend,
            audit_root=Path(tempfile.mkdtemp()),
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.self_review_attempts[-1]["ai_or_weird_probability"], 30)
        self.assertEqual(result.attempt_count, 2)
        self.assertIn("去掉总结感", result.prompt.supplemental_prompts[0])

    def test_probability_40_passes_without_retry(self):
        backend = ScriptedBackend([
            _reply_payload("现场听起来挺舒服。你一般会听哪种？"),
            _self_review(40),
        ])

        result = generate_reply_with_refinement(
            _evidence_pack(),
            backend=backend,
            audit_root=Path(tempfile.mkdtemp()),
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.attempt_count, 1)

    def test_initial_supplemental_prompt_is_included(self):
        backend = ScriptedBackend([
            _reply_payload("现场听起来挺舒服。你一般会听哪种？"),
            _self_review(20),
        ])

        result = generate_reply_with_refinement(
            _evidence_pack(),
            backend=backend,
            audit_root=Path(tempfile.mkdtemp()),
            supplemental_prompts=["Policy revision required before staging."],
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.prompt.supplemental_prompts, ["Policy revision required before staging."])

    def test_refinement_normalizes_conversation_move_in_payload(self):
        reply = _reply_payload("哈哈那我也喜欢人少的时候出门")
        reply["conversation_move"] = "answer_or_riff：用共鸣接住当前话题"
        backend = ScriptedBackend([reply, _self_review(20)])

        result = generate_reply_with_refinement(
            _evidence_pack(),
            backend=backend,
            audit_root=Path(tempfile.mkdtemp()),
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.draft.conversation_move, "answer_or_riff")
        self.assertEqual(result.draft_payload["conversation_move"], "answer_or_riff")

    def test_three_failed_self_reviews_block_generation(self):
        backend = ScriptedBackend(
            [
                _reply_payload("第一版"),
                _self_review(80, "更自然"),
                _reply_payload("第二版"),
                _self_review(70, "更像真人"),
                _reply_payload("第三版"),
                _self_review(50, "再短"),
            ]
        )

        result = generate_reply_with_refinement(
            _evidence_pack(),
            backend=backend,
            audit_root=Path(tempfile.mkdtemp()),
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.primary_reason, "draft_refinement_exhausted")
        self.assertEqual(result.attempt_count, 3)
        self.assertIsNone(result.draft)


if __name__ == "__main__":
    unittest.main()
