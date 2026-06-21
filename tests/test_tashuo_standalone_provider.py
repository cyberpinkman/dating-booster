import json
from pathlib import Path
import tempfile
import unittest

from dating_boost.apps.tashuo.standalone import (
    TaShuoMacIosStageExecutor,
    TaShuoMacIosStandaloneObservationProvider,
    TaShuoStandaloneTargetCache,
)
from dating_boost.intelligence.vision_backends import ScriptedVisionBackend


class FakeTaShuoAdapter:
    def __init__(self, screen_path: str, *, stage_payload: dict | None = None):
        self.screen_path = screen_path
        self.stage_payload = stage_payload
        self.calls = []

    def run_action(self, action, *, dry_run=False, output_dir=None, **options):
        self.calls.append(("run_action", action, options))
        return {"schema_version": 1, "status": "ok", "screen_state": "tashuo_chat_list"}

    def observe(self, *, output_dir=None):
        self.calls.append(("observe", None, {}))
        return {
            "schema_version": 1,
            "status": "ok",
            "screen_state": "tashuo_chat_list",
            "screen": {"path": self.screen_path},
        }

    def stage_draft(self, draft_text, *, dry_run=False, output_dir=None):
        self.calls.append(("stage_draft", draft_text, {}))
        if self.stage_payload is not None:
            return dict(self.stage_payload)
        return {
            "schema_version": 1,
            "status": "ok",
            "stage_attempt_status": "completed",
            "staged_text_verified": True,
        }


class TaShuoStandaloneProviderTests(unittest.TestCase):
    def test_message_list_observation_caches_visual_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "rows": [
                            {
                                "tap_ratio": {"x": 0.5, "y": 0.42},
                                "visible_name": "Ada",
                                "latest_preview": "你好",
                                "visual_anchor_hash": "7f83a1d2",
                                "confidence": "high",
                            }
                        ],
                    }
                ),
                adapter_factory=lambda: adapter,
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cached = TaShuoStandaloneTargetCache(Path(temp_dir) / "data").get("tashuo_visual_7f83a1d2")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["candidates"][0]["tap_ratio"], {"x": 0.5, "y": 0.42})
        self.assertEqual(cached["visible_name"], "Ada")

    def test_observe_thread_uses_cached_tap_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "tap_ratio": {"x": 0.5, "y": 0.42},
                    "visible_name": "Ada",
                    "latest_preview": "你好",
                    "visual_anchor_hash": "7f83a1d2",
                }
            )
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "Ada",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )
            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_7f83a1d2")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(adapter.calls[0][0], "run_action")
        self.assertEqual(adapter.calls[0][2]["tap_ratio"], {"x": 0.5, "y": 0.42})
        self.assertEqual(payload["conversation_observation"]["visible_messages"][0]["text"], "你好呀")

    def test_observe_thread_blocks_when_perceived_identity_differs_from_cached_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "tap_ratio": {"x": 0.5, "y": 0.42},
                    "visible_name": "Ada",
                    "latest_preview": "你好",
                    "visual_anchor_hash": "7f83a1d2",
                }
            )
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "Bea",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )
            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_7f83a1d2")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "current_thread_visual_identity_mismatch")
        self.assertEqual(payload["cached_visible_name"], "Ada")
        self.assertEqual(payload["perceived_visible_name"], "Bea")

    def test_observe_thread_blocks_stale_cached_tap_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            cache_path = data_dir / "standalone_session" / "tashuo_targets.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(
                """
                {
                  "schema_version": 1,
                  "targets": {
                    "tashuo_visual_7f83a1d2": {
                      "candidate_key": "tashuo_visual_7f83a1d2",
                      "tap_ratio": {"x": 0.5, "y": 0.42},
                      "visible_name": "Ada",
                      "visual_anchor_hash": "7f83a1d2",
                      "observed_at": "2026-06-21T00:00:00Z"
                    }
                  }
                }
                """,
                encoding="utf-8",
            )
            adapter = FakeTaShuoAdapter(str(Path(temp_dir) / "screen.png"))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend({"status": "ok", "visible_messages": [], "visual_anchor_hash": "hash"}),
                adapter_factory=lambda: adapter,
            )
            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_7f83a1d2")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_standalone_target_stale")
        self.assertEqual(adapter.calls, [])

    def test_observe_thread_blocks_without_cached_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {"status": "ok", "visible_messages": [], "visual_anchor_hash": "hash"}
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(Path(temp_dir) / "screen.png")),
            )
            payload = provider.observe_thread(app_id="tashuo", candidate_key="missing")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_standalone_target_not_found")

    def test_stage_executor_validates_work_item_before_gui_stage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeTaShuoAdapter(str(Path(temp_dir) / "screen.png"))
            executor = TaShuoMacIosStageExecutor(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                adapter_factory=lambda: adapter,
            )
            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "payload_text": "你好",
                    "target_match_id": "match_1",
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "invalid_send_work_item:action_request_id")
        self.assertEqual(adapter.calls, [])

    def test_stage_executor_persists_gui_stage_evidence_to_audit_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "screen.png"),
                stage_payload={
                    "schema_version": 1,
                    "status": "ok",
                    "stage_attempt_status": "completed",
                    "staged_text_verified": True,
                    "staged_text_verification": {"status": "verified", "exact_text_ax_verified": True},
                },
            )
            executor = TaShuoMacIosStageExecutor(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                adapter_factory=lambda: adapter,
            )
            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                },
                app_id="tashuo",
            )
            record = (data_dir / "audit" / "stage_results.jsonl").read_text(encoding="utf-8")
            event = json.loads(record)

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(event["stage_attempt_status"], "completed")
        self.assertTrue(event["staged_text_verified"])
        self.assertEqual(event["staged_text_verification"], {"status": "verified", "exact_text_ax_verified": True})
