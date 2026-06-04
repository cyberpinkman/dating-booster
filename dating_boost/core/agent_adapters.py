from __future__ import annotations

from contextlib import nullcontext
from importlib import resources
import json
import tempfile
from pathlib import Path
from typing import Any, ContextManager

from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.skill_doctor import run_skill_doctor


ROOT = Path(__file__).resolve().parents[2]
SOURCE_AGENT_ADAPTERS_DIR = ROOT / "agent_adapters"
SOURCE_CODEX_SKILL_DIR = ROOT / "skills" / "dating-booster-codex"
SOURCE_CLAUDE_CODE_ADAPTER_DIR = SOURCE_AGENT_ADAPTERS_DIR / "claude-code"
SOURCE_OPENCLAW_ADAPTER_DIR = SOURCE_AGENT_ADAPTERS_DIR / "openclaw"
SOURCE_SHARED_REFERENCES_DIR = SOURCE_AGENT_ADAPTERS_DIR / "shared" / "references"
PACKAGED_AGENT_ADAPTERS_DIR = resources.files("dating_boost.resources").joinpath("agent_adapters")


def install_claude_code_adapter(*, scope: str, target: Path | None, dry_run: bool) -> dict[str, Any]:
    target_path = _claude_skill_target_path(scope=scope, target=target)
    planned_files = _claude_install_files(target_path)
    adapter_root = _claude_code_adapter_dir()
    payload = {
        "schema_version": 1,
        "status": "dry_run" if dry_run else "ok",
        "target_host": "claude_code",
        "scope": scope,
        "target_path": str(target_path),
        "source_path": str(adapter_root.joinpath("skills", "dating-booster")),
        "adapter_package": _display_resource_path(_claude_code_adapter_package()),
        "files": [
            {
                "source": str(source),
                "target": str(destination),
            }
            for source, destination in planned_files
        ],
        "next_action": "run dating-boost adapter claude-code doctor --data-dir .local/dating-boost --json",
    }
    if dry_run:
        return payload

    for source, destination in planned_files:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return payload


def install_openclaw_adapter(
    *,
    scope: str,
    target: Path | None,
    dry_run: bool,
    target_host: str = "openclaw",
) -> dict[str, Any]:
    compatibility_target = "openclaw"
    target_path = _openclaw_skill_target_path(scope=scope, target=target)
    planned_files = _openclaw_install_files(target_path)
    adapter_root = _openclaw_adapter_dir()
    payload = {
        "schema_version": 1,
        "status": "dry_run" if dry_run else "ok",
        "target_host": target_host,
        "compatibility_target": compatibility_target,
        "compatibility_mode": "openclaw_skill",
        "scope": scope,
        "target_path": str(target_path),
        "source_path": str(adapter_root.joinpath("skills", "dating-booster")),
        "adapter_package": _display_resource_path(_openclaw_adapter_package()),
        "files": [
            {
                "source": str(source),
                "target": str(destination),
            }
            for source, destination in planned_files
        ],
        "next_action": (
            f"run dating-boost adapter {target_host} doctor --data-dir .local/dating-boost --json"
        ),
    }
    if dry_run:
        return payload

    for source, destination in planned_files:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return payload


def install_codex_adapter(*, scope: str, target: Path | None, dry_run: bool) -> dict[str, Any]:
    target_path = _codex_skill_target_path(scope=scope, target=target)
    planned_files = _codex_install_files(target_path)
    skill_root = _codex_skill_dir()
    payload = {
        "schema_version": 1,
        "status": "dry_run" if dry_run else "ok",
        "target_host": "codex",
        "scope": scope,
        "target_path": str(target_path),
        "source_path": str(skill_root),
        "adapter_package": _display_resource_path(_codex_skill_package()),
        "files": [
            {
                "source": str(source),
                "target": str(destination),
            }
            for source, destination in planned_files
        ],
        "next_action": "run dating-boost adapter codex doctor --data-dir .local/dating-boost --json",
    }
    if dry_run:
        return payload

    for source, destination in planned_files:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return payload


def run_openclaw_adapter_doctor(data_dir: Path, *, target_host: str = "openclaw") -> dict[str, Any]:
    package_source = _openclaw_adapter_package()
    with _adapter_package_path(package_source) as package_path:
        skill_doctor = run_skill_doctor(package_path, data_dir)
    capabilities = build_capabilities(data_dir)
    agent_caps = capabilities.get("agent_native_capabilities") or {}
    package_target_host = _adapter_target_host(package_source)
    issues: list[str] = []

    if target_host not in {"openclaw", "hermes"}:
        issues.append("unsupported_target_host")
    if package_target_host != "openclaw":
        issues.append("target_host_mismatch")
    if skill_doctor.get("status") != "ok":
        issues.append("skill_doctor_failed")
    if agent_caps.get("openclaw_adapter") is not True:
        issues.append("openclaw_adapter_capability_missing")
    if "openclaw" not in set(agent_caps.get("host_agent_adapters") or []):
        issues.append("host_agent_adapter_missing")
    if target_host == "hermes":
        if agent_caps.get("hermes_openclaw_compatible_adapter") is not True:
            issues.append("hermes_openclaw_compatible_adapter_capability_missing")
        if "hermes" not in set(agent_caps.get("host_agent_adapters") or []):
            issues.append("hermes_host_agent_adapter_missing")

    status = "ok" if not issues else "blocked"
    return {
        "schema_version": 1,
        "status": status,
        "target_host": target_host,
        "compatibility_target": "openclaw",
        "compatibility_mode": "openclaw_skill",
        "adapter_package": _display_resource_path(package_source),
        "data_dir": str(data_dir.resolve()),
        "skill_doctor": skill_doctor,
        "issues": issues,
        "capabilities": {
            "tool_version": capabilities.get("tool_version"),
            "git_commit": capabilities.get("git_commit"),
            "host_agent_adapters": agent_caps.get("host_agent_adapters"),
            "supported_app_profiles": agent_caps.get("supported_app_profiles"),
            "openclaw_adapter": agent_caps.get("openclaw_adapter"),
            "hermes_openclaw_compatible_adapter": agent_caps.get(
                "hermes_openclaw_compatible_adapter"
            ),
        },
        "next_action": "ready" if status == "ok" else "stop",
    }


def run_claude_code_adapter_doctor(data_dir: Path) -> dict[str, Any]:
    package_source = _claude_code_adapter_package()
    with _adapter_package_path(package_source) as package_path:
        skill_doctor = run_skill_doctor(package_path, data_dir)
    capabilities = build_capabilities(data_dir)
    agent_caps = capabilities.get("agent_native_capabilities") or {}
    target_host = _adapter_target_host(package_source)
    issues: list[str] = []

    if target_host != "claude_code":
        issues.append("target_host_mismatch")
    if skill_doctor.get("status") != "ok":
        issues.append("skill_doctor_failed")
    if agent_caps.get("claude_code_adapter") is not True:
        issues.append("claude_code_adapter_capability_missing")
    if "claude_code" not in set(agent_caps.get("host_agent_adapters") or []):
        issues.append("host_agent_adapter_missing")

    status = "ok" if not issues else "blocked"
    return {
        "schema_version": 1,
        "status": status,
        "target_host": "claude_code",
        "adapter_package": _display_resource_path(package_source),
        "data_dir": str(data_dir.resolve()),
        "skill_doctor": skill_doctor,
        "issues": issues,
        "capabilities": {
            "tool_version": capabilities.get("tool_version"),
            "git_commit": capabilities.get("git_commit"),
            "host_agent_adapters": agent_caps.get("host_agent_adapters"),
            "supported_app_profiles": agent_caps.get("supported_app_profiles"),
            "claude_code_adapter": agent_caps.get("claude_code_adapter"),
        },
        "next_action": "ready" if status == "ok" else "stop",
    }


def run_codex_adapter_doctor(data_dir: Path) -> dict[str, Any]:
    package_source = _codex_skill_package()
    with _adapter_package_path(package_source) as package_path:
        skill_doctor = run_skill_doctor(package_path, data_dir)
    capabilities = build_capabilities(data_dir)
    agent_caps = capabilities.get("agent_native_capabilities") or {}
    target_host = _adapter_target_host(package_source)
    issues: list[str] = []

    if target_host != "codex":
        issues.append("target_host_mismatch")
    if skill_doctor.get("status") != "ok":
        issues.append("skill_doctor_failed")
    if agent_caps.get("codex_skill") is not True:
        issues.append("codex_skill_capability_missing")
    if "codex" not in set(agent_caps.get("host_agent_adapters") or []):
        issues.append("host_agent_adapter_missing")

    status = "ok" if not issues else "blocked"
    return {
        "schema_version": 1,
        "status": status,
        "target_host": "codex",
        "adapter_package": _display_resource_path(package_source),
        "data_dir": str(data_dir.resolve()),
        "skill_doctor": skill_doctor,
        "issues": issues,
        "capabilities": {
            "tool_version": capabilities.get("tool_version"),
            "git_commit": capabilities.get("git_commit"),
            "host_agent_adapters": agent_caps.get("host_agent_adapters"),
            "supported_app_profiles": agent_caps.get("supported_app_profiles"),
            "codex_skill": agent_caps.get("codex_skill"),
        },
        "next_action": "ready" if status == "ok" else "stop",
    }


def _claude_skill_target_path(*, scope: str, target: Path | None) -> Path:
    if target is None:
        base = Path.cwd() if scope == "project" else Path.home()
    else:
        base = target
    base = base.expanduser().absolute()
    if scope == "user" and base.name == ".claude":
        return base / "skills" / "dating-booster"
    return base / ".claude" / "skills" / "dating-booster"


def _codex_skill_target_path(*, scope: str, target: Path | None) -> Path:
    if target is None:
        base = Path.cwd() if scope == "project" else Path(
            str(_codex_home())
        )
    else:
        base = target
    base = base.expanduser().absolute()
    if base.name == ".codex":
        return base / "skills" / "dating-booster-codex"
    return base / ".codex" / "skills" / "dating-booster-codex"


def _openclaw_skill_target_path(*, scope: str, target: Path | None) -> Path:
    if target is None:
        base = Path.cwd() if scope == "project" else Path.home()
    else:
        base = target
    base = base.expanduser().absolute()
    if base.name == ".openclaw":
        return base / "skills" / "dating-booster"
    return base / ".openclaw" / "skills" / "dating-booster"


def _claude_install_files(target_path: Path) -> list[tuple[Any, Path]]:
    adapter_root = _claude_code_adapter_dir()
    shared_references = _shared_references_dir()
    return [
        (adapter_root.joinpath("skills", "dating-booster", "SKILL.md"), target_path / "SKILL.md"),
        (adapter_root.joinpath("adapter-package.json"), target_path / "adapter-package.json"),
        (adapter_root.joinpath("README.md"), target_path / "README.md"),
        (adapter_root.joinpath("INSTALL.md"), target_path / "INSTALL.md"),
        (shared_references.joinpath("contracts.md"), target_path / "references" / "contracts.md"),
        (shared_references.joinpath("workflows.md"), target_path / "references" / "workflows.md"),
    ]


def _openclaw_install_files(target_path: Path) -> list[tuple[Any, Path]]:
    adapter_root = _openclaw_adapter_dir()
    shared_references = _shared_references_dir()
    return [
        (adapter_root.joinpath("skills", "dating-booster", "SKILL.md"), target_path / "SKILL.md"),
        (adapter_root.joinpath("adapter-package.json"), target_path / "adapter-package.json"),
        (adapter_root.joinpath("README.md"), target_path / "README.md"),
        (adapter_root.joinpath("INSTALL.md"), target_path / "INSTALL.md"),
        (shared_references.joinpath("contracts.md"), target_path / "references" / "contracts.md"),
        (shared_references.joinpath("workflows.md"), target_path / "references" / "workflows.md"),
    ]


def _codex_install_files(target_path: Path) -> list[tuple[Any, Path]]:
    skill_root = _codex_skill_dir()
    return [
        (source, target_path / relative_path)
        for source, relative_path in _resource_tree_files(skill_root)
    ]


def _claude_code_adapter_dir() -> Any:
    if (SOURCE_CLAUDE_CODE_ADAPTER_DIR / "adapter-package.json").exists():
        return SOURCE_CLAUDE_CODE_ADAPTER_DIR
    return PACKAGED_AGENT_ADAPTERS_DIR.joinpath("claude-code")


def _openclaw_adapter_dir() -> Any:
    if (SOURCE_OPENCLAW_ADAPTER_DIR / "adapter-package.json").exists():
        return SOURCE_OPENCLAW_ADAPTER_DIR
    return PACKAGED_AGENT_ADAPTERS_DIR.joinpath("openclaw")


def _codex_skill_dir() -> Any:
    if (SOURCE_CODEX_SKILL_DIR / "skill-package.json").exists():
        return SOURCE_CODEX_SKILL_DIR
    return PACKAGED_AGENT_ADAPTERS_DIR.joinpath("codex", "dating-booster-codex")


def _shared_references_dir() -> Any:
    if (SOURCE_SHARED_REFERENCES_DIR / "contracts.md").exists():
        return SOURCE_SHARED_REFERENCES_DIR
    return PACKAGED_AGENT_ADAPTERS_DIR.joinpath("shared", "references")


def _claude_code_adapter_package() -> Any:
    return _claude_code_adapter_dir().joinpath("adapter-package.json")


def _openclaw_adapter_package() -> Any:
    return _openclaw_adapter_dir().joinpath("adapter-package.json")


def _codex_skill_package() -> Any:
    return _codex_skill_dir().joinpath("skill-package.json")


def _codex_home() -> Path:
    import os

    value = os.environ.get("CODEX_HOME")
    return Path(value).expanduser() if value else Path.home() / ".codex"


def _resource_tree_files(root: Any, relative_root: Path | None = None) -> list[tuple[Any, Path]]:
    relative_root = relative_root or Path()
    files: list[tuple[Any, Path]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if child.name == "__pycache__" or child.name.endswith(".pyc"):
            continue
        relative_path = relative_root / child.name
        if child.is_dir():
            files.extend(_resource_tree_files(child, relative_path))
        else:
            files.append((child, relative_path))
    return files


def _adapter_package_path(package_source: Any) -> ContextManager[Path]:
    if isinstance(package_source, Path) and package_source.exists():
        return nullcontext(package_source)

    temp_dir = tempfile.TemporaryDirectory()
    package_path = Path(temp_dir.name) / "adapter-package.json"
    package_path.write_bytes(package_source.read_bytes())
    return _TemporaryPackagePath(temp_dir, package_path)


class _TemporaryPackagePath:
    def __init__(self, temp_dir: tempfile.TemporaryDirectory[str], package_path: Path):
        self._temp_dir = temp_dir
        self._package_path = package_path

    def __enter__(self) -> Path:
        return self._package_path

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._temp_dir.cleanup()


def _adapter_target_host(package_source: Any) -> str | None:
    try:
        payload = json.loads(package_source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    target_host = payload.get("target_host")
    return str(target_host) if target_host is not None else None


def _display_resource_path(resource: Any) -> str:
    if isinstance(resource, Path):
        return str(resource.resolve())
    return str(resource)
