from __future__ import annotations

from .runtime_common import *
from .targeting import *
from .send_input_ax import *
from .send_verification import *

def run_tashuo_workflow(
    session: Any,
    workflow: str,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
    **options: Any,
) -> dict[str, Any]:
    try:
        planned_steps = _tashuo_workflow_steps(workflow, **options)
    except KeyError:
        return {
            **session._base_payload("blocked"),
            "workflow": workflow,
            "reason": "unknown_tashuo_harness_workflow",
            **tashuo_guardrails_payload(),
        }
    payload = {
        **session._base_payload("ok"),
        "workflow": workflow,
        "mode": "dry_run" if dry_run else "execute",
        "planned_steps": planned_steps,
        **tashuo_guardrails_payload(),
    }
    if dry_run:
        return payload
    return session._execute_planned_steps(payload, output_dir=output_dir)

from .stage_runtime import stage_tashuo_draft
from .input_runtime import clear_tashuo_message_input
from .live_send_runtime import send_tashuo_message


__all__ = [name for name in globals() if not name.startswith("__")]
