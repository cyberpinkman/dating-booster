from __future__ import annotations

import csv
import io
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo import message_list_grounding as module
from dating_boost.apps.tashuo import standalone
from dating_boost.apps.tashuo.message_list_grounding import ground_message_list_rows

pytestmark = pytest.mark.managed_critical


def _png(path, width=320, height=640):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"".join(b"\x00" + bytes([y % 256, 40, 80]) * width for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def _row(name, **extra):
    return {"candidate_key": "tashuo_visual_old", "visible_name": name, "tap_ratio": {"x": 0.51, "y": 0.39}, "visual_anchor_region": {"x1": 0.06, "y1": 0.32, "x2": 0.95, "y2": 0.46}, "visual_anchor_hash": "old", "confidence": "high", **extra}


def _tsv(words):
    output = io.StringIO()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(["level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"])
    for index, word in enumerate(words, 1):
        text, line, left, top, width, height = word
        writer.writerow([5, 1, 1, 1, line, index, left, top, width, height, 95, text])
    return output.getvalue()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    image = tmp_path / "list.png"
    _png(image)
    anchor = Mock(return_value={"status": "ok", "visual_anchor_hash": "0123456789abcdef", "grid_size": 8})
    monkeypatch.setattr(module, "_tashuo_visual_anchor_hash_for_path", anchor)
    return image, anchor


def test_unique_full_name_word_sequence_uses_actual_bbox_center_and_consistent_anchor(setup):
    image, anchor = setup
    ocr = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 30, 16), ("Lovelace", 1, 90, 160, 70, 16), ("12:30", 1, 260, 160, 40, 16)])})
    result = ground_message_list_rows([_row("Ada Lovelace")], screen_path=image, ocr_tsv=ocr)
    row = result.rows[0]
    assert row["tap_ratio"] == {"x": 0.3281, "y": 0.2625}
    assert row["visual_anchor_region"] == {"x1": 0.1313, "y1": 0.2375, "x2": 0.525, "y2": 0.2875}
    assert row["candidate_key"] == "tashuo_visual_" + row["visual_anchor_hash"]
    assert row["tap_ratio_source"] == "post_vision_ocr_exact_name_bbox"
    assert anchor.call_args.kwargs["region"] == row["visual_anchor_region"]
    ocr.assert_called_once_with(image)
    assert result.summary["grounded_count"] == 1
    assert "Ada" not in str(result.summary)


def test_cjk_word_segmentation_spaces_can_join_but_english_boundaries_are_preserved(setup):
    image, _ = setup
    ocr = Mock(return_value={"status": "ok", "text": _tsv([("小", 1, 50, 160, 15, 16), ("明", 1, 65, 160, 15, 16), ("Ann", 2, 50, 240, 30, 16), ("a", 2, 90, 240, 10, 16)])})
    result = ground_message_list_rows([_row("小明"), _row("Anna")], screen_path=image, ocr_tsv=ocr)
    assert result.rows[0]["spatial_grounding"]["status"] == "verified"
    assert result.rows[1]["spatial_grounding"]["reason"] == "exact_name_not_found"
    assert result.summary["grounded_count"] == 1
    ocr.assert_called_once()


@pytest.mark.parametrize("expected,observed", [("Ann", "Anna"), ("小明", "小明同学"), ("alice", "Alice"), ("小明", "小明!"), ("小名", "小明")])
def test_partial_fuzzy_case_and_punctuation_name_matches_never_ground(setup, expected, observed):
    image, anchor = setup
    source = _row(expected)
    result = ground_message_list_rows([source], screen_path=image, ocr_tsv=lambda _: {"status": "ok", "text": _tsv([(observed, 1, 50, 160, 80, 16)])})
    assert result.rows[0]["tap_ratio"] == source["tap_ratio"]
    assert result.rows[0]["visual_anchor_hash"] == "old"
    assert result.rows[0]["spatial_grounding"]["reason"] == "exact_name_not_found"
    anchor.assert_not_called()


@pytest.mark.parametrize("second_top", [320, -10])
def test_duplicate_full_names_skip_candidate_even_when_one_bbox_is_invalid(setup, second_top):
    image, anchor = setup
    result = ground_message_list_rows([_row("小明")], screen_path=image, ocr_tsv=lambda _: {"status": "ok", "text": _tsv([("小明", 1, 50, 160, 50, 16), ("小明", 2, 50, second_top, 50, 16)])})
    assert result.rows == []
    assert result.skipped == [{"position": 1, "reason": "message_list_name_location_ambiguous", "matching_occurrence_count": 2, "source": "post_vision_ocr_tsv"}]
    assert "小明" not in str(result)
    anchor.assert_not_called()


@pytest.mark.parametrize("bounds", [(-1, 160, 50, 16), (300, 160, 50, 16), (50, -1, 50, 16), (50, 630, 50, 16), (50, 160, 0, 16), (50, 160, 50, "nan")])
def test_invalid_or_out_of_png_bbox_never_creates_grounded_identity(setup, bounds):
    image, anchor = setup
    result = ground_message_list_rows([_row("小明")], screen_path=image, ocr_tsv=lambda _: {"status": "ok", "text": _tsv([("小明", 1, *bounds)])})
    assert result.rows[0]["spatial_grounding"]["reason"] == "exact_name_bbox_invalid"
    assert result.rows[0]["candidate_key"] == "tashuo_visual_old"
    anchor.assert_not_called()


@pytest.mark.parametrize("failure", [None, {"status": "unavailable"}, {"status": "ok", "text": "malformed"}, RuntimeError("PRIVATE RAW TEXT")])
def test_unavailable_ocr_preserves_visual_route_without_exposing_raw_errors(setup, failure):
    image, _ = setup
    ocr = None if failure is None else Mock(side_effect=failure if isinstance(failure, Exception) else None, return_value=failure)
    source = [_row("小明")]
    result = ground_message_list_rows(source, screen_path=image, ocr_tsv=ocr)
    assert result.rows == source
    assert result.skipped == []
    assert result.summary["status"] == "unavailable"
    assert "PRIVATE" not in str(result.summary)


def test_anchor_failure_does_not_emit_partially_changed_candidate_key_or_geometry(setup):
    image, anchor = setup
    anchor.return_value = {"status": "blocked"}
    source = _row("小明")
    result = ground_message_list_rows([source], screen_path=image, ocr_tsv=lambda _: {"status": "ok", "text": _tsv([("小明", 1, 50, 160, 50, 16)])})
    assert result.rows[0]["spatial_grounding"]["reason"] == "exact_name_anchor_unavailable"
    for field in ("candidate_key", "visual_anchor_hash", "visual_anchor_region", "tap_ratio"):
        assert result.rows[0][field] == source[field]


def test_one_tsv_is_reused_for_every_candidate(setup):
    image, _ = setup
    names = ["Ada", "Bob", "Carol", "Dora", "Emma", "Fran"]
    ocr = Mock(return_value={"status": "ok", "text": _tsv([(name, index, 50, 80 * index, 50, 16) for index, name in enumerate(names, 1)])})
    result = ground_message_list_rows([_row(name) for name in names], screen_path=image, ocr_tsv=ocr)
    ocr.assert_called_once()
    assert result.summary["grounded_count"] == 6
    assert result.summary["ocr_request_count"] == 1


def _provider(tmp_path, monkeypatch, image, *, ocr, perceived):
    adapter = SimpleNamespace(session=SimpleNamespace(_ocr_tsv=lambda path, **kwargs: ocr(path))) if ocr is not None else SimpleNamespace()
    provider = standalone.TaShuoMacIosStandaloneObservationProvider(root=tmp_path / "data", output_dir=tmp_path / "harness", vision_backend=Mock(), adapter_factory=lambda: adapter)
    provider.precheck_payload = Mock(return_value={"status": "ok", "screen": {"path": str(image)}})
    provider.targets = Mock()
    monkeypatch.setattr(standalone, "_analyze_tashuo_message_list_with_retry", perceived)
    return provider


def test_two_distinct_visual_rows_cannot_own_the_same_grounded_target(tmp_path, monkeypatch):
    image = tmp_path / "list.png"
    _png(image)
    rows = [
        _row("Alex", candidate_key="row_one", latest_preview="first preview"),
        _row("Alex", candidate_key="row_two", latest_preview="second preview"),
    ]
    provider = _provider(
        tmp_path, monkeypatch, image,
        perceived=Mock(return_value={"status": "ok", "rows": rows}),
        ocr=lambda _: {"status": "ok", "text": _tsv([("Alex", 1, 50, 120, 40, 16)])},
    )

    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})

    assert result["message_list_snapshot"]["entries"] == []
    assert [row["reason"] for row in result["skipped_candidates"]] == ["ambiguous_candidate_key"] * 2
    provider.targets.put.assert_not_called()


@pytest.mark.parametrize("replace_during", ["vision", "final_anchor"])
def test_grounding_does_not_publish_rows_from_different_frames(tmp_path, monkeypatch, replace_during):
    image = tmp_path / "list.png"
    _png(image)

    def vision(*args, **kwargs):
        if replace_during == "vision":
            _png(image, width=321)
        return {"status": "ok", "rows": [_row("Alex")]}

    def attach(rows, *, screen_path):
        if replace_during == "final_anchor":
            _png(image, width=321)
        return rows

    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=vision)
    recognize = Mock(return_value={"status": "ok", "text": _tsv([("Alex", 1, 50, 120, 40, 16)])})
    provider.adapter_factory = lambda: SimpleNamespace(session=SimpleNamespace(_native_ocr_tsv=recognize))
    monkeypatch.setattr(standalone, "_attach_tashuo_message_list_perceptual_anchors", attach)

    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})

    assert result["status"] == "blocked"
    assert result["reason"] == "tashuo_message_list_image_changed"
    provider.targets.put.assert_not_called()


def test_provider_grounds_after_vision_before_final_anchor_attachment(setup, tmp_path, monkeypatch):
    image, _ = setup
    events = []
    def vision(*args, **kwargs):
        events.append("vision")
        return {"status": "ok", "rows": [_row("小明")]}
    def ocr(path):
        events.append("ocr")
        return {"status": "ok", "text": _tsv([("小明", 1, 50, 160, 50, 16)])}
    def attach(rows, *, screen_path):
        events.append("attach")
        assert rows[0]["tap_ratio"]["y"] == 0.2625
        assert rows[0]["candidate_key"] == "tashuo_visual_" + rows[0]["visual_anchor_hash"]
        return rows
    provider = _provider(tmp_path, monkeypatch, image, ocr=ocr, perceived=vision)
    monkeypatch.setattr(standalone, "_attach_tashuo_message_list_perceptual_anchors", attach)
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert events == ["vision", "ocr", "attach"]
    assert result["message_list_grounding"]["grounded_count"] == 1
    assert result["candidates"][0]["tap_ratio"]["y"] == 0.2625
    provider.targets.put.assert_called_once()


def test_provider_does_not_recreate_ambiguous_candidate_with_grid_fallback(setup, tmp_path, monkeypatch):
    image, _ = setup
    ocr = Mock(return_value={"status": "ok", "text": _tsv([("小明", 1, 50, 160, 50, 16), ("小明", 2, 50, 320, 50, 16)])})
    provider = _provider(tmp_path, monkeypatch, image, ocr=ocr, perceived=Mock(return_value={"status": "ok", "rows": [_row("小明")]}))
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert result["candidates"] == []
    assert result["skipped_candidates"][0]["reason"] == "message_list_name_location_ambiguous"
    provider.targets.put.assert_not_called()


def test_provider_with_no_session_keeps_visual_route_and_never_invokes_local_ocr(setup, tmp_path, monkeypatch):
    image, _ = setup
    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=Mock(return_value={"status": "ok", "rows": [_row("小明")]}))
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert result["message_list_grounding"]["ocr_request_count"] == 0
    assert result["candidates"][0]["tap_ratio"] == {"x": 0.51, "y": 0.39}


@pytest.mark.parametrize("with_promo", [False, True])
def test_provider_preserves_uneven_visual_rows_when_emoji_names_have_no_exact_ocr(setup, tmp_path, monkeypatch, with_promo):
    image, _ = setup
    rows = [
        _row("Alice", candidate_key="alice", tap_ratio={"x": 0.46, "y": 0.535},
             visual_anchor_region={"x1": 0.1, "y1": 0.49, "x2": 0.7, "y2": 0.58}),
        _row("Bee😀", candidate_key="bee", tap_ratio={"x": 0.43, "y": 0.610},
             visual_anchor_region={"x1": 0.1, "y1": 0.57, "x2": 0.7, "y2": 0.66}),
        _row("Celia", candidate_key="celia", tap_ratio={"x": 0.47, "y": 0.725},
             visual_anchor_region={"x1": 0.1, "y1": 0.69, "x2": 0.7, "y2": 0.78}),
    ]
    perceived = ([_row("52人喜欢了你", tap_ratio={"x": 0.5, "y": 0.455})] if with_promo else []) + rows
    ocr = Mock(return_value={"status": "ok", "text": _tsv([])})
    provider = _provider(tmp_path, monkeypatch, image, ocr=ocr, perceived=Mock(return_value={"status": "ok", "rows": perceived}))

    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})

    assert len(result["candidates"]) == len(rows)
    for source, candidate in zip(rows, result["candidates"], strict=True):
        assert candidate["tap_ratio"] == source["tap_ratio"]
        assert candidate["visual_anchor_region"] == source["visual_anchor_region"]
        assert candidate.get("tap_ratio_source") != "corrected_all_messages_row_action"
    assert provider.targets.put.call_count == 3


@pytest.mark.parametrize(("override", "reason"), [
    ({"tap_ratio": None}, "missing_tap_ratio"),
    ({"tap_ratio": {"x": 0.4, "y": float("nan")}}, "invalid_tap_ratio"),
    ({"tap_ratio": {"x": 0.4, "y": 1.1}}, "invalid_tap_ratio"),
    ({"visual_anchor_region": None}, "missing_visual_anchor_region"),
    ({"visual_anchor_region": {"x1": 0.1, "y1": 0.6, "x2": 0.8, "y2": 0.3}}, "missing_visual_anchor_region"),
    ({"visual_anchor_region_source": "derived_from_tap_ratio_missing_vision_region"}, "missing_visual_anchor_region"),
    ({"visual_anchor_region_source": "derived_from_tap_ratio_after_invalid_vision_region"}, "missing_visual_anchor_region"),
])
def test_provider_skips_missing_or_invented_geometry_instead_of_creating_grid_rows(setup, tmp_path, monkeypatch, override, reason):
    image, _ = setup
    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=Mock(return_value={
        "status": "ok", "rows": [_row("Bee😀", **override)],
    }))

    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})

    assert result["candidates"] == []
    assert result["message_list_snapshot"]["entries"] == []
    assert result["skipped_candidates"][0]["reason"] == reason
    provider.targets.put.assert_not_called()


def test_provider_accepts_center_derived_from_real_visual_bbox_when_tap_is_missing(setup, tmp_path, monkeypatch):
    from dating_boost.apps.tashuo.perception import _normalize_row

    image, _ = setup
    row = _normalize_row(_row("Bee😀", tap_ratio=None), screen_path=image)
    assert row["tap_ratio_source"] == "derived_from_visual_anchor_region"
    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=Mock(return_value={"status": "ok", "rows": [row]}))

    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})

    assert result["candidates"][0]["tap_ratio"] == {"x": 0.505, "y": 0.39}
    assert result["candidates"][0]["visual_anchor_region"] == row["visual_anchor_region"]
    provider.targets.put.assert_called_once()


def test_provider_never_runs_ocr_before_successful_visual_semantic_analysis(setup, tmp_path, monkeypatch):
    image, _ = setup
    ocr = Mock(side_effect=AssertionError("no visual-first candidates"))
    provider = _provider(tmp_path, monkeypatch, image, ocr=ocr, perceived=Mock(return_value={"status": "blocked", "reason": "vision_unavailable"}))
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert result["status"] == "blocked"
    ocr.assert_not_called()


def test_small_name_bbox_anchor_keeps_same_shape_when_shared_relocator_moves_it(setup, monkeypatch):
    from dating_boost.apps.tashuo import targeting

    image, _ = setup
    result = ground_message_list_rows([_row("Ada")], screen_path=image, ocr_tsv=lambda _: {"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 10, 2)])})
    row = result.rows[0]
    region = row["visual_anchor_region"]
    region_width = region["x2"] - region["x1"]
    region_height = region["y2"] - region["y1"]
    assert region_width >= 0.05
    assert 0.03 <= region_height <= 0.28
    assert row["tap_ratio"]["y"] == round(161 / 640, 4)
    evidence = targeting._normalize_tashuo_message_list_relocation_evidence(row)
    monkeypatch.setattr(targeting, "_read_png_pixels", lambda _: object())

    def hasher(pixels, *, region):
        same_size = abs(region["x2"] - region["x1"] - region_width) < 1e-8 and abs(region["y2"] - region["y1"] - region_height) < 1e-8
        matches = same_size and abs(region["y1"] - 0.4) < 1e-8
        return {"status": "ok", "visual_anchor_hash": row["visual_anchor_hash"] if matches else "fedcba9876543210"}

    monkeypatch.setattr(targeting, "_tashuo_visual_anchor_hash_for_pixels", hasher)
    located = targeting._locate_tashuo_message_list_visual_target({"status": "ok", "state": "tashuo_chat_list", "path": str(image)}, evidence)
    assert located["status"] == "ok"
    assert located["visual_anchor_scanned"] is True
    assert located["tap_ratio"]["y"] == pytest.approx(row["tap_ratio"]["y"] + 0.4 - region["y1"])
    assert located["tap_adjustment"]["adjusted"] is False


def test_sparse_layout_only_fills_primary_misses_without_overwriting_primary_identity(setup):
    image, _ = setup
    primary = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 50, 16)])})
    sparse = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 500, 50, 16), ("Bob", 2, 50, 240, 50, 16), ("Carol", 3, 50, 320, 50, 16)])})
    result = ground_message_list_rows([_row("Ada"), _row("Bob"), _row("Carol"), _row("Dora")], screen_path=image, ocr_tsv=primary, sparse_ocr_tsv=sparse)
    assert result.rows[0]["tap_ratio"]["y"] == 0.2625
    assert result.rows[1]["tap_ratio"]["y"] == 0.3875
    assert result.rows[2]["tap_ratio"]["y"] == 0.5125
    assert result.rows[3]["spatial_grounding"]["reason"] == "exact_name_not_found"
    assert result.summary["grounded_count"] == 3
    assert result.summary["sparse_grounded_count"] == 2
    assert result.summary["ocr_request_count"] == 2
    primary.assert_called_once_with(image)
    sparse.assert_called_once_with(image)


def test_primary_ambiguity_is_never_resurrected_when_sparse_has_unique_name(setup):
    image, _ = setup
    primary = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 50, 16), ("Ada", 2, 50, 240, 50, 16)])})
    sparse = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 50, 16), ("Bob", 2, 50, 320, 50, 16)])})
    result = ground_message_list_rows([_row("Ada"), _row("Bob")], screen_path=image, ocr_tsv=primary, sparse_ocr_tsv=sparse)
    assert [row["visible_name"] for row in result.rows] == ["Bob"]
    assert result.skipped[0]["position"] == 1
    assert result.skipped[0]["matching_occurrence_count"] == 2
    assert result.summary["ambiguous_count"] == 1


def test_sparse_ambiguity_skips_original_candidate_position_and_preserves_others(setup):
    image, _ = setup
    primary = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 50, 16)])})
    sparse = Mock(return_value={"status": "ok", "text": _tsv([("Bob", 1, 50, 240, 50, 16), ("Bob", 2, 50, 320, 50, 16), ("Carol", 3, 50, 400, 50, 16)])})
    result = ground_message_list_rows([_row("Ada"), _row("Bob"), _row("Carol")], screen_path=image, ocr_tsv=primary, sparse_ocr_tsv=sparse)
    assert [row["visible_name"] for row in result.rows] == ["Ada", "Carol"]
    assert result.skipped[0]["position"] == 2
    assert result.skipped[0]["segmentation_mode"] == 11
    assert result.summary["grounded_count"] == 2
    assert result.summary["ambiguous_count"] == 1


@pytest.mark.parametrize("state", ["grounded", "ambiguous", "invalid_bbox", "primary_unavailable"])
def test_sparse_layout_is_not_requested_without_primary_exact_name_misses(setup, state):
    image, _ = setup
    words = [("Ada", 1, 50, 160, 50, 16)]
    if state == "ambiguous":
        words.append(("Ada", 2, 50, 320, 50, 16))
    if state == "invalid_bbox":
        words = [("Ada", 1, 50, -10, 50, 16)]
    primary = Mock(return_value={"status": "unavailable"} if state == "primary_unavailable" else {"status": "ok", "text": _tsv(words)})
    sparse = Mock(side_effect=AssertionError("must not request sparse OCR"))
    result = ground_message_list_rows([_row("Ada")], screen_path=image, ocr_tsv=primary, sparse_ocr_tsv=sparse)
    sparse.assert_not_called()
    assert result.summary["ocr_request_count"] == 1


@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE"), {"status": "unavailable"}, {"status": "ok", "text": "invalid"}])
def test_sparse_failure_is_bounded_and_keeps_primary_results(setup, failure):
    image, _ = setup
    primary = Mock(return_value={"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 50, 16)])})
    sparse = Mock(side_effect=failure if isinstance(failure, Exception) else None, return_value=failure)
    result = ground_message_list_rows([_row("Ada"), _row("Bob")], screen_path=image, ocr_tsv=primary, sparse_ocr_tsv=sparse)
    assert result.rows[0]["spatial_grounding"]["status"] == "verified"
    assert result.rows[1]["tap_ratio"] == {"x": 0.51, "y": 0.39}
    assert result.summary["ocr_request_count"] == 2
    assert "PRIVATE" not in str(result.summary)
    sparse.assert_called_once()


def test_provider_requests_exactly_the_two_bounded_layout_modes(setup, tmp_path, monkeypatch):
    image, _ = setup
    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=Mock(return_value={"status": "ok", "rows": [_row("Ada"), _row("Bob")]}))
    reader = Mock(side_effect=[{"status": "ok", "text": _tsv([("Ada", 1, 50, 160, 50, 16)])}, {"status": "ok", "text": _tsv([("Bob", 2, 50, 320, 50, 16)])}])
    provider.adapter_factory = lambda: SimpleNamespace(session=SimpleNamespace(_ocr_tsv=reader))
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert reader.call_count == 2
    assert [call.kwargs for call in reader.call_args_list] == [{"segmentation_mode": 6, "allow_language_fallback": False}, {"segmentation_mode": 11, "allow_language_fallback": False}]
    assert result["message_list_grounding"]["ocr_request_count"] == 2


@pytest.mark.parametrize("native_status", ["ok", "unavailable"])
def test_native_grounding_runs_once_after_vision_without_tesseract_fallback(setup, tmp_path, monkeypatch, native_status):
    image, _ = setup
    events = []

    def vision(*args, **kwargs):
        events.append("vision")
        return {"status": "ok", "rows": [_row("小明", candidate_key="row_one"), _row("Ada😀", candidate_key="row_two")]}

    def recognize(path):
        assert path == image
        events.append("native_ocr")
        return {"status": native_status, "text": _tsv([("小明", 1, 50, 160, 50, 16)]), "backend": "apple_vision"}

    def attach(rows, *, screen_path):
        events.append("attach")
        return rows

    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=vision)
    native = Mock(side_effect=recognize)
    legacy = Mock(side_effect=AssertionError("native path must not trigger Tesseract"))
    provider.adapter_factory = lambda: SimpleNamespace(session=SimpleNamespace(_native_ocr_tsv=native, _ocr_tsv=legacy))
    monkeypatch.setattr(standalone, "_attach_tashuo_message_list_perceptual_anchors", attach)
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert events == ["vision", "native_ocr", "attach"]
    native.assert_called_once_with(image)
    legacy.assert_not_called()
    assert result["message_list_grounding"]["backend"] == "apple_vision"
    assert result["message_list_grounding"]["ocr_request_count"] == 1
    # Native misses with no available observed nickname anchor cannot retain a
    # guessed model coordinate. The exact primary result remains usable.
    provider.vision_backend.analyze_image_structured.assert_not_called()
    if native_status == "ok":
        assert result["skipped_candidates"]
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["tap_ratio"]["y"] == 0.2625
    else:
        assert len(result["candidates"]) == 2
        assert result["candidates"][0]["tap_ratio"] == {"x": 0.51, "y": 0.39}
        assert result["candidates"][1]["tap_ratio"] == {"x": 0.51, "y": 0.39}


def test_native_selector_reuses_one_ocr_after_initial_vision_and_before_final_anchors(setup, tmp_path, monkeypatch):
    image, _ = setup
    events = []

    def vision(*args, **kwargs):
        events.append("vision")
        return {"status": "ok", "rows": [_row("小明"), _row("Ada😀")]}

    def recognize(path):
        events.append("native_ocr")
        return {"status": "ok", "backend": "apple_vision", "text": _tsv([
            ("小明", 1, 50, 160, 50, 16), ("Ada", 2, 50, 320, 50, 16),
        ])}

    def select(*args):
        events.append("select_anchor")
        return {"selections": [{"candidate_index": 2, "anchor_id": "text_2", "confidence": "high"}]}

    def attach(rows, *, screen_path):
        events.append("attach")
        assert rows[1]["visible_name"] == "Ada😀"
        assert rows[1]["tap_ratio"] == {"x": 0.2344, "y": 0.5125}
        assert rows[1]["candidate_key"] == "tashuo_visual_" + rows[1]["visual_anchor_hash"]
        return rows

    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=vision)
    native = Mock(side_effect=recognize)
    legacy = Mock(side_effect=AssertionError("no additional OCR"))
    provider.adapter_factory = lambda: SimpleNamespace(session=SimpleNamespace(_native_ocr_tsv=native, _ocr_tsv=legacy))
    provider.vision_backend.analyze_image_structured.side_effect = select
    monkeypatch.setattr(standalone, "_attach_tashuo_message_list_perceptual_anchors", attach)
    result = provider.observe_message_list(app_id="tashuo", scan_cursor={})
    assert events == ["vision", "native_ocr", "select_anchor", "attach"]
    native.assert_called_once_with(image)
    legacy.assert_not_called()
    provider.vision_backend.analyze_image_structured.assert_called_once()
    assert result["message_list_grounding"]["ocr_request_count"] == 1
    assert result["message_list_grounding"]["selector_request_count"] == 1
    assert result["message_list_grounding"]["selector_grounded_count"] == 1


def test_native_grounding_is_never_invoked_before_successful_list_vision(setup, tmp_path, monkeypatch):
    image, _ = setup
    provider = _provider(tmp_path, monkeypatch, image, ocr=None, perceived=Mock(return_value={"status": "blocked"}))
    native = Mock(side_effect=AssertionError("vision has not produced identities"))
    provider.adapter_factory = lambda: SimpleNamespace(session=SimpleNamespace(_native_ocr_tsv=native))
    assert provider.observe_message_list(app_id="tashuo", scan_cursor={})["status"] == "blocked"
    native.assert_not_called()


def test_native_session_reader_only_passes_runner_and_saved_image(monkeypatch):
    from dating_boost.apps.native_gui_session import AppSpecificNativeGuiSessionMixin
    from dating_boost.harness import native_text

    reader = Mock(return_value={"status": "unavailable", "backend": "apple_vision"})
    monkeypatch.setattr(native_text, "apple_vision_tsv", reader)
    session = SimpleNamespace(runner=object())
    image = Path("saved-list.png")
    assert AppSpecificNativeGuiSessionMixin._native_ocr_tsv(session, image) == reader.return_value
    reader.assert_called_once_with(session.runner, image)


def test_shared_ocr_default_preserves_existing_consumers_psm6_and_language_fallback():
    from subprocess import CompletedProcess
    from dating_boost.apps.native_gui_session import AppSpecificNativeGuiSessionMixin

    runner = Mock()
    runner.run.side_effect = [CompletedProcess([], 1, "", "missing language"), CompletedProcess([], 0, "fallback tsv", "")]
    session = SimpleNamespace(_command_available=Mock(return_value=True), runner=runner)
    result = AppSpecificNativeGuiSessionMixin._ocr_tsv(session, Path("saved.png"))
    assert result == {"status": "ok", "text": "fallback tsv"}
    assert runner.run.call_args_list[0].args[0] == ["tesseract", "saved.png", "stdout", "-l", "eng+chi_sim", "--psm", "6", "tsv"]
    assert runner.run.call_args_list[1].args[0] == ["tesseract", "saved.png", "stdout", "--psm", "6", "tsv"]


@pytest.mark.parametrize("mode", [6, 11])
def test_bounded_layout_reader_never_retries_failed_tesseract(mode):
    from subprocess import CompletedProcess
    from dating_boost.apps.native_gui_session import AppSpecificNativeGuiSessionMixin

    runner = Mock()
    runner.run.return_value = CompletedProcess([], 1, "", "PRIVATE")
    session = SimpleNamespace(_command_available=Mock(return_value=True), runner=runner)
    result = AppSpecificNativeGuiSessionMixin._ocr_tsv(session, Path("saved.png"), segmentation_mode=mode, allow_language_fallback=False)
    assert result == {"status": "failed", "text": "", "reason": "ocr_tsv_failed"}
    runner.run.assert_called_once()
    assert runner.run.call_args.args[0][-3:] == ["--psm", str(mode), "tsv"]
