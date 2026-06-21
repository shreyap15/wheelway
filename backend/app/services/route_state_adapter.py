"""Adapter: back the shared ``accessroute.route_state`` store with Redis.

Wraps the backend ``state_store`` (Redis or memory) so the canonical route-session
layer persists through the SAME abstraction the rest of the app uses. The shared
layer never imports the raw Redis client -- it only sees this RouteStore.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services import state_store


class RedisRouteStoreAdapter:
    """Implements accessroute.route_state.RouteStore over backend state_store."""

    @property
    def mode(self) -> str:
        return state_store.storage_mode()

    def save_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        return state_store.save_route_session(session["route_session_id"], session)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return state_store.get_route_session(session_id)

    def save_alert(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        # state_store.save_alert emits alert.created (matches in-memory store).
        return state_store.save_alert(alert)

    def list_session_alerts(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        alerts = state_store.list_alerts(500)
        return [a for a in alerts if a.get("route_session_id") == session_id][-limit:]

    def append_event(self, event_type: str, payload: Dict[str, Any]):
        return state_store.append_event(event_type, payload)

    def recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        return state_store.list_events(limit)

    def claim_dedupe_key(self, key: str, ttl_seconds: int) -> bool:
        return state_store.claim_dedupe_key(key, ttl_seconds)


def install() -> None:
    """Point the shared route-state layer at the Redis-backed adapter."""
    from accessroute import route_state

    route_state.set_store(RedisRouteStoreAdapter())
