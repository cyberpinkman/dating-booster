from __future__ import annotations

import csv
import io
import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo import message_list_grounding
from dating_boost.apps.tashuo.message_list_grounding import ground_message_list_rows
from dating_boost.harness.native_text import apple_vision_tsv

pytestmark = pytest.mark.managed_critical


def _png(path: Path, width: int = 320, height: int = 640) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = (b"\x00" + b"\x40\x50\x60" * width) * height
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    )


@pytest.fixture
def image_path(tmp_path: Path) -> Path:
    image = tmp_path / "synthetic list.png"
    _png(image)
    return image


def _observation(text: str = "PRIVATE_RECOGNIZED_TEXT", **overrides: object) -> dict:
    return {"text": text, "x": 0.25, "y": 0.625, "width": 0.375, "height": 0.0625, **overrides}


def _payload(observations: list | None = None, **overrides: object) -> dict:
    return {"width": 320, "height": 640, "observations": [_observation()] if observations is None else observations, **overrides}


def _runner(payload: object = None, *, stdout: str | None = None, returncode: int = 0) -> SimpleNamespace:
    result = SimpleNamespace(
        returncode=returncode,
        stdout=json.dumps(payload, ensure_ascii=False) if stdout is None else stdout,
        stderr="PRIVATE_RUNNER_STDERR",
    )
    return SimpleNamespace(run=Mock(return_value=result))


def _assert_unavailable(result: dict, runner: SimpleNamespace) -> None:
    assert result["status"] == "unavailable"
    assert result["backend"] == "apple_vision"
    assert isinstance(result.get("reason"), str) and result["reason"]
    assert "text" not in result
    assert "PRIVATE" not in str(result)
    assert runner.run.call_count <= 1


def _tsv_rows(result: dict) -> list[dict[str, str]]:
    assert result["status"] == "ok"
    assert result["backend"] == "apple_vision"
    reader = csv.DictReader(io.StringIO(result["text"]), delimiter="\t")
    assert set(reader.fieldnames or []) == {
        "level", "page_num", "block_num", "par_num", "line_num", "word_num",
        "left", "top", "width", "height", "conf", "text",
    }
    return list(reader)


def test_bottom_origin_observations_become_top_origin_pixel_boxes_in_one_request(image_path: Path) -> None:
    runner = _runner(_payload([
        _observation("upper"),
        _observation("bottom", x=0, y=0, width=0.125),
    ]))

    rows = {row["text"]: row for row in _tsv_rows(apple_vision_tsv(runner, image_path))}

    assert tuple(int(rows["upper"][key]) for key in ("left", "top", "width", "height")) == (80, 200, 120, 40)
    assert tuple(int(rows["bottom"][key]) for key in ("left", "top", "width", "height")) == (0, 600, 40, 40)
    assert all(row["level"] == "5" for row in rows.values())
    command = runner.run.call_args.args[0]
    assert command[:2] == ["swift", "-e"]
    assert len(command) == 4
    assert command[3] == str(image_path.resolve())
    assert "PRIVATE" not in command[2]
    runner.run.assert_called_once()


def test_recognized_text_is_lossless_in_tsv_without_name_or_emoji_rewriting(image_path: Path) -> None:
    texts = ["A😀!", "a", "A", "  A\tB\n😀!  ", "e\u0301"]
    runner = _runner(_payload([_observation(text, y=index / 8) for index, text in enumerate(texts)]))

    rows = _tsv_rows(apple_vision_tsv(runner, image_path))

    assert sorted(row["text"] for row in rows) == sorted(texts)
    command = runner.run.call_args.args[0]
    assert "customWords" not in command[2]
    assert all(text not in command[2] for text in ("A😀!", "e\u0301"))


def test_empty_observations_produce_a_valid_empty_tsv(image_path: Path) -> None:
    runner = _runner(_payload([]))
    assert _tsv_rows(apple_vision_tsv(runner, image_path)) == []
    runner.run.assert_called_once()


@pytest.mark.parametrize("payload", [
    None, [], "PRIVATE_SCHEMA_ERROR", {},
    _payload(extra="PRIVATE_UNEXPECTED_FIELD"),
    _payload(width=True), _payload(width=320.0), _payload(width="320"),
    _payload(width=0), _payload(width=-320), _payload(width=321),
    _payload(height=False), _payload(height=640.0), _payload(height=641),
    _payload(observations={"text": "PRIVATE_BAD_LIST"}),
    _payload([None]), _payload([[]]), _payload([{}]),
    _payload([_observation(text=None)]),
    _payload([_observation(extra="PRIVATE_OBSERVATION_FIELD")]),
])
def test_schema_and_image_dimensions_are_strict_and_fail_without_raw_values(image_path: Path, payload: object) -> None:
    runner = _runner(payload)
    _assert_unavailable(apple_vision_tsv(runner, image_path), runner)


@pytest.mark.parametrize("override", [
    {"x": True}, {"y": False}, {"width": True}, {"height": False},
    {"x": "0.25"}, {"height": None},
    {"x": float("nan")}, {"y": float("inf")}, {"width": float("-inf")},
    {"x": -0.01}, {"y": -0.01}, {"x": 1}, {"y": 1},
    {"width": 0}, {"height": 0}, {"width": -0.25}, {"height": -0.0625},
    {"x": 0.75, "width": 0.375}, {"y": 0.99, "height": 0.0625},
])
def test_any_invalid_normalized_box_rejects_the_entire_result(image_path: Path, override: dict) -> None:
    # A malformed duplicate must not disappear and make the valid one unique.
    runner = _runner(_payload([_observation(), _observation(**override)]))
    _assert_unavailable(apple_vision_tsv(runner, image_path), runner)


@pytest.mark.parametrize("stdout", [
    "PRIVATE_NOT_JSON", "```json\n{}\n```", "{} PRIVATE_TRAILING_TEXT",
    '{"width":320,"width":320,"height":640,"observations":[]}',
    '{"width":320,"height":640,"observations":[{"text":"PRIVATE_FIRST","text":"PRIVATE_SECOND","x":0.25,"y":0.625,"width":0.375,"height":0.0625}]}',
])
def test_malformed_json_and_duplicate_keys_are_unavailable(image_path: Path, stdout: str) -> None:
    runner = _runner(stdout=stdout)
    _assert_unavailable(apple_vision_tsv(runner, image_path), runner)


def test_nonzero_runner_exit_never_consumes_even_valid_stdout(image_path: Path) -> None:
    runner = _runner(_payload(), returncode=1)
    _assert_unavailable(apple_vision_tsv(runner, image_path), runner)
    runner.run.assert_called_once()


@pytest.mark.parametrize("failure", [FileNotFoundError("PRIVATE_EXECUTABLE_PATH"), RuntimeError("PRIVATE_RUNNER_EXCEPTION")])
def test_runner_failure_is_fixed_diagnostic_without_retry(image_path: Path, failure: Exception) -> None:
    runner = _runner()
    runner.run.side_effect = failure
    _assert_unavailable(apple_vision_tsv(runner, image_path), runner)
    runner.run.assert_called_once()


@pytest.mark.parametrize("header", [None, b"PRIVATE_NOT_A_PNG", b"\x89PNG\r\n\x1a\n", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 0, 640)])
def test_missing_or_invalid_png_never_produces_geometry(tmp_path: Path, header: bytes | None) -> None:
    image = tmp_path / "PRIVATE_IMAGE_PATH.png"
    if header is not None:
        image.write_bytes(header)
    runner = _runner(_payload())
    _assert_unavailable(apple_vision_tsv(runner, image), runner)


def _candidate(name: str) -> dict:
    return {
        "candidate_key": "tashuo_visual_original", "visible_name": name,
        "tap_ratio": {"x": 0.5, "y": 0.4},
        "visual_anchor_region": {"x1": 0.1, "y1": 0.35, "x2": 0.9, "y2": 0.45},
        "visual_anchor_hash": "original", "confidence": "high",
    }


def test_duplicate_exact_names_from_native_tsv_remain_ambiguous_to_grounder(image_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    anchor = Mock()
    monkeypatch.setattr(message_list_grounding, "_tashuo_visual_anchor_hash_for_path", anchor)
    runner = _runner(_payload([_observation("小明"), _observation("小明", y=0.25)]))

    result = ground_message_list_rows(
        [_candidate("小明")], screen_path=image_path,
        ocr_tsv=lambda path: apple_vision_tsv(runner, path),
    )

    assert result.rows == []
    assert result.skipped[0]["reason"] == "message_list_name_location_ambiguous"
    assert result.skipped[0]["matching_occurrence_count"] == 2
    assert "小明" not in str(result)
    anchor.assert_not_called()
    runner.run.assert_called_once()


@pytest.mark.parametrize(("expected", "observed"), [("A😀", "A"), ("A", "A😀"), ("Alice", "alice"), ("Ann", "Anna")])
def test_native_text_does_not_create_fuzzy_or_emoji_stripped_identity_matches(image_path: Path, monkeypatch: pytest.MonkeyPatch, expected: str, observed: str) -> None:
    anchor = Mock()
    monkeypatch.setattr(message_list_grounding, "_tashuo_visual_anchor_hash_for_path", anchor)
    runner = _runner(_payload([_observation(observed)]))
    candidate = _candidate(expected)

    result = ground_message_list_rows(
        [candidate], screen_path=image_path,
        ocr_tsv=lambda path: apple_vision_tsv(runner, path),
    )

    assert result.rows[0]["spatial_grounding"]["reason"] == "exact_name_not_found"
    assert result.rows[0]["tap_ratio"] == candidate["tap_ratio"]
    assert result.rows[0]["visual_anchor_hash"] == candidate["visual_anchor_hash"]
    anchor.assert_not_called()


def test_native_box_coordinates_ground_the_verified_name_on_the_same_image(image_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    anchor = Mock(return_value={"status": "ok", "visual_anchor_hash": "0123456789abcdef", "grid_size": 8})
    monkeypatch.setattr(message_list_grounding, "_tashuo_visual_anchor_hash_for_path", anchor)
    runner = _runner(_payload([_observation("Celia")]))

    result = ground_message_list_rows(
        [_candidate("Celia")], screen_path=image_path,
        ocr_tsv=lambda path: apple_vision_tsv(runner, path),
    )

    assert result.rows[0]["spatial_grounding"]["status"] == "verified"
    assert result.rows[0]["tap_ratio"] == {"x": 0.4375, "y": 0.3438}
    assert anchor.call_args.args[0] == image_path
    assert result.summary["grounded_count"] == 1
    runner.run.assert_called_once()
