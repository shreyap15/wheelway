"""Route-session endpoints: select an alternative, read the active session.

Updates the SAME route session (no new unrelated session) and appends a
route.selected event + reroute alert. Isolated from routing/pipeline code.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from accessroute import route_state
from app.services import session_service

route_sessions_bp = Blueprint("route_sessions", __name__)


@route_sessions_bp.post("/route-sessions/<session_id>/select")
def select_route(session_id):
    data = request.get_json(silent=True) or {}
    route_id = data.get("route_id")
    if not route_id:
        return jsonify({"error": "invalid_request", "message": "route_id is required"}), 400

    payload, error = session_service.select_alternative(session_id, route_id)
    if error == "not_found":
        return jsonify({"error": "session_not_found", "route_session_id": session_id}), 404
    if error == "invalid_route":
        return jsonify({"error": "invalid_route", "message": "route_id not in this session"}), 400
    return jsonify(payload)


@route_sessions_bp.get("/route-sessions/<session_id>")
def get_route_session(session_id):
    session = route_state.get_session(session_id)
    if not session:
        return jsonify({"error": "session_not_found", "route_session_id": session_id}), 404
    return jsonify(
        {
            "session": session,
            "alerts": route_state.list_session_alerts(session_id),
        }
    )
