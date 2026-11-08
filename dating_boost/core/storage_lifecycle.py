"""Stable coordination for replacing a data directory used by live repositories."""
from __future__ import annotations

import errno
import hashlib
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if sys.platform == "win32":  # pragma: no cover - exercised on the native host.
    import msvcrt
else:
    import fcntl

_HELD = threading.local()


def storage_lifecycle_path(root: Path) -> Path:
    root = root.resolve()
    identity = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:24]
    return root.parent / f".dating_boost_lifecycle_{identity}.lock"


@contextmanager
def storage_lifecycle_lease(root: Path, *, exclusive: bool = False, blocking: bool = True) -> Iterator[bool]:
    """Acquire before run/state/write locks; never replace this lock with the data.

    Readers, executors and repository writes share the lease. Restore/delete-all
    take it exclusively. Nested calls reuse the outer descriptor; an attempted
    shared-to-exclusive upgrade fails instead of deadlocking or losing a lease.
    """
    root = root.resolve()
    key = (os.getpid(), root)
    held: dict[tuple[int, Path], bool] = getattr(_HELD, "leases", {})
    if key in held:
        yield not exclusive or held[key]
        return

    path = storage_lifecycle_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        try:
            if sys.platform == "win32":  # pragma: no cover
                # Windows conservatively serializes shared users too.
                msvcrt.locking(descriptor, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                fcntl.flock(descriptor, mode | (0 if blocking else fcntl.LOCK_NB))
            acquired = True
        except OSError as exc:
            if not blocking and exc.errno in {errno.EACCES, errno.EAGAIN}:
                yield False
                return
            raise
        _HELD.leases = {**held, key: exclusive}
        try:
            yield True
        finally:
            _HELD.leases = held
    finally:
        if acquired:
            if sys.platform == "win32":  # pragma: no cover
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
