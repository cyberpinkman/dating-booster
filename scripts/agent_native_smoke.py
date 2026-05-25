#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "intelligence"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the agent-native Dating Booster fixture workflow end to end.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Local Dating Booster data directory. Defaults to a temporary directory.",
    )
    args = parser.parse_args(argv)

    if args.data_dir is None:
        with tempfile.TemporaryDirectory(prefix="dating-boost-smoke-") as temp_dir:
            return _run_smoke(Path(temp_dir) / "data")
    return _run_smoke(args.data_dir)


def _run_smoke(data_dir: Path) -> int:
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    commands: dict[str, int] = {}

    capabilities = _run_cli(
        "capabilities",
        "--json",
        "--data-dir",
        str(data_dir),
        command_key="capabilities",
        commands=commands,
    )
    _run_cli(
        "init-profile",
        "--data-dir",
        str(data_dir),
        "--input",
        str(FIXTURE_DIR / "user_profile.json"),
        command_key="init_profile",
        commands=commands,
    )
    ingest = _run_cli(
        "memory",
        "ingest-observation",
        "--data-dir",
        str(data_dir),
        "--input",
        str(FIXTURE_DIR / "app_observation_chat.json"),
        command_key="memory_ingest_observation",
        commands=commands,
    )
    match_id = str(ingest["match_id"])
    _run_cli(
        "memory",
        "get-match",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        command_key="memory_get_match",
        commands=commands,
    )
    context = _run_cli(
        "context",
        "build",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        "--mode",
        "adaptive",
        command_key="context_build",
        commands=commands,
    )
    context_path = data_dir / "context.json"
    _write_json(context_path, context)

    host_draft = _read_json(FIXTURE_DIR / "scripted_reply.json")
    draft_path = data_dir / "host_draft.json"
    _write_json(draft_path, host_draft)
    _run_cli(
        "policy",
        "check-draft",
        "--input",
        str(draft_path),
        "--context",
        str(context_path),
        command_key="policy_check_draft",
        commands=commands,
    )
    _run_cli(
        "policy",
        "check-action",
        "paste_draft",
        command_key="policy_check_action",
        commands=commands,
    )

    action_result_path = data_dir / "action_result.json"
    _write_json(
        action_result_path,
        {
            "action": "paste_draft",
            "target_match_id": match_id,
            "payload_hash": _payload_hash(host_draft),
            "pre_action_observation_id": "obs_chat_001",
            "post_action_observation_id": "obs_chat_001",
            "result_status": "succeeded",
            "evidence": {
                "verification": "Fixture smoke test records host paste-draft success.",
            },
        },
    )
    _run_cli(
        "action",
        "record-result",
        "--data-dir",
        str(data_dir),
        "--input",
        str(action_result_path),
        command_key="action_record_result",
        commands=commands,
    )
    _run_cli(
        "feedback",
        "record",
        "--data-dir",
        str(data_dir),
        "--match-id",
        match_id,
        "--draft-id",
        "smoke_draft_1",
        "--mode",
        "adaptive",
        "--label",
        "accepted",
        command_key="feedback_record",
        commands=commands,
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "data_dir": str(data_dir),
                "match_id": match_id,
                "tool_version": capabilities["tool_version"],
                "commands": commands,
                "artifacts": {
                    "context": str(context_path),
                    "host_draft": str(draft_path),
                    "action_result": str(action_result_path),
                    "action_audit": str(data_dir / "audit" / "action_results.jsonl"),
                    "feedback": str(data_dir / "matches" / match_id / "feedback_events.jsonl"),
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _run_cli(*args: str, command_key: str, commands: dict[str, int]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "dating_boost.cli", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    commands[command_key] = result.returncode
    if result.returncode != 0:
        raise RuntimeError(
            f"dating-boost {' '.join(args)} failed with exit {result.returncode}: {result.stderr or result.stdout}"
        )
    return json.loads(result.stdout)


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
