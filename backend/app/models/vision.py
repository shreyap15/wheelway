"""Validation + normalization for `source=vision_modal` observations.

These come from the Raspberry Pi obstacle-detection pipeline (the upstream
``vision_modal`` project) via the WheelWay bridge. Monocular looming is a
RELATIVE cue, never metric depth -- we validate ranges/shape but never require a
meter/centimeter distance.

`normalize_vision_observation` raises ``ValueError`` on a hard contract
violation (the endpoint maps that to HTTP 400); other observation sources are
untouched (backward compatible).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

SOURCE = "vision_modal"

# Known avoidance actions from upstream planning/avoidance.Command.action.
AVOIDANCE_ACTIONS = {"STOP", "LEFT", "RIGHT", "CLEAR"}
# Hazard observations vs periodic camera heartbeats.
FEATURE_TYPES = {"dynamic_obstacle", "camera_status"}

MAX_TRAJECTORY_POINTS = 16
MAX_OTHER_RISKS = 8
MAX_LABEL_LEN = 64
MAX_REASON_LEN = 240
MAX_SCENE_LEN = 600
MAX_FRAME_DIM = 8192


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite")
    return f


def _unit_or_none(value: Any, name: str) -> Optional[float]:
    if value is None:
        return None
    f = _finite_number(value, name)
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"{name} must be between 0 and 1")
    return f


def _nonneg_or_none(value: Any, name: str) -> Optional[float]:
    """Nonnegative finite number, or None. Used for TTC (null when inf/unknown)."""
    if value is None:
        return None
    # A JSON Infinity may arrive as a string or float('inf'); treat as null.
    if isinstance(value, str) and value.strip().lower() in {"inf", "infinity", "+inf"}:
        return None
    if isinstance(value, float) and math.isinf(value):
        return None
    f = _finite_number(value, name)
    if f < 0:
        raise ValueError(f"{name} must be nonnegative")
    return f


def _clean_text(value: Any, name: str, max_len: int) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value[:max_len]


def _validate_bbox(bbox: Any) -> Optional[Dict[str, int]]:
    if bbox is None:
        return None
    if not isinstance(bbox, dict):
        raise ValueError("bounding_box must be an object")
    try:
        x_min = int(bbox["x_min"]); y_min = int(bbox["y_min"])
        x_max = int(bbox["x_max"]); y_max = int(bbox["y_max"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("bounding_box requires integer x_min,y_min,x_max,y_max")
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("bounding_box must have x_max>x_min and y_max>y_min")
    return {"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max}


def _validate_trajectory(traj: Any) -> List[Dict[str, float]]:
    if traj is None:
        return []
    if not isinstance(traj, list):
        raise ValueError("predicted_trajectory must be a list")
    out: List[Dict[str, float]] = []
    for point in traj[:MAX_TRAJECTORY_POINTS]:  # bound length
        if not isinstance(point, dict):
            raise ValueError("trajectory points must be objects")
        t_s = _finite_number(point.get("t_s", 0.0), "trajectory.t_s")
        x = _finite_number(point.get("x"), "trajectory.x")
        y = _finite_number(point.get("y"), "trajectory.y")
        out.append({"t_s": round(t_s, 3), "x": round(x, 4), "y": round(y, 4)})
    return out


def _validate_steer(steer: Any) -> Optional[Dict[str, float]]:
    if steer is None:
        return None
    if not isinstance(steer, dict):
        raise ValueError("steer_vector must be an object")
    return {
        "x": round(_finite_number(steer.get("x", 0.0), "steer_vector.x"), 4),
        "y": round(_finite_number(steer.get("y", 0.0), "steer_vector.y"), 4),
    }


def _validate_frame_dim(value: Any, name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be an integer")
    iv = int(value)
    if not (0 < iv <= MAX_FRAME_DIM):
        raise ValueError(f"{name} out of range")
    return iv


def is_vision_observation(data: Dict[str, Any]) -> bool:
    return isinstance(data, dict) and data.get("source") == SOURCE


def normalize_vision_observation(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + normalize a vision_modal observation. Raises ValueError on bad input."""
    obs = dict(data)

    feature_type = obs.get("feature_type", "dynamic_obstacle")
    if feature_type not in FEATURE_TYPES:
        raise ValueError(f"feature_type must be one of {sorted(FEATURE_TYPES)}")

    action = obs.get("avoidance_action")
    # camera_status heartbeats may omit an avoidance action.
    if feature_type == "dynamic_obstacle":
        if action not in AVOIDANCE_ACTIONS:
            raise ValueError(f"avoidance_action must be one of {sorted(AVOIDANCE_ACTIONS)}")
    elif action is not None and action not in AVOIDANCE_ACTIONS:
        raise ValueError(f"avoidance_action must be one of {sorted(AVOIDANCE_ACTIONS)}")

    obs["source"] = SOURCE
    obs["feature_type"] = feature_type
    obs["confidence"] = _unit_or_none(obs.get("confidence"), "confidence")
    obs["collision_risk"] = _unit_or_none(obs.get("collision_risk"), "collision_risk")
    obs["time_to_collision_s"] = _nonneg_or_none(obs.get("time_to_collision_s"), "time_to_collision_s")

    if obs.get("looming") is not None:
        obs["looming"] = round(_finite_number(obs["looming"], "looming"), 4)
    # Looming is ALWAYS a relative cue in this pipeline (monocular).
    obs["looming_is_relative"] = True

    if obs.get("in_danger_corridor") is not None:
        obs["in_danger_corridor"] = bool(obs["in_danger_corridor"])

    if obs.get("track_id") is not None:
        if isinstance(obs["track_id"], bool) or not isinstance(obs["track_id"], int):
            raise ValueError("track_id must be an integer")

    obs["bounding_box"] = _validate_bbox(obs.get("bounding_box"))
    obs["predicted_trajectory"] = _validate_trajectory(obs.get("predicted_trajectory"))
    obs["steer_vector"] = _validate_steer(obs.get("steer_vector"))
    obs["object_label"] = _clean_text(obs.get("object_label"), "object_label", MAX_LABEL_LEN)
    obs["avoidance_reason"] = _clean_text(obs.get("avoidance_reason"), "avoidance_reason", MAX_REASON_LEN)
    obs["scene_summary"] = _clean_text(obs.get("scene_summary"), "scene_summary", MAX_SCENE_LEN)

    if obs.get("scene_summary_age_s") is not None:
        obs["scene_summary_age_s"] = round(
            _nonneg_or_none(obs["scene_summary_age_s"], "scene_summary_age_s") or 0.0, 2
        )

    obs["frame_width"] = _validate_frame_dim(obs.get("frame_width"), "frame_width")
    obs["frame_height"] = _validate_frame_dim(obs.get("frame_height"), "frame_height")
    obs["model"] = _clean_text(obs.get("model"), "model", MAX_LABEL_LEN)
    obs["pipeline_version"] = _clean_text(obs.get("pipeline_version"), "pipeline_version", MAX_LABEL_LEN)

    # Compact array of other active risks (optional). Bound + light-validate.
    others = obs.get("other_active_risks")
    if others is not None:
        if not isinstance(others, list):
            raise ValueError("other_active_risks must be a list")
        clean_others = []
        for o in others[:MAX_OTHER_RISKS]:
            if not isinstance(o, dict):
                raise ValueError("other_active_risks items must be objects")
            clean_others.append(
                {
                    "track_id": o.get("track_id"),
                    "object_label": _clean_text(o.get("object_label"), "object_label", MAX_LABEL_LEN),
                    "collision_risk": _unit_or_none(o.get("collision_risk"), "collision_risk"),
                    "time_to_collision_s": _nonneg_or_none(o.get("time_to_collision_s"), "time_to_collision_s"),
                    "avoidance_action": o.get("avoidance_action")
                    if o.get("avoidance_action") in AVOIDANCE_ACTIONS or o.get("avoidance_action") is None
                    else None,
                }
            )
        obs["other_active_risks"] = clean_others

    # Spatial context: camera hazards are local until localization exists (§8).
    obs.setdefault("route_session_id", None)
    obs.setdefault("latitude", None)
    obs.setdefault("longitude", None)
    obs["route_affected"] = bool(obs.get("route_affected", False))

    return obs
