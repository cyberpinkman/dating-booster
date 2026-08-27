from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Callable

from dating_boost.apps.legacy import LegacyHarnessAdapter
from dating_boost.apps.tashuo import managed_live_action as tashuo_managed_live_action
from dating_boost.apps.tashuo import native as tashuo_native
from dating_boost.core.gui_runtime_lock import GuiRuntimeLock, RuntimeLockError


class TaShuoAdapter(LegacyHarnessAdapter):
    def __init__(self, **kwargs: Any):
        runner = kwargs.get("runner")
        super().__init__(**kwargs)
        tashuo_native.install_tashuo_session_hooks(self.session)
        self._runtime_lock_enabled = self.session.harness_backend == "mac_ios_app" and (
            runner is None or os.environ.get("DATING_BOOST_ENFORCE_RUNTIME_LOCK_FOR_TESTS") == "1"
        )

    def launch(self, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_native.launch_tashuo(self.session, dry_run=dry_run, output_dir=output_dir),
            dry_run=dry_run,
        )

    def doctor(self, *, capture: bool = True, output: Path | None = None, ocr: bool = True) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: self.session.doctor(capture=capture, output=output, ocr=ocr),
            dry_run=not capture,
        )

    def observe(self, *, output_dir: Path | None = None) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_native.observe_tashuo_screen(self.session, output_dir=output_dir)
        )

    def run_action(
        self,
        action: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_native.run_tashuo_action(
                self.session,
                action,
                dry_run=dry_run,
                output_dir=output_dir,
                **options,
            ),
            dry_run=dry_run,
        )

    def run_workflow(
        self,
        workflow: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_native.run_tashuo_workflow(
                self.session,
                workflow,
                dry_run=dry_run,
                output_dir=output_dir,
                **options,
            ),
            dry_run=dry_run,
        )

    def send_message(
        self,
        draft_text: str,
        *,
        dry_run: bool = False,
        output_dir: Path | None = None,
        target_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_native.send_tashuo_message(
                self.session,
                draft_text,
                dry_run=dry_run,
                output_dir=output_dir,
                target_binding=target_binding,
            ),
            dry_run=dry_run,
        )

    def stage_draft(self, draft_text: str, *, dry_run: bool = False, output_dir: Path | None = None) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_native.stage_tashuo_draft(
                self.session,
                draft_text,
                dry_run=dry_run,
                output_dir=output_dir,
            ),
            dry_run=dry_run,
        )

    def observe_managed_composer(
        self,
        *,
        target_binding: dict[str, Any],
        inbound_revision: str,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_managed_live_action.observe_tashuo_managed_composer(
                self.session,
                target_binding=target_binding,
                inbound_revision=inbound_revision,
                output_dir=output_dir,
            )
        )

    def observe_managed_inbound_revision(
        self,
        *,
        target_binding: dict[str, Any],
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_managed_live_action.observe_tashuo_managed_inbound_revision(
                self.session,
                target_binding=target_binding,
                output_dir=output_dir,
            )
        )

    def stage_managed_text(
        self,
        draft_text: str,
        *,
        target_binding: dict[str, Any],
        inbound_revision: str,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_managed_live_action.stage_tashuo_managed_text(
                self.session,
                draft_text,
                target_binding=target_binding,
                inbound_revision=inbound_revision,
                output_dir=output_dir,
            )
        )

    def click_managed_send_only(
        self,
        expected_text: str,
        *,
        target_binding: dict[str, Any],
        inbound_revision: str,
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_managed_live_action.click_tashuo_managed_send_only(
                self.session,
                expected_text,
                target_binding=target_binding,
                inbound_revision=inbound_revision,
                output_dir=output_dir,
            )
        )

    def observe_managed_post_send(
        self,
        expected_text: str,
        *,
        target_binding: dict[str, Any],
        inbound_revision: str,
        click_receipt: dict[str, Any],
        output_dir: Path | None = None,
    ) -> dict[str, Any]:
        return self._with_runtime_guard(
            lambda: tashuo_managed_live_action.observe_tashuo_managed_post_send(
                self.session,
                expected_text,
                target_binding=target_binding,
                inbound_revision=inbound_revision,
                click_receipt=click_receipt,
                output_dir=output_dir,
            )
        )

    def _with_runtime_guard(
        self,
        operation: Callable[[], dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not self._runtime_lock_enabled or dry_run:
            return operation()
        state_root = os.environ.get("DATING_BOOST_RUNTIME_LOCK_ROOT")
        runtime_lock = GuiRuntimeLock(state_root=Path(state_root) if state_root else None)
        delegated = os.environ.get("DATING_BOOST_GUI_RUNTIME_CAPABILITY")
        if delegated:
            try:
                capability = json.loads(delegated)
            except json.JSONDecodeError:
                return _runtime_blocked("runtime_delegated_capability_invalid")
            if not isinstance(capability, dict):
                return _runtime_blocked("runtime_delegated_capability_invalid")
            validation = runtime_lock.validate_delegated_capability(capability)
            if validation.get("status") != "ok":
                return _runtime_blocked(str(validation.get("reason") or "runtime_delegated_capability_invalid"))
            return operation()
        try:
            handle = runtime_lock.acquire(
                owner_id=f"tashuo_adapter_{os.getpid()}",
                owner_nonce=secrets.token_hex(16),
            )
        except RuntimeLockError as exc:
            return _runtime_blocked(str(exc))
        try:
            return operation()
        finally:
            handle.release()

    def target_binding_policy(self) -> dict[str, Any]:
        return {
            **super().target_binding_policy(),
            "requires_target_specific_marker": True,
        }

    launch_tashuo = launch
    observe_tashuo_screen = observe
    run_tashuo_action = run_action
    run_tashuo_workflow = run_workflow
    stage_tashuo_draft = stage_draft
    send_tashuo_message = send_message


def _runtime_blocked(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "blocked",
        "reason": reason,
        "app_id": "tashuo",
        "runtime": "mac-ios-app",
    }
