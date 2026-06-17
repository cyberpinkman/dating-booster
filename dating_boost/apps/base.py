from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AppManifest:
    app_id: str
    display_name: str
    support_level: str
    backend: str
    host_loop_supported: bool
    host_loop_send_modes: tuple[str, ...]
    supported_stage_actions: tuple[str, ...]
    supported_live_actions: tuple[str, ...]
    supported_actions: tuple[str, ...]
    supported_workflows: tuple[str, ...]
    default_window_title: str
    required_send_evidence: tuple[str, ...]
    target_binding_policy: dict[str, Any]
    managed_session_policy: dict[str, Any]
    cli_aliases: dict[str, dict[str, Any]]
    runtime_profiles: dict[str, dict[str, Any]]

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> "AppManifest":
        harness = profile.get("native_gui_harness") if isinstance(profile.get("native_gui_harness"), dict) else {}
        chat_navigation = harness.get("chat_navigation") if isinstance(harness.get("chat_navigation"), dict) else {}
        adapter = profile.get("adapter") if isinstance(profile.get("adapter"), dict) else {}
        capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
        requirements = (
            profile.get("live_send_requirements") if isinstance(profile.get("live_send_requirements"), dict) else {}
        )
        target_binding = profile.get("target_binding") if isinstance(profile.get("target_binding"), dict) else {}
        managed_session = profile.get("managed_session") if isinstance(profile.get("managed_session"), dict) else {}
        cli_aliases = profile.get("cli_aliases") if isinstance(profile.get("cli_aliases"), dict) else {}
        alternate_runtimes = (
            harness.get("alternate_runtimes") if isinstance(harness.get("alternate_runtimes"), dict) else {}
        )
        actions = capabilities.get("actions") or harness.get("supported_actions") or harness.get("supported_stage_actions") or []
        workflows = capabilities.get("workflows") or harness.get("high_level_workflows") or []
        evidence = requirements.get("required_evidence") or harness.get("required_send_evidence") or [
            "staged_text_verified",
            "outbound_message_verified",
        ]
        return cls(
            app_id=str(profile["app_id"]),
            display_name=str(profile["display_name"]),
            support_level=str(profile["support_level"]),
            backend=str(adapter.get("backend") or harness.get("backend") or ""),
            host_loop_supported=bool(profile["host_loop_supported"]),
            host_loop_send_modes=tuple(str(mode) for mode in profile.get("host_loop_send_modes", [])),
            supported_stage_actions=tuple(str(item) for item in harness.get("supported_stage_actions", [])),
            supported_live_actions=tuple(str(item) for item in harness.get("supported_live_actions", [])),
            supported_actions=tuple(str(item) for item in actions),
            supported_workflows=tuple(str(item) for item in workflows),
            default_window_title=str(
                adapter.get("default_window_title") or harness.get("window_title") or chat_navigation.get("window_title") or ""
            ),
            required_send_evidence=tuple(str(item) for item in evidence),
            target_binding_policy=dict(target_binding),
            managed_session_policy=dict(managed_session),
            cli_aliases={str(name): dict(spec) for name, spec in cli_aliases.items() if isinstance(spec, dict)},
            runtime_profiles={
                str(name): dict(spec) for name, spec in alternate_runtimes.items() if isinstance(spec, dict)
            },
        )


class AppAdapter(Protocol):
    manifest: AppManifest

    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        ...

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        ...

    def doctor(self, *, capture: bool = True, output: Path | None = None, ocr: bool = True) -> dict[str, Any]:
        ...

    def run_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        ...

    def run_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        ...

    def stage_draft(self, draft_text: str, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        ...

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def target_binding_policy(self) -> dict[str, Any]:
        ...

    def required_send_evidence(self) -> tuple[str, ...]:
        ...


class UnsupportedAdapterOperation(NotImplementedError):
    pass


def unsupported_operation_payload(app_id: str, operation: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "status": "blocked",
        "app_id": app_id,
        "reason": f"{operation}_not_supported_for_app",
    }
