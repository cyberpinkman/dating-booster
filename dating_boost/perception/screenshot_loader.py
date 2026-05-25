from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.perception.observations import AppObservation


def build_observation_from_screenshot_analysis(
    screenshot_path: Path,
    analysis: dict[str, Any],
) -> AppObservation:
    data = {
        "observation_id": analysis["observation_id"],
        "source_type": "screenshot_fixture",
        "app_id": analysis.get("app_id", "unknown"),
        "adapter_id": analysis.get("adapter_id", "manual.screenshot.v1"),
        "captured_at": analysis["captured_at"],
        "page_type": analysis.get("page_type", "unknown"),
        "page_confidence": analysis.get("page_confidence", "medium"),
        "match_identity_hints": analysis.get("match_identity_hints", {}),
        "profile_observation": analysis.get("profile_observation", {}),
        "conversation_observation": analysis.get("conversation_observation", {}),
        "element_observations": analysis.get("element_observations", []),
        "exception_state": analysis.get("exception_state", "none"),
        "provenance": {
            **dict(analysis.get("provenance", {})),
            "screenshot_path": str(screenshot_path),
            "analysis_type": "manual",
        },
        "raw_ref": str(screenshot_path),
    }
    return AppObservation.from_dict(data)
