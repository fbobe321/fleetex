"""LockManager — per-compile-dir in-memory lock (port of LockManager.js).

One lock per project (keyed by compile dir). Acquiring a held+unexpired lock
raises AlreadyCompilingError (423); exceeding the concurrency limit raises
TooManyCompileRequestsError (503).
"""

from __future__ import annotations

import time
from contextlib import contextmanager

from .errors import AlreadyCompilingError, TooManyCompileRequestsError

_LOCK_TTL_SECONDS = 600 + 120  # MAX_TIMEOUT + 120s


class LockManager:
    def __init__(self, concurrency_limit: int = 64) -> None:
        self.concurrency_limit = concurrency_limit
        self._locks: dict[str, float] = {}  # compile_dir -> expiry epoch

    def _purge_expired(self) -> None:
        now = time.time()
        self._locks = {k: exp for k, exp in self._locks.items() if exp > now}

    @contextmanager
    def acquire(self, compile_dir: str):
        self._purge_expired()
        if compile_dir in self._locks:
            raise AlreadyCompilingError("compile already in progress for this project")
        if len(self._locks) >= self.concurrency_limit:
            raise TooManyCompileRequestsError("too many concurrent compiles")
        self._locks[compile_dir] = time.time() + _LOCK_TTL_SECONDS
        try:
            yield
        finally:
            self._locks.pop(compile_dir, None)
