"""Event + alert contracts for the live-state layer.

Events are appended to a durable Redis Stream (``wheelway:events``); alerts
follow the shared cross-service alert contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# --- Durable event types (Redis Stream) --- #
EVENT_OBSERVATION_CREATED = "observation.created"
EVENT_ROUTE_SELECTED = "route.selected"
EVENT_ROUTE_RECALCULATED = "route.recalculated"
EVENT_ALERT_CREATED = "alert.created"
EVENT_DEVICE_UPDATED = "device.updated"

EVENT_TYPES = {
    EVENT_OBSERVATION_CREATED,
    EVENT_ROUTE_SELECTED,
    EVENT_ROUTE_RECALCULATED,
    EVENT_ALERT_CREATED,
    EVENT_DEVICE_UPDATED,
}

# --- Shared alert contract --- #
ALERT_TYPES = {"obstacle", "reroute", "steep_slope", "stairs", "destination"}
ALERT_PRIORITIES = {"info", "warning", "critical"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_alert(
    *,
    type: str,
    text: str,
    priority: str = "info",
    dedupe_key: Optional[str] = None,
    route_session_id: Optional[str] = None,
    alert_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a validated alert dict matching the shared contract.

    Raises ValueError for an unknown ``type`` or ``priority`` so bad alerts fail
    loudly rather than being stored silently.
    """
    if type not in ALERT_TYPES:
        raise ValueError(f"invalid alert type: {type!r}")
    if priority not in ALERT_PRIORITIES:
        raise ValueError(f"invalid alert priority: {priority!r}")
    return {
        "alert_id": alert_id or uuid.uuid4().hex,
        "type": type,
        "text": text,
        "priority": priority,
        "dedupe_key": dedupe_key,
        "route_session_id": route_session_id,
        "created_at": created_at or _now_iso(),
    }


def make_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build an event envelope for the durable stream."""
    return {
        "event_id": uuid.uuid4().hex,
        "type": event_type,
        "created_at": _now_iso(),
        "payload": payload or {},
    }
