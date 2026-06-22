#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dating_boost.core.tashuo_standalone_alpha_gate import evaluate_alpha_gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check TaShuo standalone stage-only alpha release gate evidence.")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--smoke-json", required=True, help="Path to smoke JSON output, or '-' for stdin.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    smoke_payload = _read_smoke_json(args.smoke_json)
    payload = evaluate_alpha_gate(smoke_payload, data_dir=args.data_dir)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: {payload['reason']}")
    return 0 if payload["status"] == "ok" else 2


def _read_smoke_json(path: str) -> dict[str, Any]:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("smoke JSON must be an object")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
