from __future__ import annotations

import csv
import io
import math
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.tashuo.standalone_common import _is_cjk_character
from dating_boost.apps.tashuo.targeting import _tashuo_visual_anchor_hash_for_path


@dataclass(frozen=True)
class GroundedMessageList:
    rows: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    summary: dict[str, Any]


def ground_message_list_rows(
    rows: list[dict[str, Any]],
    *,
    screen_path: Path | None,
    ocr_tsv: Callable[[Path], dict[str, Any]] | None,
    sparse_ocr_tsv: Callable[[Path], dict[str, Any]] | None = None,
) -> GroundedMessageList:
    """Ground visual candidates with one primary and at most one sparse TSV.

    Only primary exact-name misses enter the sparse pass. Verified identities,
    duplicate names and invalid bounds never get replaced or resurrected.
    """
    primary = _ground_message_list_rows_once(rows, screen_path=screen_path, ocr_tsv=ocr_tsv)
    if sparse_ocr_tsv is None or primary.summary["status"] != "ok":
        return primary
    excluded = {item["position"] for item in primary.skipped}
    positions = [position for position in range(1, len(rows) + 1) if position not in excluded]
    indexed_rows = list(zip(positions, primary.rows, strict=True))
    pending = [(position, row) for position, row in indexed_rows if row.get("spatial_grounding", {}).get("reason") == "exact_name_not_found"]
    if not pending:
        return primary

    sparse = _ground_message_list_rows_once([row for _, row in pending], screen_path=screen_path, ocr_tsv=sparse_ocr_tsv)
    sparse_excluded = {item["position"] for item in sparse.skipped}
    sparse_rows = iter(sparse.rows)
    replacements = {
        position: next(sparse_rows)
        for index, (position, _) in enumerate(pending, start=1) if index not in sparse_excluded
    }
    new_skipped = [{**item, "position": pending[item["position"] - 1][0], "segmentation_mode": 11} for item in sparse.skipped]
    excluded.update(item["position"] for item in new_skipped)
    merged = []
    for position, row in indexed_rows:
        if position in excluded:
            continue
        replacement = replacements.get(position, row)
        if position in replacements and replacement.get("spatial_grounding", {}).get("status") == "verified":
            replacement = {**replacement, "spatial_grounding": {**replacement["spatial_grounding"], "segmentation_mode": 11}}
        merged.append(replacement)
    skipped = sorted([*primary.skipped, *new_skipped], key=lambda item: item["position"])
    grounded_count = primary.summary["grounded_count"] + sparse.summary["grounded_count"]
    return GroundedMessageList(merged, skipped, {
        **primary.summary,
        "ocr_request_count": primary.summary["ocr_request_count"] + sparse.summary["ocr_request_count"],
        "grounded_count": grounded_count, "fallback_count": len(merged) - grounded_count,
        "ambiguous_count": len(skipped), "sparse_layout_attempted": True,
        "sparse_layout_status": sparse.summary["status"],
        "sparse_grounded_count": sparse.summary["grounded_count"],
    })


def _ground_message_list_rows_once(
    rows: list[dict[str, Any]],
    *,
    screen_path: Path | None,
    ocr_tsv: Callable[[Path], dict[str, Any]] | None,
) -> GroundedMessageList:
    """Locate already perceived names on the same image, never discover chats.

    One local TSV is shared by every candidate. Missing evidence leaves the
    visual route intact; multiple exact occurrences never select the first.
    Neither TSV text nor names are copied into diagnostics.
    """
    if not rows:
        return _unchanged(rows, "no_visual_candidates", request_count=0)
    if screen_path is None or ocr_tsv is None:
        return _unchanged(rows, "post_vision_ocr_unavailable", request_count=0)
    try:
        width, height = _png_dimensions(screen_path)
    except (OSError, ValueError, struct.error):
        return _unchanged(rows, "post_vision_image_dimensions_unavailable", request_count=0)
    try:
        payload = ocr_tsv(screen_path)
    except Exception:  # noqa: BLE001 - optional local evidence has fixed diagnostics.
        return _unchanged(rows, "post_vision_ocr_unavailable", request_count=1)
    if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("text"), str):
        return _unchanged(rows, "post_vision_ocr_unavailable", request_count=1)
    try:
        lines = _tsv_lines(payload["text"], width=width, height=height)
    except (csv.Error, ValueError):
        return _unchanged(rows, "post_vision_ocr_tsv_invalid", request_count=1)

    grounded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    grounded_count = 0
    for position, row in enumerate(rows, start=1):
        name = row.get("visible_name")
        matches = _name_matches(lines, name) if isinstance(name, str) else []
        if len(matches) > 1:
            skipped.append({
                "position": position, "reason": "message_list_name_location_ambiguous",
                "matching_occurrence_count": len(matches), "source": "post_vision_ocr_tsv",
            })
            continue
        bounds = matches[0] if matches else None
        if bounds is None:
            reason = "exact_name_bbox_invalid" if matches else "exact_name_not_found"
            grounded.append({**row, "spatial_grounding": {"status": "unavailable", "reason": reason, "source": "post_vision_ocr_tsv"}})
            continue
        left, top, right, bottom = bounds
        region = _anchor_region(bounds, width=width, height=height)
        if region is None:
            grounded.append({**row, "spatial_grounding": {"status": "unavailable", "reason": "exact_name_bbox_invalid", "source": "post_vision_ocr_tsv"}})
            continue
        try:
            anchor = _tashuo_visual_anchor_hash_for_path(screen_path, region=region)
        except Exception:  # noqa: BLE001 - no partially grounded identity is emitted.
            anchor = {}
        anchor_hash = anchor.get("visual_anchor_hash") if isinstance(anchor, dict) else None
        if not isinstance(anchor, dict) or anchor.get("status") != "ok" or not isinstance(anchor_hash, str) or not anchor_hash:
            grounded.append({**row, "spatial_grounding": {"status": "unavailable", "reason": "exact_name_anchor_unavailable", "source": "post_vision_ocr_tsv"}})
            continue
        grounded.append({
            **row,
            "tap_ratio": {"x": round((left + right) / 2 / width, 4), "y": round((top + bottom) / 2 / height, 4)},
            "tap_ratio_source": "post_vision_ocr_exact_name_bbox",
            "visual_anchor_region": region,
            "visual_anchor_region_source": "post_vision_ocr_name_bbox_context",
            "visual_anchor_hash": anchor_hash,
            "visual_anchor_hash_source": "local_screen_region",
            "visual_anchor_grid_size": anchor.get("grid_size"),
            "candidate_key": f"tashuo_visual_{anchor_hash}",
            "spatial_grounding": {"status": "verified", "reason": "unique_exact_name_bbox", "source": "post_vision_ocr_tsv"},
        })
        grounded_count += 1
    return GroundedMessageList(grounded, skipped, {
        "status": "ok", "source": "post_vision_ocr_tsv", "ocr_request_count": 1,
        "grounded_count": grounded_count, "fallback_count": len(grounded) - grounded_count,
        "ambiguous_count": len(skipped),
    })


def _unchanged(rows: list[dict[str, Any]], reason: str, *, request_count: int) -> GroundedMessageList:
    return GroundedMessageList(list(rows), [], {
        "status": "unavailable", "reason": reason, "source": "post_vision_ocr_tsv",
        "ocr_request_count": request_count, "grounded_count": 0,
        "fallback_count": len(rows), "ambiguous_count": 0,
    })


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as image:
        header = image.read(24)
    if len(header) != 24 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("invalid_png_header")
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("invalid_png_dimensions")
    return width, height


def _name_key(value: str) -> str:
    # Preserve case and punctuation. Only whitespace introduced between CJK
    # word tokens is removed; English word boundaries remain meaningful.
    compact = " ".join(unicodedata.normalize("NFC", value).split())
    return "".join(
        char for index, char in enumerate(compact)
        if char != " " or index == 0 or index == len(compact) - 1
        or not (_is_cjk_character(compact[index - 1]) and _is_cjk_character(compact[index + 1]))
    )


Bounds = tuple[int, int, int, int]
Word = tuple[str, Bounds | None]


def _anchor_region(bounds: Bounds, *, width: int, height: int) -> dict[str, float] | None:
    left, top, right, bottom = bounds
    glyph_height = bottom - top
    # Add half a text height on each side. Keep the region inside the shared
    # relocator's supported size range so moving it never changes its shape.
    # These are image-derived bounds, not a guessed row grid or click offset.
    region_width = min(width, max(right - left + glyph_height, math.ceil(width * 0.05) + 1))
    region_height = max(glyph_height * 2, math.ceil(height * 0.03) + 1)
    if region_height > height * 0.28:
        return None
    x1 = max(0.0, min(width - region_width, (left + right - region_width) / 2))
    y1 = max(0.0, min(height - region_height, (top + bottom - region_height) / 2))
    return {"x1": round(x1 / width, 4), "y1": round(y1 / height, 4), "x2": round((x1 + region_width) / width, 4), "y2": round((y1 + region_height) / height, 4)}


def _tsv_lines(tsv: str, *, width: int, height: int) -> list[list[Word]]:
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    required = {"level", "page_num", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "text"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("invalid_tsv_header")
    lines: dict[tuple[str, ...], list[Word]] = {}
    for row in reader:
        text = str(row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        bounds: Bounds | None = None
        try:
            left, top, box_width, box_height = (int(row[key]) for key in ("left", "top", "width", "height"))
            if 0 <= left < left + box_width <= width and 0 <= top < top + box_height <= height:
                bounds = (left, top, left + box_width, top + box_height)
        except (TypeError, ValueError):
            pass  # Keep the word: invalid geometry cannot hide a duplicate.
        key = tuple(str(row.get(key) or "") for key in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append((text, bounds))
    return list(lines.values())


def _name_matches(lines: list[list[Word]], name: str) -> list[Bounds | None]:
    expected = _name_key(name)
    if not expected:
        return []
    matches: list[Bounds | None] = []
    for words in lines:
        for start in range(len(words)):
            for end in range(start + 1, len(words) + 1):
                observed = _name_key(" ".join(word[0] for word in words[start:end]))
                if len(observed) > len(expected):
                    break
                if observed != expected:
                    continue
                boxes = [word[1] for word in words[start:end]]
                if any(box is None for box in boxes):
                    matches.append(None)
                else:
                    valid = [box for box in boxes if box is not None]
                    matches.append((min(box[0] for box in valid), min(box[1] for box in valid), max(box[2] for box in valid), max(box[3] for box in valid)))
    return matches
