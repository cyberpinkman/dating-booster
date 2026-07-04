from __future__ import annotations

from typing import Any

from dating_boost.core.memory.review_queue import review_item_display


def _build_summary(
    states: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    user_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "match_count": len(states),
        "new_match_count": sum(1 for state in states if state.get("candidate_type") == "new_match_candidate"),
        "open_chat_candidate_count": sum(1 for state in states if state.get("candidate_type") == "open_chat_candidate"),
        "action_request_count": sum(1 for state in states if state.get("state") == "send_requested"),
        "staged_pending_user_count": sum(1 for state in states if state.get("state") == "staged_pending_user"),
        "waiting_count": sum(1 for state in states if state.get("state") in {"sent_waiting", "waiting_for_match"}),
        "historical_thread_count": sum(1 for state in states if state.get("state") == "historical_thread"),
        "nudge_count": sum(1 for state in states if state.get("state") == "nudge_scheduled"),
        "handoff_count": sum(1 for state in states if state.get("state") == "appointment_handoff"),
        "slot_count": len(ledger),
        "slot_conflict_count": sum(1 for slot in ledger if slot.get("conflict")),
        "user_profile_ready": bool(user_readiness and user_readiness.get("ready")),
        "disclosure_usage_count": sum(1 for state in states if state.get("last_disclosure_source")),
        "low_investment_repair_count": sum(1 for state in states if state.get("low_investment_repair_applied")),
        "paused_due_to_low_reciprocity": sum(
            1
            for state in states
            if state.get("state") in {"paused", "waiting_for_match"}
            and state.get("pause_reason") == "low_reciprocity"
        ),
    }


def _report_with_memory_display(report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    memory_review = normalized.get("memory_review")
    if not isinstance(memory_review, dict):
        return normalized
    review = dict(memory_review)
    items: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()
    for item in review.get("items", []):
        if not isinstance(item, dict):
            continue
        review_item_id = str(item.get("review_item_id") or "")
        if review_item_id and review_item_id in seen_review_ids:
            continue
        if review_item_id:
            seen_review_ids.add(review_item_id)
        enriched = dict(item)
        enriched["display"] = review_item_display(enriched)
        items.append(enriched)
    review["items"] = items
    normalized["memory_review"] = review
    return normalized


def _human_report(report: dict[str, Any]) -> str:
    report = _report_with_memory_display(report)
    summary = report["summary"]
    states = list(report.get("states", []))
    plans = list(report.get("conversation_plans", []))
    plans_by_match = {plan.get("match_id"): dict(plan) for plan in plans if isinstance(plan, dict)}
    ledger = list(report.get("appointment_ledger", []))
    queue = list(report.get("next_priority_queue", []))

    lines = [
        "# Dating Booster Session Report",
        "",
        "## Summary",
        "",
        f"- Session: {report['session_id']}",
        f"- Matches tracked: {summary['match_count']}",
        f"- New matches: {summary['new_match_count']}",
        f"- Send requests pending: {summary['action_request_count']}",
        f"- Staged drafts pending user: {summary.get('staged_pending_user_count', 0)}",
        f"- Waiting: {summary['waiting_count']}",
        f"- Nudge scheduled: {summary['nudge_count']}",
        f"- Handoffs: {summary['handoff_count']}",
        f"- Slot conflicts: {summary['slot_conflict_count']}",
        f"- User profile ready: {summary.get('user_profile_ready')}",
        f"- Disclosure usage: {summary.get('disclosure_usage_count')}",
        f"- Low-investment repairs: {summary.get('low_investment_repair_count')}",
        f"- Paused for low reciprocity: {summary.get('paused_due_to_low_reciprocity')}",
        "",
        "## Match States",
        "",
    ]
    if states:
        for state in states:
            plan = plans_by_match.get(state.get("match_id"), {})
            scores = dict(plan.get("scores", {}))
            lines.append(
                "- "
                + " | ".join(
                    [
                        f"match={state.get('match_id')}",
                        f"candidate={state.get('candidate_key')}",
                        f"state={state.get('state')}",
                        f"stage={state.get('conversation_stage') or plan.get('stage') or 'unknown'}",
                        f"topic={plan.get('current_topic') or 'unknown'}",
                        f"topic_state={plan.get('topic_state') or state.get('topic_exit_pressure') or 'unknown'}",
                        f"engagement={scores.get('engagement')}",
                        f"momentum={scores.get('momentum')}",
                        f"handoff={state.get('handoff_reason') or 'none'}",
                        f"next_due_at={state.get('next_due_at') or 'none'}",
                        f"question_debt={state.get('question_debt', 0)}",
                        f"self_disclosure_debt={state.get('self_disclosure_debt', 0)}",
                        f"low_investment={state.get('low_investment_streak', 0)}",
                        f"next_milestone={state.get('next_milestone') or plan.get('next_milestone') or 'none'}",
                        f"next_host_action={_state_next_host_action(state)}",
                        f"failure_hypothesis={_failure_hypothesis(state, plan)}",
                    ]
                )
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Conversation Plans", ""])
    if plans:
        for plan in plans:
            scores = dict(plan.get("scores", {}))
            lines.append(
                "- "
                + " | ".join(
                    [
                        f"match={plan.get('match_id')}",
                        f"stage={plan.get('stage')}",
                        f"move={plan.get('recommended_move')}",
                        f"topic={plan.get('current_topic')}",
                        f"milestone={plan.get('next_milestone')}",
                        f"engagement={scores.get('engagement')}",
                        f"warmth={scores.get('warmth')}",
                        f"logistics={scores.get('logistics_readiness')}",
                    ]
                )
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Handoffs", ""])
    handoff_states = [state for state in states if state.get("state") == "appointment_handoff"]
    if handoff_states:
        for state in handoff_states:
            lines.append(
                f"- match={state.get('match_id')} candidate={state.get('candidate_key')} "
                f"reason={state.get('handoff_reason') or 'unknown'}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Appointment Ledger", ""])
    if ledger:
        for slot in ledger:
            lines.append(
                f"- slot={slot.get('slot_id')} match={slot.get('match_id')} "
                f"status={slot.get('status')} conflict={bool(slot.get('conflict'))}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Next Priority Queue", ""])
    if queue:
        for item in queue:
            lines.append(
                f"- priority={item.get('priority')} match={item.get('match_id')} "
                f"candidate={item.get('candidate_key')} state={item.get('state')}"
            )
    else:
        lines.append("- none")

    memory_review = report.get("memory_review", {})
    pending_items = list(memory_review.get("items", []))
    lines.extend(["", "## Memory Suggestions", ""])
    if pending_items:
        for item in pending_items:
            display = item.get("display") if isinstance(item.get("display"), dict) else {}
            lines.append(
                f"- id={item.get('review_item_id')} | "
                f"{display.get('summary') or '可能要记住一条新的聊天线索。'} "
                f"({display.get('accept_label') or '接受'} / {display.get('reject_label') or '拒绝'})"
            )
        lines.append("")
        lines.append("接受或拒绝时仍使用上面的 id。")
        lines.append("To accept: memory review decide --data-dir DIR --accept <id> --confirm memory-review:<session_id>")
        lines.append("To reject: memory review decide --data-dir DIR --reject <id> --confirm memory-review:<session_id>")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _state_next_host_action(state: dict[str, Any]) -> str:
    state_name = str(state.get("state") or "")
    if state_name == "needs_thread_scan":
        return "open_thread"
    if state_name in {"needs_reply", "draft_ready"}:
        return "author_or_review_draft"
    if state_name == "send_requested":
        return "verify_or_record_pending_send"
    if state_name == "staged_pending_user":
        return "wait_for_user_send_confirmation"
    if state_name == "stage_needs_verification":
        return "verify_staged_text"
    if state_name == "appointment_handoff":
        return "user_takeover"
    if state_name == "nudge_scheduled":
        return "wait_until_due"
    if state_name in {"sent_waiting", "waiting_for_match"}:
        return "wait_for_match"
    return "none"


def _failure_hypothesis(state: dict[str, Any], plan: dict[str, Any]) -> str:
    if state.get("handoff_reason"):
        return f"handoff:{state.get('handoff_reason')}"
    if state.get("pause_reason") == "low_reciprocity":
        return "low_reciprocity_or_over_questioning"
    if int(state.get("low_investment_streak") or 0) >= 2:
        return "match_low_investment"
    scores = dict(plan.get("scores", {}))
    if int(scores.get("topic_saturation") or 0) >= 70:
        return "topic_saturated"
    if state.get("last_action_result_error"):
        return f"action_result:{state.get('last_action_result_error')}"
    return "none"
