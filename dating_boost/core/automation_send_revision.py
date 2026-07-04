from __future__ import annotations

from typing import Any


def _mark_draft_revision_required(state: dict[str, Any], *, reason: str) -> None:
    state["state"] = "needs_reply"
    state["draft_revision_required"] = True
    state["draft_revision_reason"] = str(reason)
    state.pop("handoff_reason", None)


def _append_draft_revision_request(
    scan_requests: list[dict[str, Any]],
    *,
    candidate_key: str,
    match_id: str,
    visible_name: str | None,
    reason: str,
) -> None:
    if any(
        item.get("candidate_key") == candidate_key
        and item.get("reason") == "draft_revision_required"
        for item in scan_requests
    ):
        return
    scan_requests.append(
        {
            "candidate_key": candidate_key,
            "match_id": match_id,
            "visible_name": visible_name,
            "reason": "draft_revision_required",
            "draft_revision_reason": str(reason),
            "requires_revised_draft": True,
        }
    )


def _request_draft_revision(
    *,
    state: dict[str, Any],
    scan_requests: list[dict[str, Any]],
    warnings: list[str],
    candidate_key: str,
    match_id: str,
    visible_name: str | None,
    reason: str,
    extra_warning: str | None = None,
) -> None:
    _mark_draft_revision_required(state, reason=reason)
    warnings.append(reason)
    if extra_warning is not None:
        warnings.append(extra_warning)
    _append_draft_revision_request(
        scan_requests,
        candidate_key=candidate_key,
        match_id=match_id,
        visible_name=visible_name,
        reason=reason,
    )
