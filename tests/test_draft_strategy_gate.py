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

    def test_blocks_stale_thread_reactivation_that_keeps_talking_old_topic(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "这条我居然漏到现在😂 那晚确实有点魔幻，F1 的 afterparty 比正赛还像大型社交局，感觉你也像是会误入名场面的人",
                "conversation_move": "bridge_topic",
                "selected_hook": "F1 afterparty story",
                "strategic_delta": "Shift from old cool-story reaction into a playful hypothesis that she also has mis-entered famous-scene stories.",
                "risk_flags": ["stale_thread_reactivation", "delayed_reply_should_be_acknowledged"],
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 0,
                "topic_lifecycle": {
                    "current_topic": "F1 afterparty story",
                    "topic_state": "active",
                    "new_information": ["match reacted positively to the afterparty story"],
                    "stale_hooks": ["the visible timestamp is 2026-02-03, so the reply must acknowledge delay"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=["F1 afterparty story"],
                latest_inbound_messages=[{"sender": "match", "text": "哇，那很酷"}],
            ),
        )

        self.assertEqual(reason, "draft_stale_reactivation_continues_old_topic")

    def test_blocks_stale_weather_reply_without_present_bridge(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "这天气还挺会接梗，雨负责铺气氛，太阳负责收尾😂",
                "conversation_move": "deepen_current",
                "selected_hook": "weather_after_rain",
                "strategic_delta": "Use the rain-stopped/sun-out moment to keep a light exchange going.",
            },
            {
                "recommended_move": "deepen_current",
                "low_investment_streak": 0,
                "topic_lifecycle": {
                    "current_topic": "weather_after_rain",
                    "topic_state": "active",
                    "latest_inbound_age_days": 3,
                    "new_information": ["对方几天前说雨停了、太阳出来了"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[
                    {"sender": "match", "text": "雨停了吧", "sent_at": "2026-06-14T23:00:00+08:00"},
                    {"sender": "match", "text": "我看太阳出来了", "sent_at": "2026-06-14T23:01:00+08:00"},
                    {"sender": "match", "text": "哈哈哈哈哈", "sent_at": "2026-06-14T23:02:00+08:00"},
                ],
            ),
        )

        self.assertEqual(reason, "draft_stale_temporal_topic_without_bridge")

    def test_blocks_generic_ai_ab_choice_question(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "懂了，原来是晚班选手😂 那你下班后是倒头就睡，还是会先缓一会儿",
                "conversation_move": "deepen_current",
                "selected_hook": "night_work_schedule",
                "strategic_delta": "Use her night-work detail to ask about her routine.",
            },
            {
                "recommended_move": "deepen_current",
                "low_investment_streak": 0,
                "topic_lifecycle": {
                    "current_topic": "night_work_schedule",
                    "topic_state": "active",
                    "new_information": ["对方说晚上上班"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "我晚上上班呀"}],
            ),
        )

        self.assertEqual(reason, "draft_ai_survey_choice_question")

    def test_blocks_reply_with_no_answerable_relationship_handle(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "哈哈你这句还挺会接梗的😂",
                "conversation_move": "deepen_current",
                "selected_hook": "weather_after_rain",
                "strategic_delta": "Keep the light exchange going.",
            },
            {
                "recommended_move": "deepen_current",
                "low_investment_streak": 0,
                "topic_lifecycle": {
                    "current_topic": "weather_after_rain",
                    "topic_state": "active",
                    "new_information": ["对方说哈哈哈哈哈"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "哈哈哈哈哈"}],
            ),
        )

        self.assertEqual(reason, "draft_no_answerable_relationship_handle")

    def test_blocks_redundant_confirmation_question_from_latest_context(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "昨天那雨确实适合直接切室内模式😂 我这种天气基本会把出门欲望清零，你那天是不是也被困住了",
                "conversation_move": "bridge_topic",
                "selected_hook": "室内模式",
                "strategic_delta": "从昨天大雨桥到她是不是也被雨困住。",
                "question_count": 1,
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 1,
                "topic_lifecycle": {
                    "current_topic": "yesterday_heavy_rain",
                    "topic_state": "saturating",
                    "new_information": ["对方说昨天雨太大了"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "昨天雨太大了"}],
            ),
        )

        self.assertEqual(reason, "draft_redundant_confirmation_question")

    def test_allows_unknown_rainy_day_home_routine_question(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "昨天那雨确实适合直接切室内模式😂 这种雨天你在家一般会干嘛",
                "conversation_move": "bridge_topic",
                "selected_hook": "雨天在家一般做什么",
                "strategic_delta": "从昨天大雨桥到她雨天在家的生活细节。",
                "question_count": 1,
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 1,
                "topic_lifecycle": {
                    "current_topic": "yesterday_heavy_rain",
                    "topic_state": "saturating",
                    "new_information": ["对方说昨天雨太大了"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "昨天雨太大了"}],
            ),
        )

        self.assertIsNone(reason)

    def test_blocks_obvious_consequence_confirmation_without_shared_words(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "昨天那雨确实适合直接切室内模式😂 那你是不是被困住了",
                "conversation_move": "bridge_topic",
                "selected_hook": "室内模式",
                "strategic_delta": "从昨天大雨桥到确认她是不是被雨困住。",
                "question_count": 1,
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 1,
                "topic_lifecycle": {
                    "current_topic": "yesterday_heavy_rain",
                    "topic_state": "saturating",
                    "new_information": ["对方说昨天雨太大了"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "昨天雨太大了"}],
            ),
        )

        self.assertEqual(reason, "draft_redundant_confirmation_question")

    def test_blocks_obvious_no_outing_question_after_heavy_rain(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "昨天雨确实有点夸张😂 那你是不是也没出门",
                "conversation_move": "bridge_topic",
                "selected_hook": "雨天安排",
                "strategic_delta": "从大雨转到确认她是否出门。",
                "question_count": 1,
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 1,
                "topic_lifecycle": {
                    "current_topic": "yesterday_heavy_rain",
                    "topic_state": "saturating",
                    "new_information": ["对方说昨天雨太大了"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "昨天雨太大了"}],
            ),
        )

        self.assertEqual(reason, "draft_redundant_confirmation_question")

    def test_allows_unknown_rainy_day_play_at_home_question(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "昨天雨确实有点夸张😂 这种雨天你在家一般玩什么",
                "conversation_move": "bridge_topic",
                "selected_hook": "雨天在家玩什么",
                "strategic_delta": "从大雨转到她在家会玩的具体内容。",
                "question_count": 1,
            },
            {
                "recommended_move": "bridge_topic",
                "low_investment_streak": 1,
                "topic_lifecycle": {
                    "current_topic": "yesterday_heavy_rain",
                    "topic_state": "saturating",
                    "new_information": ["对方说昨天雨太大了"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "昨天雨太大了"}],
            ),
        )

        self.assertIsNone(reason)

    def test_allows_single_yes_no_hypothesis_with_clear_handle(self):
        reason = _draft_strategy_block_reason(
            {
                "best_reply": "懂了，那你下班后是不是会先找点东西缓一下",
                "conversation_move": "deepen_current",
                "selected_hook": "night_work_schedule",
                "strategic_delta": "Test one concrete routine hypothesis from her night-work detail.",
            },
            {
                "recommended_move": "deepen_current",
                "low_investment_streak": 0,
                "topic_lifecycle": {
                    "current_topic": "night_work_schedule",
                    "topic_state": "active",
                    "new_information": ["对方说晚上上班"],
                },
            },
            _observation(
                profile_text="",
                hook_candidates=[],
                latest_inbound_messages=[{"sender": "match", "text": "我晚上上班呀"}],
            ),
        )

        self.assertIsNone(reason)


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
