from __future__ import annotations

import hashlib
from importlib import metadata as importlib_metadata
import json
import os
from pathlib import Path
from typing import Any
import tomllib

from dating_boost import __version__
from dating_boost.core.capabilities import SCHEMA_VERSIONS
from dating_boost.core.production_store import RELEASE_MANIFEST_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def release_manifest() -> dict[str, Any]:
    paths = _release_paths()
    skill_package = paths["skill_package"]
    claude_code_adapter = paths["claude_code_adapter"]
    openclaw_adapter = paths["openclaw_adapter"]
    packaged_codex_skill = paths["packaged_codex_skill"]
    pyproject = paths["pyproject"]
    source_checkout = paths["layout"] == "source_checkout"
    dist_version = __version__.replace("-rc.", "rc")
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "status": "ok",
        "tool_version": __version__,
        "git_commit": _git_commit(),
        "execution_layout": paths["layout"],
        "artifacts": {
            "wheel": f"dating_booster-{dist_version}-py3-none-any.whl",
            "sdist": f"dating_booster-{dist_version}.tar.gz",
            "skill_package": f"dating-booster-codex-{__version__}.tar.gz",
            "claude_code_adapter": f"dating-booster-claude-code-{__version__}.tar.gz",
            "openclaw_adapter": f"dating-booster-openclaw-{__version__}.tar.gz",
        },
        "artifact_sources": {
            "pyproject": str(pyproject) if pyproject is not None else "installed-distribution:dating-booster",
            "skill_package": str(skill_package),
            "claude_code_adapter": (
                str(claude_code_adapter.relative_to(ROOT)) if source_checkout else str(claude_code_adapter)
            ),
            "openclaw_adapter": (
                str(openclaw_adapter.relative_to(ROOT)) if source_checkout else str(openclaw_adapter)
            ),
        },
        "source_hashes": {
            "pyproject.toml": _file_sha256(pyproject) if pyproject is not None else _distribution_metadata_sha256(),
            "skill-package.json": _file_sha256(skill_package),
            "claude-code/adapter-package.json": _file_sha256(claude_code_adapter),
            "openclaw/adapter-package.json": _file_sha256(openclaw_adapter),
            "codex-packaged-resource-tree": _tree_sha256(packaged_codex_skill),
        },
        "schema_versions": dict(SCHEMA_VERSIONS),
        "release_capabilities": {
            "pypi": True,
            "github_release": True,
            "skill_package": True,
            "claude_code_adapter": True,
            "openclaw_adapter": True,
            "hermes_openclaw_compatible_adapter": True,
            "trusted_publishing": True,
            "macos_ci": True,
            "redacted_diagnostics": True,
        },
    }


def release_doctor() -> dict[str, Any]:
    manifest = release_manifest()
    issues: list[str] = []
    paths = _release_paths()
    source_checkout = paths["layout"] == "source_checkout"
    pyproject_path = paths["pyproject"]
    skill_package_path = paths["skill_package"]
    claude_code_adapter_path = paths["claude_code_adapter"]
    openclaw_adapter_path = paths["openclaw_adapter"]
    if source_checkout:
        try:
            pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pyproject = {}
            issues.append("pyproject_unreadable")
        if pyproject.get("project", {}).get("version") != __version__:
            issues.append("pyproject_version_mismatch")
    else:
        installed_version = _installed_distribution_version()
        if installed_version is None:
            issues.append("distribution_metadata_unreadable")
        elif _normalized_distribution_version(installed_version) != _normalized_distribution_version(__version__):
            issues.append("distribution_version_mismatch")
    _validate_release_package(
        skill_package_path,
        issues,
        unreadable_issue="skill_package_unreadable",
        issue_prefix="",
        expected_target_host="codex",
    )
    _validate_release_package(
        claude_code_adapter_path,
        issues,
        unreadable_issue="claude_code_adapter_unreadable",
        issue_prefix="claude_code_adapter_",
        expected_target_host="claude_code",
    )
    _validate_release_package(
        openclaw_adapter_path,
        issues,
        unreadable_issue="openclaw_adapter_unreadable",
        issue_prefix="openclaw_adapter_",
        expected_target_host="openclaw",
    )
    if source_checkout:
        issues.extend(
            _codex_skill_resource_parity_issues(
                source_root=skill_package_path.parent,
                packaged_root=paths["packaged_codex_skill"],
            )
        )
        if not _release_workflow_isolated():
            issues.append("release_workflow_artifact_isolation_missing")
    else:
        issues.extend(_installed_codex_skill_resource_issues(skill_package_path.parent))
    if source_checkout and _strict_release_mode():
        expected_ref = f"v{__version__}"
        actual_ref = os.environ.get("GITHUB_REF_NAME")
        if actual_ref and actual_ref != expected_ref:
            issues.append("release_tag_mismatch")
        if _git_dirty():
            issues.append("dirty_source_tree")
    return {
        **manifest,
        "status": "ok" if not issues else "blocked",
        "issues": issues,
    }


def _release_paths() -> dict[str, Any]:
    pyproject = ROOT / "pyproject.toml"
    source_skill = ROOT / "skills" / "dating-booster-codex"
    source_layout = pyproject.is_file() and source_skill.is_dir()
    if source_layout:
        packaged_adapters = ROOT / "dating_boost" / "resources" / "agent_adapters"
        return {
            "layout": "source_checkout",
            "pyproject": pyproject,
            "skill_package": source_skill / "skill-package.json",
            "claude_code_adapter": ROOT / "agent_adapters" / "claude-code" / "adapter-package.json",
            "openclaw_adapter": ROOT / "agent_adapters" / "openclaw" / "adapter-package.json",
            "packaged_codex_skill": packaged_adapters / "codex" / "dating-booster-codex",
        }
    packaged_adapters = PACKAGE_ROOT / "resources" / "agent_adapters"
    packaged_skill = packaged_adapters / "codex" / "dating-booster-codex"
    return {
        "layout": "installed_distribution",
        "pyproject": None,
        "skill_package": packaged_skill / "skill-package.json",
        "claude_code_adapter": packaged_adapters / "claude-code" / "adapter-package.json",
        "openclaw_adapter": packaged_adapters / "openclaw" / "adapter-package.json",
        "packaged_codex_skill": packaged_skill,
    }


def _validate_release_package(
    package_path: Path,
    issues: list[str],
    *,
    unreadable_issue: str,
    issue_prefix: str,
    expected_target_host: str,
) -> None:
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        issues.append(unreadable_issue)
        return
    for key in ("package_version", "dating_boost_min_version"):
        if package.get(key) != __version__:
            issues.append(f"{issue_prefix}{key}_mismatch")
    expected_source_ref = f"v{__version__}" if _strict_release_mode() else _expected_source_ref()
    if package.get("source_ref") != expected_source_ref:
        issues.append(f"{issue_prefix}source_ref_mismatch")
    if package.get("target_host") != expected_target_host:
        issues.append(f"{issue_prefix}target_host_mismatch")


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _installed_distribution_version() -> str | None:
    try:
        return importlib_metadata.version("dating-booster")
    except importlib_metadata.PackageNotFoundError:
        return None


def _distribution_metadata_sha256() -> str:
    try:
        metadata_text = importlib_metadata.distribution("dating-booster").read_text("METADATA")
    except importlib_metadata.PackageNotFoundError:
        return "missing"
    if metadata_text is None:
        return "missing"
    return hashlib.sha256(metadata_text.encode("utf-8")).hexdigest()


def _normalized_distribution_version(value: str) -> str:
    return value.replace("-rc.", "rc")


def _tree_sha256(root: Path) -> str:
    files = _tree_hashes(root)
    if not files:
        return "missing"
    digest = hashlib.sha256()
    for relative_path, file_hash in sorted(files.items()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in root.rglob("*")
        if _is_release_resource(path, root=root)
    }


def _is_release_resource(path: Path, *, root: Path) -> bool:
    if not path.is_file():
        return False
    relative = path.relative_to(root)
    return "__pycache__" not in relative.parts and path.suffix not in {".pyc", ".pyo"}


def _codex_skill_resource_parity_issues(
    *,
    source_root: Path | None = None,
    packaged_root: Path | None = None,
) -> list[str]:
    source_root = source_root or ROOT / "skills" / "dating-booster-codex"
    packaged_root = packaged_root or (
        ROOT / "dating_boost" / "resources" / "agent_adapters" / "codex" / "dating-booster-codex"
    )
    source_files = _tree_hashes(source_root)
    packaged_files = _tree_hashes(packaged_root)
    issues: list[str] = []
    for relative_path in sorted(source_files.keys() - packaged_files.keys()):
        issues.append(f"codex_skill_resource_missing:{relative_path}")
    for relative_path in sorted(packaged_files.keys() - source_files.keys()):
        issues.append(f"codex_skill_resource_unexpected:{relative_path}")
    for relative_path in sorted(source_files.keys() & packaged_files.keys()):
        if source_files[relative_path] != packaged_files[relative_path]:
            issues.append(f"codex_skill_resource_mismatch:{relative_path}")
    return issues


def _installed_codex_skill_resource_issues(skill_root: Path) -> list[str]:
    package_path = skill_root / "skill-package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    required_paths = {
        "INSTALL.md",
        "SKILL.md",
        "skill-package.json",
        str(package.get("bootstrap_script") or ""),
        str(package.get("doctor_script") or ""),
        *(str(item) for item in package.get("references") or []),
    }
    issues: list[str] = []
    resolved_root = skill_root.resolve()
    for relative_path in sorted(path for path in required_paths if path):
        candidate = (skill_root / relative_path).resolve()
        if not candidate.is_relative_to(resolved_root):
            issues.append(f"codex_skill_resource_invalid_path:{relative_path}")
        elif not candidate.is_file():
            issues.append(f"codex_skill_resource_missing:{relative_path}")
    return issues


def _git_commit() -> str:
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True)
    except Exception:  # noqa: BLE001
        return "unknown"
    return result.stdout.strip() or "unknown"


def _expected_source_ref() -> str:
    return "main" if ".dev" in __version__ else f"v{__version__}"


def _strict_release_mode() -> bool:
    return os.environ.get("DATING_BOOST_RELEASE_STRICT") == "1" or (
        os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REF_TYPE") == "tag"
    )


def _git_dirty() -> bool:
    import subprocess

    try:
        result = subprocess.run(["git", "status", "--porcelain"], check=True, capture_output=True, text=True)
    except Exception:  # noqa: BLE001
        return True
    return bool(result.stdout.strip())


def _release_workflow_isolated() -> bool:
    workflow = ROOT / ".github" / "workflows" / "release.yml"
    if not workflow.exists():
        return False
    text = workflow.read_text(encoding="utf-8")
    return (
        "python -m build --outdir dist/python" in text
        and "packages-dir: dist/python" in text
        and "dist/skill/*" in text
        and "dating-booster-codex-${GITHUB_REF_NAME#v}.tar.gz" in text
        and "dating-booster-claude-code-${GITHUB_REF_NAME#v}.tar.gz" in text
        and "dating-booster-openclaw-${GITHUB_REF_NAME#v}.tar.gz" in text
        and "-C agent_adapters claude-code" in text
        and "-C agent_adapters openclaw" in text
    )
