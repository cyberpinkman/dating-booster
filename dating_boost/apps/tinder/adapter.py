from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.apps.legacy import LegacyHarnessAdapter


class TinderAdapter(LegacyHarnessAdapter):
    def open_profile(
        self,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        launch_if_needed: bool = False,
    ) -> dict[str, Any]:
        return self.session.open_tinder_profile(
            dry_run=dry_run,
            output_dir=output_dir,
            launch_if_needed=launch_if_needed,
        )

    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.launch_tinder(dry_run=dry_run, output_dir=output_dir)

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.observe_tinder_screen(output_dir=output_dir)

    def run_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return self.session.run_tinder_action(action, dry_run=dry_run, output_dir=output_dir, **options)

    def run_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return self.session.run_tinder_workflow(workflow, dry_run=dry_run, output_dir=output_dir, **options)

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.session.send_tinder_message(
            draft_text,
            dry_run=dry_run,
            output_dir=output_dir,
            target_binding=target_binding,
        )

    launch_tinder = launch
    observe_tinder_screen = observe
    run_tinder_action = run_action
    run_tinder_workflow = run_workflow
    send_tinder_message = send_message
