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
    parser = argparse.ArgumentParser(description="Install or upgrade the local dating-boost CLI.")
    parser.add_argument("--package", type=Path, default=PACKAGE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    package = _read_json(args.package)
    source_repo = _required(package, "source_repo")
    source_ref = _required(package, "source_ref")
    cli_command = str(package.get("cli_command") or "dating-boost")
    package_spec = f"git+https://github.com/{source_repo}.git@{source_ref}"
    command = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", package_spec]

    if args.dry_run:
        _print_json(
            {
                "schema_version": 1,
                "status": "dry_run",
                "install_command": command,
                "cli_command": cli_command,
            }
        )
        return 0

    result = subprocess.run(command, check=False, capture_output=True, text=True)
    cli_path = shutil.which(cli_command)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "ok" if result.returncode == 0 and cli_path else "error",
        "install_command": command,
        "returncode": result.returncode,
        "cli_command": cli_command,
        "cli_path": cli_path,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
        "warnings": [],
    }
    if result.returncode == 0 and cli_path is None:
        payload["warnings"].append(
            f"{cli_command} installed but is not on PATH. Add the Python user scripts directory to PATH."
        )
    _print_json(payload)
    return 0 if payload["status"] == "ok" else 2


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"skill-package.json missing {key}")
    return value


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
