"""Route-session orchestration: persist sessions, emit events, derive alerts.

Wraps the shared ``accessroute.route_state`` layer. ALL persistence is best-effort
-- a state/alert failure never breaks the route response (the caller still
returns Mapbox geometry). Speech is decided client-side from ``auto_speak_alerts``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from accessroute import route_state

logger = logging.getLogger("wheelway.route")


def _slope_limit(result: Dict[str, Any]) -> float:
    profile = result.get("profile") or {}
    return float(profile.get("max_incline_grade") or 8.33)


def create_route_session(result: Dict[str, Any]) -> Dict[str, Any]:
    """Create + persist a session for a successful /real-route result.

    Returns the enrichment to merge into the response: route_session_id, alerts,
    auto_speak_alerts. On any failure returns a minimal stub (route still works).
    """
    try:
        routes = result.get("routes") or []
        session = route_state.make_route_session(
            origin=result.get("origin", {}),
            destination=result.get("destination", {}),
            profile=result.get("profile", {}),
            routes=routes,
            destination_place=result.get("destination_place"),
        )
        route_state.save_session(session)
        route_state.append_event(
            route_state.EVENT_ROUTE_CREATED,
            {"route_session_id": session["route_session_id"],
             "selected_route_id": session["selected_route_id"]},
        )

        logger.info(
            "[route] requested session=%s alternatives=%d",
            session["route_session_id"],
            len(routes),
        )
        logger.info(
            "[route] selected route_id=%s session=%s",
            session["selected_route_id"],
            session["route_session_id"],
        )

        alerts = route_state.build_route_alerts(
            session,
            slope_limit=_slope_limit(result),
            service_degraded=bool(result.get("service_degraded")),
        )
        for alert in alerts:
            route_state.save_alert(alert)
            # Warning text stays on the frontend; only type/priority are logged.
            logger.info(
                "[alert] type=%s priority=%s",
                alert.get("type"),
                alert.get("priority"),
            )

        auto = [a for a in alerts if a["type"] in route_state.AUTO_SPEAK_TYPES]
        return {
            "route_session_id": session["route_session_id"],
            "selected_route_id": session["selected_route_id"],
            "alerts": alerts,
            "auto_speak_alerts": auto,
        }
    except Exception as exc:  # never break the route response
        logger.warning("route-session persistence failed: %s", type(exc).__name__)
        return {"route_session_id": None, "alerts": [], "auto_speak_alerts": []}


def select_alternative(session_id: str, route_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Update the selected alternative within an existing session.

    Returns (payload, error). error in {"not_found","invalid_route"} or None.
    """
    session = route_state.get_session(session_id)
    if not session:
        return None, "not_found"
    summaries = session.get("available_routes") or []
    match = next((s for s in summaries if s.get("route_id") == route_id), None)
    if not match:
        return None, "invalid_route"

    changed = session.get("selected_route_id") != route_id
    session["selected_route_id"] = route_id
    session["selected_route"] = match
    session["updated_at"] = route_state._now_iso()
    route_state.save_session(session)
    route_state.append_event(
        route_state.EVENT_ROUTE_SELECTED,
        {"route_session_id": session_id, "selected_route_id": route_id},
    )

    logger.info("[route] selected route_id=%s session=%s", route_id, session_id)

    alerts: List[Dict[str, Any]] = []
    if changed:
        reroute = route_state.make_reroute_alert(session_id, route_id)
        route_state.save_alert(reroute)
        alerts.append(reroute)
        logger.info(
            "[alert] type=%s priority=%s",
            reroute.get("type"),
            reroute.get("priority"),
        )

    auto = [a for a in alerts if a["type"] in route_state.AUTO_SPEAK_TYPES]
    return (
        {
            "route_session_id": session_id,
            "selected_route_id": route_id,
            "selected_route": match,
            "alerts": alerts,
            "auto_speak_alerts": auto,
        },
        None,
    )
