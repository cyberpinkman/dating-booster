"""Deterministic offline evaluation runner for reply quality cases."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.memory.models import (
    CommitmentMemory,
    EvidenceRef,
    IdentityTrustStatus,
    MatchMemoryProjection,
    MemoryFact,
    MemoryFactStatus,
    MemoryFactType,
    MemoryScope,
)
from dating_boost.core.memory.retrieval import build_memory_context
from dating_boost.perception.fixture_loader import load_observation
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


MEMORY_EVAL_DEFAULT_NOW = "2026-06-06T00:00:00Z"
MIN_MEMORY_EVAL_CASES = 12


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


def run_memory_eval(path: Path | None = None) -> EvalResult:
    """Run deterministic memory retrieval/context regression assertions."""

    fixture_path = path or Path("tests/fixtures/evals/memory_cases.jsonl")
    cases_payload = _read_cases(fixture_path)
    failures: list[str] = []
    case_results: list[dict[str, Any]] = []
    if len(cases_payload) < MIN_MEMORY_EVAL_CASES:
        failures.append(
            f"Expected at least {MIN_MEMORY_EVAL_CASES} memory eval cases, found {len(cases_payload)}."
        )

    for index, raw_case in enumerate(cases_payload, start=1):
        case_id = str(raw_case.get("case_id") or f"case_{index}")
        mismatches: list[str] = []
        mode_expectations = raw_case.get("mode_expectations")
        if isinstance(mode_expectations, dict):
            for mode, expected in mode_expectations.items():
                if isinstance(expected, dict):
                    mismatches.extend(
                        f"{mode} {mismatch}"
                        for mismatch in _memory_case_mismatches(raw_case, mode=str(mode), expected=expected)
                    )
                else:
                    mismatches.append(f"{mode} expectation must be an object")
        else:
            expected = raw_case.get("expected")
            if not isinstance(expected, dict):
                mismatches.append("expected must be an object")
            else:
                mismatches.extend(
                    _memory_case_mismatches(
                        raw_case,
                        mode=str(raw_case.get("reply_mode") or "adaptive"),
                        expected=expected,
                    )
                )
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


def _memory_case_mismatches(raw_case: Mapping[str, Any], *, mode: str, expected: Mapping[str, Any]) -> list[str]:
    case_id = str(raw_case.get("case_id") or "memory_case")
    now = str(raw_case.get("now") or MEMORY_EVAL_DEFAULT_NOW)
    projection = _memory_projection_from_case(raw_case, now=now)
    observation = None
    observation_fixture = raw_case.get("latest_observation_fixture")
    if isinstance(observation_fixture, str) and observation_fixture:
        observation = load_observation(Path(observation_fixture))
    max_items = raw_case.get("max_memory_items")
    memory_context = build_memory_context(
        projection.match_id,
        projection,
        latest_observation=observation,
        now=now,
        max_items=int(max_items) if isinstance(max_items, int) else None,
        reply_mode=mode,
    )
    conversation_memory = dict(memory_context["conversation_memory"])
    conversation_memory["memory_items"] = memory_context["memory_items"]
    conversation_memory["excluded_memory"] = memory_context["excluded_memory"]
    context_pack = build_context_pack(
        user_profile=_memory_eval_user_profile(raw_case.get("user_profile")),
        match_profile=memory_context["match_profile"],
        conversation_memory=conversation_memory,
        reply_mode=mode,
        max_items=None,
    )

    labels = [str(item.get("label")) for item in context_pack["items"]]
    excluded_reasons = {
        str(item.get("reason"))
        for item in memory_context["excluded_memory"]
        if isinstance(item, dict) and item.get("reason")
    }
    context_text = json.dumps(context_pack, ensure_ascii=False, sort_keys=True)
    mismatches: list[str] = []

    for label in _expected_list(expected, "labels_include"):
        if label not in labels:
            mismatches.append(f"missing label {label!r}")
    for label in _expected_list(expected, "labels_exclude"):
        if label in labels:
            mismatches.append(f"unexpected label {label!r}")
    for reason in _expected_list(expected, "excluded_reasons_include"):
        if reason not in excluded_reasons:
            mismatches.append(f"missing exclusion reason {reason!r}")
    for text in _expected_list(expected, "text_include"):
        if text not in context_text:
            mismatches.append(f"missing text {text!r}")
    for text in _expected_list(expected, "text_exclude"):
        if text in context_text:
            mismatches.append(f"unexpected text {text!r}")
    for before, after in _expected_pairs(expected, "label_order_before"):
        if before not in labels:
            mismatches.append(f"order label {before!r} missing")
        elif after not in labels:
            mismatches.append(f"order label {after!r} missing")
        elif labels.index(before) >= labels.index(after):
            mismatches.append(f"label {before!r} should precede {after!r}")
    if "trusted_for_managed_send" in expected:
        expected_trust = bool(expected["trusted_for_managed_send"])
        if projection.trusted_for_managed_send != expected_trust:
            mismatches.append(
                f"trusted_for_managed_send expected {expected_trust!r}, got {projection.trusted_for_managed_send!r}"
            )
    if not isinstance(raw_case.get("projection"), dict):
        mismatches.append(f"{case_id} projection must be an object")
    return mismatches


def _memory_projection_from_case(raw_case: Mapping[str, Any], *, now: str) -> MatchMemoryProjection:
    raw_projection = raw_case.get("projection")
    if not isinstance(raw_projection, dict):
        raw_projection = {}
    match_id = str(raw_case.get("match_id") or raw_projection.get("match_id") or "match_eval")
    identity_status = IdentityTrustStatus(str(raw_projection.get("identity_status") or IdentityTrustStatus.TRUSTED.value))
    trusted_for_context = bool(raw_projection.get("trusted_for_context", identity_status != IdentityTrustStatus.CONFLICTED))
    trusted_for_managed_send = bool(
        raw_projection.get("trusted_for_managed_send", identity_status == IdentityTrustStatus.TRUSTED)
    )
    return MatchMemoryProjection(
        match_id=match_id,
        identity_status=identity_status,
        trusted_for_context=trusted_for_context,
        trusted_for_managed_send=trusted_for_managed_send,
        updated_at=str(raw_projection.get("updated_at") or now),
        facts=[
            _memory_fact_from_compact(item, now=now, default_fact_type=MemoryFactType.VISIBLE_FACT)
            for item in raw_projection.get("facts", [])
            if isinstance(item, dict)
        ],
        inferences=[
            _memory_fact_from_compact(item, now=now, default_fact_type=MemoryFactType.INFERENCE)
            for item in raw_projection.get("inferences", [])
            if isinstance(item, dict)
        ],
        active_commitments=[
            _commitment_from_compact(item, now=now, status="active")
            for item in raw_projection.get("active_commitments", [])
            if isinstance(item, dict)
        ],
        resolved_commitments=[
            _commitment_from_compact(item, now=now, status="resolved")
            for item in raw_projection.get("resolved_commitments", [])
            if isinstance(item, dict)
        ],
        feedback_preferences=dict(raw_projection.get("feedback_preferences", {})),
    )


def _memory_fact_from_compact(
    raw_fact: Mapping[str, Any],
    *,
    now: str,
    default_fact_type: MemoryFactType,
) -> MemoryFact:
    fact_type = MemoryFactType(str(raw_fact.get("fact_type") or default_fact_type.value))
    return MemoryFact(
        fact_id=str(
            raw_fact.get("fact_id")
            or f"fact_{hashlib.sha256(json.dumps(raw_fact, sort_keys=True).encode('utf-8')).hexdigest()[:12]}"
        ),
        scope=MemoryScope(str(raw_fact.get("scope") or MemoryScope.MATCH_PROFILE.value)),
        fact_type=fact_type,
        subject=str(raw_fact.get("subject") or "Alex"),
        predicate=str(raw_fact.get("predicate") or "profile_cue"),
        value=raw_fact.get("value"),
        qualifiers=dict(raw_fact.get("qualifiers") or {"app_id": "eval"}),
        confidence=str(raw_fact.get("confidence") or ("low" if fact_type == MemoryFactType.INFERENCE else "medium")),
        evidence=EvidenceRef(
            source_type="eval_fixture",
            evidence_text=str(raw_fact.get("evidence_text") or "Synthetic memory eval fixture."),
            confidence=str(raw_fact.get("confidence") or "medium"),
        ),
        created_at=str(raw_fact.get("created_at") or now),
        last_seen_at=str(raw_fact.get("last_seen_at") or now),
        valid_from=raw_fact.get("valid_from"),
        valid_until=raw_fact.get("valid_until"),
        supersedes=list(raw_fact.get("supersedes", [])),
        status=MemoryFactStatus(str(raw_fact.get("status") or MemoryFactStatus.ACTIVE.value)),
    )


def _commitment_from_compact(raw_commitment: Mapping[str, Any], *, now: str, status: str) -> CommitmentMemory:
    return CommitmentMemory(
        commitment_id=str(raw_commitment.get("commitment_id") or "commitment_eval"),
        text=str(raw_commitment.get("text") or ""),
        evidence=EvidenceRef(source_type="eval_fixture", evidence_text="Synthetic memory eval fixture."),
        created_at=str(raw_commitment.get("created_at") or now),
        last_seen_at=str(raw_commitment.get("last_seen_at") or now),
        resolved_at=raw_commitment.get("resolved_at"),
        status=str(raw_commitment.get("status") or status),
    )


def _memory_eval_user_profile(raw_user_profile: Any) -> dict[str, Any]:
    user_profile = {
        "facts": [],
        "preferences": [],
        "boundaries": [],
        "style_examples": [],
    }
    if isinstance(raw_user_profile, dict):
        for key in user_profile:
            value = raw_user_profile.get(key)
            if isinstance(value, list):
                user_profile[key] = list(value)
    return user_profile


def _expected_list(expected: Mapping[str, Any], key: str) -> list[str]:
    value = expected.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _expected_pairs(expected: Mapping[str, Any], key: str) -> list[tuple[str, str]]:
    value = expected.get(key, [])
    if not isinstance(value, list):
        return []
    pairs: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, list) and len(item) == 2:
            pairs.append((str(item[0]), str(item[1])))
    return pairs


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
