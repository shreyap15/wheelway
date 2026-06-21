"""POST /speak -- server-side Deepgram TTS for WheelWay voice alerts.

Returns playable mp3 audio (Content-Type: audio/mpeg) on success. Requires only
text + priority; an optional dedupe_key suppresses repeats within a short TTL via
the pluggable dedupe service (swappable for Redis later, no endpoint change).

Errors (JSON): 400 invalid request · 409 duplicate suppressed ·
503 Deepgram not configured · 502 synthesis failed.
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from app.models.speech import SpeechRequest
from app.services import deepgram_service
from app.services.dedupe_service import get_dedupe

speech_bp = Blueprint("speech", __name__)
logger = logging.getLogger("wheelway.speech")

# How long a dedupe_key suppresses repeats server-side.
DEDUPE_TTL_SECONDS = 30


@speech_bp.post("/speak")
def speak():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "invalid_request", "message": "Missing or invalid JSON body."}), 400
    try:
        req = SpeechRequest(**data)
    except ValidationError as exc:
        # Sanitize: pydantic error ctx can hold non-serializable exception objects.
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return (
            jsonify({"error": "invalid_request", "message": "Invalid speech request.", "details": details}),
            400,
        )

    # Alert text is user-facing; log only priority + type (never the text/keys).
    logger.info("[speech] requested priority=%s type=%s", req.priority, req.type)

    # Configuration check before any dedupe claim (so 503 is deterministic).
    if not deepgram_service.deepgram_configured():
        logger.warning("[speech] not_configured priority=%s", req.priority)
        return (
            jsonify(
                {
                    "error": "deepgram_not_configured",
                    "message": "DEEPGRAM_API_KEY is not configured; voice synthesis unavailable.",
                }
            ),
            503,
        )

    # Optional dedupe: skip if this key was spoken within its TTL.
    if req.dedupe_key:
        if not get_dedupe().claim_dedupe_key(req.dedupe_key, DEDUPE_TTL_SECONDS):
            logger.info("[speech] duplicate_suppressed key=%s", req.dedupe_key)
            return (
                jsonify({"error": "duplicate_suppressed", "dedupe_key": req.dedupe_key}),
                409,
            )

    try:
        audio = deepgram_service.synthesize(req.text, model=req.model)
    except deepgram_service.DeepgramNotConfigured:
        logger.warning("[speech] not_configured priority=%s", req.priority)
        return jsonify({"error": "deepgram_not_configured"}), 503
    except deepgram_service.DeepgramSynthesisError as exc:
        logger.warning("[speech] failed priority=%s error=%s", req.priority, type(exc).__name__)
        return jsonify({"error": "synthesis_failed", "message": str(exc)}), 502

    logger.info("[speech] success priority=%s", req.priority)
    resp = Response(audio, mimetype=deepgram_service.AUDIO_MIME)
    resp.headers["X-Alert-Priority"] = req.priority
    resp.headers["Cache-Control"] = "no-store"
    return resp
