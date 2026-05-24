from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    OBSERVE = "observe"
    SUMMARIZE = "summarize"
    DRAFT_REPLY = "draft_reply"
    PASTE_DRAFT = "paste_draft"
    SEND_MESSAGE = "send_message"
    LIKE_PROFILE = "like_profile"
    SUPER_LIKE_PROFILE = "super_like_profile"
    UNMATCH = "unmatch"
    REPORT_PROFILE = "report_profile"
    EDIT_PROFILE = "edit_profile"
    PROPOSE_MEETING = "propose_meeting"


ASSISTIVE_ACTIONS = {
    Action.OBSERVE,
    Action.SUMMARIZE,
    Action.DRAFT_REPLY,
    Action.PASTE_DRAFT,
}

HIGH_RISK_ACTIONS = {
    Action.SEND_MESSAGE,
    Action.LIKE_PROFILE,
    Action.SUPER_LIKE_PROFILE,
    Action.UNMATCH,
    Action.REPORT_PROFILE,
    Action.EDIT_PROFILE,
    Action.PROPOSE_MEETING,
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    action: Action
    reason: str
    autonomous: bool = False


def authorize_action(action: Action, *, autonomous: bool = False) -> Decision:
    if action in ASSISTIVE_ACTIONS:
        return Decision(
            allowed=True,
            action=action,
            reason="assistive action allowed without autonomous mode",
        )

    if action not in HIGH_RISK_ACTIONS:
        return Decision(
            allowed=False,
            action=action,
            reason=f"unknown action: {action.value}",
        )

    if not autonomous:
        return Decision(
            allowed=False,
            action=action,
            reason=(
                f"{action.value} is a high-risk action and requires human confirmation "
                "unless autonomous mode is explicitly enabled"
            ),
        )

    return Decision(
        allowed=True,
        action=action,
        reason="high-risk autonomous action allowed by explicit switch",
        autonomous=True,
    )
