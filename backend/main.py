import logging
import os
import sys
from pathlib import Path

from flask import Flask, jsonify
from flask_cors import CORS

# Concise terminal logging for meaningful runtime events (route/alert/speech/
# storage/gateway). Honors LOG_LEVEL; defaults to INFO. Set once at startup.
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("wheelway")

# Allow the Flask backend to reuse the sibling accessroute package (Mapbox
# walking directions + Google elevation/places enrichment, shared route state).
_ACCESSROUTE_ROOT = Path(__file__).resolve().parents[1] / "accessroute"
if str(_ACCESSROUTE_ROOT) not in sys.path:
    sys.path.insert(0, str(_ACCESSROUTE_ROOT))

from app.api.routes import route_bp
from app.api.real_route import real_route_bp
from app.api.speech import speech_bp
from app.api.observations import observations_bp
from app.api.events import events_bp
from app.api.route_sessions import route_sessions_bp
from app.services import deepgram_service, redis_service, state_store
from app.services.route_state_adapter import install as install_route_state

app = Flask(__name__)
CORS(app)

# Back the shared route-session/alert layer with the Redis-or-memory state store.
install_route_state()


def _bool_env(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _log_startup_status() -> None:
    """Log safe gateway/storage booleans once at startup (never keys or URLs)."""
    logger.info(
        "[gateway] fetchai_configured=%s mapbox_configured=%s google_enrichment=%s deepgram_configured=%s",
        str(_bool_env("ASI_ONE_API_KEY")).lower(),
        str(_bool_env("MAPBOX_ACCESS_TOKEN")).lower(),
        str(_bool_env("GOOGLE_MAPS_API_KEY")).lower(),
        str(deepgram_service.deepgram_configured()).lower(),
    )
    # Trigger the one-time backend selection so [storage] mode=... is logged.
    state_store.storage_mode()


_log_startup_status()

# /route          -> offline A* algorithm demo (synthetic Berkeley graph)
# /real-route     -> real Mapbox geometry + elevation/places enrichment + session
# /route-sessions -> select active alternative / read session
# /speak          -> Deepgram text-to-speech (audio/mpeg)
# /observations   -> live-state observations (Redis or memory)
# /events,/alerts -> durable event/alert log
app.register_blueprint(route_bp)
app.register_blueprint(real_route_bp)
app.register_blueprint(route_sessions_bp)
app.register_blueprint(speech_bp)
app.register_blueprint(observations_bp)
app.register_blueprint(events_bp)


@app.get("/")
def home():
    return jsonify({"name": "Wheelway API", "status": "running"})


@app.get("/health")
def health():
    # Safe booleans/statuses only -- never expose URLs or keys.
    mode = state_store.storage_mode()
    redis_connected = mode == "redis" and state_store.health_check()
    return jsonify(
        {
            "status": "ok",
            "storage_mode": mode,
            "redis_configured": redis_service.redis_configured(),
            "redis_connected": redis_connected,
            "deepgram_configured": deepgram_service.deepgram_configured(),
            "mapbox_configured": _bool_env("MAPBOX_ACCESS_TOKEN"),
            "google_enrichment_configured": _bool_env("GOOGLE_MAPS_API_KEY"),
            "fetchai_gateway_configured": _bool_env("ASI_ONE_API_KEY"),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
