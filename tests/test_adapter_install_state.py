import shlex
from functools import partial
from pathlib import Path

import pytest

from dating_boost.core import agent_adapters as adapters


HOSTS = [
    (adapters.install_codex_adapter, adapters.run_codex_adapter_doctor),
    (adapters.install_claude_code_adapter, adapters.run_claude_code_adapter_doctor),
    (adapters.install_openclaw_adapter, adapters.run_openclaw_adapter_doctor),
    (partial(adapters.install_openclaw_adapter, target_host="hermes"),
     partial(adapters.run_openclaw_adapter_doctor, target_host="hermes")),
]


@pytest.mark.parametrize("install,doctor", HOSTS, ids=["codex", "claude-code", "openclaw", "hermes"])
def test_doctor_checks_the_whole_planned_install_and_never_repairs_it(tmp_path, install, doctor):
    target = {"scope": "project", "target": tmp_path / "space here"}
    data = tmp_path / "data"
    planned = install(**target, dry_run=True)
    destination = Path(planned["target_path"])
    doctor_cmd = shlex.split(planned["startup_commands"][0])
    assert doctor_cmd[doctor_cmd.index("--scope") + 1] == target["scope"]
    assert doctor_cmd[doctor_cmd.index("--target") + 1] == str(target["target"])
    missing = doctor(data, **target)
    assert (missing["status"], missing["installation"]["status"]) == ("blocked", "missing")
    assert missing["skill_doctor"]["status"] == "ok"
    assert not destination.exists()
    install(**target, dry_run=False)
    (destination / "__pycache__").mkdir()
    (destination / "__pycache__" / "cache.pyc").write_bytes(b"ignored")
    (destination / ".DS_Store").write_text("ignored")
    healthy = doctor(data, **target)
    assert healthy["status"] == "ok" and healthy["target_path"] == str(destination)
    (destination / "references" / "workflows.md").write_text("obsolete instructions")
    (destination / "legacy-instructions.md").write_text("leftover")
    stale = doctor(data, **target)
    assert stale["issues"] == ["adapter_installation_stale"]
    assert stale["installation"]["changed_files"] == ["references/workflows.md"]
    assert stale["installation"]["extra_files"] == ["legacy-instructions.md"]
    (destination / "SKILL.md").unlink()
    partial_result = doctor(data, **target)
    assert partial_result["installation"]["status"] == "partial"
    assert partial_result["installation"]["missing_files"] == ["SKILL.md"]
    assert not (destination / "SKILL.md").exists()


def test_codex_user_target_respects_custom_codex_home_without_an_extra_dotcodex(tmp_path, monkeypatch):
    home = tmp_path / "custom-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    expected = home / "skills" / "dating-booster-codex"
    installed = adapters.install_codex_adapter(scope="user", target=None, dry_run=False)
    assert installed["target_path"] == str(expected)
    result = adapters.run_codex_adapter_doctor(tmp_path / "data")
    assert result["status"] == "ok" and result["target_path"] == str(expected)
    assert not (home / ".codex").exists()


def test_packaged_hermes_layout_uses_shared_openclaw_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "SOURCE_OPENCLAW_ADAPTER_DIR", tmp_path / "no-source")
    monkeypatch.setattr(adapters, "SOURCE_SHARED_REFERENCES_DIR", tmp_path / "no-references")
    target = {"scope": "user", "target": tmp_path, "target_host": "hermes"}
    installed = adapters.install_openclaw_adapter(**target, dry_run=False)
    healthy = adapters.run_openclaw_adapter_doctor(tmp_path / "data", **target)
    assert healthy["status"] == "ok" and healthy["compatibility_target"] == "openclaw"
    (Path(installed["target_path"]) / "adapter-package.json").write_text("{}")
    result = adapters.run_openclaw_adapter_doctor(tmp_path / "data", **target)
    assert result["installation"]["changed_files"] == ["adapter-package.json"]


def test_doctor_does_not_follow_unexpected_installed_links(tmp_path):
    target = {"scope": "project", "target": tmp_path}
    installed = adapters.install_codex_adapter(**target, dry_run=False)
    skill = Path(installed["target_path"]) / "SKILL.md"
    skill.unlink()
    skill.symlink_to(Path(installed["source_path"]) / "SKILL.md")
    result = adapters.run_codex_adapter_doctor(tmp_path / "data", **target)
    assert result["status"] == "blocked"
    assert result["installation"]["unreadable_files"] == ["SKILL.md"]
