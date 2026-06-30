import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


class TimeoutOnceVisionBackend:
    def __init__(self, payload: dict):
        self.payload = dict(payload)
        self.calls = 0

    def analyze_image_structured(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("Request timed out.")
        return dict(self.payload)


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

    def test_corrected_tap_ratios_use_likes_row_as_all_messages_anchor(self):
        rows = [
            {
                "candidate_key": "tashuo_visual_msg_likes_43",
                "visible_name": "43人喜欢了你",
                "latest_preview": "哇！她们是谁？？",
                "tap_ratio": {"x": 0.5, "y": 0.534},
                "visual_anchor_hash": "msg_likes_43",
                "visual_anchor_region": {"x1": 0.063, "y1": 0.451, "x2": 0.938, "y2": 0.617},
            },
            {
                "candidate_key": "tashuo_visual_msg_letty",
                "visible_name": "Letty",
                "latest_preview": "你们已经可以进行会话了",
                "tap_ratio": {"x": 0.5, "y": 0.635},
                "visual_anchor_hash": "msg_letty",
                "visual_anchor_region": {"x1": 0.063, "y1": 0.582, "x2": 0.938, "y2": 0.688},
            },
            {
                "candidate_key": "tashuo_visual_msg_yvaine",
                "visible_name": "Yvaine",
                "latest_preview": "哈喽",
                "tap_ratio": {"x": 0.5, "y": 0.694},
                "visual_anchor_hash": "msg_yvaine",
                "visual_anchor_region": {"x1": 0.063, "y1": 0.641, "x2": 0.938, "y2": 0.746},
            },
            {
                "candidate_key": "tashuo_visual_msg_xiaoyaowanr",
                "visible_name": "小药丸儿",
                "latest_preview": "我工作时间没办法哈哈哈 但我也喜…",
                "tap_ratio": {"x": 0.5, "y": 0.757},
                "visual_anchor_hash": "msg_xiaoyaowanr",
                "visual_anchor_region": {"x1": 0.063, "y1": 0.704, "x2": 0.938, "y2": 0.81},
            },
        ]

        corrected = _correct_tashuo_message_list_tap_ratios(rows)
        xiaoyaowan = corrected[3]

        self.assertEqual(corrected[0]["tap_ratio"]["y"], 0.455)
        self.assertEqual(corrected[1]["tap_ratio"]["y"], 0.577)
        self.assertEqual(corrected[2]["tap_ratio"]["y"], 0.699)
        self.assertEqual(xiaoyaowan["tap_ratio"]["y"], 0.821)
        self.assertLessEqual(xiaoyaowan["visual_anchor_region"]["y1"], xiaoyaowan["tap_ratio"]["y"])
        self.assertGreaterEqual(xiaoyaowan["visual_anchor_region"]["y2"], xiaoyaowan["tap_ratio"]["y"])

    def test_corrected_tap_ratios_click_action_area_when_anchor_is_avatar_region(self):
        rows = [
            {
                "candidate_key": "tashuo_visual_liked_44_row",
                "visible_name": "44人喜欢了你",
                "latest_preview": "哇！她们是谁？？",
                "tap_ratio": {"x": 0.205, "y": 0.455},
                "visual_anchor_hash": "liked_44_row",
                "visual_anchor_region": {"x1": 0.041, "y1": 0.405, "x2": 0.37, "y2": 0.505},
            },
            {
                "candidate_key": "tashuo_visual_avatar_girl_selfie",
                "visible_name": "Yvaine",
                "latest_preview": "哈喽",
                "tap_ratio": {"x": 0.205, "y": 0.577},
                "visual_anchor_hash": "avatar_girl_selfie",
                "visual_anchor_region": {"x1": 0.041, "y1": 0.527, "x2": 0.37, "y2": 0.627},
            },
            {
                "candidate_key": "tashuo_visual_avatar_hiker_seaside",
                "visible_name": "Letty",
                "latest_preview": "你们已经可以进行会话了",
                "tap_ratio": {"x": 0.205, "y": 0.699},
                "visual_anchor_hash": "avatar_hiker_seaside",
                "visual_anchor_region": {"x1": 0.041, "y1": 0.649, "x2": 0.37, "y2": 0.749},
            },
            {
                "candidate_key": "tashuo_visual_avatar_bw_dark",
                "visible_name": "小药丸儿",
                "latest_preview": "我工作时间没办法哈哈哈 但我也喜…",
                "tap_ratio": {"x": 0.205, "y": 0.821},
                "visual_anchor_hash": "avatar_bw_dark",
                "visual_anchor_region": {"x1": 0.041, "y1": 0.7705, "x2": 0.37, "y2": 0.8715},
            },
        ]

        corrected = _correct_tashuo_message_list_tap_ratios(rows)
        xiaoyaowan = corrected[3]

        self.assertEqual(xiaoyaowan["tap_ratio"], {"x": 0.87, "y": 0.821})
        self.assertEqual(xiaoyaowan["tap_ratio_source"], "corrected_all_messages_row_action")
        self.assertEqual(xiaoyaowan["visual_anchor_region"]["x1"], 0.041)
        self.assertEqual(xiaoyaowan["visual_anchor_region"]["x2"], 0.37)

    def test_corrected_tap_ratios_infer_top_message_grid_when_promo_anchor_missing(self):
        rows = [
            {
                "candidate_key": "tashuo_visual_yvaine",
                "visible_name": "Yvaine",
                "latest_preview": "哈喽",
                "tap_ratio": {"x": 0.55, "y": 0.605},
                "visual_anchor_hash": "yvaine_row",
                "visual_anchor_region": {"x1": 0.06, "y1": 0.555, "x2": 0.95, "y2": 0.685},
            },
            {
                "candidate_key": "tashuo_visual_letty",
                "visible_name": "Letty",
                "latest_preview": "你们已经可以进行会话了",
                "tap_ratio": {"x": 0.87, "y": 0.635},
                "visual_anchor_hash": "letty_row",
                "visual_anchor_region": {"x1": 0.06, "y1": 0.57, "x2": 0.95, "y2": 0.7},
            },
            {
                "candidate_key": "tashuo_visual_xiaoyaowan",
                "visible_name": "小药丸儿",
                "latest_preview": "我工作时间没办法哈哈哈 但我也喜...",
                "tap_ratio": {"x": 0.87, "y": 0.757},
                "visual_anchor_hash": "xiaoyaowan_row",
                "visual_anchor_region": {"x1": 0.06, "y1": 0.6945, "x2": 0.95, "y2": 0.8195},
            },
        ]

        corrected = _correct_tashuo_message_list_tap_ratios(rows)

        self.assertEqual([row["tap_ratio"]["y"] for row in corrected], [0.577, 0.699, 0.821])
        self.assertEqual([row["tap_ratio"]["x"] for row in corrected], [0.87, 0.87, 0.87])
        self.assertEqual(corrected[2]["visual_anchor_region"], {"x1": 0.06, "y1": 0.7585, "x2": 0.95, "y2": 0.8835})

    def test_message_list_skips_action_artifact_without_shifting_grid(self):
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
                                "tap_ratio": {"x": 0.50, "y": 0.455},
                                "visible_name": "50人喜欢了你",
                                "latest_preview": "哇！她们是谁？？",
                                "visual_anchor_hash": "likes_50_row",
                                "visual_anchor_region": {"x1": 0.06, "y1": 0.405, "x2": 0.94, "y2": 0.505},
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.50, "y": 0.577},
                                "visible_name": "Yvaine",
                                "latest_preview": "哈喽",
                                "visual_anchor_hash": "yvaine_avatar",
                                "visual_anchor_region": {"x1": 0.06, "y1": 0.527, "x2": 0.94, "y2": 0.627},
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.91, "y": 0.635},
                                "visible_name": "去回复按钮",
                                "latest_preview": "去回复 - Yvaine action",
                                "visual_anchor_hash": "reply_button_yvaine",
                                "visual_anchor_region": {"x1": 0.82, "y1": 0.585, "x2": 1.0, "y2": 0.685},
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.50, "y": 0.699},
                                "visible_name": "Letty",
                                "latest_preview": "你们已经可以进行会话了",
                                "visual_anchor_hash": "male_hiker_avatar_purple_button",
                                "visual_anchor_region": {"x1": 0.06, "y1": 0.649, "x2": 0.94, "y2": 0.749},
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.50, "y": 0.821},
                                "visible_name": "小药丸儿",
                                "latest_preview": "我工作时间没办法哈哈哈 但我也喜...",
                                "visual_anchor_hash": "xiaoyaowan_avatar",
                                "visual_anchor_region": {"x1": 0.06, "y1": 0.771, "x2": 0.94, "y2": 0.871},
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )

            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cache = TaShuoStandaloneTargetCache(Path(temp_dir) / "data")
            promo_cached = cache.get("tashuo_visual_likes_50_row")
            action_cached = cache.get("tashuo_visual_reply_button_yvaine")
            letty_cached = cache.get("tashuo_visual_male_hiker_avatar_purple_button")
            xiaoyaowan_cached = cache.get("tashuo_visual_xiaoyaowan_avatar")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            [entry["candidate_key"] for entry in payload["message_list_snapshot"]["entries"]],
            [
                "tashuo_visual_yvaine_avatar",
                "tashuo_visual_male_hiker_avatar_purple_button",
                "tashuo_visual_xiaoyaowan_avatar",
            ],
        )
        self.assertEqual([candidate["tap_ratio"]["y"] for candidate in payload["candidates"]], [0.577, 0.699, 0.821])
        self.assertEqual([item["reason"] for item in payload["skipped_candidates"]], ["non_chat_gate", "non_chat_gate"])
        self.assertIsNone(promo_cached)
        self.assertIsNone(action_cached)
        self.assertEqual(letty_cached["tap_ratio"]["y"], 0.699)
        self.assertEqual(xiaoyaowan_cached["tap_ratio"]["y"], 0.821)

    def test_message_list_retries_once_after_vision_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = TimeoutOnceVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.5, "y": 0.5},
                            "visible_name": "Ada",
                            "latest_preview": "你好",
                            "visual_anchor_hash": "ada_row",
                            "visual_anchor_region": {"x1": 0.1, "y1": 0.4, "x2": 0.9, "y2": 0.6},
                            "confidence": "high",
                        }
                    ],
                }
            )
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=backend,
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )

            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(backend.calls, 2)
        self.assertEqual(payload["message_list_snapshot"]["entries"][0]["visible_name"], "Ada")

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

    def test_message_list_observation_skips_rows_without_visible_name(self):
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
                                "candidate_key": "tashuo_visual_0f3990839b0a",
                                "tap_ratio": {"x": 0.87, "y": 0.69},
                                "visual_anchor_region": {"x1": 0.04, "y1": 0.64, "x2": 0.96, "y2": 0.75},
                                "visible_name": "",
                                "latest_preview": "",
                                "visual_anchor_hash": "0f3990839b0a",
                                "confidence": "low",
                            },
                            {
                                "candidate_key": "tashuo_visual_ada",
                                "tap_ratio": {"x": 0.87, "y": 0.82},
                                "visual_anchor_region": {"x1": 0.04, "y1": 0.77, "x2": 0.96, "y2": 0.87},
                                "visible_name": "Ada",
                                "latest_preview": "刚刚问你忙不忙",
                                "visual_anchor_hash": "ada_row",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cache = TaShuoStandaloneTargetCache(Path(temp_dir) / "data")
            skipped_cached = cache.get("tashuo_visual_0f3990839b0a")
            ada_cached = cache.get("tashuo_visual_ada_row")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["warnings"], ["tashuo_message_list_visual_row_skipped"])
        self.assertEqual(payload["skipped_candidates"][0]["candidate_key"], "tashuo_visual_0f3990839b0a")
        self.assertEqual(payload["skipped_candidates"][0]["reason"], "missing_visible_name")
        self.assertEqual([entry["candidate_key"] for entry in payload["message_list_snapshot"]["entries"]], ["tashuo_visual_ada_row"])
        self.assertIsNone(skipped_cached)
        self.assertEqual(ada_cached["visible_name"], "Ada")

    def test_message_list_observation_skips_structural_tab_header_row(self):
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
                                "candidate_key": "tashuo_visual_000000ffffe7e7ef",
                                "tap_ratio": {"x": 0.5, "y": 0.12},
                                "visual_anchor_region": {"x1": 0.3, "y1": 0.09, "x2": 0.7, "y2": 0.16},
                                "visible_name": "Tab header: 消息 / 动态",
                                "latest_preview": "Message tab header",
                                "visual_anchor_hash": "000000ffffe7e7ef",
                                "confidence": "medium",
                            },
                            {
                                "candidate_key": "tashuo_visual_yvaine",
                                "tap_ratio": {"x": 0.87, "y": 0.70},
                                "visual_anchor_region": {"x1": 0.04, "y1": 0.65, "x2": 0.96, "y2": 0.76},
                                "visible_name": "Yvaine",
                                "latest_preview": "hhhh辛苦",
                                "visual_anchor_hash": "yvaine_row",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cache = TaShuoStandaloneTargetCache(Path(temp_dir) / "data")
            skipped_cached = cache.get("tashuo_visual_000000ffffe7e7ef")
            yvaine_cached = cache.get("tashuo_visual_yvaine_row")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["warnings"], ["tashuo_message_list_visual_row_skipped"])
        self.assertEqual(payload["skipped_candidates"][0]["candidate_key"], "tashuo_visual_000000ffffe7e7ef")
        self.assertEqual(payload["skipped_candidates"][0]["reason"], "non_chat_gate")
        self.assertEqual([entry["candidate_key"] for entry in payload["message_list_snapshot"]["entries"]], ["tashuo_visual_yvaine_row"])
        self.assertIsNone(skipped_cached)
        self.assertEqual(yvaine_cached["visible_name"], "Yvaine")

    def test_message_list_observation_skips_unusable_perception_rows(self):
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
                                "visible_name": "坏行",
                                "latest_preview": "缺少点击位置",
                                "visual_anchor_hash": "",
                                "confidence": "medium",
                            },
                            {
                                "tap_ratio": {"x": 0.87, "y": 0.82},
                                "visual_anchor_region": {"x1": 0.04, "y1": 0.77, "x2": 0.96, "y2": 0.87},
                                "visible_name": "Ada",
                                "latest_preview": "刚刚问你忙不忙",
                                "visual_anchor_hash": "ada_row",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})

        self.assertEqual(payload["status"], "ok")
        self.assertIn("tashuo_message_list_perception_row_skipped", payload["warnings"])
        self.assertNotIn("tashuo_message_list_visual_row_skipped", payload["warnings"])
        self.assertEqual(payload["skipped_candidates"][0]["reason"], "tashuo_message_row_tap_ratio_required")
        self.assertEqual([entry["candidate_key"] for entry in payload["message_list_snapshot"]["entries"]], ["tashuo_visual_ada_row"])

    def test_message_list_observation_uses_grid_fallback_when_model_only_reports_non_chat_rows(self):
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
                                "tap_ratio": {"x": 0.205, "y": 0.455},
                                "visual_anchor_region": {"x1": 0.041, "y1": 0.405, "x2": 0.37, "y2": 0.505},
                                "visible_name": "52人喜欢了你",
                                "latest_preview": "别让她们等太久，快去认识下",
                                "visual_anchor_hash": "liked_you_row",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(
                    str(screen),
                    observe_payloads=[
                        {
                            "schema_version": 1,
                            "status": "ok",
                            "screen_state": "tashuo_chat_list",
                            "message_list_top_anchor_present": True,
                            "screen": {"path": str(screen)},
                        }
                    ],
                ),
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cache = TaShuoStandaloneTargetCache(Path(temp_dir) / "data")
            entries = payload["message_list_snapshot"]["entries"]
            cached_first = cache.get(entries[0]["candidate_key"])

        self.assertEqual(payload["status"], "ok")
        self.assertIn("tashuo_message_list_visual_row_skipped", payload["warnings"])
        self.assertIn("tashuo_message_list_grid_fallback_used", payload["warnings"])
        self.assertEqual(len(entries), 3)
        self.assertEqual([entry["message_list_evidence"]["tap_ratio"]["y"] for entry in entries], [0.577, 0.699, 0.821])
        self.assertTrue(entries[0]["visible_name"].startswith("TaShuo visible chat row"))
        self.assertEqual(entries[0]["message_list_evidence"]["selection_method"], "standalone_visual_message_list_grid_fallback")
        self.assertIsNotNone(cached_first)
        self.assertEqual(cached_first["selection_method"], "standalone_visual_message_list_grid_fallback")

    def test_message_list_observation_dedupes_same_visible_name_and_preview(self):
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
                                "tap_ratio": {"x": 0.87, "y": 0.82},
                                "visual_anchor_region": {"x1": 0.04, "y1": 0.77, "x2": 0.96, "y2": 0.87},
                                "visible_name": "小药丸儿",
                                "latest_preview": "我工作时间没办法哈哈哈 但我也喜...",
                                "visual_anchor_hash": "xiaoyaowan_row",
                                "confidence": "high",
                            },
                            {
                                "tap_ratio": {"x": 0.50, "y": 0.82},
                                "visual_anchor_region": {"x1": 0.04, "y1": 0.77, "x2": 0.50, "y2": 0.87},
                                "visible_name": "小药丸儿",
                                "latest_preview": "我工作时间没办法哈哈哈 但我也喜...",
                                "visual_anchor_hash": "xiaoyaowan_duplicate",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )
            payload = provider.observe_message_list(app_id="tashuo", scan_cursor={})
            cache = TaShuoStandaloneTargetCache(Path(temp_dir) / "data")
            cached_kept = cache.get("tashuo_visual_xiaoyaowan_row")
            cached_duplicate = cache.get("tashuo_visual_xiaoyaowan_duplicate")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual([entry["candidate_key"] for entry in payload["message_list_snapshot"]["entries"]], ["tashuo_visual_xiaoyaowan_row"])
        self.assertIn("tashuo_message_list_duplicate_visual_row_skipped", payload["warnings"])
        self.assertEqual(payload["skipped_candidates"][0]["reason"], "duplicate_visual_row")
        self.assertIsNotNone(cached_kept)
        self.assertIsNone(cached_duplicate)

    def test_message_list_skips_tashuo_recommendation_gates_and_likes_promos(self):
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
                                "visible_name": "Pending question avatar (illustration)",
                                "latest_preview": "Pending question row avatar",
                                "visual_anchor_hash": "pending_question_avatar",
                                "confidence": "medium",
                            },
                            {
                                "tap_ratio": {"x": 0.36, "y": 0.675},
                                "visible_name": "匿名提问卡片",
                                "latest_preview": "待回答横向问题卡片",
                                "visual_anchor_hash": "anonymous_question_card",
                                "confidence": "medium",
                            },
                            {
                                "tap_ratio": {"x": 0.36, "y": 0.675},
                                "visible_name": "有个很抢手的女生喜欢了你",
                                "latest_preview": "她比80%的女生都受欢迎哦~",
                                "visual_anchor_hash": "blurred_likes_you_new_badge_red_dot",
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
            cache = TaShuoStandaloneTargetCache(Path(temp_dir) / "data")
            answer_pending_cached = cache.get("tashuo_visual_answer_pending_portrait")
            pending_question_cached = cache.get("tashuo_visual_pending_question_avatar")
            anonymous_question_cached = cache.get("tashuo_visual_anonymous_question_card")
            likes_promo_cached = cache.get("tashuo_visual_blurred_likes_you_new_badge_red_dot")
            letty_cached = cache.get("tashuo_visual_male_hiker_avatar_purple_button")

        entries = payload["message_list_snapshot"]["entries"]
        self.assertEqual([entry["candidate_key"] for entry in entries], ["tashuo_visual_male_hiker_avatar_purple_button"])
        self.assertEqual(entries[0]["candidate_type"], "open_chat_candidate")
        self.assertEqual(payload["warnings"], ["tashuo_message_list_visual_row_skipped"])
        self.assertEqual(
            [item["reason"] for item in payload["skipped_candidates"]],
            ["non_chat_gate", "non_chat_gate", "non_chat_gate", "non_chat_gate"],
        )
        self.assertEqual(payload["candidates"][0]["tap_ratio"]["y"], 0.577)
        self.assertIsNone(answer_pending_cached)
        self.assertIsNone(pending_question_cached)
        self.assertIsNone(anonymous_question_cached)
        self.assertIsNone(likes_promo_cached)
        self.assertEqual(letty_cached["visible_name"], "Letty")

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

    def test_observe_thread_uses_local_header_anchor_when_model_hash_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_xiaoyaowan_preview",
                    "tap_ratio": {"x": 0.87, "y": 0.821},
                    "visual_anchor_region": {"x1": 0.0, "y1": 0.753, "x2": 1.0, "y2": 0.889},
                    "visible_name": "小药丸儿",
                    "latest_preview": "我工作时间没办法哈哈哈 但我也喜...",
                    "visual_anchor_hash": "rowhash",
                }
            )
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "小药丸儿",
                        "visual_anchor_hash": "",
                        "visible_messages": [
                            {
                                "direction": "inbound",
                                "text": "我工作时间没办法哈哈哈 但我也喜欢人少时候出门",
                                "confidence": "high",
                            }
                        ],
                    }
                ),
                adapter_factory=lambda: adapter,
            )
            with patch(
                "dating_boost.apps.tashuo.perception._tashuo_visual_anchor_hash_for_path",
                return_value={"status": "ok", "visual_anchor_hash": "localthreadhash", "grid_size": 8},
            ):
                payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_xiaoyaowan_preview")

        self.assertEqual(payload["status"], "ok", payload)
        thread_evidence = payload["target_binding"]["thread_evidence"]
        self.assertEqual(thread_evidence["visual_anchor_hash"], "localthreadhash")
        self.assertEqual(thread_evidence["source"], "local_perceptual_thread_anchor")
        self.assertEqual(thread_evidence["visual_anchor_region"], {"x1": 0.0, "y1": 0.08, "x2": 1.0, "y2": 0.65})
        self.assertEqual(payload["target_binding"]["visible_name"], "小药丸儿")

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

    def test_observe_thread_allows_tashuo_notification_prompt_wrapped_visible_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_yvaine",
                    "tap_ratio": {"x": 0.5, "y": 0.64},
                    "visible_name": "Yvaine",
                    "latest_preview": "哈嗲",
                    "visual_anchor_hash": "yvaine_row",
                }
            )
            adapter = FakeTaShuoAdapter(str(screen))
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=data_dir,
                output_dir=Path(temp_dir) / "harness",
                vision_backend=ScriptedVisionBackend(
                    {
                        "status": "ok",
                        "visible_name": "不要让Yvaine等太久",
                        "visual_anchor_hash": "threadhash",
                        "visible_messages": [{"direction": "inbound", "text": "哈嗲", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = provider.observe_thread(app_id="tashuo", candidate_key="tashuo_visual_yvaine")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_binding"]["visible_name"], "Yvaine")
        self.assertEqual(payload["target_binding"]["thread_evidence"]["visual_anchor_hash"], "threadhash")

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

    def test_observe_thread_reobserves_current_thread_without_cached_target(self):
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
                        "screen": {"path": str(screen)},
                    }
                ],
            )
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
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

            payload = provider.observe_thread(app_id="tashuo", candidate_key="current_thread")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["candidate_key"], "current_thread")
        self.assertEqual(payload["target_binding"]["binding_type"], "current_thread_visual_identity")
        self.assertEqual(payload["target_binding"]["thread_evidence"]["visual_anchor_hash"], "threadhash")
        self.assertEqual([call[0] for call in adapter.calls], ["observe"])

    def test_observe_current_thread_retries_once_after_vision_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            backend = TimeoutOnceVisionBackend(
                {
                    "status": "ok",
                    "visible_name": "Ada",
                    "visual_anchor_hash": "threadhash",
                    "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}],
                }
            )
            provider = TaShuoMacIosStandaloneObservationProvider(
                root=Path(temp_dir) / "data",
                output_dir=Path(temp_dir) / "harness",
                vision_backend=backend,
                adapter_factory=lambda: FakeTaShuoAdapter(str(screen)),
            )

            payload = provider.observe_thread(app_id="tashuo", candidate_key="current_thread")

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(backend.calls, 2)
        self.assertEqual(payload["candidate_key"], "current_thread")

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

    def test_stage_executor_verifies_current_thread_without_cached_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
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
                    "candidate_key": "current_thread",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "current_thread",
                        "visible_name": "Ada",
                        "thread_evidence": {"visual_anchor_hash": "threadhash"},
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(payload["target_verification"]["status"], "ok")
        self.assertEqual(payload["target_verification"]["candidate_key"], "current_thread")
        self.assertEqual([call for call in adapter.calls if call[0] == "run_action"], [])
        self.assertEqual(adapter.calls[-1][0], "stage_draft")

    def test_stage_executor_allows_current_thread_visible_name_continuity_when_latest_fingerprint_absent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
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
                        "visual_anchor_hash": "changed-threadhash",
                        "visible_messages": [],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "current_thread",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "current_thread",
                        "visible_name": "Ada",
                        "thread_evidence": {
                            "visual_anchor_hash": "threadhash",
                            "latest_inbound_fingerprint": "sha256:7eca689f0d3389d9dea66ae112e5cfd7f4fc2586cbb909d6405b6361e3a21f8d",
                        },
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(payload["target_verification"]["status"], "ok")
        self.assertEqual(payload["target_verification"]["thread_visual_anchor_hash"], "changed-threadhash")
        self.assertEqual([call for call in adapter.calls if call[0] == "run_action"], [])
        self.assertEqual(adapter.calls[-1][0], "stage_draft")

    def test_stage_executor_blocks_current_thread_when_latest_fingerprint_conflicts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
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
                        "visual_anchor_hash": "changed-threadhash",
                        "visible_messages": [{"direction": "inbound", "text": "不是原来的消息", "confidence": "high"}],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "current_thread",
                    "payload_text": "你好",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "current_thread",
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
        self.assertEqual(payload["reason"], "tashuo_standalone_target_not_found")
        self.assertEqual(payload["target_verification"]["reason"], "tashuo_standalone_target_not_found")
        self.assertEqual(payload["target_verification"]["in_place_result"]["reason"], "current_thread_binding_evidence_mismatch")
        self.assertNotIn(("stage_draft", "你好", {}), adapter.calls)

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

    def test_stage_executor_allows_anchor_drift_when_latest_preview_matches_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            TaShuoStandaloneTargetCache(data_dir).put(
                {
                    "candidate_key": "tashuo_visual_xiaoyaowaner_chat_row",
                    "tap_ratio": {"x": 0.87, "y": 0.821},
                    "visible_name": "小药丸儿",
                    "latest_preview": "我工作时间没办法哈哈哈 但我也喜...",
                    "visual_anchor_hash": "row_anchor",
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
                        "visible_name": "小药丸儿",
                        "visual_anchor_hash": "fresh_thread_anchor",
                        "visible_messages": [
                            {
                                "direction": "outbound",
                                "text": "错峰型人格实锤了哈哈",
                                "confidence": "high",
                            },
                            {
                                "direction": "inbound",
                                "text": "我工作时间没办法哈哈哈 但我也喜欢人少时候出门",
                                "confidence": "high",
                            },
                        ],
                    }
                ),
                adapter_factory=lambda: adapter,
            )

            payload = executor.execute(
                {
                    "work_item_type": "send_message",
                    "action_request_id": "act_1",
                    "candidate_key": "tashuo_visual_xiaoyaowaner_chat_row",
                    "payload_text": "哈哈哈理解",
                    "payload_hash": "hash_1",
                    "target_match_id": "match_1",
                    "target_binding": {
                        "binding_type": "current_thread_visual_identity",
                        "candidate_key": "tashuo_visual_xiaoyaowaner_chat_row",
                        "visible_name": "小药丸儿",
                        "thread_evidence": {
                            "visual_anchor_hash": "old_thread_anchor",
                            "latest_inbound_fingerprint": "sha256:not-the-current-fingerprint",
                        },
                    },
                },
                app_id="tashuo",
            )

        self.assertEqual(payload["status"], "stage_recorded")
        self.assertEqual(payload["target_verification"]["status"], "ok")
        self.assertEqual(
            payload["target_verification"]["verification_method"],
            "tashuo_stage_target_in_place_vision_identity_check",
        )
        self.assertNotIn("run_action", [call[0] for call in adapter.calls])

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
