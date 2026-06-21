from datetime import datetime, timezone
import random
import sys
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

# Allow Flask backend to reuse the accessroute Mapbox directions engine.
_ACCESSROUTE_ROOT = Path(__file__).resolve().parents[1] / "accessroute"
if str(_ACCESSROUTE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ACCESSROUTE_ROOT))

from accessroute.main import build_route_candidates
from accessroute.schemas import LatLng, RouteEvaluationRequest, WheelchairProfile

app = Flask(__name__)
CORS(app)

observations = []


@app.get("/")
def home():
    return jsonify({
        "name": "Wheelway API",
        "status": "running"
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/routes/mapbox")
def get_mapbox_routes():
    """Fetch Mapbox walking candidates using the shared accessroute engine."""
    data = request.get_json(silent=True) or {}
    origin = data.get("origin") or {}
    destination = data.get("destination") or {}

    try:
        route_request = RouteEvaluationRequest(
            session_id=data.get("session_id", "backend-session"),
            origin=LatLng(
                lat=float(origin.get("lat")),
                lng=float(origin.get("lng")),
            ),
            destination=LatLng(
                lat=float(destination.get("lat")),
                lng=float(destination.get("lng")),
            ),
            profile=WheelchairProfile(device_type=data.get("device_type", "power")),
            travel_mode=data.get("travel_mode", "WALK"),
        )
        candidates = build_route_candidates(route_request)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(candidates.dict())


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