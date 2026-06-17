from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.apps.base import AppManifest, unsupported_operation_payload
from dating_boost.apps.native_gui_session import AppSpecificNativeGuiSessionMixin
from dating_boost.core.gui_harness import NativeGuiHarness


class AppNativeGuiSession(AppSpecificNativeGuiSessionMixin, NativeGuiHarness):
    """Adapter-owned session with app behavior bound outside the platform class."""


class LegacyHarnessAdapter:
    manifest: AppManifest

    def __init__(
        self,
        *,
        manifest: AppManifest,
        platform: str | None = None,
        runner: Any | None = None,
        window_title: str | None = None,
        runtime: str | None = None,
        session: Any | None = None,
    ):
        self.manifest = manifest
        runtime_key = _normalize_runtime_name(runtime)
        runtime_config = self.manifest.runtime_profiles.get(runtime_key, {}) if runtime_key is not None else {}
        title = (
            window_title
            or str(runtime_config.get("process_name") or "")
            or self.manifest.default_window_title
            or "iPhone Mirroring"
        )
        self.session = session or AppNativeGuiSession(
            app_id=self.manifest.app_id,
            platform=platform,
            runner=runner,
            window_title=title,
            runtime=str(runtime_config.get("backend") or runtime_key or self.manifest.backend),
        )
        self.session.harness_backend = str(runtime_config.get("backend") or runtime_key or self.manifest.backend)
        self.session.runtime_config = dict(runtime_config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return unsupported_operation_payload(self.manifest.app_id, "launch")

    def doctor(self, *, capture: bool = True, output: Path | None = None, ocr: bool = True) -> dict[str, Any]:
        return self.session.doctor(capture=capture, output=output, ocr=ocr)

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        return unsupported_operation_payload(self.manifest.app_id, "observe")

    def run_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return unsupported_operation_payload(self.manifest.app_id, f"action_{action}")

    def run_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return unsupported_operation_payload(self.manifest.app_id, f"workflow_{workflow}")

    def stage_draft(self, draft_text: str, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return unsupported_operation_payload(self.manifest.app_id, "stage_draft")

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return unsupported_operation_payload(self.manifest.app_id, "send_message")

    def target_binding_policy(self) -> dict[str, Any]:
        return {
            "requires_target_binding": "send_message" in self.manifest.supported_live_actions,
            **self.manifest.target_binding_policy,
        }

    def required_send_evidence(self) -> tuple[str, ...]:
        return self.manifest.required_send_evidence


def _normalize_runtime_name(runtime: str | None) -> str | None:
    if runtime is None:
        return None
    normalized = runtime.strip().replace("-", "_")
    return normalized or None
