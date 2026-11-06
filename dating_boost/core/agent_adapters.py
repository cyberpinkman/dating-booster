from __future__ import annotations

from contextlib import nullcontext
from importlib import resources
import json
import shlex
import stat
import shutil
import tempfile
from pathlib import Path
from typing import Any, ContextManager

from dating_boost.core.capabilities import build_capabilities
from dating_boost.core.live_send_contract import managed_live_send_guidance
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
    doctor = _doctor_arguments("claude-code", scope, target)
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
        "next_action": f"run dating-boost {doctor}",
        "startup_commands": [
            f"python3 -m dating_boost.cli {doctor}",
            "python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost",
        ],
        "managed_live_send_guidance": managed_live_send_guidance(),
    }
    if dry_run:
        return payload

    _write_clean_install(target_path, planned_files)
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
    doctor = _doctor_arguments(target_host, scope, target)
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
        "next_action": f"run dating-boost {doctor}",
        "startup_commands": [
            f"python3 -m dating_boost.cli {doctor}",
            "python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost",
        ],
        "managed_live_send_guidance": managed_live_send_guidance(),
    }
    if dry_run:
        return payload

    _write_clean_install(target_path, planned_files)
    return payload


def install_codex_adapter(*, scope: str, target: Path | None, dry_run: bool) -> dict[str, Any]:
    target_path = _codex_skill_target_path(scope=scope, target=target)
    planned_files = _codex_install_files(target_path)
    skill_root = _codex_skill_dir()
    doctor = _doctor_arguments("codex", scope, target)
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
        "next_action": f"run dating-boost {doctor}",
        "startup_commands": [
            f"python3 -m dating_boost.cli {doctor}",
            "python3 -m dating_boost.cli capabilities --json --data-dir .local/dating-boost",
        ],
        "managed_live_send_guidance": managed_live_send_guidance(),
    }
    if dry_run:
        return payload

    _write_clean_install(target_path, planned_files)
    return payload


def _doctor_arguments(host: str, scope: str, target: Path | None) -> str:
    args = ["adapter", host, "doctor", "--scope", scope]
    if target is not None or scope == "project":
        base = target.expanduser().absolute() if target is not None else Path.cwd()
        args.extend(["--target", str(base)])
    return shlex.join([*args, "--data-dir", ".local/dating-boost", "--json"])


def _write_clean_install(target_path: Path, planned_files: list[tuple[Any, Path]]) -> None:
    if target_path.exists():
        shutil.rmtree(target_path)
    for source, destination in planned_files:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())


def run_openclaw_adapter_doctor(
    data_dir: Path, *, target_host: str = "openclaw", scope: str = "project", target: Path | None = None,
) -> dict[str, Any]:
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

    target_path = _openclaw_skill_target_path(scope=scope, target=target)
    installation = _inspect_installation(target_path, _openclaw_install_files(target_path))
    if installation["status"] != "ok":
        issues.append("adapter_installation_" + installation["status"])
    status = "ok" if not issues else "blocked"
    return {
        "schema_version": 1,
        "status": status,
        "target_host": target_host,
        "compatibility_target": "openclaw",
        "compatibility_mode": "openclaw_skill",
        "adapter_package": _display_resource_path(package_source),
        "scope": scope,
        "target_path": str(target_path),
        "installation": installation,
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
        "managed_live_send_guidance": managed_live_send_guidance(),
        "next_action": "ready" if status == "ok" else "stop",
    }


def run_claude_code_adapter_doctor(
    data_dir: Path, *, scope: str = "project", target: Path | None = None,
) -> dict[str, Any]:
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

    target_path = _claude_skill_target_path(scope=scope, target=target)
    installation = _inspect_installation(target_path, _claude_install_files(target_path))
    if installation["status"] != "ok":
        issues.append("adapter_installation_" + installation["status"])
    status = "ok" if not issues else "blocked"
    return {
        "schema_version": 1,
        "status": status,
        "target_host": "claude_code",
        "adapter_package": _display_resource_path(package_source),
        "scope": scope,
        "target_path": str(target_path),
        "installation": installation,
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
        "managed_live_send_guidance": managed_live_send_guidance(),
        "next_action": "ready" if status == "ok" else "stop",
    }


def run_codex_adapter_doctor(
    data_dir: Path, *, scope: str = "user", target: Path | None = None,
) -> dict[str, Any]:
    report = check_codex_adapter_package(data_dir)
    target_path = _codex_skill_target_path(scope=scope, target=target)
    installation = _inspect_installation(target_path, _codex_install_files(target_path))
    report.update(scope=scope, target_path=str(target_path), installation=installation)
    if installation["status"] != "ok":
        report["issues"].append("adapter_installation_" + installation["status"])
        report.update(status="blocked", next_action="stop")
    return report


def check_codex_adapter_package(data_dir: Path) -> dict[str, Any]:
    """Check the distribution's skill contract used by both host and standalone preflight."""
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
        "managed_live_send_guidance": managed_live_send_guidance(),
        "next_action": "ready" if status == "ok" else "stop",
    }


def _ignored_install_entry(name: str) -> bool:
    return name in {"__pycache__", ".DS_Store"} or name.endswith(".pyc")


def _inspect_installation(target: Path, planned_files: list[tuple[Any, Path]]) -> dict[str, Any]:
    expected = {destination.relative_to(target).as_posix(): source for source, destination in planned_files}
    seen: set[str] = set()
    changed: list[str] = []
    unreadable: list[str] = []
    extra: list[str] = []
    status = "ok"

    def inspect_directory(directory: Path) -> None:
        try:
            entries = list(directory.iterdir())
        except OSError:
            unreadable.append(directory.relative_to(target).as_posix())
            return
        for entry in entries:
            if _ignored_install_entry(entry.name):
                continue
            relative = entry.relative_to(target).as_posix()
            try:
                mode = entry.lstat().st_mode
                if stat.S_ISDIR(mode):
                    inspect_directory(entry)
                    continue
                seen.add(relative)
                if relative not in expected:
                    extra.append(relative)
                elif not stat.S_ISREG(mode):
                    # Copy-based installs contain regular files. Never dereference
                    # a foreign link or read a device/FIFO while inspecting them.
                    unreadable.append(relative)
                else:
                    source = expected[relative].read_bytes()
                    with entry.open("rb") as installed:
                        if installed.read(len(source) + 1) != source:
                            changed.append(relative)
            except OSError:
                unreadable.append(relative)

    try:
        if stat.S_ISDIR(target.lstat().st_mode):
            inspect_directory(target)
        else:
            unreadable.append(".")
    except FileNotFoundError:
        status = "missing"
    except OSError:
        unreadable.append(".")
    missing = sorted(expected.keys() - seen)
    if unreadable:
        status = "unreadable"
    elif status != "missing":
        if missing:
            status = "partial"
        elif changed or extra:
            status = "stale"
    return {
        "status": status,
        "missing_files": missing,
        "changed_files": sorted(changed),
        "extra_files": sorted(extra),
        "unreadable_files": sorted(unreadable),
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
    if target is None and scope == "user":
        return _codex_home().absolute() / "skills" / "dating-booster-codex"
    base = target if target is not None else Path.cwd()
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
        if _ignored_install_entry(child.name):
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
