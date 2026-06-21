"""WheelWay bridge for the upstream ``vision_modal`` obstacle-detection pipeline.

WheelWay-owned integration code. The upstream project (git submodule under
``hardware/vision_modal``) is unchanged: the bridge attaches at the final
risk/planning boundary via a dependency-injected event sink, translating
upstream snapshots into the canonical WheelWay vision observation and publishing
them nonblocking to the Flask backend.
"""

from .observation import build_heartbeat, build_observation, select_top_risk
from .publisher import NoOpPublisher, Publisher
from .sink import NoOpEventSink, WheelwayEventSink, build_sink_from_env
from .status import DeviceStatus
from .throttler import Throttler, ttc_band

__all__ = [
    "build_heartbeat",
    "build_observation",
    "select_top_risk",
    "Publisher",
    "NoOpPublisher",
    "WheelwayEventSink",
    "NoOpEventSink",
    "build_sink_from_env",
    "DeviceStatus",
    "Throttler",
    "ttc_band",
]
