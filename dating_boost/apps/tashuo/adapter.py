from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.apps.legacy import LegacyHarnessAdapter
from dating_boost.apps.tashuo import native as tashuo_native


class TaShuoAdapter(LegacyHarnessAdapter):
    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        tashuo_native.install_tashuo_session_hooks(self.session)

    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return tashuo_native.launch_tashuo(self.session, dry_run=dry_run, output_dir=output_dir)

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        return tashuo_native.observe_tashuo_screen(self.session, output_dir=output_dir)

    def run_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return tashuo_native.run_tashuo_action(
            self.session,
            action,
            dry_run=dry_run,
            output_dir=output_dir,
            **options,
        )

    def run_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return tashuo_native.run_tashuo_workflow(
            self.session,
            workflow,
            dry_run=dry_run,
            output_dir=output_dir,
            **options,
        )

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return tashuo_native.send_tashuo_message(
            self.session,
            draft_text,
            dry_run=dry_run,
            output_dir=output_dir,
            target_binding=target_binding,
        )

    def target_binding_policy(self) -> dict[str, Any]:
        return {
            **super().target_binding_policy(),
            "requires_target_specific_marker": True,
        }

    launch_tashuo = launch
    observe_tashuo_screen = observe
    run_tashuo_action = run_action
    run_tashuo_workflow = run_workflow
    send_tashuo_message = send_message
