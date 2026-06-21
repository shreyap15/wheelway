"""Read-only event/alert endpoints over the durable live-state log.

GET /events  -- recent durable events (Redis Stream, newest first)
GET /alerts  -- recent stored alerts
Isolated from routing code; reads only via ``state_store``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services import state_store

events_bp = Blueprint("events", __name__)


def _limit(default: int = 100, cap: int = 500) -> int:
    try:
        return max(1, min(cap, int(request.args.get("limit", default))))
    except (TypeError, ValueError):
        return default


@events_bp.get("/events")
def get_events():
    return jsonify(state_store.list_events(_limit()))


@events_bp.get("/alerts")
def get_alerts():
    return jsonify(state_store.list_alerts(_limit()))
