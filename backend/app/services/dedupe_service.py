"""Pluggable deduplication interface for voice alerts.

Default is an in-process TTL implementation. The signature mirrors a future
Redis-backed ``claim_dedupe_key(key, ttl_seconds)`` so /speak can be switched to
Redis later WITHOUT any endpoint change -- just call ``set_dedupe(redis_impl)``.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol


class Dedupe(Protocol):
    def claim_dedupe_key(self, key: str, ttl_seconds: int) -> bool:
        """Return True if the key was claimed now; False if still held (within TTL)."""
        ...


class InMemoryDedupe:
    """Thread-safe in-memory TTL dedupe. Replaceable by a Redis implementation."""

    def __init__(self, time_fn=time.time):
        self._time = time_fn
        self._lock = threading.Lock()
        self._keys: dict[str, float] = {}  # key -> expiry epoch

    def claim_dedupe_key(self, key: str, ttl_seconds: int) -> bool:
        now = self._time()
        with self._lock:
            exp = self._keys.get(key)
            if exp is not None and now < exp:
                return False
            self._keys[key] = now + ttl_seconds
            return True


_dedupe: Dedupe = InMemoryDedupe()


def get_dedupe() -> Dedupe:
    return _dedupe


def set_dedupe(impl: Dedupe) -> None:
    """Swap the dedupe backend (e.g. a Redis-backed claim_dedupe_key)."""
    global _dedupe
    _dedupe = impl


def reset_dedupe() -> None:
    global _dedupe
    _dedupe = InMemoryDedupe()
