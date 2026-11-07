from __future__ import annotations

import re
import shlex
from copy import deepcopy
from pathlib import Path

import pytest

from dating_boost import cli
from dating_boost.cli_parser import build_parser
from dating_boost.core import agent_adapters as adapters
from dating_boost.core import skill_doctor


HEADING = "ManagedRun (TaShuo mac-ios-app)"


def _section(text, heading):
    return text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0].strip()


@pytest.mark.parametrize("source", ["checkout", "packaged"])
@pytest.mark.parametrize("host", ["codex", "claude-code", "openclaw", "hermes"])
def test_installed_host_guidance_has_one_flagship_route_and_scoped_compatibility(tmp_path, monkeypatch, host, source):
    if source == "packaged":
        for setting in (
            "SOURCE_CODEX_SKILL_DIR", "SOURCE_CLAUDE_CODE_ADAPTER_DIR",
            "SOURCE_OPENCLAW_ADAPTER_DIR", "SOURCE_SHARED_REFERENCES_DIR",
        ):
            monkeypatch.setattr(adapters, setting, tmp_path / "absent-source" / setting)
    options = {"scope": "project", "target": tmp_path / host}
    if host == "codex":
        installed = adapters.install_codex_adapter(**options, dry_run=False)
        doctor = adapters.run_codex_adapter_doctor(tmp_path / "data", **options)
    elif host == "claude-code":
        installed = adapters.install_claude_code_adapter(**options, dry_run=False)
        doctor = adapters.run_claude_code_adapter_doctor(tmp_path / "data", **options)
    else:
        installed = adapters.install_openclaw_adapter(**options, target_host=host, dry_run=False)
        doctor = adapters.run_openclaw_adapter_doctor(tmp_path / "data", **options, target_host=host)
    assert doctor["installation"]["status"] == "ok"
    destination = Path(installed["target_path"])
    skill = (destination / "SKILL.md").read_text()
    workflows = (destination / "references/workflows.md").read_text()
    assert "references/workflows.md#managedrun-tashuo-mac-ios-app" in skill
    flagship = _section(workflows, HEADING)
    # Codex has additional app-specific references, but all installed hosts must
    # preserve the same host-neutral lifecycle instead of inventing a new route.
    shared = Path("agent_adapters/shared/references/workflows.md").read_text()
    assert flagship == _section(shared, HEADING)

    parser = build_parser(cli)
    commands = [
        shlex.split(line)
        for block in re.findall(r"```bash\n(.*?)```", flagship, re.DOTALL)
        for line in block.replace("\\\n", " ").splitlines()
        if line.startswith("dating-boost ")
    ]
    assert len(commands) == 2
    start, run = [parser.parse_args(command[1:]) for command in commands]
    assert (start.manage_command, start.app_id, start.runtime) == ("start", "tashuo", "mac-ios-app")
    assert start.authorization is None and start.config is None
    assert start.data_dir == run.data_dir
    assert run.manage_command == "run" and run.wait
    assert start.duration_minutes > 0 and start.send_budget > 0 and not start.nudge
    for phrase in (
        "manage status", "manage pause", "manage resume", "manage stop", "same run",
        "relationship_progress_report", "foreground", "no background daemon", "prepared_to_click",
        "unknown_after_click", "manage reconcile", "Return-only", "fresh post-send",
        "explicitly requests", "Model execution errors or observation failures pause",
    ):
        assert phrase in flagship

    compatibility = _section(workflows, "Session-scoped Managed Runner (Compatibility)")
    assert "managed-session" in compatibility and "host-loop" in compatibility
    assert "mac-ios-app" in compatibility and "--harness-runtime" in compatibility
    installed_text = "\n".join(
        path.read_text() for path in (
            destination / "SKILL.md", destination / "references/workflows.md", destination / "references/contracts.md",
            destination / "INSTALL.md", destination / "README.md", destination / "references/README.md",
            destination / "references/host-loop.md", destination / "references/start-prompts.md",
        )
        if path.is_file()
    )
    for obsolete in (
        "Agent-facing live sends must use", "the agent-facing managed live-send path",
        "Live send must be executed by host-loop", "Live send must run through host-loop",
        "It does not own the LLM call in this workflow.",
    ):
        assert obsolete not in " ".join(installed_text.split())
    assert "do not handcraft" in installed_text.lower()
    assert "executor-internal" in installed_text

    # A matching installation is not compatible if its CLI cannot run or
    # recover the workflow that the installed instructions now require.
    manifest = destination / ("skill-package.json" if host == "codex" else "adapter-package.json")
    capabilities = adapters.build_capabilities(tmp_path / "data")
    for missing in ("manage run", "manage reconcile", "managed_run"):
        old_cli = deepcopy(capabilities)
        if missing == "managed_run":
            del old_cli["schema_versions"][missing]
        else:
            old_cli["supported_commands"].remove(missing)
        monkeypatch.setattr(skill_doctor, "build_capabilities", lambda data_dir: old_cli)
        incompatible = skill_doctor.run_skill_doctor(manifest, tmp_path / "data")
        assert incompatible["status"] == "incompatible", (host, source, missing)
        if missing == "managed_run":
            assert incompatible["schema_mismatches"] == [{"schema": "managed_run", "expected": 1, "actual": None}]
        else:
            assert incompatible["missing_commands"] == [missing]
