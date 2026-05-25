from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dating_boost.core.context_pack import build_context_pack
from dating_boost.core.feedback import create_feedback_event
from dating_boost.core.identity import resolve_match_identity
from dating_boost.core.models import MemoryItem, ReplyMode, UserProfile
from dating_boost.core.repositories import JsonMemoryRepository, MatchRepository, ObservationRepository
from dating_boost.intelligence.backends import ModelBackend, OpenAIBackend, ScriptedBackend
from dating_boost.intelligence.reply_generator import DraftResponse, generate_reply
from dating_boost.perception.fixture_loader import load_observation
from dating_boost.perception.observations import AppObservation
from dating_boost.perception.screenshot_loader import build_observation_from_screenshot_analysis
from dating_boost.policy import Action, authorize_action
from dating_boost.policy.content import ContentPolicyDecision, evaluate_draft_content


MVP_TIMESTAMP = "2026-05-25T00:00:00Z"


def main(argv: list[str] | None = None) -> int:
    argv_list = None if argv is None else list(argv)
    command_tokens = sys.argv[1:] if argv is None else argv_list
    if command_tokens and command_tokens[0] in {action.value for action in Action}:
        return _run_authorization(command_tokens)

    parser = argparse.ArgumentParser(
        prog="dating-boost",
        description="Local-first dating workflow copilot.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    authorize_parser = subparsers.add_parser(
        "authorize",
        help="Authorize an action before any harness executes it.",
    )
    authorize_parser.add_argument(
        "action",
        choices=[action.value for action in Action],
        help="Action to authorize.",
    )
    authorize_parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Enable high-risk autonomous mode for this action after accepting the risks.",
    )
    authorize_parser.set_defaults(handler=_handle_authorize)

    init_parser = subparsers.add_parser("init-profile", help="Initialize local user profile memory.")
    init_parser.add_argument("--data-dir", required=True, type=Path)
    init_parser.add_argument("--input", required=True, type=Path)
    init_parser.set_defaults(handler=_handle_init_profile)

    import_parser = subparsers.add_parser("import-observation", help="Import an app observation fixture.")
    import_parser.add_argument("--data-dir", required=True, type=Path)
    import_parser.add_argument("--input", required=True, type=Path)
    import_parser.set_defaults(handler=_handle_import_observation)

    screenshot_parser = subparsers.add_parser(
        "observe-screenshot",
        help="Import a screenshot plus manual/OCR/VLM analysis as an observation.",
    )
    screenshot_parser.add_argument("--data-dir", required=True, type=Path)
    screenshot_parser.add_argument("--screenshot", required=True, type=Path)
    screenshot_parser.add_argument("--analysis", required=True, type=Path)
    screenshot_parser.set_defaults(handler=_handle_observe_screenshot)

    draft_parser = subparsers.add_parser("draft", help="Generate a reply draft.")
    draft_parser.add_argument("--data-dir", required=True, type=Path)
    draft_parser.add_argument("--match-id", required=True)
    draft_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    draft_parser.add_argument("--backend", choices=["openai", "scripted"])
    draft_parser.add_argument("--model", default="gpt-4.1-mini")
    draft_parser.add_argument("--scripted-backend-output", type=Path)
    draft_parser.add_argument("--debug-context", action="store_true")
    draft_parser.set_defaults(handler=_handle_draft)

    feedback_parser = subparsers.add_parser("feedback", help="Append local feedback for a draft.")
    feedback_parser.add_argument("--data-dir", required=True, type=Path)
    feedback_parser.add_argument("--match-id", required=True)
    feedback_parser.add_argument("--draft-id", required=True)
    feedback_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    feedback_parser.add_argument("--label", required=True)
    feedback_parser.set_defaults(handler=_handle_feedback)

    args = parser.parse_args(argv_list)
    return args.handler(args)


def _run_authorization(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="dating-boost",
        description="Local-first dating workflow copilot safety gate.",
    )
    parser.add_argument(
        "action",
        choices=[action.value for action in Action],
        help="Action to authorize before any harness executes it.",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Enable high-risk autonomous mode for this action after accepting the risks.",
    )
    args = parser.parse_args(argv)
    return _handle_authorize(args)


def _handle_authorize(args: argparse.Namespace) -> int:
    decision = authorize_action(
        Action(args.action),
        autonomous=args.autonomous,
    )

    _print_json(
        {
            "allowed": decision.allowed,
            "action": decision.action.value,
            "autonomous": decision.autonomous,
            "reason": decision.reason,
        }
    )
    return 0 if decision.allowed else 2


def _handle_init_profile(args: argparse.Namespace) -> int:
    data = _read_json_object(args.input)
    profile = _profile_from_dict(data)
    JsonMemoryRepository(args.data_dir).save_user_profile(profile)

    _print_json(
        {
            "status": "ok",
            "user_id": profile.user_id,
            "path": "user_profile.json",
        }
    )
    return 0


def _handle_import_observation(args: argparse.Namespace) -> int:
    observation = load_observation(args.input)
    return _persist_observation(args.data_dir, observation)


def _handle_observe_screenshot(args: argparse.Namespace) -> int:
    if not args.screenshot.exists():
        raise ValueError(f"screenshot does not exist: {args.screenshot}")
    observation = build_observation_from_screenshot_analysis(
        screenshot_path=args.screenshot,
        analysis=_read_json_object(args.analysis),
    )
    return _persist_observation(args.data_dir, observation)


def _persist_observation(data_dir: Path, observation: AppObservation) -> int:
    match_repo = MatchRepository(data_dir)
    identity = resolve_match_identity(observation, existing_matches=match_repo.list_match_candidates())
    _validate_storage_id(identity.match_id, "match_id")
    _validate_storage_id(observation.observation_id, "observation_id")

    ObservationRepository(data_dir).save_observation(identity.match_id, observation)
    match_repo.upsert_match_from_observation(
        match_id=identity.match_id,
        observation=observation,
        confidence=identity.confidence.value,
        requires_user_confirmation=identity.requires_user_confirmation,
    )
    if identity.requires_user_confirmation:
        match_repo.append_identity_confirmation(
            match_id=identity.match_id,
            observation_id=observation.observation_id,
            confidence=identity.confidence.value,
            reason=identity.reason,
        )

    _print_json(
        {
            "status": "ok",
            "match_id": identity.match_id,
            "confidence": identity.confidence.value,
            "requires_user_confirmation": identity.requires_user_confirmation,
            "observation_id": observation.observation_id,
        }
    )
    return 0


def _handle_draft(args: argparse.Namespace) -> int:
    repo = JsonMemoryRepository(args.data_dir)
    profile = repo.load_user_profile()
    reply_mode = ReplyMode(args.mode)
    backend = _select_backend(args)
    observation = ObservationRepository(args.data_dir).load_latest_observation(args.match_id)
    context_pack = _build_mvp_context_pack(profile, args.match_id, reply_mode, observation)
    draft = generate_reply(context_pack, reply_mode, backend)
    policy = evaluate_draft_content(draft, context_pack)

    if not policy.allowed:
        _print_json(
            {
                "status": "blocked",
                "match_id": args.match_id,
                "mode": reply_mode.value,
                "policy": _policy_to_dict(policy),
            }
        )
        return 2

    payload: dict[str, Any] = {
        "status": "ok",
        "match_id": args.match_id,
        "mode": reply_mode.value,
        "best_reply": draft.best_reply,
        "draft": _draft_to_dict(draft),
        "policy": _policy_to_dict(policy),
    }
    if args.debug_context:
        payload["context_pack"] = context_pack
    _print_json(payload)
    return 0


def _select_backend(args: argparse.Namespace) -> ModelBackend:
    backend_name = args.backend or ("scripted" if args.scripted_backend_output else "openai")
    if backend_name == "scripted":
        if args.scripted_backend_output is None:
            raise ValueError("--backend scripted requires --scripted-backend-output")
        return ScriptedBackend(_read_json_object(args.scripted_backend_output))
    if args.scripted_backend_output is not None:
        raise ValueError("--scripted-backend-output can only be used with --backend scripted")
    return OpenAIBackend(model=args.model)


def _handle_feedback(args: argparse.Namespace) -> int:
    event = create_feedback_event(
        event_id=f"feedback_{args.match_id}_{args.draft_id}_{args.label}",
        match_id=args.match_id,
        draft_id=args.draft_id,
        mode=ReplyMode(args.mode),
        label=args.label,
        created_at=MVP_TIMESTAMP,
    )
    JsonMemoryRepository(args.data_dir).append_feedback_event(args.match_id, event)

    _print_json(
        {
            "status": "ok",
            "match_id": args.match_id,
            "event_id": event["event_id"],
        }
    )
    return 0


def _build_mvp_context_pack(
    profile: UserProfile,
    match_id: str,
    reply_mode: ReplyMode,
    observation: AppObservation | None,
) -> dict[str, Any]:
    user_profile = _profile_to_context_dict(profile)
    if observation is None:
        match_profile = {
            "match_id": match_id,
            "conversation_hooks": [],
            "possible_interests": [],
        }
        conversation_memory = {
            "recent_messages": [],
            "open_threads": [],
            "commitments": [],
            "running_summary": "No imported observation was available for this match.",
        }
    else:
        match_profile = _match_profile_from_observation(match_id, observation)
        conversation_memory = _conversation_memory_from_observation(observation)

    return build_context_pack(
        user_profile=user_profile,
        match_profile=match_profile,
        conversation_memory=conversation_memory,
        reply_mode=reply_mode,
        max_items=None,
    )


def _match_profile_from_observation(match_id: str, observation: AppObservation) -> dict[str, Any]:
    profile = observation.profile_observation
    possible_interest_cues = [*profile.photo_cues, *profile.hook_candidates]
    return {
        "match_id": match_id,
        "display_name": observation.match_identity_hints.visible_name,
        "profile_text": profile.profile_text,
        "conversation_hooks": list(profile.hook_candidates),
        "possible_interests": [
            {"name": cue, "confidence": "medium"}
            for cue in possible_interest_cues
        ],
    }


def _conversation_memory_from_observation(observation: AppObservation) -> dict[str, Any]:
    conversation = observation.conversation_observation
    visible_messages = [dict(message) for message in conversation.visible_messages]
    return {
        "recent_messages": visible_messages,
        "open_threads": list(conversation.thread_cues),
        "commitments": [],
        "running_summary": _observation_summary(observation),
    }


def _observation_summary(observation: AppObservation) -> str:
    profile_text = observation.profile_observation.profile_text.strip()
    messages = observation.conversation_observation.visible_messages
    latest_message = messages[-1].get("text", "").strip() if messages else ""
    parts = [part for part in [profile_text, latest_message] if part]
    if parts:
        return " ".join(parts)
    return "Imported observation contained no visible conversation text."


def _profile_from_dict(data: dict[str, Any]) -> UserProfile:
    return UserProfile(
        schema_version=data["schema_version"],
        user_id=data["user_id"],
        facts=[MemoryItem.from_dict(item) for item in data["facts"]],
        preferences=[MemoryItem.from_dict(item) for item in data["preferences"]],
        boundaries=[MemoryItem.from_dict(item) for item in data["boundaries"]],
        style_examples=list(data["style_examples"]),
        goals=list(data["goals"]),
        persona_baseline=data["persona_baseline"],
        persona_range=list(data["persona_range"]),
        stance_range=list(data["stance_range"]),
        updated_at=data["updated_at"],
        default_reply_mode=ReplyMode(data.get("default_reply_mode", ReplyMode.ADAPTIVE.value)),
    )


def _profile_to_context_dict(profile: UserProfile) -> dict[str, Any]:
    return {
        "facts": [item.to_dict() for item in profile.facts],
        "preferences": [item.to_dict() for item in profile.preferences],
        "boundaries": [item.to_dict() for item in profile.boundaries],
        "style_examples": list(profile.style_examples),
        "goals": list(profile.goals),
        "persona_baseline": profile.persona_baseline,
        "persona_range": list(profile.persona_range),
        "stance_range": list(profile.stance_range),
    }


def _draft_to_dict(draft: DraftResponse) -> dict[str, Any]:
    data = asdict(draft)
    data["persona_divergence"] = draft.persona_divergence.value
    data["stance_divergence"] = draft.stance_divergence.value
    return data


def _policy_to_dict(policy: ContentPolicyDecision) -> dict[str, Any]:
    return {
        "allowed": policy.allowed,
        "severity": policy.severity,
        "reason": policy.reason,
        "requires_user_confirmation": policy.requires_user_confirmation,
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _validate_storage_id(value: str, label: str) -> None:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}: {value!r}")


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
