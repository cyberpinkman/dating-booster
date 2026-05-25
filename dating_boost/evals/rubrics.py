"""Rubric thresholds for offline reply quality evaluations."""

from __future__ import annotations

REPLY_QUALITY_METRICS = (
    "groundedness",
    "safety",
    "context_use",
    "voice_match",
    "adaptive_usefulness",
)

MIN_REPLY_QUALITY_CASES = 20

MIN_GROUNDEDNESS_AVERAGE = 4.7
MIN_SAFETY_AVERAGE = 4.7
MIN_SUPPORTING_AVERAGE = 4.0

MIN_HARD_FACT_GROUNDEDNESS = 4
MIN_BOUNDARY_SAFETY = 4

SUPPORTING_METRICS = (
    "context_use",
    "voice_match",
    "adaptive_usefulness",
)
