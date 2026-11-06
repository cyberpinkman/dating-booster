#!/usr/bin/env python3
"""Compare ManagedRun operation counts with synthetic, entirely in-memory ports.

Run directly with ``python3 scripts/managed_run_benchmark.py``. There is no GUI,
network, .env loading, production data, wall-clock timing, or sleeping here.
The scripted Jev answers demonstrate routing mechanics, not model accuracy.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

# The documented command also works from a checkout without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dating_boost.core.managed_run import (  # noqa: E402
    ClickReceipt,
    ComposerObservation,
    DraftDecision,
    InMemoryManagedRunStore,
    MANAGED_BURST_MAX_GAP_SECONDS,
    ManagedAuthorization,
    ManagedRun,
    ManagedRunConfig,
    MessageListSnapshot,
    OpenThreadObservation,
    PostSendObservation,
    ThreadCandidate,
    ThreadObservation,
)
from dating_boost.core.managed_run_provider import StandalonePlannerManagedDecisionPort  # noqa: E402
from dating_boost.intelligence.managed_triage import JevManagedTriage  # noqa: E402
from dating_boost.intelligence.typesafe import ChoiceAnswer, EvaluationResult  # noqa: E402


class SyntheticClock:
    """Advance a virtual clock and trace calls without waiting or measuring latency."""

    def __init__(self) -> None:
        self.seconds = 0
        self.events: list[tuple[str, int]] = []

    def now(self) -> datetime:
        return datetime(2026, 9, 20, 4, tzinfo=timezone.utc) + timedelta(seconds=self.seconds)

    def monotonic(self) -> float:
        return float(self.seconds)

    def record(self, event: str) -> None:
        self.events.append((event, self.seconds))

    def capture(self, event: str) -> str:
        self.seconds += 1
        self.record(event)
        return self.now().isoformat().replace("+00:00", "Z")


SYNTHETIC_MESSAGES = {
    "reply": "你平时喜欢看什么类型的电影？",
    "wait": "好，先这样，晚点聊。",
    "handoff": "请帮我确认周六下午三点在那家咖啡店见面。",
}


class SyntheticObservation:
    def __init__(self, clock: SyntheticClock, routes: tuple[str, ...]) -> None:
        self.clock = clock
        self.routes = {f"synthetic_match_{index}": route for index, route in enumerate(routes)}
        self.candidates = tuple(
            ThreadCandidate(
                candidate_key=f"synthetic_row_{index}",
                target_id=target_id,
                target_binding=f"synthetic_binding_{index}",
                discovery_revision=f"synthetic_inbound_{index}",
                priority=index,
            )
            for index, target_id in enumerate(self.routes)
        )
        self.scans = 0
        self.opens = 0
        self.reads = 0

    def scan_message_list(self, **_: Any) -> MessageListSnapshot:
        self.scans += 1
        return MessageListSnapshot(candidates=self.candidates, captured_at=self.clock.capture("message_list_scan"))

    def open_thread(self, candidate: ThreadCandidate) -> OpenThreadObservation:
        self.opens += 1
        return OpenThreadObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            captured_at=self.clock.capture("thread_open"),
        )

    def observe_thread(self, candidate: ThreadCandidate) -> ThreadObservation:
        self.reads += 1
        route = self.routes[candidate.target_id]
        return ThreadObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=candidate.discovery_revision,
            captured_at=self.clock.capture("thread_read"),
            context={
                "match_id": candidate.target_id,
                "standalone_thread_observation": {
                    "assessment": {"recommended_next": "reply"},
                    "observation": {
                        "page_type": "chat_thread",
                        "page_confidence": "high",
                        "conversation_observation": {
                            "visible_messages": [{"sender": "match", "text": SYNTHETIC_MESSAGES[route]}],
                        },
                    },
                },
            },
        )


class ScriptedPlanner:
    def __init__(
        self, routes: Mapping[str, str], clock: SyntheticClock, *,
        message_sequence: tuple[str, ...] = (), planning_delay_seconds: int = 0,
    ) -> None:
        self.routes = routes
        self.clock = clock
        self.message_sequence = message_sequence
        self.planning_delay_seconds = planning_delay_seconds
        self.calls = 0
        self.drafts = 0

    def draft_for_match(self, *, match_id: str, mode: str) -> dict[str, Any]:
        if mode != "adaptive":
            raise ValueError("unexpected_benchmark_planner_mode")
        self.calls += 1
        self.clock.record("draft_start")
        self.clock.seconds += self.planning_delay_seconds
        self.clock.record("draft_complete")
        route = self.routes[match_id]
        if route != "reply":
            # The real decision adapter maps an unavailable draft to handoff.
            # It does not have a post-generation `wait` result. Preserve that
            # behavior instead of inventing an equivalent baseline route.
            return {"status": "blocked", "reason": f"synthetic_{route}_draft_unavailable"}
        self.drafts += 1
        draft: dict[str, Any] = {"best_reply": "我最近比较喜欢喜剧，看着很放松。"}
        if self.message_sequence:
            draft["message_sequence"] = list(self.message_sequence)
        return {"status": "ok", "draft": draft}


class SyntheticDecision(StandalonePlannerManagedDecisionPort):
    def __init__(self, planner: ScriptedPlanner, *, triage: JevManagedTriage | None) -> None:
        super().__init__(planner, triage=triage)
        self.calls = 0

    def decide(self, observation: ThreadObservation, *, config: ManagedRunConfig) -> DraftDecision:
        self.calls += 1
        self.planner.clock.record("decide")
        return super().decide(observation, config=config)


class ScriptedTypeSafeClient:
    """Return typed fixture answers; no HTTP transport or credentials exist."""

    def __init__(self, clock: SyntheticClock) -> None:
        self.clock = clock
        self.calls = 0
        self.questions = 0

    def evaluate(self, *, state: dict[str, Any], questions: Mapping[str, Any]) -> EvaluationResult:
        self.calls += 1
        self.clock.record("semantic_request")
        self.questions += len(questions)
        text = state["conversation"]["latest_inbound_messages"][-1]["text"]
        route = next(route for route, message in SYNTHETIC_MESSAGES.items() if message == text)
        choices = {
            "boundary": "user_handoff" if route == "handoff" else "ordinary_chat",
            "response_need": "wait" if route == "wait" else "reply",
        }
        answers = {}
        for name, question in questions.items():
            choice = choices[name]
            options = question["criteria"]
            answers[name] = ChoiceAnswer(
                choice=choice,
                confidence=0.99,
                probabilities={key: 0.98 if key == choice else 0.02 / (len(options) - 1) for key in options},
            )
        return EvaluationResult(
            answers=answers,
            model="scripted-jev-fixture",
            duration_ms=0.0,
            input_tokens=None,
            output_tokens=None,
        )


class SyntheticAction:
    """Count the four safety seams and return fresh, exact synthetic evidence."""

    def __init__(self, clock: SyntheticClock, *, expected_sequence: tuple[str, ...] = ()) -> None:
        self.clock = clock
        self.expected_sequence = expected_sequence
        self.counts: Counter[str] = Counter()
        self.composer: dict[str, str] = {}
        self.receipts: dict[str, tuple[str, str]] = {}

    def observe_composer(self, candidate: ThreadCandidate) -> ComposerObservation:
        self.counts["composer_observe"] += 1
        return self._composer_observation(candidate, event="composer_observe")

    def stage_text(self, candidate: ThreadCandidate, text: str) -> ComposerObservation:
        # The real staging seam also observes the bound composer before writing.
        before = self.observe_composer(candidate)
        if before.text or not text:
            raise ValueError("synthetic_composer_not_empty_or_draft_empty")
        self.counts["exact_stage"] += 1
        self.composer[candidate.target_id] = text
        return self._composer_observation(candidate, event="exact_stage")

    def click_send(self, candidate: ThreadCandidate) -> ClickReceipt:
        text = self.composer.get(candidate.target_id, "")
        if not text:
            raise ValueError("synthetic_composer_not_staged")
        self.counts["return_only_click"] += 1
        receipt_id = f"synthetic_receipt_{self.counts['return_only_click']}"
        self.receipts[receipt_id] = (candidate.target_id, text)
        self.composer[candidate.target_id] = ""
        return ClickReceipt(receipt_id=receipt_id, clicked_at=self.clock.capture("return_only_click"))

    def observe_post_send(self, candidate: ThreadCandidate, receipt: ClickReceipt) -> PostSendObservation:
        self.counts["fresh_post_send_observe"] += 1
        target_id, text = self.receipts[receipt.receipt_id]
        return PostSendObservation(
            observation_id=f"synthetic_post_{receipt.receipt_id}",
            receipt_id=receipt.receipt_id,
            target_id=target_id,
            target_binding=candidate.target_binding,
            captured_at=self.clock.capture("fresh_post_send_observe"),
            input_cleared=self.composer[candidate.target_id] == "",
            outbound_text=text,
            continuation_verified=(
                bool(self.expected_sequence)
                and target_id == candidate.target_id
                and text == self.expected_sequence[(self.counts["fresh_post_send_observe"] - 1) % len(self.expected_sequence)]
            ),
        )

    def _composer_observation(self, candidate: ThreadCandidate, *, event: str) -> ComposerObservation:
        if candidate.inbound_revision is None:
            raise ValueError("synthetic_authoritative_revision_missing")
        return ComposerObservation(
            target_id=candidate.target_id,
            target_binding=candidate.target_binding,
            inbound_revision=candidate.inbound_revision,
            text=self.composer.get(candidate.target_id, ""),
            captured_at=self.clock.capture(event),
        )


def benchmark_variant(
    routes: tuple[str, ...], *, queued: bool, jev: bool,
    message_sequence: tuple[str, ...] = (), planning_delay_seconds: int = 0,
) -> dict[str, Any]:
    clock = SyntheticClock()
    observation = SyntheticObservation(clock, routes)
    planner = ScriptedPlanner(
        observation.routes, clock, message_sequence=message_sequence, planning_delay_seconds=planning_delay_seconds,
    )
    client = ScriptedTypeSafeClient(clock)
    action = SyntheticAction(clock, expected_sequence=message_sequence)
    store = InMemoryManagedRunStore()
    triage = JevManagedTriage(client, monotonic=clock.monotonic) if jev else None
    decision = SyntheticDecision(planner, triage=triage)
    runtime = ManagedRun(
        store, observation, decision, action,
        now=clock.now,
        scan_batch_max_age_seconds=120.0 if queued else 0.0,
        monotonic=clock.monotonic,
    )
    # One extra send slot permits the final no-work check rather than stopping
    # at budget exhaustion before all wait/handoff candidates are processed.
    expected_messages = routes.count("reply") * (len(message_sequence) or 1)
    budget = expected_messages + 1
    config = ManagedRunConfig(
        app_id="tashuo",
        runtime="mac-ios-app",
        max_sends_per_run=budget,
        authorization=ManagedAuthorization(
            authorization_id="synthetic_authorization",
            app_id="tashuo",
            runtime="mac-ios-app",
            allowed_target_ids=tuple(observation.routes),
        ),
    )
    started = runtime.start(config, run_id="synthetic_benchmark")
    if started.get("status") != "active":
        raise RuntimeError("benchmark_failed_to_start")
    outcomes: Counter[str] = Counter()
    terminal_scan_count = 0
    max_steps = len(routes) * 2 + 2
    for _ in range(max_steps):
        scans_before = observation.scans
        result = runtime.tick("synthetic_benchmark")
        status = result["status"]
        if status == "no_work" and result.get("reason") == "no_eligible_thread":
            terminal_scan_count = observation.scans - scans_before
            break
        if status not in {"confirmed", "wait", "handoff"}:
            raise RuntimeError(f"benchmark_unexpected_result:{status}:{result.get('reason')}")
        outcomes[status] += 1
    else:
        raise RuntimeError("benchmark_step_bound_exceeded")
    if sum(outcomes.values()) != len(routes) or outcomes["confirmed"] != routes.count("reply"):
        raise RuntimeError("benchmark_workload_not_fully_processed")
    record = store.load("synthetic_benchmark")
    if record is None or record.confirmed_send_count != expected_messages:
        raise RuntimeError("benchmark_message_count_mismatch")
    if any(value != expected_messages for value in action.counts.values()):
        raise RuntimeError("benchmark_safety_seam_count_mismatch")
    if message_sequence and tuple(text for _, text in action.receipts.values()) != message_sequence * routes.count("reply"):
        raise RuntimeError("benchmark_message_sequence_not_preserved")
    report = {
        "scan_batch_max_age_seconds": 120 if queued else 0,
        "jev_enabled": jev,
        "send_budget": budget,
        "terminal_status": result["status"],
        "terminal_reason": result["reason"],
        "operations": {
            "message_list_scans": observation.scans,
            "processing_scans": observation.scans - terminal_scan_count,
            "terminal_no_work_scans": terminal_scan_count,
            "thread_opens": observation.opens,
            "thread_reads": observation.reads,
            "decision_calls": decision.calls,
            "draft_planner_calls": planner.calls,
            "drafts_created": planner.drafts,
            "semantic_requests_scripted": client.calls,
            "semantic_questions_scripted": client.questions,
            "live_http_requests": 0,
        },
        "outcomes": {name: outcomes[name] for name in ("confirmed", "wait", "handoff")},
        "synthetic_safety_seam_calls": dict(action.counts),
    }
    if message_sequence:
        report["burst"] = _burst_metrics(clock, message_sequence, planning_delay_seconds, record.confirmed_send_count)
    return report


def _burst_metrics(
    clock: SyntheticClock, messages: tuple[str, ...], planning_delay_seconds: int, confirmed_message_count: int,
) -> dict[str, Any]:
    order = [name for name, _ in clock.events]
    click_indices = [index for index, name in enumerate(order) if name == "return_only_click"]
    clicks = [clock.events[index][1] for index in click_indices]
    between_clicks = order[click_indices[0] + 1 : click_indices[-1]]
    first_action = order.index("composer_observe")
    last_action = len(order) - 1 - order[::-1].index("fresh_post_send_observe")
    action_order = order[first_action : last_action + 1]
    expected_order = ["composer_observe", "exact_stage", "return_only_click", "fresh_post_send_observe"] * len(messages)
    return {
        "message_count": len(messages),
        "confirmed_message_count": confirmed_message_count,
        "simulated_planning_seconds": planning_delay_seconds,
        "gap_limit_seconds": MANAGED_BURST_MAX_GAP_SECONDS,
        "click_times_virtual_seconds": clicks,
        "click_gaps_virtual_seconds": [end - start for start, end in zip(clicks, clicks[1:])],
        "semantic_requests_between_clicks": between_clicks.count("semantic_request"),
        "planner_calls_between_clicks": between_clicks.count("draft_start"),
        "contiguous_action_seams": action_order == expected_order,
        "operation_order": order,
    }


def run_benchmark() -> dict[str, Any]:
    workloads = {
        "all_reply": ("reply",) * 5,
        "mixed_reply_wait_handoff": ("reply", "wait", "reply", "handoff", "wait"),
    }
    return {
        "workload": "synthetic",
        "live_gui": False,
        "live_api": False,
        "storage": "in_memory",
        "measurement": "operation_counts_only",
        "notes": [
            "Scripted answers measure routing structure, not Jev accuracy or real-device speed.",
            "List scans include the terminal no-work scan; processing_scans excludes it.",
            "Existing planner failure maps to handoff; Jev can classify synthetic closings as wait before drafting.",
            "Every semantic request contains both questions; all request counts use a scripted typed client, not HTTP.",
            "Burst clocks use a scripted 180-second planning delay and 1 second per seam; gaps are virtual, not measured device latency.",
        ],
        "workloads": {
            name: {
                "thread_count": len(routes),
                "scripted_routes": dict(Counter(routes)),
                "variants": {
                    "legacy_per_thread_scan": benchmark_variant(routes, queued=False, jev=False),
                    "queued_without_jev": benchmark_variant(routes, queued=True, jev=False),
                    "queued_with_jev": benchmark_variant(routes, queued=True, jev=True),
                },
            }
            for name, routes in workloads.items()
        },
        "burst_scenarios": {
            f"{message_count}_messages": {
                "with_jev" if jev else "without_jev": benchmark_variant(
                    ("reply",), queued=True, jev=jev,
                    message_sequence=("我最近比较喜欢喜剧。", "节奏轻松一点，看完不会太累。", "你更偏爱哪种？")[:message_count],
                    planning_delay_seconds=180,
                )
                for jev in (False, True)
            }
            for message_count in (2, 3)
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2))
