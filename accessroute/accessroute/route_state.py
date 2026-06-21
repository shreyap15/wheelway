"""Canonical route-session + alert contract shared by Flask and Fetch.ai.

This is the SINGLE source of truth for the live route session, the alert
contract, and how they are read/written -- so the Flask ``/real-route`` flow and
the Agentverse orchestrator answer questions about the *same* active route
without duplicating routing logic or touching Redis directly.

Persistence is dependency-injected: the default is an in-process store; the
backend installs a Redis-backed adapter (``set_store``) at startup. Nothing here
imports the redis client.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

# --- Alert contract --- #
ALERT_TYPES = {"reroute", "steep_slope", "stairs", "no_compliant_route", "destination", "degraded"}
ALERT_PRIORITIES = {"info", "warning", "critical"}

# Event types appended to the durable log.
EVENT_ROUTE_CREATED = "route.created"
EVENT_ROUTE_SELECTED = "route.selected"
EVENT_ALERT_CREATED = "alert.created"

# Alert types that may be auto-spoken (everything else is text-only).
AUTO_SPEAK_TYPES = {"no_compliant_route", "stairs", "steep_slope", "reroute"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session_id() -> str:
    return "rs-" + uuid.uuid4().hex[:16]


# --------------------------------------------------------------------------- #
# Models (plain dicts on the wire)
# --------------------------------------------------------------------------- #
def route_summary(route: Dict[str, Any]) -> Dict[str, Any]:
    """Compact summary of one route -- NO geometry (avoids duplicate coord arrays)."""
    return {
        "route_id": route.get("route_id"),
        "distance_m": route.get("distance_m"),
        "duration_s": route.get("duration_s"),
        "max_slope_pct": route.get("max_slope_pct"),
        "exceeds_limit_distance_m": route.get("exceeds_limit_distance_m"),
        "exceeds_limit_percentage": route.get("exceeds_limit_percentage"),
        "accessibility_score": route.get("accessibility_score"),
        "stairs_status": route.get("stairs_status"),
        "recommended": route.get("recommended", False),
        "accessibility_rank": route.get("accessibility_rank"),
        "selection_reasons": route.get("selection_reasons", []),
    }


def make_route_session(
    *,
    origin: Dict[str, float],
    destination: Dict[str, float],
    profile: Dict[str, Any],
    routes: List[Dict[str, Any]],
    selected_route_id: Optional[str] = None,
    destination_place: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    summaries = [route_summary(r) for r in routes]
    sid = session_id or new_session_id()
    selected = selected_route_id or (summaries[0]["route_id"] if summaries else None)
    now = _now_iso()
    return {
        "route_session_id": sid,
        "selected_route_id": selected,
        "origin": origin,
        "destination": destination,
        "profile": profile,
        "available_routes": summaries,
        "selected_route": next((s for s in summaries if s["route_id"] == selected), None),
        "destination_place": destination_place,
        "created_at": now,
        "updated_at": now,
    }


def make_alert(
    *,
    type: str,
    text: str,
    route_session_id: str,
    priority: str = "info",
    dedupe_key: Optional[str] = None,
    alert_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    if type not in ALERT_TYPES:
        raise ValueError(f"invalid alert type: {type!r}")
    if priority not in ALERT_PRIORITIES:
        raise ValueError(f"invalid alert priority: {priority!r}")
    return {
        "alert_id": alert_id or ("alert-" + uuid.uuid4().hex[:16]),
        "type": type,
        "text": text,
        "priority": priority,
        "dedupe_key": dedupe_key or f"{type}:{route_session_id}",
        "route_session_id": route_session_id,
        "created_at": created_at or _now_iso(),
    }


def build_route_alerts(
    session: Dict[str, Any],
    *,
    slope_limit: float,
    service_degraded: bool = False,
) -> List[Dict[str, Any]]:
    """Derive meaningful alerts for the selected route. No per-field narration."""
    sid = session["route_session_id"]
    selected = session.get("selected_route") or {}
    rid = selected.get("route_id")
    routes = session.get("available_routes") or []
    alerts: List[Dict[str, Any]] = []

    # No route under the slope limit (all known routes exceed it).
    known = [r for r in routes if r.get("exceeds_limit_distance_m") is not None]
    if known and all((r.get("exceeds_limit_distance_m") or 0) > 0 for r in known):
        alerts.append(make_alert(
            type="no_compliant_route", priority="warning", route_session_id=sid,
            text=f"No route stayed under your {slope_limit}% slope limit. Showing the least steep option.",
            dedupe_key=f"no_compliant_route:{sid}",
        ))

    # Stairs on the selected route.
    if selected.get("stairs_status") in ("confirmed", "likely"):
        confirmed = selected["stairs_status"] == "confirmed"
        alerts.append(make_alert(
            type="stairs", priority="critical", route_session_id=sid,
            text="Confirmed stairs on the selected route." if confirmed else "Likely stairs on the selected route.",
            dedupe_key=f"stairs:{sid}:{rid}",
        ))

    # Selected route exceeds slope limit.
    exceed = selected.get("exceeds_limit_distance_m")
    if exceed and exceed > 0:
        alerts.append(make_alert(
            type="steep_slope", priority="warning", route_session_id=sid,
            text=f"Selected route has about {round(exceed)} meters above your {slope_limit}% slope limit.",
            dedupe_key=f"steep_slope:{sid}:{rid}",
        ))

    # Accessible-entrance information (info -> not auto-spoken).
    place = session.get("destination_place") or {}
    if place.get("wheelchair_accessible_entrance") is True:
        alerts.append(make_alert(
            type="destination", priority="info", route_session_id=sid,
            text=f"Accessible entrance found at {place.get('place_name') or 'the destination'}.",
            dedupe_key=f"destination:{sid}",
        ))

    # Accessibility-confidence degradation (e.g. elevation unavailable).
    if service_degraded:
        alerts.append(make_alert(
            type="degraded", priority="warning", route_session_id=sid,
            text="Some accessibility data was unavailable; slope/stair confidence is reduced.",
            dedupe_key=f"degraded:{sid}",
        ))
    return alerts


def make_reroute_alert(session_id: str, new_route_id: str) -> Dict[str, Any]:
    return make_alert(
        type="reroute", priority="warning", route_session_id=session_id,
        text="Route changed. A different alternative is now selected.",
        dedupe_key=f"reroute:{session_id}:{new_route_id}",
    )


# --------------------------------------------------------------------------- #
# Pluggable store
# --------------------------------------------------------------------------- #
class RouteStore(Protocol):
    mode: str

    def save_session(self, session: Dict[str, Any]) -> Dict[str, Any]: ...
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    def save_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]: ...
    def list_session_alerts(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]: ...
    def append_event(self, event_type: str, payload: Dict[str, Any]) -> Any: ...
    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]: ...
    def claim_dedupe_key(self, key: str, ttl_seconds: int) -> bool: ...


class InMemoryRouteStore:
    """Default in-process store; replaced by a Redis-backed adapter in the backend."""

    mode = "memory"

    def __init__(self, time_fn=time.time):
        self._time = time_fn
        self._lock = threading.Lock()
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._alerts: List[Dict[str, Any]] = []
        self._events: List[Dict[str, Any]] = []
        self._dedupe: Dict[str, float] = {}

    def save_session(self, session):
        with self._lock:
            self._sessions[session["route_session_id"]] = session
        return session

    def get_session(self, session_id):
        return self._sessions.get(session_id)

    def save_alert(self, alert):
        with self._lock:
            self._alerts.append(alert)
            self._alerts = self._alerts[-500:]
        # Emit alert.created so both stores behave identically.
        self.append_event(EVENT_ALERT_CREATED, {"alert_id": alert.get("alert_id"),
                                                "route_session_id": alert.get("route_session_id")})
        return alert

    def list_session_alerts(self, session_id, limit=50):
        return [a for a in self._alerts if a.get("route_session_id") == session_id][-limit:]

    def append_event(self, event_type, payload):
        with self._lock:
            evt = {"type": event_type, "payload": payload, "created_at": _now_iso(),
                   "stream_id": f"{len(self._events) + 1}-0"}
            self._events.append(evt)
            self._events = self._events[-1000:]
        return evt["stream_id"]

    def recent_events(self, limit=50):
        return list(reversed(self._events[-limit:]))

    def claim_dedupe_key(self, key, ttl_seconds):
        now = self._time()
        with self._lock:
            exp = self._dedupe.get(key)
            if exp is not None and now < exp:
                return False
            self._dedupe[key] = now + ttl_seconds
            return True


_store: RouteStore = InMemoryRouteStore()


def set_store(store: RouteStore) -> None:
    global _store
    _store = store


def get_store() -> RouteStore:
    return _store


def reset_store() -> None:
    global _store
    _store = InMemoryRouteStore()


# --- Module-level convenience (preferred call surface) --- #
def save_session(session):
    return _store.save_session(session)


def get_session(session_id):
    return _store.get_session(session_id)


def save_alert(alert):
    return _store.save_alert(alert)


def list_session_alerts(session_id, limit=50):
    return _store.list_session_alerts(session_id, limit)


def append_event(event_type, payload):
    return _store.append_event(event_type, payload)


def recent_events(limit=50):
    return _store.recent_events(limit)


def claim_dedupe_key(key, ttl_seconds):
    return _store.claim_dedupe_key(key, ttl_seconds)


def storage_mode():
    return _store.mode
