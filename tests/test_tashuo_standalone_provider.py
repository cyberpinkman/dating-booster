import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from dating_boost.apps.tashuo.standalone import (
    TaShuoMacIosStageExecutor,
    TaShuoMacIosStandaloneObservationProvider,
    TaShuoStandalonePrecheckHarness,
    TaShuoStandaloneTargetCache,
    _correct_tashuo_message_list_tap_ratios,
)
from dating_boost.core.scan_authoring import validate_scan_batch
from dating_boost.intelligence.vision_backends import ScriptedVisionBackend


class FakeTaShuoAdapter:
    def __init__(
        self,
        screen_path: str,
        *,
        stage_payload: dict | None = None,
        observe_payloads: list[dict] | None = None,
    ):
        self.screen_path = screen_path
        self.stage_payload = stage_payload
        self.observe_payloads = list(observe_payloads or [])
        self.calls = []

    def run_action(self, action, *, dry_run=False, output_dir=None, **options):
        self.calls.append(("run_action", action, options))
        return {"schema_version": 1, "status": "ok", "screen_state": "tashuo_chat_list"}

    def observe(self, *, output_dir=None):
        self.calls.append(("observe", None, {}))
        if self.observe_payloads:
            return dict(self.observe_payloads.pop(0))
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
    def test_corrected_tap_ratios_keep_visual_anchor_region_on_same_row(self):
        rows = [
            {
                "candidate_key": "tashuo_visual_blurred_avatar_new_badge",
                "visible_name": "有个优秀的女生想认识你",
                "latest_preview": "她毕业于知名院校，是个学霸",
                "tap_ratio": {"x": 0.5, "y": 0.53},
                "visual_anchor_hash": "blurred_avatar_new_badge",
                "visual_anchor_region": {"x1": 0.04, "y1": 0.49, "x2": 0.96, "y2": 0.6},
            },
            {
                "candidate_key": "tashuo_visual_row2_letty_outdoor_photo_draft_badge",
                "visible_name": "Letty",
                "latest_preview": "[草稿] 嗨Letty，我也没想到真的能…",
                "tap_ratio": {"x": 0.5, "y": 0.77},
                "visual_anchor_hash": "row2_letty_outdoor_photo_draft_badge",
                "visual_anchor_region": {"x1": 0.04, "y1": 0.708, "x2": 0.96, "y2": 0.819},
            },
        ]

        corrected = _correct_tashuo_message_list_tap_ratios(rows)
        letty = corrected[1]

        self.assertEqual(letty["tap_ratio"]["y"], 0.647)
        self.assertLessEqual(letty["visual_anchor_region"]["y1"], letty["tap_ratio"]["y"])
        self.assertGreaterEqual(letty["visual_anchor_region"]["y2"], letty["tap_ratio"]["y"])
        self.assertEqual(letty["visual_anchor_region"], {"x1": 0.04, "y1": 0.5915, "x2": 0.96, "y2": 0.7025})

    def test_precheck_harness_observes_current_screen_without_prepare_message_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            adapter = FakeTaShuoAdapter(
                str(screen),
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "layout_hints": {"page": "conversation"},
                        "screen": {"path": str(screen)},
                    }
                ],
            )
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend({"status": "ok"}),
                adapter_factory=lambda: adapter,
            )
            harness = TaShuoStandalonePrecheckHarness(provider, app_id="tashuo", runtime="mac-ios-app")

            payload = harness.observe()

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["screen_state"], "tashuo_conversation")
        self.assertEqual(payload["runtime"], "mac-ios-app")
        self.assertEqual([call[0] for call in adapter.calls], ["observe"])

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
                                "visual_anchor_region": {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
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
        self.assertEqual(payload["message_list_snapshot"]["entries"][0]["candidate_key"], "tashuo_visual_7f83a1d2")
        self.assertEqual(payload["message_list_snapshot"]["entries"][0]["latest_preview_hash"][:7], "sha256:")
        self.assertEqual(
            payload["message_list_snapshot"]["entries"][0]["message_list_evidence"]["tap_ratio"],
            {"x": 0.5, "y": 0.42},
        )
        self.assertEqual(
            payload["message_list_snapshot"]["entries"][0]["message_list_evidence"]["visual_anchor_region"],
            {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
        )
        self.assertEqual(cached["visible_name"], "Ada")
        self.assertEqual(cached["visual_anchor_region"], {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49})

    def test_message_list_marks_tashuo_recommendation_gates_as_non_chat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "rows": [
                            {
                                "tap_ratio": {"x": 0.25, "y": 0.341},
                                "visible_name": "待回答 头像",
                                "latest_preview": "待回答用户",
                                "visual_anchor_hash": "answer_pending_portrait",
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.36, "y": 0.675},
                                "visible_name": "有个优秀的女生想认识你",
                                "latest_preview": "她毕业于知名院校，是个学霸",
                                "visual_anchor_hash": "blurred_avatar_new_badge_red_dot",
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.36, "y": 0.787},
                                "visible_name": "Letty",
                                "latest_preview": "你们已经可以进行会话了",
                                "visual_anchor_hash": "male_hiker_avatar_purple_button",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )

            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})

        entries = payload["message_list_snapshot"]["entries"]
        self.assertEqual(entries[0]["candidate_type"], "non_chat_gate")
        self.assertEqual(entries[1]["candidate_type"], "non_chat_gate")
        self.assertEqual(entries[2]["candidate_type"], "open_chat_candidate")
        self.assertEqual(payload["candidates"][0]["tap_ratio"]["y"], 0.341)
        self.assertEqual(payload["candidates"][1]["tap_ratio"]["y"], 0.525)
        self.assertEqual(payload["candidates"][2]["tap_ratio"]["y"], 0.647)

    def test_observe_thread_uses_cached_tap_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "tap_ratio": {"x": 0.5, "y": 0.42},
                    "visual_anchor_region": {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
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
        self.assertEqual(payload["observation"]["conversation_observation"]["visible_messages"][0]["text"], "你好呀")
        self.assertEqual(payload["assessment"]["recommended_next"], "reply")
        self.assertEqual(payload["planner_assessment"]["recommended_move"], "answer_or_riff")
        self.assertEqual(payload["target_binding"]["binding_type"], "current_thread_visual_identity")
        self.assertEqual(payload["target_binding"]["thread_evidence"]["visual_anchor_hash"], "threadhash")
        self.assertEqual(payload["target_binding"]["thread_evidence"]["screen_state"], "tashuo_conversation")
        self.assertEqual(payload["target_binding"]["message_list_evidence"]["tap_ratio"], {"x": 0.5, "y": 0.42})
        self.assertEqual(
            payload["target_binding"]["message_list_evidence"]["visual_anchor_region"],
            {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
        )
        scan_validation = validate_scan_batch(
            {
                "schema_version": 1,
                "session_id": "session_test",
                "app_id": "tashuo",
                "captured_at": "2026-06-21T00:00:00Z",
                "message_list_snapshot": {
                    "entries": [{"candidate_key": "tashuo_visual_7f83a1d2"}],
                },
                "thread_observations": [payload],
            }
        )
        self.assertEqual(scan_validation["status"], "ok", scan_validation)

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

    def test_observe_thread_allows_cjk_visible_name_ocr_near_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_rushi",
                    "tap_ratio": {"x": 0.5, "y": 0.82},
                    "visible_name": "如是偏是",
                    "latest_preview": "确实，端午就该给自己开个省电",
                    "visual_anchor_hash": "rushi_row",
                }
            )
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "如是儒是",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [{"direction": "inbound", "text": "确实", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_rushi")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_binding"]["visible_name"], "如是儒是")

    def test_observe_thread_allows_name_conflict_when_latest_preview_matches_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_rushi",
                    "tap_ratio": {"x": 0.5, "y": 0.82},
                    "visible_name": "如是偏见",
                    "latest_preview": "确实，端午就该给自己开个省电…",
                    "visual_anchor_hash": "rushi_row",
                }
            )
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "如是儒是",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [
                            {
                                "direction": "outbound",
                                "text": "确实，端午就该给自己开个省电模式",
                                "confidence": "high",
                            }
                        ],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_rushi")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_binding"]["visible_name"], "如是儒是")

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

    def test_observe_thread_allows_slow_visual_anchor_backed_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            cache_path = data_dir / "standalone_session" / "tashuo_targets.json"
            cache_path.parent.mkdir(parents=True)
            observed_at = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat().replace("+00:00", "Z")
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "targets": {
                            "tashuo_visual_7f83a1d2": {
                                "candidate_key": "tashuo_visual_7f83a1d2",
                                "tap_ratio": {"x": 0.5, "y": 0.42},
                                "visible_name": "Ada",
                                "visual_anchor_hash": "7f83a1d2",
                                "visual_anchor_region": {"x1": 0.1, "y1": 0.3, "x2": 0.9, "y2": 0.5},
                                "observed_at": observed_at,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            adapter = FakeTaShuoAdapter(str(Path(temp_dir) / "screen.png"))
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
        self.assertEqual(adapter.calls[0][0:2], ("run_action", "open-conversation"))
        self.assertEqual(adapter.calls[0][2]["message_list_evidence"]["visual_anchor_region"]["y1"], 0.3)

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

    def test_stage_executor_blocks_when_target_candidate_key_absent(self):
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
                    "action_request_id": "act_1",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_stage_target_candidate_key_absent")
        self.assertEqual(adapter.calls, [])

    def test_stage_executor_persists_gui_stage_evidence_to_audit_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "tap_ratio": {"x": 0.5, "y": 0.42},
                    "visible_name": "Ada",
                    "latest_preview": "你好呀",
                    "visual_anchor_hash": "7f83a1d2",
                }
            )
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "screen.png"),
                stage_payload={
                    "schema_version": 1,
                    "status": "ok",
                    "stage_attempt_status": "completed",
                    "staged_text_verified": True,
                    "staged_text_verification": {"status": "verified", "exact_text_ax_verified": True},
                },
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "screen": {"path": str(Path(temp_dir) / "screen.png")},
                    }
                ],
            )
            executor = TaShuoMacIosStageExecutor(
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
            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_7f83a1d2",
                        "visible_name": "Ada",
                        "thread_evidence": {
                            "visual_anchor_hash": "threadhash",
                            "latest_inbound_fingerprint": "sha256:7eca689f0d3389d9dea66ae112e5cfd7f4fc2586cbb909d6405b6361e3a21f8d",
                        },
                    },
                },
                app_id="tashuo",
            )
            record = (data_dir / "audit" / "stage_results.jsonl").read_text(encoding="utf-8")
            event = json.loads(record)

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(event["stage_attempt_status"], "completed")
        self.assertTrue(event["staged_text_verified"])
        self.assertEqual(event["staged_text_verification"], {"status": "verified", "exact_text_ax_verified": True})

    def test_stage_executor_verifies_current_thread_before_staging_without_reopen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "thread.png"),
                stage_payload={
                    "schema_version": 1,
                    "status": "ok",
                    "stage_attempt_status": "completed",
                    "staged_text_verified": True,
                    "staged_text_verification": {"status": "verified"},
                },
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "screen": {"path": str(Path(temp_dir) / "thread.png")},
                    }
                ],
            )
            executor = TaShuoMacIosStageExecutor(
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

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_7f83a1d2",
                        "visible_name": "Ada",
                    },
                },
                app_id="tashuo",
            )
            record = (data_dir / "audit" / "stage_results.jsonl").read_text(encoding="utf-8")
            event = json.loads(record)

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(payload["target_verification"]["status"], "ok")
        self.assertEqual(
            payload["target_verification"]["verification_method"],
            "tashuo_stage_target_in_place_vision_identity_check",
        )
        self.assertEqual(event["target_verification"]["status"], "ok")
        self.assertEqual([call for call in adapter.calls if call[0] == "run_action"], [])
        self.assertEqual(adapter.calls[-1][0], "stage_draft")

    def test_stage_executor_blocks_when_current_thread_binding_evidence_differs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "thread.png"),
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "screen": {"path": str(Path(temp_dir) / "thread.png")},
                    }
                ],
            )
            executor = TaShuoMacIosStageExecutor(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "Ada",
                        "visual_anchor_hash": "wrong-thread-anchor",
                        "visible_messages": [{"direction": "inbound", "text": "不是原来的消息", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_7f83a1d2",
                        "visible_name": "Ada",
                        "thread_evidence": {
                            "visual_anchor_hash": "threadhash",
                            "latest_inbound_fingerprint": "sha256:7eca689f0d3389d9dea66ae112e5cfd7f4fc2586cbb909d6405b6361e3a21f8d",
                        },
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "current_thread_binding_evidence_mismatch")
        self.assertNotIn(("stage_draft", "你好", {}), adapter.calls)

    def test_stage_executor_allows_cjk_visible_name_ocr_near_match_before_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_rushi",
                    "tap_ratio": {"x": 0.5, "y": 0.82},
                    "visible_name": "如是偏是",
                    "latest_preview": "确实，端午就该给自己开个省电",
                    "visual_anchor_hash": "rushi_row",
                }
            )
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "thread.png"),
                stage_payload={
                    "schema_version": 1,
                    "status": "ok",
                    "stage_attempt_status": "completed",
                    "staged_text_verified": True,
                    "staged_text_verification": {"status": "verified"},
                },
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "screen": {"path": str(Path(temp_dir) / "thread.png")},
                    }
                ],
            )
            executor = TaShuoMacIosStageExecutor(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "如是儒是",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [{"direction": "inbound", "text": "确实", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_rushi",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_rushi",
                        "visible_name": "如是偏是",
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(payload["target_verification"]["status"], "ok")
        self.assertEqual(adapter.calls[-1][0], "stage_draft")

    def test_stage_executor_allows_name_conflict_when_latest_preview_matches_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_rushi",
                    "tap_ratio": {"x": 0.5, "y": 0.82},
                    "visible_name": "如是偏见",
                    "latest_preview": "确实，端午就该给自己开个省电…",
                    "visual_anchor_hash": "rushi_row",
                }
            )
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "thread.png"),
                stage_payload={
                    "schema_version": 1,
                    "status": "ok",
                    "stage_attempt_status": "completed",
                    "staged_text_verified": True,
                    "staged_text_verification": {"status": "verified"},
                },
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "screen": {"path": str(Path(temp_dir) / "thread.png")},
                    }
                ],
            )
            executor = TaShuoMacIosStageExecutor(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "如是儒是",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [
                            {
                                "direction": "outbound",
                                "text": "确实，端午就该给自己开个省电模式",
                                "confidence": "high",
                            }
                        ],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_rushi",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_rushi",
                        "visible_name": "如是偏见",
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(payload["target_verification"]["status"], "ok")
        self.assertEqual(adapter.calls[-1][0], "stage_draft")

    def test_stage_executor_reopens_bound_target_only_when_current_screen_is_not_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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
            adapter = FakeTaShuoAdapter(
                str(Path(temp_dir) / "thread.png"),
                stage_payload={
                    "schema_version": 1,
                    "status": "ok",
                    "stage_attempt_status": "completed",
                    "staged_text_verified": True,
                    "staged_text_verification": {"status": "verified"},
                },
                observe_payloads=[
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_chat_list",
                        "screen": {"path": str(Path(temp_dir) / "list.png")},
                    },
                    {
                        "schema_version": 1,
                        "status": "ok",
                        "screen_state": "tashuo_conversation",
                        "screen": {"path": str(Path(temp_dir) / "thread.png")},
                    },
                ],
            )
            executor = TaShuoMacIosStageExecutor(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    [
                        {
                            "status": "ok",
                            "visible_name": "Ada",
                            "visual_anchor_hash": "threadhash",
                            "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}],
                        }
                    ]
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_7f83a1d2",
                        "visible_name": "Ada",
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(
            payload["target_verification"]["verification_method"],
            "tashuo_stage_target_reopen_and_vision_identity_check",
        )
        self.assertEqual(payload["target_verification"]["in_place_result"]["reason"], "tashuo_current_screen_not_conversation")
        self.assertEqual(
            [call[1] for call in adapter.calls if call[0] == "run_action"],
            ["prepare-message-page", "open-conversation"],
        )

    def test_stage_executor_blocks_when_reopened_thread_identity_differs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
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
            adapter = FakeTaShuoAdapter(str(Path(temp_dir) / "thread.png"))
            executor = TaShuoMacIosStageExecutor(
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

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_7f83a1d2",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_7f83a1d2",
                        "visible_name": "Ada",
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "current_thread_visual_identity_mismatch")
        self.assertNotIn("stage_draft", [call[0] for call in adapter.calls])
