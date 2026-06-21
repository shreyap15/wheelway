"""Event sink: the single integration seam the Pi runner calls each loop.

Combines the adapter (observation), the throttler (when to emit), and the
publisher (nonblocking HTTP). The runner injects either a ``WheelwayEventSink``
or a ``NoOpEventSink`` -- so standalone vision_modal behaves exactly as before.

The conceptual hot-loop call (after tracks/trajectories/risks/command are ready):

    sink.publish(command=command, tracks=tracks, risks=risks,
                 trajectories=trajectories, frame_width=w, frame_height=h,
                 timestamp=ts, scene_reasoning=scene.get())

``publish`` never performs network I/O on the calling thread.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from . import observation as obs_adapter
from .publisher import NoOpPublisher, Publisher
from .status import DeviceStatus
from .throttler import Throttler

logger = logging.getLogger("wheelway.bridge.sink")


class NoOpEventSink:
    """Disabled sink -- vision_modal runs exactly as upstream."""

    def publish(self, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class WheelwayEventSink:
    def __init__(
        self,
        publisher: Publisher,
        throttler: Throttler,
        status: DeviceStatus,
        *,
        device_id: str = "wheelway-pi-01",
        model: str = "efficientdet_lite0",
        pipeline_version: str = "vision-modal",
        risk_threshold: float = 0.5,
        predict_horizon_s: float = 1.0,
        now_fn=None,
    ):
        self.publisher = publisher
        self.throttler = throttler
        self.status = status
        self.device_id = device_id
        self.model = model
        self.pipeline_version = pipeline_version
        self.risk_threshold = risk_threshold
        self.predict_horizon_s = predict_horizon_s
        import time as _time
        self._now = now_fn or _time.monotonic

    def start(self) -> None:
        self.publisher.start()

    def stop(self) -> None:
        self.publisher.stop()

    def publish(
        self,
        *,
        command,
        tracks: Sequence,
        risks: Sequence,
        trajectories: Sequence,
        frame_width: int,
        frame_height: int,
        timestamp: Optional[Any] = None,
        scene_reasoning: Any = None,
    ) -> None:
        """Decide + enqueue. Pure-CPU + a bounded-queue append; no HTTP here."""
        now = self._now()
        action = getattr(command, "action", "CLEAR")
        self.status.mark_physics(action)

        top = obs_adapter.select_top_risk(tracks, risks, trajectories, self.risk_threshold)
        top_id = getattr(top[0], "id", None) if top else None
        ttc = obs_adapter._ttc_or_none(getattr(top[1], "ttc", None)) if top else None
        risk = (obs_adapter._finite(getattr(top[1], "risk", 0.0)) if top else None)
        in_corridor = bool(getattr(top[1], "in_corridor", False)) if top else False

        reasons = self.throttler.decide(
            now, action=action, top_track_id=top_id, ttc=ttc, risk=risk, in_corridor=in_corridor
        )

        # Periodic heartbeat regardless of hazard activity.
        if self.throttler.due_for_heartbeat(now):
            hb = obs_adapter.build_heartbeat(
                {**self.status.snapshot(), "publisher_online": self.publisher.online},
                device_id=self.device_id,
                pipeline_version=self.pipeline_version,
                model=self.model,
            )
            self.publisher.submit(hb, critical=False)

        if not reasons:
            return

        obs = obs_adapter.build_observation(
            command=command,
            tracks=tracks,
            risks=risks,
            trajectories=trajectories,
            frame_width=frame_width,
            frame_height=frame_height,
            timestamp=timestamp if isinstance(timestamp, str) else None,
            scene=scene_reasoning,
            device_id=self.device_id,
            model=self.model,
            pipeline_version=self.pipeline_version,
            risk_threshold=self.risk_threshold,
            predict_horizon_s=self.predict_horizon_s,
        )
        critical = action == "STOP" or "stop" in reasons or "ttc_critical" in reasons
        accepted = self.publisher.submit(obs, critical=critical)
        self.status.mark_publish_attempt(self.publisher.online)
        if not accepted and self.publisher.enabled:
            logger.info("[publish] dropped action=%s reasons=%s", action, ",".join(reasons))


def build_sink_from_env(env: dict) -> Any:
    """Construct a WheelwayEventSink (or NoOpEventSink when disabled) from env vars.

    Reads only WHEELWAY_* config. Never logs secrets.
    """
    def _flag(name, default="true"):
        return str(env.get(name, default)).strip().lower() in {"1", "true", "yes", "on"}

    if not _flag("WHEELWAY_PUBLISH_ENABLED", "true"):
        return NoOpEventSink()

    device_id = env.get("WHEELWAY_DEVICE_ID", "wheelway-pi-01")
    publisher = Publisher(
        env.get("WHEELWAY_BACKEND_URL", "http://127.0.0.1:5000"),
        device_id=device_id,
        token=env.get("WHEELWAY_DEVICE_TOKEN") or None,
        enabled=True,
        timeout=float(env.get("WHEELWAY_PUBLISH_TIMEOUT_SECONDS", "2") or 2),
        queue_size=int(env.get("WHEELWAY_QUEUE_SIZE", "20") or 20),
    )
    throttler = Throttler(
        warning_ttc=float(env.get("WHEELWAY_WARNING_TTC_SECONDS", "3") or 3),
        critical_ttc=float(env.get("WHEELWAY_CRITICAL_TTC_SECONDS", "1.5") or 1.5),
        heartbeat_s=float(env.get("WHEELWAY_HEARTBEAT_SECONDS", "5") or 5),
    )
    status = DeviceStatus(device_id)
    return WheelwayEventSink(
        publisher, throttler, status,
        device_id=device_id,
        pipeline_version=env.get("WHEELWAY_PIPELINE_VERSION", "vision-modal-7b9d823"),
    )
