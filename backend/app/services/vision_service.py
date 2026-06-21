"""Derive concise WheelWay alerts from a normalized vision_modal observation.

Severity comes mainly from the upstream avoidance command, TTC, collision risk,
and danger-corridor status (§7). The FULL technical observation is stored as-is
by the caller; here we only produce a short, user-facing alert and claim a stable
dedupe key so the same hazard is not re-alerted. Speech is decided client-side
(the frontend reads ``auto_speak`` and calls /speak), so a Deepgram failure can
never reject an observation.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from accessroute import route_state
from app.services import state_store

logger = logging.getLogger("wheelway.vision")

ALERT_DEDUPE_TTL_SECONDS = 30

# Thresholds for promoting a steering command to critical. Reconciled with the
# Pi-side WHEELWAY_*_TTC envs; safe defaults when unset.
WARNING_TTC = float(os.getenv("WHEELWAY_WARNING_TTC_SECONDS", "3") or 3)
CRITICAL_TTC = float(os.getenv("WHEELWAY_CRITICAL_TTC_SECONDS", "1.5") or 1.5)
CRITICAL_RISK = 0.8

# User-facing text -- no track ids, probabilities, or physics terms.
TEXT = {
    "collision_risk": "Stop. Collision risk ahead.",
    "avoid_left": "Obstacle approaching. Move left.",
    "avoid_right": "Obstacle approaching. Move right.",
    "vision_offline": "Camera obstacle detection is unavailable.",
}


def _is_critical_steer(ttc: Optional[float], risk: Optional[float]) -> bool:
    if ttc is not None and ttc <= CRITICAL_TTC:
        return True
    if risk is not None and risk >= CRITICAL_RISK:
        return True
    return False


def derive_alert(obs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map a normalized vision observation to (type, priority, text, dedupe_key).

    Returns the alert spec dict, or None when no hazard alert is warranted
    (CLEAR, or a healthy heartbeat). Does not persist anything.
    """
    device_id = str(obs.get("device_id") or "wheelway-pi")
    feature_type = obs.get("feature_type")
    action = obs.get("avoidance_action")
    track_id = obs.get("track_id")
    ttc = obs.get("time_to_collision_s")
    risk = obs.get("collision_risk")

    # Camera/model failure heartbeat -> offline warning.
    if feature_type == "camera_status":
        camera_online = obs.get("camera_online", True)
        detector_online = obs.get("detector_online", True)
        if camera_online is False or detector_online is False:
            return {
                "type": "vision_offline",
                "priority": "warning",
                "text": TEXT["vision_offline"],
                "dedupe_key": f"vision-offline:{device_id}",
            }
        return None  # healthy heartbeat -> no reactive alert

    if action == "STOP":
        return {
            "type": "collision_risk",
            "priority": "critical",
            "text": TEXT["collision_risk"],
            "dedupe_key": f"vision-stop:{device_id}:{track_id}",
        }
    if action in ("LEFT", "RIGHT"):
        critical = _is_critical_steer(ttc, risk)
        side = "left" if action == "LEFT" else "right"
        return {
            "type": f"avoid_{side}",
            "priority": "critical" if critical else "warning",
            "text": TEXT[f"avoid_{side}"],
            "dedupe_key": f"vision-{side}:{device_id}:{track_id}",
        }
    # CLEAR -> no hazard alert (frontend debounces the banner away itself).
    return None


def ingest_vision_observation(obs: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a hazard alert (deduped) for a stored vision observation.

    Returns enrichment: {"alert": <alert|None>, "auto_speak": bool, "duplicate": bool}.
    Best-effort -- never raises, so observation ingestion is unaffected.
    """
    try:
        spec = derive_alert(obs)
    except Exception as exc:  # never break ingestion
        logger.warning("[vision] alert derivation failed: %s", type(exc).__name__)
        return {"alert": None, "auto_speak": False, "duplicate": False}

    if spec is None:
        return {"alert": None, "auto_speak": False, "duplicate": False}

    # Dedupe so the same hazard/track is not re-alerted within the TTL.
    if not state_store.claim_dedupe_key(spec["dedupe_key"], ALERT_DEDUPE_TTL_SECONDS):
        logger.info("[vision] alert_suppressed type=%s key=%s", spec["type"], spec["dedupe_key"])
        return {"alert": None, "auto_speak": False, "duplicate": True}

    alert = route_state.make_alert(
        type=spec["type"],
        text=spec["text"],
        route_session_id=obs.get("route_session_id"),  # None for local camera hazards
        priority=spec["priority"],
        dedupe_key=spec["dedupe_key"],
    )
    try:
        route_state.save_alert(alert)
    except Exception as exc:  # never break ingestion
        logger.warning("[vision] save_alert failed: %s", type(exc).__name__)

    logger.info("[alert] type=%s priority=%s source=vision_modal", alert["type"], alert["priority"])
    return {
        "alert": alert,
        "auto_speak": spec["type"] in route_state.AUTO_SPEAK_TYPES,
        "duplicate": False,
    }
