import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.standalone_runtime import StandaloneAgentRuntime, StandaloneDraftPlanner
from dating_boost.intelligence.backend_factory import create_model_backend
from dating_boost.intelligence.backends import BackendCapability, ScriptedBackend
from dating_boost.policy.draft_review import DraftReviewDecision, DraftReviewFinding


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SCRIPTED_REPLY_PATH = FIXTURE_DIR / "intelligence" / "scripted_reply.json"


class BackendFactoryTests(unittest.TestCase):
    def test_creates_scripted_backend_from_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "scripted.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "best_reply": "好呀",
                        "safer_reply": "可以",
                        "bolder_reply": "走",
                        "why_this_works": "短",
                    }
                ),
                encoding="utf-8",
            )

            backend = create_model_backend({"type": "scripted", "path": str(payload_path)})

        self.assertIsInstance(backend, ScriptedBackend)
        self.assertIn(BackendCapability.GENERATE_STRUCTURED, backend.capabilities)

    def test_rejects_unknown_backend_type(self):
        with self.assertRaisesRegex(ValueError, "unsupported_model_backend"):
            create_model_backend({"type": "unknown"})

    def test_creates_minimax_backend_with_coding_plan_config(self):
        class FakeMiniMaxBackend:
            created_configs: list[dict[str, object]] = []

            def __init__(self, **kwargs):
                self.created_configs.append(dict(kwargs))

        with patch("dating_boost.intelligence.backend_factory.MiniMaxBackend", FakeMiniMaxBackend):
            backend = create_model_backend(
                {
                    "type": "minimax",
                    "model": "MiniMax-M2.5",
                    "base_url": "https://api.minimax.io/v1",
                    "api_key_env": "MINIMAX_CODE_KEY",
                }
            )

        self.assertIsInstance(backend, FakeMiniMaxBackend)
        self.assertEqual(
            FakeMiniMaxBackend.created_configs,
            [
                {
                    "model": "MiniMax-M2.5",
                    "base_url": "https://api.minimax.io/v1",
                    "api_key_env": "MINIMAX_CODE_KEY",
                }
            ],
        )

    def test_creates_minimax_backend_with_timeout_config(self):
        class FakeMiniMaxBackend:
            created_configs: list[dict[str, object]] = []

            def __init__(self, **kwargs):
                self.created_configs.append(dict(kwargs))

        with patch("dating_boost.intelligence.backend_factory.MiniMaxBackend", FakeMiniMaxBackend):
            backend = create_model_backend({"type": "minimax", "timeout_seconds": 17.5})

        self.assertIsInstance(backend, FakeMiniMaxBackend)
        self.assertEqual(FakeMiniMaxBackend.created_configs[0]["timeout_seconds"], 17.5)

    def test_creates_minimax_backend_with_cn_coding_plan_default_base_url(self):
        class FakeMiniMaxBackend:
            created_configs: list[dict[str, object]] = []

            def __init__(self, **kwargs):
                self.created_configs.append(dict(kwargs))

        with patch("dating_boost.intelligence.backend_factory.MiniMaxBackend", FakeMiniMaxBackend):
            backend = create_model_backend({"type": "minimax"})

        self.assertIsInstance(backend, FakeMiniMaxBackend)
        self.assertEqual(
            FakeMiniMaxBackend.created_configs,
            [
                {
                    "model": "MiniMax-M3",
                    "base_url": "https://api.minimaxi.com/v1",
                    "api_key_env": "MINIMAX_API_KEY",
                }
            ],
        )


class StandaloneDraftPlannerTests(unittest.TestCase):
    def test_scripted_backend_generates_policy_checked_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            import_exit, match_id = self._prepare_planner_data(data_dir)
            planner = StandaloneDraftPlanner(
                data_dir,
                backend_config={"type": "scripted", "path": str(SCRIPTED_REPLY_PATH)},
            )

            payload = planner.draft_for_match(match_id=match_id, mode="adaptive")

        self.assertEqual(import_exit, 0)
        self.assertIn(payload["status"], {"ok", "blocked"})
        self.assertIn("draft_generation_summary", payload)
        if payload["status"] == "ok":
            self.assertIn("draft", payload)
            self.assertIn("draft_review", payload)
            self.assertIn("draft_generation_id", payload["draft"])
            self.assertIn("draft_self_review_summary", payload["draft"])
            self.assertEqual(payload["draft"]["draft_self_review_summary"]["status"], "ok")
        else:
            self.assertIn("reason", payload)

    def test_model_backend_failure_returns_structured_blocked_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _import_exit, match_id = self._prepare_planner_data(data_dir)
            planner = StandaloneDraftPlanner(data_dir, backend_config={"type": "unknown"})

            payload = planner.draft_for_match(match_id=match_id, mode="adaptive")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "draft_generation_failed")
        self.assertEqual(payload["error_type"], "ValueError")
        self.assertIn("draft_evidence", payload)

    def test_draft_generation_runtime_error_retries_before_blocking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _import_exit, match_id = self._prepare_planner_data(data_dir)
            planner = StandaloneDraftPlanner(
                data_dir,
                backend_config={"type": "scripted", "path": str(SCRIPTED_REPLY_PATH)},
            )

            with patch(
                "dating_boost.intelligence.draft_generation.generate_reply_with_refinement",
                side_effect=RuntimeError("temporary structured output failure"),
            ) as generate:
                payload = planner.draft_for_match(match_id=match_id, mode="adaptive")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "draft_generation_failed")
        self.assertEqual(payload["error_type"], "RuntimeError")
        self.assertEqual(len(payload["generation_error_attempts"]), 2)
        self.assertEqual(generate.call_count, 2)
        self.assertIn("draft_evidence", payload)

    def test_stage_soft_accept_keeps_refinement_budget_without_retrying_policy(self):
        class FakeGeneration:
            status = "ok"
            primary_reason = None
            draft_payload = {
                "best_reply": "我一般忙完集中回，可能会慢一点",
                "safer_reply": "我一般忙完集中回，有时候会慢一点",
                "bolder_reply": "我一般忙完集中回，但不是消失",
            }
            self_review_attempts = [{"ai_or_weird_probability": 30, "reason": "ok"}]
            generation_id = "generation_1"

            def summary(self):
                return {
                    "schema_version": 1,
                    "status": "ok",
                    "generation_id": "generation_1",
                    "prompt_id": "prompt_1",
                    "prompt_hash": "hash_1",
                    "attempt_count": 1,
                    "self_review_attempts": [],
                }

        review = DraftReviewDecision(
            schema_version=1,
            status="needs_revision",
            allowed_for_display=True,
            allowed_for_stage=True,
            allowed_for_managed_send=False,
            requires_user_confirmation=False,
            primary_reason="draft_strategy_delta_missing",
            summary={"stage": True, "managed_live": False},
            findings=[
                DraftReviewFinding(
                    code="draft_strategy_delta_missing",
                    category="strategy",
                    severity="medium",
                    message="needs a stronger handle",
                    revision_hint="add a concrete handle",
                    blocks_display=False,
                    blocks_stage=False,
                    blocks_managed_send=True,
                )
            ],
            revision_hints=["add a concrete handle"],
            payload_hash="payload_hash_1",
            payload_format="single",
            message_count=1,
            review_id="review_1",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            _import_exit, match_id = self._prepare_planner_data(data_dir)
            planner = StandaloneDraftPlanner(
                data_dir,
                backend_config={"type": "scripted", "path": str(SCRIPTED_REPLY_PATH)},
                allow_stage_soft_accept=True,
            )
            with patch(
                "dating_boost.intelligence.draft_generation.generate_reply_with_refinement",
                return_value=FakeGeneration(),
            ) as generate:
                with patch("dating_boost.policy.draft_review.review_draft", return_value=review) as review_draft:
                    payload = planner.draft_for_match(match_id=match_id, mode="adaptive")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["draft_review"]["allowed_for_stage"], True)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(review_draft.call_count, 1)
        self.assertEqual(generate.call_args.kwargs["max_attempts"], 3)
        self.assertEqual(generate.call_args.kwargs["soft_accept_after_attempts"], 1)
        self.assertEqual(generate.call_args.kwargs["soft_accept_threshold"], 65)

    def _prepare_planner_data(self, data_dir: Path) -> tuple[int, str]:
        self._run_cli(
            [
                "init-profile",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "intelligence" / "user_profile.json"),
            ]
        )
        import_exit, import_payload = self._run_cli(
            [
                "import-observation",
                "--data-dir",
                str(data_dir),
                "--input",
                str(FIXTURE_DIR / "intelligence" / "app_observation_chat.json"),
            ]
        )
        match_id = import_payload["match_id"]
        UserMemoryRepository(data_dir).ensure_profile_source(
            app_id="tinder",
            runtime="default",
            observed_at="2026-06-06T12:00:00Z",
        )
        return import_exit, match_id

    def _run_cli(self, argv):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, json.loads(buffer.getvalue()) if buffer.getvalue().strip() else {}


class StandaloneAgentRuntimeTests(unittest.TestCase):
    def test_open_thread_revision_work_item_passes_revision_prompt_to_planner(self):
        class FakeObservationProvider:
            def observe_message_list(self, **_kwargs):
                raise AssertionError("message list should not be observed")

            def observe_current_thread(self, **_kwargs):
                raise AssertionError("current thread should not be observed")

            def observe_thread(self, **_kwargs):
                return {
                    "schema_version": 1,
                    "status": "ok",
                    "observation_type": "thread",
                    "candidate_key": "candidate_ada",
                    "assessment": {
                        "recommended_next": "reply",
                        "continuation_opportunity": "yes",
                        "reply_window_status": "open",
                    },
                    "observation": _app_observation_dict(),
                }

        class FakePlanner:
            def __init__(self):
                self.calls = []

            def draft_for_match(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "schema_version": 1,
                    "status": "ok",
                    "draft": {
                        "best_reply": "那我忙完集中回，别误会我消失了",
                        "safer_reply": "我一般忙完集中回，慢一点别介意",
                        "bolder_reply": "我忙完集中回，属于延迟但不失联",
                        "why_this_works": "解释回复节奏",
                        "situation_read": "对方在等回复",
                        "conversation_move": "low_investment_repair",
                        "hook_source": "latest_inbound",
                        "naturalness_notes": ["短"],
                        "followup_if_match_replies": "继续接",
                        "risk_flags": [],
                        "missing_info": [],
                        "mode_notes": "stage",
                        "persona_divergence": "low",
                        "stance_divergence": "low",
                    },
                    "draft_generation_summary": {},
                    "draft_review": {"allowed_for_managed_send": True},
                }

        class FakeOperator:
            def __init__(self):
                self.ingested = []

            def ingest_observation(self, observation):
                self.ingested.append(observation)
                return {"schema_version": 1, "status": "ok"}

            def get_state_payload(self):
                return {"operator_session": {"status": "active"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            planner = FakePlanner()
            runtime = StandaloneAgentRuntime(
                Path(temp_dir) / "data",
                observation_provider=FakeObservationProvider(),
                draft_planner=planner,
            )
            runtime.operator = FakeOperator()

            payload = runtime.consume_work_item(
                {
                    "work_item_type": "open_thread",
                    "work_item_id": "work_1",
                    "candidate_key": "candidate_ada",
                    "requires_revised_draft": True,
                    "draft_revision_reason": "message_sequence_mechanical_split",
                },
                managed_payload={"schema_version": 1, "app_id": "tashuo"},
            )

        self.assertEqual(payload["status"], "work_consumed")
        self.assertIn("message_sequence_mechanical_split", planner.calls[0]["supplemental_prompts"][0])
        self.assertEqual(runtime.operator.ingested[0]["draft"]["best_reply"], "那我忙完集中回，别误会我消失了")


def _app_observation_dict() -> dict:
    return {
        "observation_id": "obs_revision",
        "source_type": "manual_fixture",
        "app_id": "tashuo",
        "adapter_id": "standalone.test",
        "captured_at": "2026-06-25T17:20:00Z",
        "page_type": "chat_thread",
        "page_confidence": "high",
        "match_identity_hints": {
            "visible_name": "Ada",
            "profile_cues": [],
            "conversation_fingerprint": "thread-ada",
            "evidence": "fixture",
        },
        "profile_observation": {
            "profile_text": "Ada",
            "photo_cues": [],
            "hook_candidates": [],
            "review_status": "observed",
            "evidence": "fixture",
        },
        "conversation_observation": {
            "visible_messages": [
                {"sender": "match", "text": "你怎么回这么慢"},
            ],
            "latest_inbound_messages": [
                {"sender": "match", "text": "你怎么回这么慢"},
            ],
            "input_state": "empty",
            "thread_cues": [],
        },
        "element_observations": [],
        "exception_state": "none",
        "provenance": {"runtime": "mac-ios-app"},
        "raw_ref": None,
    }


if __name__ == "__main__":
    unittest.main()
