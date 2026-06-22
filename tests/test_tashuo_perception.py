from pathlib import Path
import tempfile
import unittest

from dating_boost.apps.tashuo.perception import (
    analyze_tashuo_conversation,
    analyze_tashuo_message_list,
)
from dating_boost.intelligence.vision_backends import ScriptedVisionBackend


class TaShuoPerceptionTests(unittest.TestCase):
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
