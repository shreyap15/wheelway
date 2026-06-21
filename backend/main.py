from datetime import datetime, timezone
import random

from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import ValidationError

from app.data.mock_graph import build_mock_graph
from app.models.accessibility import RouteRequest, UserMobilityProfile
from app.routing.astar import find_accessible_route

app = Flask(__name__)
CORS(app)

observations = []
route_graph = build_mock_graph()


def route_result_payload(result):
    segments = []

    for step in result.steps:
        segment = step.segment.model_dump(mode="json")
        segment["accessibility_score"] = step.accessibility_score
        segment["cumulative_distance_m"] = step.cumulative_distance_m
        segment["cumulative_cost"] = step.cumulative_cost
        segments.append(segment)

    return {
        "found": result.found,
        "segments": segments,
        "total_distance_m": result.total_distance_m,
        "total_cost": result.total_cost,
        "average_accessibility_score": result.average_accessibility_score,
        "nodes_expanded": result.nodes_expanded,
        "failure_reason": result.failure_reason,
    }


@app.get("/")
def home():
    return jsonify({
        "name": "Wheelway API",
        "status": "running"
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/routes/demo")
def get_demo_route():
    result = find_accessible_route(route_graph, "A1", "D2", UserMobilityProfile())
    return jsonify(route_result_payload(result))


@app.post("/routes/accessible")
def get_accessible_route():
    data = request.get_json(silent=True) or {}

    try:
        route_request = RouteRequest(**data)
    except ValidationError as error:
        return jsonify({"error": "Invalid route request", "details": error.errors()}), 400

    result = find_accessible_route(
        route_graph,
        route_request.start_node_id,
        route_request.end_node_id,
        route_request.profile,
    )

    status = 200 if result.found else 404
    return jsonify(route_result_payload(result)), status


@app.post("/simulate")
def simulate():
    distance_cm = round(random.uniform(20, 300), 1)

    if distance_cm < 40:
        alert_level = "critical"
        alert_message = "Stop. Obstacle immediately ahead."
    elif distance_cm < 100:
        alert_level = "warning"
        alert_message = "Obstacle nearby."
    elif distance_cm < 200:
        alert_level = "notice"
        alert_message = "Object detected ahead."
    else:
        alert_level = "clear"
        alert_message = "Path appears clear."

    observation = {
        "device_id": "simulated-pi",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "distance_cm": distance_cm,
        "alert_level": alert_level,
        "alert_message": alert_message
    }

    observations.append(observation)
    return jsonify(observation)


@app.post("/observations")
def receive_observation():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    observations.append(data)
    return jsonify(data), 201


@app.get("/observations")
def get_observations():
    return jsonify(observations[-100:])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)