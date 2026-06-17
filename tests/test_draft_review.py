import json
import tempfile
import unittest
from pathlib import Path

from dating_boost.core.models import Divergence
from dating_boost.perception.observations import AppObservation
from dating_boost.policy.draft_review import review_draft


def _draft_payload(**overrides):
    payload = {
        "best_reply": "这个听起来还挺有意思。",
        "safer_reply": "这个听起来还挺有意思。",
        "bolder_reply": "展开讲讲。",
        "why_this_works": "接住话题。",
        "situation_read": "unit fixture",
        "conversation_move": "bridge_topic",
        "hook_source": "conversation_thread",
        "naturalness_notes": ["unit fixture"],
        "followup_if_match_replies": "继续接话。",
        "risk_flags": [],
        "missing_info": [],
        "mode_notes": "",
        "persona_divergence": Divergence.LOW.value,
        "stance_divergence": Divergence.LOW.value,
        "strategic_delta": "从当前话题桥到一个可回复把手。",
        "selected_hook": "雨天在家一般做什么",
        "question_count": 1,
    }
    payload.update(overrides)
    return payload


def _context_pack(**overrides):
    payload = {
        "match_id": "match_review_fixture",
        "items": [],
    }
    payload.update(overrides)
    return payload


def _observation(
    *,
    profile_text: str = "",
    hook_candidates: list[str] | None = None,
    latest_inbound_messages: list[dict[str, str]] | None = None,
    captured_at: str = "2026-06-18T10:00:00+08:00",
) -> AppObservation:
    hook_candidates = hook_candidates or []
    latest_inbound_messages = latest_inbound_messages or [{"sender": "match", "text": "昨天雨太大了"}]
    return AppObservation.from_dict(
        {
            "observation_id": "obs_draft_review",
            "source_type": "manual_fixture",
            "app_id": "tashuo",
            "adapter_id": "codex.manual.v1",
            "captured_at": captured_at,
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


class DraftReviewTests(unittest.TestCase):
    def test_blocks_hard_fact_and_soft_invite_logistics(self):
        hard_fact_review = review_draft(
            _draft_payload(best_reply="I studied overseas too."),
            _context_pack(
                items=[
                    {"label": "user_hard_facts", "content": {"education": "Chinese university graduate"}},
                    {"label": "user_boundaries", "content": "Do not claim overseas study"},
                ]
            ),
            mode="managed_live",
        )
        self.assertFalse(hard_fact_review.allowed_for_managed_send)
        self.assertIn("content_hard_fact", {finding.code for finding in hard_fact_review.findings})

        soft_invite_review = review_draft(
            _draft_payload(
                best_reply="那明晚八点在三里屯见吧",
                conversation_move="soft_invite_probe",
            ),
            _context_pack(
                items=[
                    {
                        "label": "planner_recommendation",
                        "content": {
                            "recommended_move": "soft_invite_probe",
                            "conversation_stage": "soft_invite_probe",
                            "soft_invite_allowed": True,
                        },
                    }
                ]
            ),
            mode="managed_live",
        )
        self.assertFalse(soft_invite_review.allowed_for_managed_send)
        self.assertIn("content_soft_invite_detail", {finding.code for finding in soft_invite_review.findings})

    def test_display_mode_reports_naturalness_revision_without_blocking_display(self):
        review = review_draft(
            _draft_payload(best_reply="下次我得听听 ESFP 夜猫子的放松路线：咖啡、电影、听歌你会先选哪个？"),
            _context_pack(),
            mode="display",
        )

        self.assertEqual(review.status, "needs_revision")
        self.assertTrue(review.allowed_for_display)
        self.assertTrue(review.allowed_for_stage)
        self.assertFalse(review.allowed_for_managed_send)
        self.assertTrue(review.revision_hints)
        self.assertIn("naturalness", {finding.category for finding in review.findings})

    def test_managed_live_blocks_strategy_and_temporal_fit_issues(self):
        cases = (
            (
                "ab_choice",
                _draft_payload(
                    best_reply="你懂了，那你下班后是倒头就睡，还是会先缓一会儿",
                    selected_hook="night_work_schedule",
                    strategic_delta="Use her night-work detail to ask about her routine.",
                ),
                {"recommended_move": "deepen_current", "topic_lifecycle": {"current_topic": "night_work_schedule"}},
                _observation(latest_inbound_messages=[{"sender": "match", "text": "我晚上上班呀"}]),
                "draft_ai_survey_choice_question",
            ),
            (
                "redundant",
                _draft_payload(
                    best_reply="昨天那雨确实适合直接切室内模式😂 那你是不是被困住了",
                    selected_hook="室内模式",
                    strategic_delta="从昨天大雨桥到确认她是不是被雨困住。",
                ),
                {
                    "recommended_move": "bridge_topic",
                    "topic_lifecycle": {
                        "current_topic": "yesterday_heavy_rain",
                        "topic_state": "saturating",
                        "new_information": ["对方说昨天雨太大了"],
                    },
                },
                _observation(latest_inbound_messages=[{"sender": "match", "text": "昨天雨太大了"}]),
                "draft_redundant_confirmation_question",
            ),
            (
                "no_handle",
                _draft_payload(
                    best_reply="哈哈你这句还挺会接梗的😂",
                    selected_hook="weather_after_rain",
                    strategic_delta="Keep the light exchange going.",
                ),
                {"recommended_move": "deepen_current", "topic_lifecycle": {"current_topic": "weather_after_rain"}},
                _observation(latest_inbound_messages=[{"sender": "match", "text": "哈哈哈哈哈"}]),
                "draft_no_answerable_relationship_handle",
            ),
            (
                "stale_weather",
                _draft_payload(
                    best_reply="这天气还挺会接梗，雨负责铺气氛，太阳负责收尾😂",
                    conversation_move="deepen_current",
                    selected_hook="weather_after_rain",
                    strategic_delta="Use the rain-stopped/sun-out moment to keep a light exchange going.",
                ),
                {
                    "recommended_move": "deepen_current",
                    "topic_lifecycle": {
                        "current_topic": "weather_after_rain",
                        "latest_inbound_age_days": 3,
                    },
                },
                _observation(
                    latest_inbound_messages=[
                        {"sender": "match", "text": "雨停了吧", "sent_at": "2026-06-14T23:00:00+08:00"},
                        {"sender": "match", "text": "我看太阳出来了", "sent_at": "2026-06-14T23:01:00+08:00"},
                    ]
                ),
                "draft_stale_temporal_topic_without_bridge",
            ),
            (
                "work_topic",
                _draft_payload(
                    best_reply="你平时更像救火队长，还是提前把坑都填好的那种",
                    selected_hook="运营",
                    strategic_delta="从资料里的运营切到工作风格。",
                ),
                {"recommended_move": "bridge_topic", "topic_lifecycle": {"current_topic": "生活状态"}},
                _observation(
                    profile_text="运营，喜欢露营、咖啡、电影。",
                    hook_candidates=["运营", "露营", "咖啡", "电影"],
                    latest_inbound_messages=[{"sender": "match", "text": "还好呀"}],
                ),
                "draft_work_topic_not_preferred",
            ),
        )

        for _name, draft, planner, observation, expected_code in cases:
            with self.subTest(code=expected_code):
                review = review_draft(
                    draft,
                    _context_pack(),
                    mode="managed_live",
                    observation=observation,
                    planner_recommendation=planner,
                )

                self.assertFalse(review.allowed_for_managed_send)
                self.assertIn(expected_code, {finding.code for finding in review.findings})

    def test_message_sequence_hash_count_and_mechanical_split_rules(self):
        review = review_draft(
            _draft_payload(
                best_reply="慢热联盟可以成立\n狼人杀我也一般先观察\n熟了再开麦会比较自然",
                message_sequence=["慢热联盟可以成立，", "狼人杀我也一般先观察，", "熟了再开麦会比较自然"],
                selected_hook="狼人杀",
                strategic_delta="从慢热桥到狼人杀里的观察状态。",
                question_count=0,
            ),
            _context_pack(),
            mode="managed_live",
        )

        self.assertEqual(review.payload_format, "message_sequence")
        self.assertEqual(review.message_count, 3)
        self.assertEqual(len(review.payload_hash), 64)
        self.assertIn("message_sequence_mechanical_split", {finding.code for finding in review.findings})
        self.assertFalse(review.allowed_for_managed_send)

    def test_disclosure_policy_modes(self):
        material_profile = {
            "simulation_policy": "material_only",
            "shareable_material": [{"material_id": "mat_home", "text": "周末喜欢在家做饭"}],
        }
        material_review = review_draft(
            _draft_payload(
                best_reply="我周末也喜欢在家慢慢做饭",
                conversation_move="light_self_disclosure",
                disclosure_source="user_material",
                used_user_material_ids=[],
            ),
            _context_pack(),
            mode="managed_live",
            disclosure_profile=material_profile,
        )
        self.assertFalse(material_review.allowed_for_managed_send)
        self.assertIn("disclosure_material_id_required", {finding.code for finding in material_review.findings})

        soft_review = review_draft(
            _draft_payload(
                best_reply="我周末也会先宅一会儿再决定要不要出门",
                conversation_move="light_self_disclosure",
                disclosure_source="simulated_soft",
            ),
            _context_pack(),
            mode="managed_live",
            disclosure_profile={"simulation_policy": "free_simulation_soft", "shareable_material": []},
        )
        self.assertTrue(soft_review.allowed_for_managed_send)

        confirmed_review = review_draft(
            _draft_payload(
                best_reply="我周末也会先宅一会儿再决定要不要出门",
                conversation_move="light_self_disclosure",
                disclosure_source="user_confirmed",
            ),
            _context_pack(),
            mode="managed_live",
            disclosure_profile={"simulation_policy": "user_confirmed_only", "shareable_material": []},
        )
        self.assertFalse(confirmed_review.allowed_for_managed_send)
        self.assertTrue(confirmed_review.requires_user_confirmation)

    def test_managed_live_uses_disclosure_profile_from_context_pack(self):
        review = review_draft(
            _draft_payload(
                best_reply="我周末也喜欢在家慢慢做饭",
                conversation_move="light_self_disclosure",
                disclosure_source="user_material",
                used_user_material_ids=["mat_home"],
                question_count=0,
            ),
            _context_pack(
                items=[
                    {
                        "label": "user_disclosure_profile",
                        "content": {
                            "simulation_policy": "material_only",
                            "shareable_material": [{"material_id": "mat_home", "text": "周末喜欢在家做饭"}],
                        },
                    }
                ]
            ),
            mode="managed_live",
        )

        self.assertTrue(review.allowed_for_managed_send)
        self.assertNotIn("user_disclosure_profile_required", {finding.code for finding in review.findings})

    def test_cli_managed_live_uses_context_turn_for_strategy_gate(self):
        from dating_boost.cli import main
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_path = root / "draft.json"
            context_path = root / "context.json"
            draft_path.write_text(
                json.dumps(
                    _draft_payload(
                        best_reply="懂了，那你下班后是倒头就睡，还是会先缓一会儿",
                        conversation_move="deepen_current",
                        selected_hook="night_work_schedule",
                        strategic_delta="Use her night-work detail to ask about her routine.",
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            context_path.write_text(
                json.dumps(
                    _context_pack(
                        items=[
                            {
                                "label": "planner_recommendation",
                                "content": {
                                    "recommended_move": "deepen_current",
                                    "topic_lifecycle": {"current_topic": "night_work_schedule"},
                                },
                            },
                            {
                                "label": "latest_inbound_messages",
                                "content": [{"sender": "match", "text": "我晚上上班呀"}],
                            },
                        ]
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "policy",
                        "check-draft",
                        "--input",
                        str(draft_path),
                        "--context",
                        str(context_path),
                        "--review-mode",
                        "managed-live",
                    ]
                )

            payload = json.loads(output.getvalue())

        self.assertEqual(exit_code, 2)
        self.assertFalse(payload["draft_review"]["allowed_for_managed_send"])
        self.assertIn("draft_ai_survey_choice_question", payload["draft_review"]["summary"]["finding_codes"])

    def test_cli_check_draft_writes_audit_and_returns_new_contract(self):
        from dating_boost.cli import main
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            draft_path = root / "draft.json"
            context_path = root / "context.json"
            draft_path.write_text(json.dumps(_draft_payload(best_reply="哈哈你这句还挺会接梗的😂"), ensure_ascii=False), encoding="utf-8")
            context_path.write_text(json.dumps(_context_pack(), ensure_ascii=False), encoding="utf-8")
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "policy",
                        "check-draft",
                        "--input",
                        str(draft_path),
                        "--context",
                        str(context_path),
                        "--data-dir",
                        str(data_dir),
                    ]
                )

            payload = json.loads(output.getvalue())
            audit_exists = (data_dir / "audit" / "draft_reviews.jsonl").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn(payload["status"], {"ok", "needs_revision"})
        self.assertIn("draft_review", payload)
        self.assertNotIn("policy", payload)
        self.assertTrue(audit_exists)


if __name__ == "__main__":
    unittest.main()
