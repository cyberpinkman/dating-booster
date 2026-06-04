#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGE_PATH = SKILL_DIR / "skill-package.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Dating Booster Codex skill compatibility.")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--package", type=Path, default=PACKAGE_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    package = _read_json(args.package)
    cli_command = str(package.get("cli_command") or "dating-boost")
    cli_path = shutil.which(cli_command)
    if cli_path is None:
        _print_json(
            {
                "schema_version": 1,
                "status": "needs_bootstrap",
                "skill_version": package.get("package_version"),
                "cli_found": False,
                "cli_version": None,
                "capabilities_ok": False,
                "missing_commands": list(package.get("required_commands", [])),
                "schema_mismatches": [],
                "data_dir": str(args.data_dir.resolve()),
                "warnings": [f"{cli_command} was not found on PATH"],
                "next_action": "bootstrap_cli",
            }
        )
        return 2

    result = subprocess.run(
        [cli_command, "skill", "doctor", "--package", str(args.package), "--data-dir", str(args.data_dir), "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    else:
        _print_json(
            {
                "schema_version": 1,
                "status": "error",
                "skill_version": package.get("package_version"),
                "cli_found": True,
                "cli_version": None,
                "capabilities_ok": False,
                "missing_commands": [],
                "schema_mismatches": [],
                "data_dir": str(args.data_dir.resolve()),
                "warnings": [],
                "next_action": "stop",
                "reason": result.stderr.strip() or "doctor command produced no JSON",
            }
        )
    return result.returncode


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
