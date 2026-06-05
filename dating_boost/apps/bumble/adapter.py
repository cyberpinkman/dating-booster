from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.apps.legacy import LegacyHarnessAdapter


class BumbleAdapter(LegacyHarnessAdapter):
    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.launch_bumble(dry_run=dry_run, output_dir=output_dir)

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.observe_bumble_screen(output_dir=output_dir)

    def run_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return self.session.run_bumble_action(action, dry_run=dry_run, output_dir=output_dir, **options)

    def run_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return self.session.run_bumble_workflow(workflow, dry_run=dry_run, output_dir=output_dir, **options)

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.session.send_bumble_message(
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

    launch_bumble = launch
    observe_bumble_screen = observe
    run_bumble_action = run_action
    run_bumble_workflow = run_workflow
    send_bumble_message = send_message
