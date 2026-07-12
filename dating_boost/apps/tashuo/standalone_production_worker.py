from __future__ import annotations

import argparse
import os
from pathlib import Path

from dating_boost.apps.tashuo.standalone_production_ledger import ProductionQualificationLedger
from dating_boost.apps.tashuo.standalone_production_lock import WorkerProcessRegistry
from dating_boost.apps.tashuo.standalone_production_runtime import (
    run_attempt_worker,
    run_selection_worker,
    worker_input,
    write_worker_result,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("worker_kind", choices=("selection_probe", "attempt", "recovery"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--context-id", required=True)
    parser.add_argument("--barrier-fd", type=int, required=True)
    args = parser.parse_args(argv)
    ledger = ProductionQualificationLedger(args.data_dir)
    payload = worker_input(ledger, args.context_id)
    worker_nonce = str(payload.get("worker_nonce") or "")
    try:
        released = os.read(args.barrier_fd, 1)
    finally:
        os.close(args.barrier_fd)
    if released != b"1":
        return 70
    WorkerProcessRegistry(ledger).mark_child_ready(
        context_id=args.context_id,
        worker_nonce=worker_nonce,
        pid=os.getpid(),
    )
    try:
        if args.worker_kind == "selection_probe":
            result = run_selection_worker(payload)
        else:
            result = run_attempt_worker(payload, recovery=args.worker_kind == "recovery")
    except Exception:
        result = {
            "schema_version": 1,
            "status": "failed",
            "reason": "worker_exception",
            "terminal_persisted": False,
            "safety_violations": 1,
        }
    write_worker_result(ledger, context_id=args.context_id, result=result)
    return 0 if result.get("status") in {"ok", "eligible", "inconclusive", "succeeded", "failed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
