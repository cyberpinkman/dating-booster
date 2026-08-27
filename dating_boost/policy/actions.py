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
    PASS_PROFILE = "pass_profile"
    UNMATCH = "unmatch"
    REPORT_PROFILE = "report_profile"
    EDIT_PROFILE = "edit_profile"
    PREMIUM_PURCHASE = "premium_purchase"
    CALL = "call"
    VIDEO_CALL = "video_call"
    PAYMENT = "payment"
    PROPOSE_MEETING = "propose_meeting"
    CONTACT_EXCHANGE = "contact_exchange"


ASSISTIVE_ACTIONS = {
    Action.OBSERVE,
    Action.SUMMARIZE,
    Action.DRAFT_REPLY,
    Action.PASTE_DRAFT,
}

AUTONOMOUS_ACTIONS = {
    Action.SEND_MESSAGE,
}

PROHIBITED_ACTIONS = {
    Action.LIKE_PROFILE,
    Action.SUPER_LIKE_PROFILE,
    Action.PASS_PROFILE,
    Action.UNMATCH,
    Action.REPORT_PROFILE,
    Action.EDIT_PROFILE,
    Action.PREMIUM_PURCHASE,
    Action.CALL,
    Action.VIDEO_CALL,
    Action.PAYMENT,
    Action.PROPOSE_MEETING,
    Action.CONTACT_EXCHANGE,
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

    if action in PROHIBITED_ACTIONS:
        return Decision(
            allowed=False,
            action=action,
            reason=f"{action.value} is outside the agent execution scope",
        )

    if action in AUTONOMOUS_ACTIONS and not autonomous:
        return Decision(
            allowed=False,
            action=action,
            reason=(
                f"{action.value} is a high-risk action and requires human confirmation "
                "unless autonomous mode is explicitly enabled"
            ),
        )

    if action in AUTONOMOUS_ACTIONS:
        return Decision(
            allowed=True,
            action=action,
            reason="ordinary message send allowed by explicit autonomous switch",
            autonomous=True,
        )

    return Decision(
        allowed=False,
        action=action,
        reason=f"unknown action: {action.value}",
    )
