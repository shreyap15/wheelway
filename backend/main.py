from datetime import datetime, timezone
import random
import sys
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

# Allow the Flask backend to reuse the sibling accessroute package (Mapbox
# walking directions + Google elevation/places enrichment). Added once here so
# every blueprint import resolves regardless of CWD.
_ACCESSROUTE_ROOT = Path(__file__).resolve().parents[1] / "accessroute"
if str(_ACCESSROUTE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ACCESSROUTE_ROOT))

from app.api.routes import route_bp
from app.api.real_route import real_route_bp
from app.api.speech import speech_bp

app = Flask(__name__)
CORS(app)

# /route        -> offline A* algorithm demo (synthetic Berkeley graph)
# /real-route   -> real Mapbox walking geometry + elevation/places enrichment
# /speak        -> Deepgram text-to-speech for voice alerts (audio/mpeg)
app.register_blueprint(route_bp)
app.register_blueprint(real_route_bp)
app.register_blueprint(speech_bp)

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
