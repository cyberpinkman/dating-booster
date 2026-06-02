"""Deterministic offline evaluation runner for reply quality cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dating_boost.evals.rubrics import (
    MIN_BOUNDARY_SAFETY,
    MIN_GROUNDEDNESS_AVERAGE,
    MIN_HARD_FACT_GROUNDEDNESS,
    MIN_REPLY_QUALITY_CASES,
    MIN_SAFETY_AVERAGE,
    MIN_SUPPORTING_AVERAGE,
    REPLY_QUALITY_METRICS,
    SUPPORTING_METRICS,
)


@dataclass(frozen=True)
class EvalResult:
    case_count: int
    averages: dict[str, float]
    passed: bool
    failures: tuple[str, ...]
    cases: tuple[dict[str, Any], ...] = ()

    @property
    def failure_reasons(self) -> tuple[str, ...]:
        return self.failures


def run_reply_quality_eval(path: Path) -> EvalResult:
    """Run the offline reply quality rubric against JSONL score cases."""

    cases = _read_cases(path)
    averages = _score_averages(cases)
    failure_reasons = _failure_reasons(cases, averages)

    return EvalResult(
        case_count=len(cases),
        averages=averages,
        passed=not failure_reasons,
        failures=tuple(failure_reasons),
    )


def run_conversation_eval(path: Path | None = None) -> EvalResult:
    """Run deterministic planner/automation fixture assertions."""

    fixture_path = path or Path("tests/fixtures/evals/conversation_cases.json")
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("conversation eval payload must be an object")
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list):
        raise ValueError("conversation eval payload must include cases")

    failures: list[str] = []
    case_results: list[dict[str, Any]] = []
    for index, raw_case in enumerate(cases_payload, start=1):
        if not isinstance(raw_case, dict):
            failures.append(f"case {index} must be an object")
            continue
        case_id = str(raw_case.get("case_id") or f"case_{index}")
        actual = raw_case.get("actual")
        expected = raw_case.get("expected")
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            failures.append(f"{case_id} must include actual and expected objects")
            continue
        mismatches: list[str] = []
        for field, expected_value in expected.items():
            actual_value = actual.get(field)
            if actual_value != expected_value:
                mismatches.append(f"{field}: expected {expected_value!r}, got {actual_value!r}")
        case_results.append(
            {
                "case_id": case_id,
                "passed": not mismatches,
                "mismatches": mismatches,
            }
        )
        failures.extend(f"{case_id} {mismatch}" for mismatch in mismatches)

    return EvalResult(
        case_count=len(cases_payload),
        averages={},
        passed=not failures,
        failures=tuple(failures),
        cases=tuple(case_results),
    )


def _read_cases(path: Path) -> list[Mapping[str, Any]]:
    cases: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case, dict):
            raise ValueError(f"Eval case on line {line_number} must be a JSON object.")
        cases.append(case)
    return cases


def _score_averages(cases: list[Mapping[str, Any]]) -> dict[str, float]:
    if not cases:
        return {metric: 0.0 for metric in REPLY_QUALITY_METRICS}

    return {
        metric: sum(_score(case, metric) for case in cases) / len(cases)
        for metric in REPLY_QUALITY_METRICS
    }


def _failure_reasons(cases: list[Mapping[str, Any]], averages: Mapping[str, float]) -> list[str]:
    reasons: list[str] = []

    if len(cases) < MIN_REPLY_QUALITY_CASES:
        reasons.append(f"Expected at least {MIN_REPLY_QUALITY_CASES} eval cases, found {len(cases)}.")

    if averages["groundedness"] < MIN_GROUNDEDNESS_AVERAGE:
        reasons.append(
            f"Groundedness average {averages['groundedness']:.2f} is below {MIN_GROUNDEDNESS_AVERAGE:.1f}."
        )
    if averages["safety"] < MIN_SAFETY_AVERAGE:
        reasons.append(f"Safety average {averages['safety']:.2f} is below {MIN_SAFETY_AVERAGE:.1f}.")

    for metric in SUPPORTING_METRICS:
        if averages[metric] < MIN_SUPPORTING_AVERAGE:
            reasons.append(f"{metric} average {averages[metric]:.2f} is below {MIN_SUPPORTING_AVERAGE:.1f}.")

    for case in cases:
        case_id = _case_id(case)
        if case.get("hard_fact_sample") is True and _score(case, "groundedness") < MIN_HARD_FACT_GROUNDEDNESS:
            reasons.append(f"{case_id} hard-fact groundedness is below {MIN_HARD_FACT_GROUNDEDNESS}.")
        if case.get("boundary_sample") is True and _score(case, "safety") < MIN_BOUNDARY_SAFETY:
            reasons.append(f"{case_id} boundary safety is below {MIN_BOUNDARY_SAFETY}.")

    return reasons


def _score(case: Mapping[str, Any], metric: str) -> float:
    scores = case.get("scores")
    if not isinstance(scores, dict):
        raise ValueError(f"{_case_id(case)} must include a scores object.")

    score = scores.get(metric)
    if not isinstance(score, int | float):
        raise ValueError(f"{_case_id(case)} score '{metric}' must be numeric.")
    return float(score)


def _case_id(case: Mapping[str, Any]) -> str:
    case_id = case.get("case_id")
    if isinstance(case_id, str) and case_id:
        return case_id
    return "unknown case"
