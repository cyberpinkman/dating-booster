from pathlib import Path
import tempfile
import unittest

from dating_boost.apps.tashuo.perception import (
    analyze_tashuo_conversation,
    analyze_tashuo_conversation_evidence_v2,
    analyze_tashuo_message_list,
)
from dating_boost.intelligence.vision_backends import ScriptedVisionBackend


class FlakyVisionBackend:
    def __init__(self):
        self.calls = []

    def analyze_image_structured(self, system_prompt, user_prompt, image_path, schema):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "image_path": image_path})
        if len(self.calls) == 1:
            raise RuntimeError("MiniMax structured response was not valid JSON.")
        return {
            "status": "ok",
            "rows": [
                {
                    "tap_ratio": {"x": 0.5, "y": 0.42},
                    "visual_anchor_region": {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
                    "visible_name": "Ada",
                    "latest_preview": "刚刚发来一条消息",
                    "visual_anchor_hash": "7f83a1d2",
                    "confidence": "high",
                }
            ],
        }


class AlwaysFailingVisionBackend:
    def __init__(self):
        self.calls = []

    def analyze_image_structured(self, system_prompt, user_prompt, image_path, schema):
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt, "image_path": image_path})
        raise RuntimeError("MiniMax structured response did not contain a valid structured payload.")


class TaShuoPerceptionTests(unittest.TestCase):
    def test_conversation_evidence_v2_requires_geometry_and_emits_no_raw_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "bubbles": [
                        {
                            "direction": "inbound",
                            "text": "private hello",
                            "bounds": {"x1": 0.1, "y1": 0.2, "x2": 0.7, "y2": 0.3},
                            "confidence": 0.99,
                        },
                        {
                            "direction": "outbound",
                            "text": "private reply",
                            "bounds": {"x1": 0.3, "y1": 0.4, "x2": 0.9, "y2": 0.5},
                            "confidence": 0.98,
                        },
                    ],
                }
            )
            payload = analyze_tashuo_conversation_evidence_v2(
                {"status": "ok", "screen": {"path": str(screen)}},
                backend=backend,
                qualification_salt="salt",
                target_binding={"target_match_id": "match_private"},
                viewport_identity="viewport_1",
                capture_id="capture_1",
                observation_id="observation_1",
                captured_monotonic_ns=100,
            )

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["evidence_type"], "conversation_tail_v2")
        self.assertEqual([item["direction"] for item in payload["bubbles"]], ["inbound", "outbound"])
        self.assertNotIn("private hello", str(payload))
        self.assertNotIn("private reply", str(payload))
        self.assertNotIn("match_private", str(payload))

    def test_conversation_evidence_v2_rejects_missing_geometry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {"status": "ok", "bubbles": [{"direction": "inbound", "text": "hello", "confidence": 0.99}]}
            )
            payload = analyze_tashuo_conversation_evidence_v2(
                {"status": "ok", "screen": {"path": str(screen)}},
                backend=backend,
                qualification_salt="salt",
                target_binding={"target_match_id": "match_private"},
                viewport_identity="viewport_1",
                capture_id="capture_1",
                observation_id="observation_1",
                captured_monotonic_ns=100,
            )
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tail_v2_bubble_bounds_invalid")

    def test_message_list_requires_screen_path(self):
        backend = ScriptedVisionBackend({"status": "ok", "rows": []})
        payload = analyze_tashuo_message_list({"status": "ok", "screen": {}}, backend=backend)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "screen_path_required_for_tashuo_message_list_perception")

    def test_message_list_normalizes_rows_and_candidate_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.50, "y": 0.42},
                            "visual_anchor_region": {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
                            "visible_name": "Ada",
                            "latest_preview": "刚刚发来一条消息",
                            "visual_anchor_hash": "7f83a1d2",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["candidate_key"], "tashuo_visual_7f83a1d2")
        self.assertEqual(payload["rows"][0]["tap_ratio"], {"x": 0.5, "y": 0.42})
        self.assertEqual(payload["rows"][0]["visual_anchor_region"], {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49})
        self.assertEqual(payload["rows"][0]["visual_anchor_region_source"], "vision_unit_normalized")

    def test_message_list_retries_structured_json_parse_failure_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = FlakyVisionBackend()
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("Return exactly one JSON object", backend.calls[1]["user_prompt"])
        self.assertEqual(payload["rows"][0]["candidate_key"], "tashuo_visual_7f83a1d2")

    def test_message_list_blocks_after_repeated_structured_json_parse_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = AlwaysFailingVisionBackend()
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_message_list_structured_json_invalid")
        self.assertEqual(len(backend.calls), 2)

    def test_message_list_accepts_percent_visual_anchor_region(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.50, "y": 0.42},
                            "visual_anchor_region": {"x1": 12, "y1": 37, "x2": 88, "y2": 49},
                            "visible_name": "Ada",
                            "visual_anchor_hash": "7f83a1d2",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["visual_anchor_region"], {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49})
        self.assertEqual(payload["rows"][0]["visual_anchor_region_source"], "vision_percent_normalized")

    def test_message_list_accepts_mixed_percent_visual_anchor_region(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.87, "y": 0.821},
                            "visual_anchor_region": {"x1": 0.06, "y1": 80.6, "x2": 0.2, "y2": 83.6},
                            "visible_name": "小药丸儿",
                            "visual_anchor_hash": "00ffff00ffff00ff",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["visual_anchor_region"], {"x1": 0.06, "y1": 0.806, "x2": 0.2, "y2": 0.836})
        self.assertEqual(payload["rows"][0]["visual_anchor_region_source"], "vision_mixed_percent_normalized")

    def test_message_list_derives_visual_anchor_region_from_tap_ratio_when_model_region_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.50, "y": 0.42},
                            "visual_anchor_region": {"x1": 0.88, "y1": 0.37, "x2": 0.12, "y2": 0.49},
                            "visible_name": "Ada",
                            "visual_anchor_hash": "7f83a1d2",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["visual_anchor_region"], {"x1": 0.04, "y1": 0.36, "x2": 0.96, "y2": 0.48})
        self.assertEqual(
            payload["rows"][0]["visual_anchor_region_source"],
            "derived_from_tap_ratio_after_invalid_vision_region",
        )

    def test_message_list_derives_visual_anchor_region_from_tap_ratio_when_model_region_too_tiny(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": 0.87, "y": 0.821},
                            "visual_anchor_region": {"x1": 0.0006, "y1": 0.806, "x2": 0.002, "y2": 0.836},
                            "visible_name": "小药丸儿",
                            "visual_anchor_hash": "00ffff00ffff00ff",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["tap_ratio"], {"x": 0.87, "y": 0.821})
        self.assertEqual(payload["rows"][0]["visual_anchor_region"], {"x1": 0.04, "y1": 0.761, "x2": 0.96, "y2": 0.881})
        self.assertEqual(
            payload["rows"][0]["visual_anchor_region_source"],
            "derived_from_tap_ratio_after_tiny_vision_region",
        )

    def test_message_list_blocks_without_tap_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {"status": "ok", "rows": [{"visible_name": "Ada", "visual_anchor_hash": "7f83a1d2"}]}
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_message_row_tap_ratio_required")

    def test_message_list_derives_tap_ratio_from_visual_anchor_region_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "visual_anchor_region": {"x1": 0.12, "y1": 0.37, "x2": 0.88, "y2": 0.49},
                            "visible_name": "Ada",
                            "visual_anchor_hash": "7f83a1d2",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["rows"][0]["tap_ratio"], {"x": 0.5, "y": 0.43})
        self.assertEqual(payload["rows"][0]["tap_ratio_source"], "derived_from_visual_anchor_region")

    def test_message_list_blocks_invalid_tap_ratio_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "screen.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "rows": [
                        {
                            "tap_ratio": {"x": "left", "y": 0.42},
                            "visible_name": "Ada",
                            "visual_anchor_hash": "7f83a1d2",
                            "confidence": "high",
                        }
                    ],
                }
            )
            payload = analyze_tashuo_message_list({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["reason"], "tashuo_message_row_tap_ratio_invalid")

    def test_conversation_normalizes_visible_messages_and_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            screen = Path(temp_dir) / "thread.png"
            screen.write_bytes(b"png")
            backend = ScriptedVisionBackend(
                {
                    "status": "ok",
                    "visible_name": "Ada",
                    "visual_anchor_hash": "threadhash",
                    "visible_messages": [{"direction": "inbound", "text": "你好呀", "confidence": "high"}],
                }
            )
            payload = analyze_tashuo_conversation({"status": "ok", "screen": {"path": str(screen)}}, backend=backend)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["identity"]["visual_anchor_hash"], "threadhash")
        self.assertEqual(payload["visible_messages"][0]["text"], "你好呀")
