"""Thin Redis connection helper for WheelWay's live-state layer.

Owns ONLY connection concerns: reading ``REDIS_URL``, lazily importing the
optional ``redis`` package, and creating a client. All storage logic lives in
``state_store`` -- callers never touch the raw client directly.

The app must run with Redis absent, so every path here degrades gracefully:
missing env, missing package, or an unreachable server all resolve to "no
client" and the store falls back to memory. ``REDIS_URL`` is never logged or
returned to callers.
"""

from __future__ import annotations

import os
from typing import Any, Optional


def get_redis_url() -> Optional[str]:
    """Return the configured REDIS_URL (or None). Never expose this to clients."""
    url = os.getenv("REDIS_URL", "").strip()
    return url or None


def redis_configured() -> bool:
    """True when a REDIS_URL is set (regardless of reachability)."""
    return get_redis_url() is not None


def create_client() -> Optional[Any]:
    """Create a redis client from REDIS_URL, or None if unavailable.

    Returns None when: no URL, the ``redis`` package is not installed, or the
    URL cannot be parsed. Does NOT ping here -- reachability is checked by the
    store's health_check so a transient outage never raises at import time.
    """
    url = get_redis_url()
    if not url:
        return None
    try:
        import redis  # optional dependency
    except Exception:
        return None
    try:
        return redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception:
        return None


def ping(client: Optional[Any]) -> bool:
    """Best-effort reachability check; any failure -> False (never raises)."""
    if client is None:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False
