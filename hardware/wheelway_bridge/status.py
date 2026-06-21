"""Device status tracking for the WheelWay vision bridge (§11).

Thread-safe holder updated cheaply from the hot loop; ``snapshot`` feeds the
heartbeat observation. ``now_fn`` is injectable for tests.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class DeviceStatus:
    def __init__(self, device_id: str, *, stale_after_s: float = 3.0, now_fn: Callable[[], float] = time.monotonic):
        self.device_id = device_id
        self.stale_after_s = stale_after_s
        self._now = now_fn
        self._lock = threading.Lock()
        self.last_frame_t: Optional[float] = None
        self.last_detector_t: Optional[float] = None
        self.last_physics_t: Optional[float] = None
        self.last_publish_attempt_t: Optional[float] = None
        self.last_publish_ok_t: Optional[float] = None
        self.current_action: str = "CLEAR"
        self.publisher_online: bool = False

    def mark_frame(self) -> None:
        with self._lock:
            self.last_frame_t = self._now()

    def mark_detector(self) -> None:
        with self._lock:
            self.last_detector_t = self._now()

    def mark_physics(self, action: str) -> None:
        with self._lock:
            self.last_physics_t = self._now()
            self.current_action = action

    def mark_publish_attempt(self, ok: bool) -> None:
        with self._lock:
            self.last_publish_attempt_t = self._now()
            if ok:
                self.last_publish_ok_t = self._now()
            self.publisher_online = ok

    def _fresh(self, t: Optional[float], now: float) -> bool:
        return t is not None and (now - t) <= self.stale_after_s

    def snapshot(self) -> dict:
        with self._lock:
            now = self._now()
            return {
                "device_id": self.device_id,
                "current_action": self.current_action,
                "camera_online": self._fresh(self.last_frame_t, now),
                "detector_online": self._fresh(self.last_detector_t, now),
                "physics_online": self._fresh(self.last_physics_t, now),
                "publisher_online": self.publisher_online,
                "seconds_since_frame": (now - self.last_frame_t) if self.last_frame_t else None,
                "seconds_since_publish_ok": (now - self.last_publish_ok_t) if self.last_publish_ok_t else None,
            }
