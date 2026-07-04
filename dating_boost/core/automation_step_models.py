from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dating_boost.perception.observations import AppObservation


@dataclass
class _ScanWindow:
    thread_items: dict[Any, dict[str, Any]]
    historical_entries: list[Any]
    processed_entries: list[Any]
    over_budget_entries: list[Any]
    history_cutoff_reached: bool
    scan_cursor: dict[str, Any]
    budget: int
    captured_at_for_age: str
    captured_at_present: bool
    captured_at_value: Any
    updated_at: Any

@dataclass
class _StepBuffers:
    action_requests: list[dict[str, Any]] = field(default_factory=list)
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    scan_requests: list[dict[str, Any]] = field(default_factory=list)
    scheduled_actions: list[dict[str, Any]] = field(default_factory=list)
    state_updates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    processed_match_count: int = 0

@dataclass
class _ObservedThreadContext:
    observation: AppObservation
    ingest: dict[str, Any]
    match_id: str
    assessment: dict[str, Any]
    latest_fingerprint: Any
    state: dict[str, Any]

