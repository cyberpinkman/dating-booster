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
from dating_boost.core.repositories import JsonMemoryRepository
from dating_boost.core.storage import JsonStorage
from dating_boost.intelligence.backends import ScriptedBackend
from dating_boost.intelligence.reply_generator import DraftResponse, generate_reply
from dating_boost.perception.fixture_loader import load_observation
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

    draft_parser = subparsers.add_parser("draft", help="Generate a local scripted reply draft.")
    draft_parser.add_argument("--data-dir", required=True, type=Path)
    draft_parser.add_argument("--match-id", required=True)
    draft_parser.add_argument("--mode", required=True, choices=[mode.value for mode in ReplyMode])
    draft_parser.add_argument("--scripted-backend-output", required=True, type=Path)
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
    identity = resolve_match_identity(observation, existing_matches=[])
    _validate_storage_id(identity.match_id, "match_id")
    _validate_storage_id(observation.observation_id, "observation_id")

    storage = JsonStorage(args.data_dir)
    observation_path = (
        Path("matches") / identity.match_id / "observations" / f"{observation.observation_id}.json"
    )
    storage.write_json(observation_path, observation.to_dict())

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
    backend_payload = _read_json_object(args.scripted_backend_output)
    context_pack = _build_mvp_context_pack(profile, args.match_id, reply_mode)
    draft = generate_reply(context_pack, reply_mode, ScriptedBackend(backend_payload))
    policy = evaluate_draft_content(draft, context_pack)

    _print_json(
        {
            "status": "ok",
            "match_id": args.match_id,
            "mode": reply_mode.value,
            "best_reply": draft.best_reply,
            "draft": _draft_to_dict(draft),
            "policy": _policy_to_dict(policy),
        }
    )
    return 0


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


def _build_mvp_context_pack(profile: UserProfile, match_id: str, reply_mode: ReplyMode) -> dict[str, Any]:
    user_profile = _profile_to_context_dict(profile)
    match_profile = {
        "match_id": match_id,
        "conversation_hooks": ["live music"],
        "possible_interests": [{"name": "live music", "confidence": "medium"}],
    }
    conversation_memory = {
        "recent_messages": [
            {"sender": "match", "text": "What are you up to this weekend?"},
        ],
        "open_threads": ["weekend plans"],
        "commitments": [],
        "running_summary": "A light dating-app chat with an opening for curiosity.",
    }
    return build_context_pack(
        user_profile=user_profile,
        match_profile=match_profile,
        conversation_memory=conversation_memory,
        reply_mode=reply_mode,
        max_items=None,
    )


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
