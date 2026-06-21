"""Nonblocking WheelWay publisher: bounded queue + background HTTP worker.

The camera/physics hot loop calls ``submit`` which only touches an in-memory
bounded queue under a short lock -- it NEVER waits for HTTP. A daemon worker
drains the queue and POSTs to ``/observations``. When the queue is full, stale
NON-critical events are dropped first so the newest CRITICAL event is preserved.
Failures produce one concise log; retries are bounded (no infinite loop). The
whole publisher can be disabled, leaving the reactive loop fully functional with
the backend, Redis, Deepgram, or the internet unavailable.

``post_fn`` is injectable so tests never need a network/``requests``.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("wheelway.bridge.publisher")

# (observation, critical) queue entries.
_Entry = Tuple[dict, bool]


def _default_post_fn(url: str, json: dict, headers: dict, timeout: float):
    import requests  # imported lazily so tests/import never require it

    return requests.post(url, json=json, headers=headers, timeout=timeout)


class Publisher:
    def __init__(
        self,
        backend_url: str,
        *,
        device_id: str = "wheelway-pi-01",
        token: Optional[str] = None,
        enabled: bool = True,
        timeout: float = 2.0,
        queue_size: int = 20,
        max_critical_retries: int = 1,
        post_fn: Optional[Callable] = None,
    ):
        self.url = backend_url.rstrip("/") + "/observations"
        self.device_id = device_id
        self._token = token or None
        self.enabled = enabled
        self.timeout = timeout
        self.queue_size = max(1, queue_size)
        self.max_critical_retries = max(0, max_critical_retries)
        self._post_fn = post_fn or _default_post_fn

        self._q: List[_Entry] = []
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._worker: Optional[threading.Thread] = None
        self._running = False
        # Stats for status/heartbeat (no secrets).
        self.last_attempt_ok: Optional[bool] = None
        self.last_status: Optional[int] = None
        self._dropped = 0

    # ----- producer side (hot loop) ------------------------------------- #
    def submit(self, observation: dict, *, critical: bool = False) -> bool:
        """Enqueue without blocking. Returns False if dropped/disabled."""
        if not self.enabled:
            return False
        with self._lock:
            if len(self._q) >= self.queue_size:
                if not self._make_room(critical):
                    self._dropped += 1
                    return False
            self._q.append((observation, critical))
            self._cv.notify()
        return True

    def _make_room(self, incoming_critical: bool) -> bool:
        """Evict to fit one more. Preserve criticals; keep the newest critical."""
        # Drop the oldest NON-critical first.
        for i, (_obs, crit) in enumerate(self._q):
            if not crit:
                del self._q[i]
                self._dropped += 1
                return True
        # All queued are critical.
        if incoming_critical:
            del self._q[0]  # drop oldest critical so the newest is kept
            self._dropped += 1
            return True
        # Non-critical incoming must not displace a critical -> drop incoming.
        return False

    # ----- consumer side (worker thread) -------------------------------- #
    def start(self) -> None:
        if not self.enabled or self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._run, name="wheelway-publisher", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            with self._cv:
                while self._running and not self._q:
                    self._cv.wait(timeout=1.0)
                if not self._running and not self._q:
                    return
                if not self._q:
                    continue
                observation, critical = self._q.pop(0)
            self._deliver(observation, critical)

    def _deliver(self, observation: dict, critical: bool) -> None:
        attempts = 1 + (self.max_critical_retries if critical else 0)
        for attempt in range(attempts):
            try:
                resp = self._post_fn(self.url, observation, self._headers(), self.timeout)
                status = getattr(resp, "status_code", 0)
                self.last_status = status
                if 200 <= status < 300:
                    self.last_attempt_ok = True
                    return
                self.last_attempt_ok = False
                logger.warning("[publish] rejected status=%s (attempt %d/%d)", status, attempt + 1, attempts)
            except Exception as exc:  # connection/timeout -> concise log, bounded retry
                self.last_attempt_ok = False
                logger.warning("[publish] error=%s (attempt %d/%d)", type(exc).__name__, attempt + 1, attempts)
        # Give up after bounded attempts; the next event will try fresh.

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"  # value never logged
        return h

    def stop(self) -> None:
        with self._cv:
            self._running = False
            self._cv.notify_all()
        if self._worker:
            self._worker.join(timeout=2.0)

    @property
    def online(self) -> bool:
        return bool(self.enabled and self.last_attempt_ok)

    @property
    def dropped(self) -> int:
        return self._dropped


class NoOpPublisher:
    """Publisher disabled entirely; standalone vision_modal behavior unchanged."""

    enabled = False
    online = False
    dropped = 0
    last_attempt_ok = None
    last_status = None

    def submit(self, *_a, **_k) -> bool:
        return False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass
