from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
import tomllib

from dating_boost import __version__
from dating_boost.core.capabilities import SCHEMA_VERSIONS
from dating_boost.core.production_store import RELEASE_MANIFEST_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]


def release_manifest() -> dict[str, Any]:
    skill_package = ROOT / "skills" / "dating-booster-codex" / "skill-package.json"
    pyproject = ROOT / "pyproject.toml"
    dist_version = __version__.replace("-rc.", "rc")
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "status": "ok",
        "tool_version": __version__,
        "git_commit": _git_commit(),
        "artifacts": {
            "wheel": f"dating_booster-{dist_version}-py3-none-any.whl",
            "sdist": f"dating_booster-{dist_version}.tar.gz",
            "skill_package": f"dating-booster-codex-{__version__}.tar.gz",
        },
        "artifact_sources": {
            "pyproject": str(pyproject),
            "skill_package": str(skill_package),
        },
        "source_hashes": {
            "pyproject.toml": _file_sha256(pyproject),
            "skill-package.json": _file_sha256(skill_package),
        },
        "schema_versions": dict(SCHEMA_VERSIONS),
        "release_capabilities": {
            "pypi": True,
            "github_release": True,
            "skill_package": True,
            "trusted_publishing": True,
            "macos_ci": True,
            "redacted_diagnostics": True,
        },
    }


def release_doctor() -> dict[str, Any]:
    manifest = release_manifest()
    issues: list[str] = []
    pyproject_path = ROOT / "pyproject.toml"
    skill_package_path = ROOT / "skills" / "dating-booster-codex" / "skill-package.json"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pyproject = {}
        issues.append("pyproject_unreadable")
    if pyproject.get("project", {}).get("version") != __version__:
        issues.append("pyproject_version_mismatch")
    try:
        skill = json.loads(skill_package_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        skill = {}
        issues.append("skill_package_unreadable")
    for key in ("package_version", "dating_boost_min_version"):
        if skill.get(key) != __version__:
            issues.append(f"{key}_mismatch")
    if skill.get("source_ref") != f"v{__version__}":
        issues.append("source_ref_mismatch")
    if not _release_workflow_isolated():
        issues.append("release_workflow_artifact_isolation_missing")
    if _strict_release_mode():
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


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=True, capture_output=True, text=True)
    except Exception:  # noqa: BLE001
        return "unknown"
    return result.stdout.strip() or "unknown"


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
    )
