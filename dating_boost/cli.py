from __future__ import annotations

import argparse
import json

from dating_boost.policy import Action, authorize_action


def main(argv: list[str] | None = None) -> int:
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
    decision = authorize_action(
        Action(args.action),
        autonomous=args.autonomous,
    )

    print(
        json.dumps(
            {
                "allowed": decision.allowed,
                "action": decision.action.value,
                "autonomous": decision.autonomous,
                "reason": decision.reason,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if decision.allowed else 2


if __name__ == "__main__":
    raise SystemExit(main())
