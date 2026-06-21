"""Observation endpoints, routed through the live-state storage abstraction.

Preserves the existing request contract (POST/GET /observations, POST /simulate)
while persisting through ``state_store`` so observations survive in Redis when
configured and fall back to memory otherwise. No routing/pipeline code here.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.models.observations import make_observation
from app.services import state_store

observations_bp = Blueprint("observations", __name__)


@observations_bp.post("/observations")
def receive_observation():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
    obs = make_observation(data)
    state_store.save_observation(obs)
    return jsonify(obs), 201


@observations_bp.get("/observations")
def get_observations():
    return jsonify(state_store.list_active_observations(100))


@observations_bp.post("/simulate")
def simulate():
    """Temporary stand-in for the Raspberry Pi ultrasonic sensor."""
    distance_cm = round(random.uniform(20, 300), 1)
    if distance_cm < 40:
        level, message = "critical", "Stop. Obstacle immediately ahead."
    elif distance_cm < 100:
        level, message = "warning", "Obstacle nearby."
    elif distance_cm < 200:
        level, message = "notice", "Object detected ahead."
    else:
        level, message = "clear", "Path appears clear."

    obs = make_observation(
        {
            "device_id": "simulated-pi",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "distance_cm": distance_cm,
            "alert_level": level,
            "alert_message": message,
        }
    )
    state_store.save_observation(obs)
    return jsonify(obs)
