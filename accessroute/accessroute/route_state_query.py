"""Read-only questions about the active route session, for Fetch.ai/Agentverse.

The orchestrator/mailbox calls these to explain the active route WITHOUT querying
Redis directly and without duplicating routing logic -- everything reads through
the shared ``route_state`` abstraction (Redis-backed when the host process
installs the adapter, in-memory otherwise).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from accessroute import route_state


def get_active_route(session_id: str) -> Optional[Dict[str, Any]]:
    return route_state.get_session(session_id)


def why_chosen(session_id: str) -> List[str]:
    s = route_state.get_session(session_id)
    sel = (s or {}).get("selected_route") or {}
    return sel.get("selection_reasons", [])


def steepest_section(session_id: str) -> Optional[Dict[str, Any]]:
    s = route_state.get_session(session_id)
    sel = (s or {}).get("selected_route")
    if not sel:
        return None
    return {
        "max_slope_pct": sel.get("max_slope_pct"),
        "exceeds_limit_distance_m": sel.get("exceeds_limit_distance_m"),
        "exceeds_limit_percentage": sel.get("exceeds_limit_percentage"),
    }


def stair_status(session_id: str) -> Optional[str]:
    s = route_state.get_session(session_id)
    sel = (s or {}).get("selected_route") or {}
    return sel.get("stairs_status")


def accessible_entrance(session_id: str) -> Optional[Dict[str, Any]]:
    s = route_state.get_session(session_id)
    return (s or {}).get("destination_place")


def active_alerts(session_id: str) -> List[Dict[str, Any]]:
    return route_state.list_session_alerts(session_id)


def answer_route_questions(session_id: str) -> Dict[str, Any]:
    """Bundle the canonical Fetch.ai answers for one route session."""
    session = route_state.get_session(session_id)
    if not session:
        return {"found": False, "route_session_id": session_id}
    return {
        "found": True,
        "route_session_id": session_id,
        "selected_route_id": session.get("selected_route_id"),
        "why_chosen": why_chosen(session_id),
        "steepest_section": steepest_section(session_id),
        "stair_status": stair_status(session_id),
        "accessible_entrance": accessible_entrance(session_id),
        "active_alerts": active_alerts(session_id),
    }
