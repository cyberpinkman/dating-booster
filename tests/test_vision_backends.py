from pathlib import Path
import json
import tempfile
import unittest

from dating_boost.intelligence.vision_backend_factory import create_vision_backend


class VisionBackendFactoryTests(unittest.TestCase):
    def test_scripted_vision_backend_returns_payloads_in_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vision.json"
            path.write_text(
                json.dumps([{"status": "ok", "kind": "list"}, {"status": "ok", "kind": "thread"}]),
                encoding="utf-8",
            )
            backend = create_vision_backend({"type": "scripted", "path": str(path)})
            first = backend.analyze_image_structured("system", "user", Path("screen1.png"), {"type": "object"})
            second = backend.analyze_image_structured("system", "user", Path("screen2.png"), {"type": "object"})
        self.assertEqual(first["kind"], "list")
        self.assertEqual(second["kind"], "thread")

    def test_scripted_vision_backend_requires_path(self):
        with self.assertRaises(ValueError) as raised:
            create_vision_backend({"type": "scripted"})
        self.assertEqual(str(raised.exception), "scripted_vision_backend_path_required")

    def test_scripted_vision_backend_rejects_empty_payload_array(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vision.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                create_vision_backend({"type": "scripted", "path": str(path)})
        self.assertEqual(str(raised.exception), "scripted_vision_backend_output_must_be_object_or_non_empty_array")
