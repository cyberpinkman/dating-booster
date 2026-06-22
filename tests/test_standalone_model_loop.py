import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from dating_boost.cli import main
from dating_boost.core.draft_evidence import UserMemoryRepository
from dating_boost.core.standalone_runtime import StandaloneDraftPlanner
from dating_boost.intelligence.backend_factory import create_model_backend
from dating_boost.intelligence.backends import BackendCapability, ScriptedBackend


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


if __name__ == "__main__":
    unittest.main()
