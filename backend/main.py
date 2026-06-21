from datetime import datetime, timezone
import random

from flask import Flask, jsonify, request
from flask_cors import CORS

from app.api.routes import route_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(route_bp)

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