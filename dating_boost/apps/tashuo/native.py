from __future__ import annotations

import time
from typing import Any
from pathlib import Path

from .runtime_common import *
from .launch_runtime import *
from .message_page_runtime import *
from .profile_runtime import *
from .targeting import *
from .send_runtime import *


def install_tashuo_session_hooks(session: Any) -> None:
    session.app_screen_state_observer = classify_tashuo_capture
    session.app_foreground_states = set(TASHUO_FOREGROUND_STATES)
    session.app_verified_screen_key = "requires_verified_tashuo_screen"
    session.app_foreground_not_verified_reason = "tashuo_foreground_not_verified"
    session.app_step_precondition_verifier = _verify_tashuo_step_precondition
    session.app_step_postcondition_verifier = _verify_tashuo_step_postcondition
    session.app_profile_field_coverage = _tashuo_profile_field_coverage


def run_tashuo_action(
    session: Any,
    action: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    if action in {"prepare-message-page", "prepare_message_page"}:
        return prepare_tashuo_message_page(session, dry_run=dry_run, output_dir=output_dir)
    if action in {"prepare-self-profile-page", "prepare_self_profile_page"}:
        return prepare_tashuo_self_profile_page(session, dry_run=dry_run, output_dir=output_dir)
    if action in {"open-self-profile-detail", "open_self_profile_detail"}:
        return open_tashuo_self_profile_detail(session, dry_run=dry_run, output_dir=output_dir)
    if action in {"profile-scroll-to-bottom", "profile_scroll_to_bottom"} and _is_mac_ios_app_session(session):
        return scroll_tashuo_profile_to_bottom_mac_ios_app(
            session,
            dry_run=dry_run,
            output_dir=output_dir,
            max_scrolls=int(options.get("max_scrolls") or TASHUO_PROFILE_BOTTOM_MAX_SCROLLS),
        )
    if action in {"profile-scroll-down", "profile_scroll_down", "profile-scroll-up", "profile_scroll_up"} and _is_mac_ios_app_session(session):
        return scroll_tashuo_profile_read_mac_ios_app(session, action, dry_run=dry_run, output_dir=output_dir)
    if action in {"clear-message-input", "clear_message_input"}:
        return clear_tashuo_message_input(session, dry_run=dry_run, output_dir=output_dir)
    if action in {"conversation-list-scroll-to-top", "conversation-list-return-to-top"}:
        return scroll_tashuo_conversation_list_to_top(
            session,
            dry_run=dry_run,
            output_dir=output_dir,
            max_scrolls=int(options.get("max_scrolls") or 8),
        )
    try:
        planned_steps = _tashuo_action_steps(action, **options)
    except KeyError:
        return {
            **session._base_payload("blocked"),
            "action": action,
            "reason": "unknown_tashuo_harness_action",
            **tashuo_guardrails_payload(),
        }
    payload = {
        **session._base_payload("ok"),
        "action": action,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    if action == "open-conversation":
        requires_visual_relocation = _tashuo_open_conversation_requires_visual_relocation(options)
        if not requires_visual_relocation:
            already_open = _tashuo_already_at_open_conversation_target(session, planned_steps, output_dir=output_dir)
            if already_open is not None:
                payload.update(already_open)
                return payload
        relocated = _try_tashuo_open_conversation_visual_relocation(
            session,
            payload,
            options=options,
            output_dir=output_dir,
        )
        if relocated is not None:
            return relocated
    return session._execute_planned_steps(payload, output_dir=output_dir)


__all__ = [name for name in globals() if not name.startswith("__")]
