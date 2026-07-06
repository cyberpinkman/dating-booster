from __future__ import annotations

import sys
from typing import Any

from dating_boost import cli_harness as _cli_harness
from dating_boost import cli_memory as _cli_memory
from dating_boost import cli_ops as _cli_ops
from dating_boost import cli_sessions as _cli_sessions
from dating_boost.cli_parser import build_parser

Action = _cli_ops.Action
SUPPORTED_NATIVE_HARNESS_APPS = _cli_ops.SUPPORTED_NATIVE_HARNESS_APPS
SUPPORTED_MANAGED_SESSION_APPS = _cli_ops.SUPPORTED_MANAGED_SESSION_APPS

_COMPAT_MODULES = (_cli_sessions, _cli_memory, _cli_harness, _cli_ops)

__all__ = [
    "Action",
    "SUPPORTED_MANAGED_SESSION_APPS",
    "SUPPORTED_NATIVE_HARNESS_APPS",
    "main",
    "_print_json",
]


def __getattr__(name: str) -> Any:
    for module in _COMPAT_MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main(argv: list[str] | None = None) -> int:
    argv_list = None if argv is None else list(argv)
    command_tokens = sys.argv[1:] if argv is None else argv_list
    cli_module = sys.modules[__name__]
    if command_tokens and command_tokens[0] in {action.value for action in Action}:
        return getattr(cli_module, "_run_authorization")(command_tokens)
    unsupported_harness_payload = getattr(cli_module, "_unsupported_harness_app_argv_payload")(command_tokens)
    if unsupported_harness_payload is not None:
        getattr(cli_module, "_print_json")(unsupported_harness_payload)
        return 2

    parser = build_parser(cli_module)
    args = parser.parse_args(argv_list)
    return getattr(cli_module, "_run_handler_with_support_logging")(args, command_tokens)


def _print_json(data: dict[str, Any]) -> None:
    _cli_ops._print_json(data)


if __name__ == "__main__":
    raise SystemExit(main())
