from __future__ import annotations

from pathlib import Path
from typing import Any

from dating_boost.apps.legacy import LegacyHarnessAdapter


class WeChatAdapter(LegacyHarnessAdapter):
    def doctor(self, *, capture: bool = True, output: Path | None = None) -> dict[str, Any]:
        return self.session.doctor_wechat(capture=capture, output=output)

    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.launch_wechat(dry_run=dry_run, output_dir=output_dir)

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.observe_wechat_screen(output_dir=output_dir)

    def stage_draft(self, draft_text: str, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return self.session.stage_wechat_draft(draft_text, dry_run=dry_run, output_dir=output_dir)

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.session.send_wechat_message(
            draft_text,
            dry_run=dry_run,
            output_dir=output_dir,
            target_binding=target_binding,
        )

    launch_wechat = launch
    observe_wechat_screen = observe
    stage_wechat_draft = stage_draft
    send_wechat_message = send_message
