from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from dating_boost.apps.tashuo.perception import MESSAGE_LIST_SCHEMA, analyze_tashuo_message_list
from dating_boost.apps.tashuo.standalone_message_list import _message_list_entry_from_visual_row
from dating_boost.core.managed_run_provider import StandaloneObservationManagedRunPort


pytestmark = pytest.mark.managed_critical
CAPTURED_AT = "2026-09-20T04:00:00Z"


def test_visual_list_recency_survives_normalization_without_inventing_missing_evidence() -> None:
    cases = [
        ({"timestamp_cue": " 8月31日 ", "unread_cue": "absent"}, "8月31日", "absent"),
        ({"timestamp_cue": "昨天", "unread_cue": "present"}, "昨天", "present"),
        ({"timestamp_cue": "8月31日", "unread_cue": "reply_badge"}, "8月31日", "reply_badge"),
        ({}, "", "unknown"),
        ({"timestamp_cue": None, "unread_cue": "inferred_fresh"}, "", "unknown"),
    ]
    backend = Mock()
    backend.analyze_image_structured.return_value = {
        "status": "ok",
        "rows": [
            {"tap_ratio": {"x": 0.5, "y": 0.4}, "visible_name": "Synthetic", "confidence": "high", **fields}
            for fields, _, _ in cases
        ],
    }
    # Exercise the real visual-result normalization without opening any image.
    with patch("dating_boost.apps.tashuo.perception._local_visual_anchor_hash", return_value="synthetic_anchor"):
        result = analyze_tashuo_message_list(
            {"screen": {"path": "/synthetic-not-opened.png"}}, backend=backend,
        )
    row_schema = MESSAGE_LIST_SCHEMA["properties"]["rows"]["items"]
    assert {"timestamp_cue", "unread_cue"}.issubset(row_schema["properties"])
    assert {"timestamp_cue", "unread_cue"}.issubset(row_schema["required"])
    for row, (_, timestamp, unread) in zip(result["rows"], cases, strict=True):
        entry = _message_list_entry_from_visual_row(row, position=1)
        for payload in (row, entry):
            assert payload["timestamp_cue"] == timestamp
            assert payload["unread_cue"] == unread
            assert "freshness_bucket" not in payload
            assert "last_activity_at" not in payload


def _scan_port(tmp_path: Path, entries: list[dict]) -> tuple[StandaloneObservationManagedRunPort, Mock]:
    provider = Mock()
    provider.observe_message_list.return_value = {
        "status": "ok",
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
        "captured_at": CAPTURED_AT,
        "scan_cursor": {"current": "page_1", "next": {"current": "page_2", "next": "page_3", "exhausted": False}},
        "message_list_snapshot": {"entries": entries},
    }
    return StandaloneObservationManagedRunPort(tmp_path, provider, fixture_mode=True), provider


@pytest.mark.parametrize(("fields", "eligible"), [
    ({"timestamp_cue": "8月31日", "unread_cue": "absent"}, False),
    ({"timestamp_cue": "7天前", "unread_cue": "unknown"}, False),
    ({"timestamp_cue": "6天前", "unread_cue": "absent"}, True),
    ({"timestamp_cue": "8月31日", "unread_cue": "present"}, True),
    ({"timestamp_cue": "8月31日", "unread_cue": "reply_badge"}, True),
    ({}, True),
])
def test_managed_scan_preserves_shared_recency_and_unread_rules(tmp_path: Path, fields: dict, eligible: bool) -> None:
    port, provider = _scan_port(tmp_path, [{"candidate_key": "synthetic", "inbound_revision": "revision", **fields}])
    snapshot = port.scan_message_list(run_id="synthetic_run", app_id="tashuo", runtime="mac-ios-app", cursor={})
    assert bool(snapshot.candidates) is eligible
    assert snapshot.next_cursor == (
        {"current": "page_2", "next": "page_3", "exhausted": False}
        if eligible else {"current": None, "next": None, "exhausted": True}
    )
    provider.observe_thread.assert_not_called()


def test_history_cutoff_precedes_priority_and_exhausts_nested_pagination(tmp_path: Path) -> None:
    port, provider = _scan_port(tmp_path, [
        {"candidate_key": "recent", "inbound_revision": "recent_revision", "timestamp_cue": "今天", "priority": 10},
        {"candidate_key": "old", "inbound_revision": "old_revision", "timestamp_cue": "8月31日", "unread_cue": "absent"},
        {"candidate_key": "lower_unread", "inbound_revision": "new_revision", "timestamp_cue": "刚刚", "unread_cue": "present", "priority": 1},
    ])
    snapshot = port.scan_message_list(run_id="synthetic_run", app_id="tashuo", runtime="mac-ios-app", cursor={})
    assert [candidate.candidate_key for candidate in snapshot.candidates] == ["recent"]
    assert snapshot.next_cursor == {"current": None, "next": None, "exhausted": True}
    provider.observe_thread.assert_not_called()
