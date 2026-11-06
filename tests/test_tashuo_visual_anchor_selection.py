from __future__ import annotations

import csv
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo import message_list_grounding
from dating_boost.apps.tashuo.message_list_anchor_selection import resolve_native_anchor_misses
from dating_boost.apps.tashuo.message_list_grounding import GroundedMessageList, ground_message_list_rows

pytestmark = pytest.mark.managed_critical


def _png(path: Path, *, color: int = 40) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 320, 640, 8, 2, 0, 0, 0)
    pixels = (b"\x00" + bytes([color, 50, 60]) * 320) * 640
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def _row(name: str) -> dict:
    return {
        "candidate_key": "original_" + name, "visible_name": name,
        "tap_ratio": {"x": 0.5, "y": 0.9},
        "visual_anchor_region": {"x1": 0.1, "y1": 0.85, "x2": 0.9, "y2": 0.95},
        "visual_anchor_hash": "original", "confidence": "high",
    }


def _payload(words: list[tuple[str, int, int, int, int]]) -> dict:
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"])
    for index, (text, left, top, width, height) in enumerate(words, 1):
        writer.writerow([5, 1, 1, 1, index, 1, left, top, width, height, -1, text])
    return {"status": "ok", "text": output.getvalue(), "backend": "apple_vision"}


def _selection(index: object = 1, anchor: object = "text_1", confidence: str = "high", **extra: object) -> dict:
    return {"candidate_index": index, "anchor_id": anchor, "confidence": confidence, **extra}


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    image = tmp_path / "synthetic.png"
    _png(image)

    def anchor_hash(path: Path, *, region: dict) -> dict:
        return {"status": "ok", "visual_anchor_hash": hashlib.sha256(json.dumps(region, sort_keys=True).encode()).hexdigest()[:16], "grid_size": 8}

    anchor = Mock(side_effect=anchor_hash)
    monkeypatch.setattr(message_list_grounding, "_tashuo_visual_anchor_hash_for_path", anchor)
    return SimpleNamespace(image=image, anchor=anchor)


def _primary(setup: SimpleNamespace, rows: list[dict], payload: dict) -> GroundedMessageList:
    return ground_message_list_rows(rows, screen_path=setup.image, ocr_tsv=lambda _: payload)


def _resolve(setup: SimpleNamespace, rows: list[dict], payload: dict, response: object, *, primary: GroundedMessageList | None = None, image_digest: str | None = None) -> tuple[GroundedMessageList, Mock]:
    backend = Mock()
    backend.analyze_image_structured.return_value = response
    result = resolve_native_anchor_misses(
        _primary(setup, rows, payload) if primary is None else primary,
        original_rows=rows, screen_path=setup.image, native_payload=payload,
        backend=backend,
        image_digest=image_digest if image_digest is not None else hashlib.sha256(setup.image.read_bytes()).hexdigest(),
    )
    return result, backend


def _assert_skipped(result: GroundedMessageList, positions: set[int]) -> None:
    assert {item["position"] for item in result.skipped} == positions
    assert all(isinstance(item.get("reason"), str) and item["reason"] for item in result.skipped)


def test_visual_selection_keeps_full_emoji_name_and_uses_the_selected_real_box(setup: SimpleNamespace) -> None:
    rows = [_row("Bee😀")]
    payload = _payload([("Bee", 50, 200, 90, 20)])

    result, backend = _resolve(setup, rows, payload, {"selections": [_selection()]})

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["visible_name"] == "Bee😀"
    assert row["tap_ratio"] == {"x": 0.2969, "y": 0.3281}
    assert row["visual_anchor_hash"] != "original"
    assert row["spatial_grounding"]["status"] == "verified"
    assert result.skipped == []
    backend.analyze_image_structured.assert_called_once()
    assert backend.analyze_image_structured.call_args.args[2] == setup.image
    schema = backend.analyze_image_structured.call_args.args[3]
    assert set(schema["properties"]) == {"selections"}
    selection_schema = schema["properties"]["selections"]["items"]
    assert set(selection_schema["properties"]) == {"candidate_index", "anchor_id", "confidence"}
    assert selection_schema["additionalProperties"] is False


def test_all_pending_candidates_share_one_call_and_keep_original_indices(setup: SimpleNamespace) -> None:
    rows = [_row("Alice"), _row("Bee😀"), _row("Dana"), _row("C😀")]
    payload = _payload([
        ("Alice", 50, 100, 90, 20), ("Bee", 50, 200, 90, 20),
        ("Dana", 50, 300, 90, 20), ("Dana", 50, 400, 90, 20),
        ("C", 50, 500, 90, 20),
    ])
    primary = _primary(setup, rows, payload)
    exact = primary.rows[0].copy()

    result, backend = _resolve(setup, rows, payload, {"selections": [_selection(4, "text_5"), _selection(2, "text_2")]}, primary=primary)

    assert [row["visible_name"] for row in result.rows] == ["Alice", "Bee😀", "C😀"]
    assert result.rows[0] == exact
    assert result.rows[1]["tap_ratio"] == {"x": 0.2969, "y": 0.3281}
    assert result.rows[2]["tap_ratio"] == {"x": 0.2969, "y": 0.7969}
    _assert_skipped(result, {3})
    assert result.skipped == primary.skipped
    backend.analyze_image_structured.assert_called_once()


def test_primary_exact_result_needs_no_visual_selection_call(setup: SimpleNamespace) -> None:
    rows = [_row("Alice")]
    payload = _payload([("Alice", 50, 100, 90, 20)])
    primary = _primary(setup, rows, payload)
    result, backend = _resolve(setup, rows, payload, {"selections": []}, primary=primary)
    assert result == primary
    backend.analyze_image_structured.assert_not_called()


def test_primary_ambiguous_candidate_cannot_be_resurrected(setup: SimpleNamespace) -> None:
    rows = [_row("Dana")]
    payload = _payload([("Dana", 50, 100, 90, 20), ("Dana", 50, 200, 90, 20)])
    primary = _primary(setup, rows, payload)
    result, backend = _resolve(setup, rows, payload, {"selections": [_selection()]}, primary=primary)
    assert result == primary
    assert result.rows == []
    backend.analyze_image_structured.assert_not_called()


def test_invalid_primary_exact_box_cannot_enter_visual_anchor_selection(setup: SimpleNamespace) -> None:
    rows = [_row("Bee😀")]
    payload = _payload([("Bee😀", 50, 200, 0, 20)])
    primary = _primary(setup, rows, payload)
    assert primary.rows[0]["spatial_grounding"]["reason"] == "exact_name_bbox_invalid"

    result, backend = _resolve(setup, rows, payload, {"selections": [_selection()]}, primary=primary)

    assert result.rows == []
    _assert_skipped(result, {1})
    backend.analyze_image_structured.assert_not_called()


@pytest.mark.parametrize("selection", [
    _selection(anchor=None), _selection(anchor="text_999"), _selection(anchor=""),
    _selection(confidence="medium"), _selection(confidence="low"), _selection(confidence="HIGH"),
    _selection(index=1.0), _selection(index=True), _selection(index="1"),
    _selection(index=0), _selection(index=2), _selection(anchor=1),
    _selection(tap_ratio={"x": 0.2, "y": 0.3}),
    {"candidate_index": 1, "confidence": "high"},
    {"candidate_index": 1, "anchor_id": "text_1"},
])
def test_untrusted_selection_never_falls_back_to_guessed_tap(setup: SimpleNamespace, selection: dict) -> None:
    rows = [_row("Bee😀")]
    result, backend = _resolve(setup, rows, _payload([("Bee", 50, 200, 90, 20)]), {"selections": [selection]})
    assert result.rows == []
    _assert_skipped(result, {1})
    backend.analyze_image_structured.assert_called_once()


@pytest.mark.parametrize("response", [None, [], {}, {"selections": None}, {"selections": []}, {"selections": [{}]}, {"selections": [_selection()], "tap_ratio": {"x": 0.2, "y": 0.3}}])
def test_missing_or_malformed_response_has_no_retry_and_no_visual_geometry_fallback(setup: SimpleNamespace, response: object) -> None:
    result, backend = _resolve(setup, [_row("Bee😀")], _payload([("Bee", 50, 200, 90, 20)]), response)
    assert result.rows == []
    _assert_skipped(result, {1})
    backend.analyze_image_structured.assert_called_once()


@pytest.mark.parametrize("selections", [
    [_selection(1, "text_1"), _selection(1, "text_2"), _selection(3, "text_3")],
    [_selection(1, "text_1"), _selection(2, "text_1"), _selection(3, "text_3")],
])
def test_duplicate_candidate_or_anchor_rejects_involved_rows_without_discarding_independent_selection(setup: SimpleNamespace, selections: list[dict]) -> None:
    rows = [_row("A😀"), _row("B😀"), _row("C😀")]
    payload = _payload([("A", 50, 100, 90, 20), ("B", 50, 200, 90, 20), ("C", 50, 300, 90, 20)])
    result, backend = _resolve(setup, rows, payload, {"selections": selections})
    assert [row["visible_name"] for row in result.rows] == ["C😀"]
    _assert_skipped(result, {1, 2})
    backend.analyze_image_structured.assert_called_once()


@pytest.mark.parametrize("selected_anchor", ["text_1", "text_2"])
def test_anchor_owned_by_or_overlapping_primary_exact_cannot_be_reassigned(setup: SimpleNamespace, selected_anchor: str) -> None:
    rows = [_row("Alice"), _row("Bee😀")]
    payload = _payload([("Alice", 50, 100, 90, 20), ("Ali", 55, 103, 70, 15), ("Bee", 50, 200, 90, 20)])
    primary = _primary(setup, rows, payload)
    exact = primary.rows[0].copy()

    result, _ = _resolve(setup, rows, payload, {"selections": [_selection(2, selected_anchor)]}, primary=primary)

    assert result.rows == [exact]
    _assert_skipped(result, {2})


def test_backend_failure_drops_only_unresolved_rows_and_has_no_raw_diagnostics(setup: SimpleNamespace) -> None:
    rows = [_row("Alice"), _row("Bee😀")]
    payload = _payload([("Alice", 50, 100, 90, 20), ("Bee", 50, 200, 90, 20)])
    primary = _primary(setup, rows, payload)
    backend = Mock()
    backend.analyze_image_structured.side_effect = RuntimeError("PRIVATE_MODEL_DIAGNOSTIC")

    result = resolve_native_anchor_misses(primary, original_rows=rows, screen_path=setup.image, native_payload=payload, backend=backend, image_digest=hashlib.sha256(setup.image.read_bytes()).hexdigest())

    assert result.rows == [primary.rows[0]]
    _assert_skipped(result, {2})
    assert "PRIVATE" not in str(result)
    assert "Bee" not in str(result.summary)
    backend.analyze_image_structured.assert_called_once()


@pytest.mark.parametrize("changed_before", [True, False])
def test_image_change_before_or_during_model_call_invalidates_even_primary_exact(setup: SimpleNamespace, changed_before: bool) -> None:
    rows = [_row("Alice"), _row("Bee😀")]
    payload = _payload([("Alice", 50, 100, 90, 20), ("Bee", 50, 200, 90, 20)])
    primary = _primary(setup, rows, payload)
    digest = hashlib.sha256(setup.image.read_bytes()).hexdigest()
    backend = Mock()

    def changed_response(*args: object, **kwargs: object) -> dict:
        _png(setup.image, color=80)
        return {"selections": [_selection(2, "text_2")]}

    backend.analyze_image_structured.side_effect = changed_response
    if changed_before:
        _png(setup.image, color=80)

    result = resolve_native_anchor_misses(primary, original_rows=rows, screen_path=setup.image, native_payload=payload, backend=backend, image_digest=digest)

    assert result.rows == []
    _assert_skipped(result, {1, 2})
    assert backend.analyze_image_structured.call_count == (0 if changed_before else 1)


@pytest.mark.parametrize("unavailable", ["screen", "digest", "malformed_tsv"])
def test_unavailable_anchor_evidence_skips_misses_without_model_or_guessed_geometry(setup: SimpleNamespace, unavailable: str) -> None:
    rows = [_row("Bee😀")]
    payload = _payload([("Bee", 50, 200, 90, 20)])
    primary = _primary(setup, rows, payload)
    backend = Mock()
    result = resolve_native_anchor_misses(
        primary, original_rows=rows,
        screen_path=None if unavailable == "screen" else setup.image,
        native_payload=None if unavailable == "payload" else {**payload, "text": "PRIVATE_BAD_TSV"} if unavailable == "malformed_tsv" else payload,
        backend=backend, image_digest=None if unavailable == "digest" else hashlib.sha256(setup.image.read_bytes()).hexdigest(),
    )
    assert result.rows == []
    _assert_skipped(result, {1})
    assert "PRIVATE" not in str(result)
    backend.analyze_image_structured.assert_not_called()


@pytest.mark.parametrize("native_payload", [None, {"status": "unavailable", "backend": "apple_vision"}])
def test_unavailable_native_backend_preserves_optional_visual_route(setup, native_payload):
    rows = [_row("Bee😀")]
    primary = _primary(setup, rows, {"status": "unavailable"})
    backend = Mock()
    result = resolve_native_anchor_misses(primary, original_rows=rows, screen_path=setup.image,
        native_payload=native_payload, backend=backend, image_digest=hashlib.sha256(setup.image.read_bytes()).hexdigest())
    assert result == primary
    backend.analyze_image_structured.assert_not_called()


@pytest.mark.parametrize("invalid", [
    _selection(99), _selection(2.0), _selection(2, tap_ratio={"x": .2, "y": .3}), None,
])
def test_any_malformed_or_out_of_scope_item_invalidates_all_pending_mappings(setup, invalid):
    rows = [_row("Alice"), _row("B😀"), _row("C😀")]
    payload = _payload([("Alice", 50, 100, 90, 20), ("B", 50, 200, 90, 20), ("C", 50, 300, 90, 20)])
    primary = _primary(setup, rows, payload)
    response = {"selections": [_selection(2, "text_2"), _selection(3, "text_3"), invalid]}
    result, backend = _resolve(setup, rows, payload, response, primary=primary)
    assert result.rows == [primary.rows[0]]
    _assert_skipped(result, {2, 3})
    backend.analyze_image_structured.assert_called_once()


def test_image_change_is_checked_even_when_every_primary_name_is_exact(setup):
    rows = [_row("Alice")]
    payload = _payload([("Alice", 50, 100, 90, 20)])
    primary = _primary(setup, rows, payload)
    digest = hashlib.sha256(setup.image.read_bytes()).hexdigest()
    _png(setup.image, color=80)
    result, backend = _resolve(setup, rows, payload, {"selections": []}, primary=primary, image_digest=digest)
    assert result.rows == []
    _assert_skipped(result, {1})
    backend.analyze_image_structured.assert_not_called()
