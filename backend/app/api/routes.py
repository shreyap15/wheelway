"""
WheelWay — Routing API.

Serves the accessibility-weighted A* router (app/routing/astar.py) over HTTP.
For now the graph is the in-memory mock fixture (app/data/mock_graph.py); swap
build_mock_graph() for a PostGIS/OSM-backed loader later without touching the
endpoint contract.

A fresh graph is built per request on purpose: find_k_alternative_routes()
mutates segment lengths in place to penalize already-used edges, so a shared
graph instance would corrupt subsequent requests.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.data.mock_graph import build_mock_graph
from app.models.accessibility import RouteRequest
from app.routing.astar import (
    RouteResult,
    RouteStep,
    find_accessible_route,
    find_k_alternative_routes,
)

route_bp = Blueprint("route", __name__)


def _serialize_step(step: RouteStep) -> dict:
    return {
        "segment": step.segment.model_dump(),
        "accessibility_score": round(step.accessibility_score, 1),
        "cumulative_distance_m": step.cumulative_distance_m,
        "cumulative_cost": step.cumulative_cost,
    }


def _serialize_result(result: RouteResult) -> dict:
    return {
        "found": result.found,
        "steps": [_serialize_step(s) for s in result.steps],
        "total_distance_m": result.total_distance_m,
        "total_cost": result.total_cost,
        "average_accessibility_score": result.average_accessibility_score,
        "nodes_expanded": result.nodes_expanded,
        "failure_reason": result.failure_reason,
    }


@route_bp.post("/route")
def compute_route():
    """
    Compute an accessibility-weighted route across the (mock) graph.

    Body (JSON): RouteRequest -> { start_node_id, end_node_id, profile? }
    Query: ?k=N (optional) -> return up to N alternative routes instead of one.

    Returns 200 with the route(s), 400 on a bad body, 404 if no route exists.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Missing or invalid JSON body"}), 400

    try:
        route_request = RouteRequest(**data)
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    graph = build_mock_graph()

    k_raw = request.args.get("k")
    if k_raw is not None:
        try:
            k = int(k_raw)
        except ValueError:
            return jsonify({"error": "k must be an integer"}), 400
        if k < 1:
            return jsonify({"error": "k must be >= 1"}), 400

        routes = find_k_alternative_routes(
            graph,
            route_request.start_node_id,
            route_request.end_node_id,
            route_request.profile,
            k=k,
        )
        if not routes:
            return jsonify({"error": "No accessible route found", "routes": []}), 404
        return jsonify({"routes": [_serialize_result(r) for r in routes]})

    result = find_accessible_route(
        graph,
        route_request.start_node_id,
        route_request.end_node_id,
        route_request.profile,
    )
    if not result.found:
        return jsonify(_serialize_result(result)), 404
    return jsonify(_serialize_result(result))
