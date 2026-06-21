"""WheelWay live-state storage abstraction.

A single interface over two interchangeable backends:

* ``RedisBackend``  -- durable/shared state in Redis (keys + a Stream for events)
* ``MemoryBackend`` -- in-process fallback used whenever Redis is absent

Callers use the module-level functions (``save_observation`` etc.) or
``get_store()``; nothing outside this module touches the raw Redis client.
The app keeps working with Redis down -- selection falls back to memory and
route requests never depend on this layer.

Key schema (Redis):
    wheelway:observation:{id}     SETEX json     (TTL: temporary)
    wheelway:observations         LIST  json     (capped active feed)
    wheelway:route:{session_id}   SET   json     (active route session)
    wheelway:alert:{id}           SETEX json     (TTL)
    wheelway:alerts               LIST  json     (capped alert feed)
    wheelway:device:{id}:latest   SET   json     (latest device state)
    wheelway:dedupe:{key}         SET   NX EX    (short-lived dedupe)
    wheelway:events               STREAM         (durable event log)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.models.events import (
    EVENT_ALERT_CREATED,
    EVENT_DEVICE_UPDATED,
    EVENT_OBSERVATION_CREATED,
    EVENT_ROUTE_SELECTED,
    make_event,
)
from app.services import redis_service

# --- Key helpers / tunables --- #
NS = "wheelway"
OBS_KEY = f"{NS}:observation:{{id}}"
OBS_FEED = f"{NS}:observations"
ROUTE_KEY = f"{NS}:route:{{sid}}"
ALERT_KEY = f"{NS}:alert:{{id}}"
ALERT_FEED = f"{NS}:alerts"
DEVICE_KEY = f"{NS}:device:{{id}}:latest"
DEDUPE_KEY = f"{NS}:dedupe:{{key}}"
EVENT_STREAM = f"{NS}:events"

OBS_TTL_SECONDS = 3600          # temporary observations live ~1h
ALERT_TTL_SECONDS = 6 * 3600    # alerts kept ~6h
FEED_CAP = 200                  # capped active feeds
EVENT_STREAM_MAXLEN = 5000      # approximate stream cap

logger = logging.getLogger("wheelway.storage")


# --------------------------------------------------------------------------- #
# In-memory backend (fallback)
# --------------------------------------------------------------------------- #
class MemoryBackend:
    """Process-local backend with TTL semantics; used when Redis is absent."""

    mode = "memory"

    def __init__(self, time_fn=time.time):
        self._time = time_fn
        self._obs: List[Dict[str, Any]] = []        # [{expiry, value}]
        self._routes: Dict[str, Dict[str, Any]] = {}
        self._alerts: List[Dict[str, Any]] = []     # [{expiry, value}]
        self._devices: Dict[str, Dict[str, Any]] = {}
        self._dedupe: Dict[str, float] = {}         # key -> expiry epoch
        self._events: List[Dict[str, Any]] = []

    def _alive(self, entry: Dict[str, Any]) -> bool:
        exp = entry.get("expiry")
        return exp is None or self._time() < exp

    def _expiry(self, ttl: Optional[int]) -> Optional[float]:
        return self._time() + ttl if ttl else None

    # observations
    def save_observation(self, obs: Dict[str, Any], ttl: int = OBS_TTL_SECONDS) -> Dict[str, Any]:
        self._obs.append({"expiry": self._expiry(ttl), "value": obs})
        self._obs = [e for e in self._obs if self._alive(e)][-FEED_CAP:]
        self.append_event(EVENT_OBSERVATION_CREATED, {"id": obs.get("id")})
        return obs

    def list_active_observations(self, limit: int = 100) -> List[Dict[str, Any]]:
        alive = [e["value"] for e in self._obs if self._alive(e)]
        return alive[-limit:]

    # routes
    def save_active_route(self, session_id, data, event_type=EVENT_ROUTE_SELECTED):
        self._routes[session_id] = data
        self.append_event(event_type, {"route_session_id": session_id})
        return data

    def get_active_route(self, session_id):
        return self._routes.get(session_id)

    # route sessions (event-free; the shared layer controls event emission)
    def save_route_session(self, session_id, data):
        self._routes[session_id] = data
        return data

    def get_route_session(self, session_id):
        return self._routes.get(session_id)

    # alerts
    def save_alert(self, alert: Dict[str, Any], ttl: int = ALERT_TTL_SECONDS):
        self._alerts.append({"expiry": self._expiry(ttl), "value": alert})
        self._alerts = [e for e in self._alerts if self._alive(e)][-FEED_CAP:]
        self.append_event(EVENT_ALERT_CREATED, {"alert_id": alert.get("alert_id")})
        return alert

    def get_alert(self, alert_id):
        for e in self._alerts:
            if self._alive(e) and e["value"].get("alert_id") == alert_id:
                return e["value"]
        return None

    def list_alerts(self, limit: int = 100):
        return [e["value"] for e in self._alerts if self._alive(e)][-limit:]

    # device state
    def save_device_state(self, device_id, data):
        self._devices[device_id] = data
        self.append_event(EVENT_DEVICE_UPDATED, {"device_id": device_id})
        return data

    def get_device_state(self, device_id):
        return self._devices.get(device_id)

    # events
    def append_event(self, event_type, payload):
        event = make_event(event_type, payload)
        event["stream_id"] = f"{len(self._events) + 1}-0"
        self._events.append(event)
        self._events = self._events[-EVENT_STREAM_MAXLEN:]
        return event["stream_id"]

    def list_events(self, limit: int = 100):
        return list(reversed(self._events[-limit:]))

    # dedupe
    def claim_dedupe_key(self, key: str, ttl_seconds: int) -> bool:
        now = self._time()
        exp = self._dedupe.get(key)
        if exp is not None and now < exp:
            return False
        self._dedupe[key] = now + ttl_seconds
        return True

    def health_check(self) -> bool:
        return True


# --------------------------------------------------------------------------- #
# Redis backend
# --------------------------------------------------------------------------- #
class RedisBackend:
    """Durable/shared backend. Uses keys with TTLs + a Redis Stream for events."""

    mode = "redis"

    def __init__(self, client):
        self._r = client

    # observations
    def save_observation(self, obs: Dict[str, Any], ttl: int = OBS_TTL_SECONDS) -> Dict[str, Any]:
        blob = json.dumps(obs)
        self._r.setex(OBS_KEY.format(id=obs.get("id")), ttl, blob)
        self._r.lpush(OBS_FEED, blob)
        self._r.ltrim(OBS_FEED, 0, FEED_CAP - 1)
        self.append_event(EVENT_OBSERVATION_CREATED, {"id": obs.get("id")})
        return obs

    def list_active_observations(self, limit: int = 100) -> List[Dict[str, Any]]:
        # LPUSH stores newest-first; reverse to ascending (oldest->newest) to
        # preserve the existing GET /observations contract.
        rows = self._r.lrange(OBS_FEED, 0, limit - 1) or []
        return [json.loads(x) for x in reversed(rows)]

    # routes
    def save_active_route(self, session_id, data, event_type=EVENT_ROUTE_SELECTED):
        self._r.set(ROUTE_KEY.format(sid=session_id), json.dumps(data))
        self.append_event(event_type, {"route_session_id": session_id})
        return data

    def get_active_route(self, session_id):
        raw = self._r.get(ROUTE_KEY.format(sid=session_id))
        return json.loads(raw) if raw else None

    # route sessions (event-free; the shared layer controls event emission)
    def save_route_session(self, session_id, data):
        self._r.set(ROUTE_KEY.format(sid=session_id), json.dumps(data))
        return data

    def get_route_session(self, session_id):
        raw = self._r.get(ROUTE_KEY.format(sid=session_id))
        return json.loads(raw) if raw else None

    # alerts
    def save_alert(self, alert: Dict[str, Any], ttl: int = ALERT_TTL_SECONDS):
        blob = json.dumps(alert)
        self._r.setex(ALERT_KEY.format(id=alert.get("alert_id")), ttl, blob)
        self._r.lpush(ALERT_FEED, blob)
        self._r.ltrim(ALERT_FEED, 0, FEED_CAP - 1)
        self.append_event(EVENT_ALERT_CREATED, {"alert_id": alert.get("alert_id")})
        return alert

    def get_alert(self, alert_id):
        raw = self._r.get(ALERT_KEY.format(id=alert_id))
        return json.loads(raw) if raw else None

    def list_alerts(self, limit: int = 100):
        rows = self._r.lrange(ALERT_FEED, 0, limit - 1) or []
        return [json.loads(x) for x in rows]

    # device state
    def save_device_state(self, device_id, data):
        self._r.set(DEVICE_KEY.format(id=device_id), json.dumps(data))
        self.append_event(EVENT_DEVICE_UPDATED, {"device_id": device_id})
        return data

    def get_device_state(self, device_id):
        raw = self._r.get(DEVICE_KEY.format(id=device_id))
        return json.loads(raw) if raw else None

    # events (durable Stream)
    def append_event(self, event_type, payload):
        event = make_event(event_type, payload)
        return self._r.xadd(
            EVENT_STREAM,
            {"event": json.dumps(event)},
            maxlen=EVENT_STREAM_MAXLEN,
            approximate=True,
        )

    def list_events(self, limit: int = 100):
        rows = self._r.xrevrange(EVENT_STREAM, count=limit) or []
        out = []
        for stream_id, fields in rows:
            event = json.loads(fields["event"])
            event["stream_id"] = stream_id
            out.append(event)
        return out

    # dedupe
    def claim_dedupe_key(self, key: str, ttl_seconds: int) -> bool:
        ok = self._r.set(DEDUPE_KEY.format(key=key), "1", nx=True, ex=ttl_seconds)
        return bool(ok)

    def health_check(self) -> bool:
        return redis_service.ping(self._r)


# --------------------------------------------------------------------------- #
# Singleton selection
# --------------------------------------------------------------------------- #
_store = None


def get_store():
    """Return the active store, selecting the backend once.

    Redis is used only when configured AND reachable; otherwise memory. A
    transient Redis failure at selection time degrades to memory rather than
    raising, so route requests are never blocked by this layer.
    """
    global _store
    if _store is not None:
        return _store
    client = redis_service.create_client()
    if client is not None and redis_service.ping(client):
        _store = RedisBackend(client)
        logger.info("[storage] mode=redis redis_connected=true")
    else:
        _store = MemoryBackend()
        # redis_configured but not reachable -> memory fallback.
        logger.info(
            "[storage] mode=memory redis_connected=false redis_configured=%s",
            str(redis_service.redis_configured()).lower(),
        )
    return _store


def set_store(store) -> None:
    """Override the active store (tests / explicit wiring)."""
    global _store
    _store = store


def reset_store() -> None:
    global _store
    _store = None


def storage_mode() -> str:
    return get_store().mode


# --- Module-level interface (preferred call surface) --- #
def save_observation(obs, ttl: int = OBS_TTL_SECONDS):
    return get_store().save_observation(obs, ttl)


def list_active_observations(limit: int = 100):
    return get_store().list_active_observations(limit)


def save_active_route(session_id, data, event_type=EVENT_ROUTE_SELECTED):
    return get_store().save_active_route(session_id, data, event_type)


def get_active_route(session_id):
    return get_store().get_active_route(session_id)


def save_alert(alert, ttl: int = ALERT_TTL_SECONDS):
    return get_store().save_alert(alert, ttl)


def get_alert(alert_id):
    return get_store().get_alert(alert_id)


def save_device_state(device_id, data):
    return get_store().save_device_state(device_id, data)


def append_event(event_type, payload):
    return get_store().append_event(event_type, payload)


def list_events(limit: int = 100):
    return get_store().list_events(limit)


def list_alerts(limit: int = 100):
    return get_store().list_alerts(limit)


def claim_dedupe_key(key: str, ttl_seconds: int) -> bool:
    return get_store().claim_dedupe_key(key, ttl_seconds)


def health_check() -> bool:
    return get_store().health_check()


def new_session_id() -> str:
    return uuid.uuid4().hex
