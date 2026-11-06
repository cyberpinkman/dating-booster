"""Read a saved PNG with Apple Vision and expose local text geometry as TSV."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import struct
from pathlib import Path
from typing import Any


_VISION_SCRIPT = r'''
import Foundation
import Vision
import ImageIO

guard CommandLine.arguments.count == 2,
      let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { exit(2) }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
do {
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    let observations: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": candidate.string, "x": box.minX, "y": box.minY,
                "width": box.width, "height": box.height]
    }
    let payload: [String: Any] = ["width": image.width, "height": image.height, "observations": observations]
    let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch { exit(3) }
'''


def apple_vision_tsv(runner: Any, image_path: Path) -> dict[str, str]:
    """Recognize the image once; no target names or custom vocabulary are sent."""
    try:
        path = image_path.resolve()
        image_bytes = path.read_bytes()
        if len(image_bytes) < 24 or image_bytes[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
            return _unavailable("native_ocr_image_invalid")
        width, height = struct.unpack(">II", image_bytes[16:24])
        if width <= 0 or height <= 0:
            return _unavailable("native_ocr_image_invalid")
        digest = hashlib.sha256(image_bytes).digest()
        response = runner.run(["swift", "-e", _VISION_SCRIPT, str(path)])
        if response.returncode != 0:
            return _unavailable("native_ocr_unavailable")
        if hashlib.sha256(path.read_bytes()).digest() != digest:
            return _unavailable("native_ocr_image_changed")
    except Exception:  # noqa: BLE001 - subprocess/path diagnostics must not leak content.
        return _unavailable("native_ocr_unavailable")
    try:
        payload = json.loads(response.stdout, object_pairs_hook=_unique_fields)
        text = _to_tsv(payload, width=width, height=height)
    except (TypeError, ValueError, OverflowError):
        return _unavailable("native_ocr_result_invalid")
    return {"status": "ok", "text": text, "backend": "apple_vision"}


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_native_ocr_field")
        result[key] = value
    return result


def _to_tsv(payload: Any, *, width: int, height: int) -> str:
    if not isinstance(payload, dict) or set(payload) != {"width", "height", "observations"}:
        raise ValueError("native_ocr_fields_invalid")
    if type(payload["width"]) is not int or type(payload["height"]) is not int:
        raise ValueError("native_ocr_dimensions_invalid")
    if (payload["width"], payload["height"]) != (width, height) or not isinstance(payload["observations"], list):
        raise ValueError("native_ocr_dimensions_mismatch")
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"])
    for index, observation in enumerate(payload["observations"], start=1):
        if not isinstance(observation, dict) or set(observation) != {"text", "x", "y", "width", "height"}:
            raise ValueError("native_ocr_observation_invalid")
        if not isinstance(observation["text"], str):
            raise ValueError("native_ocr_text_invalid")
        box = [observation[key] for key in ("x", "y", "width", "height")]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in box):
            raise ValueError("native_ocr_bounds_invalid")
        x, y, box_width, box_height = box
        if not (0 <= x < x + box_width <= 1 and 0 <= y < y + box_height <= 1):
            raise ValueError("native_ocr_bounds_invalid")
        left, right = math.floor(x * width), math.ceil((x + box_width) * width)
        top, bottom = max(0, math.floor((1 - y - box_height) * height)), min(height, math.ceil((1 - y) * height))
        # One Vision observation remains one word/line: no substring matching,
        # emoji deletion, or fabricated per-character geometry enters grounding.
        writer.writerow([5, 1, 1, 1, index, 1, left, top, right - left, bottom - top, -1, observation["text"]])
    return output.getvalue()


def _unavailable(reason: str) -> dict[str, str]:
    return {"status": "unavailable", "reason": reason, "backend": "apple_vision"}
