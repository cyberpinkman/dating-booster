#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dating_boost.apps.tashuo.standalone_production_artifacts import validate_production_artifact
from dating_boost.apps.tashuo.standalone_production_runner import (
    ProductionQualificationRunner,
    RunnerBlocked,
)


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TaShuo standalone stage-only production qualification gate.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    canary = subparsers.add_parser("canary")
    _root_argument(canary)
    canary.add_argument("--user-model-source-data-dir", type=Path, required=True)
    canary.add_argument("--authorization", type=Path, required=True)
    _built_artifact_argument(canary)
    _json_argument(canary)

    soak = subparsers.add_parser("soak")
    _root_argument(soak)
    _qualification_argument(soak)
    soak.add_argument("--accept-canary", required=True)
    soak.add_argument("--authorization", type=Path, required=True)
    _built_artifact_argument(soak)
    _json_argument(soak)

    status = subparsers.add_parser("status")
    _root_argument(status)
    status.add_argument("--qualification-id")
    _json_argument(status)

    resume = subparsers.add_parser("resume")
    _root_argument(resume)
    _qualification_argument(resume)
    resume.add_argument("--authorization", type=Path, required=True)
    _built_artifact_argument(resume)
    _json_argument(resume)

    finalize = subparsers.add_parser("finalize")
    _root_argument(finalize)
    _qualification_argument(finalize)
    _json_argument(finalize)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--bundle", type=Path, required=True)
    _json_argument(validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    _load_env_file(ROOT / ".env")
    args = build_parser().parse_args(argv)
    try:
        payload = _dispatch(args)
    except RunnerBlocked as exc:
        payload = _blocked(str(exc))
    except Exception as exc:
        payload = _blocked(_safe_reason(exc))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if _successful(args.command, payload) else 2


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "validate":
        return validate_production_artifact(args.bundle)
    runner = ProductionQualificationRunner(
        root_dir=args.root_dir,
        source_checkout=ROOT,
        built_artifact=getattr(args, "built_artifact", None),
    )
    if args.command != "status":
        janitor = runner.janitor()
        if janitor.get("status") != "ok":
            return _blocked("root_janitor_failed")
    if args.command == "canary":
        return runner.canary(
            user_model_source_data_dir=args.user_model_source_data_dir,
            authorization_path=args.authorization,
        )
    if args.command == "soak":
        return runner.soak(
            qualification_id=args.qualification_id,
            accept_canary=args.accept_canary,
            authorization_path=args.authorization,
        )
    if args.command == "status":
        return runner.status(qualification_id=args.qualification_id)
    if args.command == "resume":
        return runner.resume(
            qualification_id=args.qualification_id,
            authorization_path=args.authorization,
        )
    if args.command == "finalize":
        return runner.finalize(qualification_id=args.qualification_id)
    return _blocked("unsupported_command")


def _root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-dir", type=Path, required=True)


def _qualification_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--qualification-id", required=True)


def _built_artifact_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--built-artifact", type=Path)


def _json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true")


def _load_env_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _successful(command: str, payload: dict[str, Any]) -> bool:
    if command == "validate":
        return payload.get("artifact_valid") is True
    if command == "status":
        return payload.get("status") in {
            "ok",
            "created",
            "preflight_passed",
            "canary_running",
            "canary_passed",
            "soak_running",
            "protocol_passed",
            "blocked_finalized",
            "expired_finalized",
            "finalization_failed",
            "qualification_expired_pending_cleanup",
            "recovery_required",
        }
    return payload.get("status") in {"canary_passed", "protocol_passed", "resumed"}


def _safe_reason(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason:
        return reason
    return type(exc).__name__


def _blocked(reason: str) -> dict[str, Any]:
    return {"schema_version": 1, "status": "blocked", "reason": reason}


if __name__ == "__main__":
    raise SystemExit(main())
