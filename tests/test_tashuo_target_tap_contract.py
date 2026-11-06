from __future__ import annotations

from unittest.mock import Mock

import pytest

from dating_boost.apps.tashuo import targeting

pytestmark = pytest.mark.managed_critical


def _evidence(*, tap_y=0.249, source=None):
    return targeting._normalize_tashuo_message_list_relocation_evidence({
        "visual_anchor_hash": "0000000000000000",
        "visual_anchor_region": {"x1": 0.064, "y1": 0.171, "x2": 0.936, "y2": 0.327},
        "tap_ratio": {"x": 0.5, "y": tap_y},
        "tap_ratio_source": source,
    })


def _locate(monkeypatch, evidence, hash_for_region):
    monkeypatch.setattr(targeting, "_read_png_pixels", lambda path: object())
    hasher = Mock(side_effect=lambda pixels, *, region: {"status": "ok", "visual_anchor_hash": hash_for_region(region)})
    monkeypatch.setattr(targeting, "_tashuo_visual_anchor_hash_for_pixels", hasher)
    result = targeting._locate_tashuo_message_list_visual_target(
        {"status": "ok", "state": "tashuo_chat_list", "path": "offline-fixture.png"}, evidence,
    )
    return result, hasher


@pytest.mark.parametrize("source", [None, "standalone_vision_message_list_row", "corrected_all_messages_row_action"])
def test_verified_explicit_tap_is_not_replaced_by_visual_anchor_upper_band(monkeypatch, source):
    evidence = _evidence(source=source)
    result, hasher = _locate(monkeypatch, evidence, lambda region: "0000000000000000" if region == evidence["visual_anchor_region"] else "0000000000000001")
    assert result["status"] == "ok"
    assert result["tap_ratio"] == {"x": 0.5, "y": 0.249}
    assert result["raw_tap_ratio"] == result["tap_ratio"]
    assert result["visual_anchor_hamming_distance"] == 0
    assert result["visual_anchor_scanned"] is False
    assert result["tap_adjustment"]["adjusted"] is False
    hasher.assert_called_once()


@pytest.mark.parametrize("tap_y", [0.249, 0.35])
def test_moved_anchor_only_translates_explicit_tap_offset(monkeypatch, tap_y):
    evidence = _evidence(tap_y=tap_y)
    result, _ = _locate(monkeypatch, evidence, lambda region: "0000000000000000" if abs(region["y1"] - 0.424) < 1e-8 else "ffffffffffffffff")
    assert result["status"] == "ok"
    assert result["visual_anchor_scanned"] is True
    assert result["tap_ratio"]["y"] == pytest.approx(tap_y + 0.424 - 0.171)
    assert result["tap_adjustment"]["adjusted"] is False


def test_verified_tap_still_cannot_hit_bottom_navigation(monkeypatch):
    result, _ = _locate(monkeypatch, _evidence(tap_y=0.95), lambda region: "0000000000000000")
    assert result["status"] == "ok"
    assert result["tap_ratio"]["y"] == 0.86
    assert result["tap_adjustment"]["reason"] == "bottom_nav_overlap_guard"
