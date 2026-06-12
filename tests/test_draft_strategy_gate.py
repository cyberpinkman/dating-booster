import unittest

from dating_boost.core.automation import _draft_strategy_block_reason
from dating_boost.perception.observations import AppObservation


class DraftStrategyGateTests(unittest.TestCase):
    def test_blocks_ai_ab_choice_that_restates_confirmed_slow_warm_fact(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "那慢热同盟先成立\n不过我生活中还是比较能聊的\n你是聊天慢慢熟，还是见到人之后反而更容易放松",
                "message_sequence": [
                    "那慢热同盟先成立",
                    "不过我生活中还是比较能聊的",
                    "你是聊天慢慢熟，还是见到人之后反而更容易放松",
                ],
                "conversation_move": "bridge_topic",
                "selected_hook": "慢热",
                "strategic_delta": "从慢热共识转到见面舒适度。",
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 1,
                "topic_lifecycle": {
                    "current_topic": "慢热",
                    "topic_state": "active",
                    "new_information": ["对方说自己慢热"],
                },
            },
            _observation(
                profile_text="慢热，喜欢狼人杀和看展。",
                hook_candidates=["慢热", "狼人杀", "看展"],
                latest_inbound_messages=[{"sender": "match", "text": "我也是慢热一点"}],
            ),
        )

        self.assertEqual(reason, "draft_forced_choice_restates_confirmed_info")

    def test_blocks_work_topic_when_lifestyle_hooks_are_available(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "你平时更像救火队长，还是提前把坑都填好的那种",
                "conversation_move": "bridge_topic",
                "selected_hook": "运营",
                "strategic_delta": "从资料里的运营切到工作风格。",
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 0,
                "topic_lifecycle": {
                    "current_topic": "生活状态",
                    "topic_state": "active",
                    "new_information": [],
                },
            },
            _observation(
                profile_text="运营，喜欢露营、咖啡、电影。",
                hook_candidates=["运营", "露营", "咖啡", "电影"],
                latest_inbound_messages=[{"sender": "match", "text": "还好呀"}],
            ),
        )

        self.assertEqual(reason, "draft_work_topic_not_preferred")


def _observation(
    *,
    profile_text: str,
    hook_candidates: list[str],
    latest_inbound_messages: list[dict[str, str]],
) -> AppObservation:
    return AppObservation.from_dict(
        {
            "observation_id": "obs_strategy_gate",
            "source_type": "manual_fixture",
            "app_id": "tashuo",
            "adapter_id": "codex.manual.v1",
            "captured_at": "2026-06-12T10:00:00+08:00",
            "page_type": "chat_thread",
            "page_confidence": "high",
            "match_identity_hints": {
                "visible_name": "fixture",
                "profile_cues": hook_candidates,
                "conversation_fingerprint": "fixture-thread",
                "evidence": "Unit fixture.",
            },
            "profile_observation": {
                "profile_text": profile_text,
                "photo_cues": [],
                "hook_candidates": hook_candidates,
                "review_status": "observed",
                "evidence": "Unit fixture.",
            },
            "conversation_observation": {
                "visible_messages": latest_inbound_messages,
                "latest_inbound_messages": latest_inbound_messages,
                "input_state": "empty",
                "thread_cues": [],
            },
            "element_observations": [],
            "exception_state": "none",
            "provenance": {"evidence": "Unit fixture."},
            "raw_ref": None,
        }
    )


if __name__ == "__main__":
    unittest.main()
