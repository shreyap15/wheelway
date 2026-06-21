"""Adapter: upstream vision_modal objects -> canonical WheelWay observation dict.

Deliberately upstream-free: it reads only documented attributes
(``track.id/.label/.score/.bbox/.state``, ``risk.ttc/.risk/.in_corridor/...``,
``command.action/.steer``), so it is unit-testable with lightweight stand-ins and
never imports the perception/physics packages. WheelWay depends on this snapshot,
never on internal upstream classes.

Honesty rules enforced here:
* monocular looming is a RELATIVE cue (``looming_is_relative=True``); never metric.
* infinite / unavailable TTC -> ``None`` (never a fake number).
* trajectory points are 0-1 NORMALIZED image coordinates (documented), bounded
  to a compact sample count.
* no raw frames, keys, or unbounded arrays.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence

# Upstream 6-D image-plane state layout [x, y, s, vx, vy, vs] (physics/state.py).
X, Y, S, VS = 0, 1, 2, 5

MAX_TRAJECTORY_POINTS = 8
MAX_OTHER_RISKS = 5


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _ttc_or_none(ttc: Any) -> Optional[float]:
    f = _finite(ttc)
    if f is None or f < 0:
        return None
    return round(f, 2)


def _looming(state: Sequence[float]) -> Optional[float]:
    """Relative looming cue = fractional bbox-scale expansion rate (ds/dt)/s.

    Dimensionless (~1/TTC), >0 == approaching. NOT metric depth.
    """
    try:
        s = float(state[S])
        vs = float(state[VS])
    except (TypeError, ValueError, IndexError):
        return None
    if not (math.isfinite(s) and math.isfinite(vs)) or s <= 1e-6:
        return None
    return round(max(0.0, vs / s), 4)


def _bbox(track, frame_w: int, frame_h: int):
    try:
        x1, y1, x2, y2 = track.bbox
    except Exception:
        return None
    xi1, yi1 = int(round(x1)), int(round(y1))
    xi2, yi2 = int(round(x2)), int(round(y2))
    # Clamp to frame and keep a valid (x_max>x_min, y_max>y_min) box.
    xi1 = max(0, min(xi1, frame_w - 1))
    yi1 = max(0, min(yi1, frame_h - 1))
    xi2 = max(xi1 + 1, min(xi2, frame_w))
    yi2 = max(yi1 + 1, min(yi2, frame_h))
    return {"x_min": xi1, "y_min": yi1, "x_max": xi2, "y_max": yi2}


def _trajectory(traj: Sequence, frame_w: int, frame_h: int, horizon_s: float) -> List[dict]:
    if not traj:
        return []
    n = len(traj)
    # Subsample evenly to a compact representation.
    if n > MAX_TRAJECTORY_POINTS:
        idx = [round(i * (n - 1) / (MAX_TRAJECTORY_POINTS - 1)) for i in range(MAX_TRAJECTORY_POINTS)]
    else:
        idx = list(range(n))
    dt = horizon_s / max(n, 1)
    out = []
    for i in idx:
        pt = traj[i]
        try:
            x = float(pt[X]) / max(frame_w, 1)
            y = float(pt[Y]) / max(frame_h, 1)
        except (TypeError, ValueError, IndexError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        out.append({
            "t_s": round((i + 1) * dt, 3),
            "x": round(min(max(x, 0.0), 1.0), 4),
            "y": round(min(max(y, 0.0), 1.0), 4),
        })
    return out


def _reason(action: str, label: Optional[str]) -> str:
    obj = label or "obstacle"
    if action == "STOP":
        return f"{obj} entering danger corridor"
    if action == "LEFT":   # obstacle on the right -> move left
        return f"{obj} approaching from the right"
    if action == "RIGHT":  # obstacle on the left -> move right
        return f"{obj} approaching from the left"
    return "path clear"


def select_top_risk(tracks: Sequence, risks: Sequence, trajectories: Sequence, risk_threshold: float):
    """Pick the (track, risk, traj) that drives the command -- mirrors upstream
    ``avoidance.decide``: highest-risk in-corridor hazard, else highest risk."""
    triples = list(zip(tracks, risks, trajectories))
    if not triples:
        return None
    hazards = [t for t in triples if getattr(t[1], "in_corridor", False)
               and _finite(getattr(t[1], "risk", 0.0)) is not None
               and float(t[1].risk) >= risk_threshold]
    pool = hazards or triples
    return max(pool, key=lambda t: _finite(getattr(t[1], "risk", 0.0)) or 0.0)


def build_observation(
    *,
    command,
    tracks: Sequence,
    risks: Sequence,
    trajectories: Sequence,
    frame_width: int,
    frame_height: int,
    timestamp: Optional[str] = None,
    scene: Any = None,
    device_id: str = "wheelway-pi-01",
    model: str = "efficientdet_lite0",
    pipeline_version: str = "vision-modal",
    risk_threshold: float = 0.5,
    predict_horizon_s: float = 1.0,
) -> dict:
    """Build the canonical WheelWay vision observation (top-risk track + context)."""
    action = getattr(command, "action", "CLEAR")
    top = select_top_risk(tracks, risks, trajectories, risk_threshold)

    obs = {
        "device_id": device_id,
        "timestamp": timestamp or _iso_now(),
        "source": "vision_modal",
        "route_session_id": None,
        "latitude": None,
        "longitude": None,
        "feature_type": "dynamic_obstacle",
        "object_label": None,
        "confidence": None,
        "track_id": None,
        "bounding_box": None,
        "looming": None,
        "looming_is_relative": True,
        "time_to_collision_s": None,
        "collision_risk": None,
        "in_danger_corridor": False,
        "predicted_trajectory": [],
        "avoidance_action": action,
        "steer_vector": {"x": round(_finite(getattr(command, "steer", 0.0)) or 0.0, 4), "y": 0.0},
        "avoidance_reason": _reason(action, None),
        "scene_summary": None,
        "scene_summary_age_s": None,
        "frame_width": int(frame_width),
        "frame_height": int(frame_height),
        "model": model,
        "pipeline_version": pipeline_version,
    }

    if top is not None:
        track, risk, traj = top
        label = getattr(track, "label", None)
        obs.update({
            "object_label": label,
            "confidence": round(_finite(getattr(track, "score", None)) or 0.0, 4)
            if _finite(getattr(track, "score", None)) is not None else None,
            "track_id": getattr(track, "id", None),
            "bounding_box": _bbox(track, frame_width, frame_height),
            "looming": _looming(getattr(track, "state", [])),
            "time_to_collision_s": _ttc_or_none(getattr(risk, "ttc", None)),
            "collision_risk": round(min(max(_finite(getattr(risk, "risk", 0.0)) or 0.0, 0.0), 1.0), 4),
            "in_danger_corridor": bool(getattr(risk, "in_corridor", False)),
            "predicted_trajectory": _trajectory(traj, frame_width, frame_height, predict_horizon_s),
            "avoidance_reason": _reason(action, label),
        })

        # Compact array of OTHER active in-corridor risks (bounded).
        others = []
        for t, r, _tr in zip(tracks, risks, trajectories):
            if t is track:
                continue
            if getattr(r, "in_corridor", False) and (_finite(getattr(r, "risk", 0.0)) or 0.0) >= risk_threshold:
                others.append({
                    "track_id": getattr(t, "id", None),
                    "object_label": getattr(t, "label", None),
                    "collision_risk": round(_finite(getattr(r, "risk", 0.0)) or 0.0, 4),
                    "time_to_collision_s": _ttc_or_none(getattr(r, "ttc", None)),
                })
        if others:
            obs["other_active_risks"] = others[:MAX_OTHER_RISKS]

    # Optional scene reasoning enrichment (off the hot path; never overrides command).
    if scene is not None:
        ok = bool(getattr(scene, "ok", False))
        text = getattr(scene, "scene", None)
        if ok and text:
            obs["scene_summary"] = text[:600]
            age = getattr(scene, "age", lambda: None)()
            obs["scene_summary_age_s"] = round(age, 2) if (age is not None and math.isfinite(age)) else None

    return obs


def build_heartbeat(status: dict, *, device_id: str, pipeline_version: str = "vision-modal",
                    model: str = "efficientdet_lite0", timestamp: Optional[str] = None) -> dict:
    """Compact camera_status heartbeat carrying device liveness (no hazard)."""
    return {
        "device_id": device_id,
        "timestamp": timestamp or _iso_now(),
        "source": "vision_modal",
        "feature_type": "camera_status",
        "avoidance_action": status.get("current_action", "CLEAR"),
        "camera_online": bool(status.get("camera_online", False)),
        "detector_online": bool(status.get("detector_online", False)),
        "publisher_online": bool(status.get("publisher_online", False)),
        "model": model,
        "pipeline_version": pipeline_version,
    }
