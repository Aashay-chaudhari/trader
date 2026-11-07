"""One local owner for commands that can change execution or research state."""

from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class RuntimeBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeLease:
    path: Path
    handle: object
    pid: int
    thread: int

    def valid_for(self, path):
        return (
            self.path == path
            and not self.handle.closed
            and self.pid == os.getpid()
            and self.thread == threading.get_ident()
        )


@contextmanager
def runtime_ownership(state_dir, existing=None):
    """Keep the inode locked for the entire operation, including worker cleanup.

    A nested call may explicitly reuse its live lease on the same thread. Merely
    being in the same process never grants another operation ownership. The lock
    file is retained: unlinking it would permit a second owner on a new inode.
    """
    path = (Path(state_dir) / "supervisor.lock").resolve()
    if existing is not None:
        if not isinstance(existing, RuntimeLease) or not existing.valid_for(path):
            raise RuntimeBusy("Runtime ownership lease is no longer valid")
        yield existing
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeBusy(
                "The supervisor or another operational command is running; "
                "stop it before running this command. Status and dashboard remain available."
            ) from None
        lease = RuntimeLease(path, handle, os.getpid(), threading.get_ident())
        try:
            yield lease
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
