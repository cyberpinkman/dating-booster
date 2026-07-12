from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tashuo_mac_ios_standalone_production_gate.py"


def _module():
    spec = importlib.util.spec_from_file_location("tashuo_production_gate_cli", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_exposes_exactly_six_fixed_protocol_commands():
    parser = _module().build_parser()
    subparser_action = next(action for action in parser._actions if getattr(action, "choices", None))

    assert set(subparser_action.choices) == {"canary", "soak", "status", "resume", "finalize", "validate"}


@pytest.mark.parametrize(
    "flag",
    (
        "--cycle-count",
        "--soak-duration",
        "--attempt-timeout",
        "--selection-timeout",
        "--retry-delay",
        "--fake-clock",
    ),
)
def test_cli_does_not_expose_protocol_reduction_flags(flag, tmp_path):
    parser = _module().build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["status", "--root-dir", str(tmp_path), flag, "1"])


def test_root_status_is_read_only_and_discovers_empty_root_without_gui(tmp_path):
    module = _module()
    root = tmp_path / "missing-root"
    args = module.build_parser().parse_args(["status", "--root-dir", str(root), "--json"])

    payload = module._dispatch(args)

    assert payload == {"schema_version": 1, "status": "ok", "qualifications": []}
    assert not root.exists()
