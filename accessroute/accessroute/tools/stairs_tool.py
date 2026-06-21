"""Multi-source stair detection for the WheelWay real-route pipeline.

Combines three INDEPENDENT, honest evidence sources and fuses them into a
canonical stair verdict per route. No source is treated as ground truth on its
own; geometry from Mapbox is never modified here.

    1. Mapbox step text   -- weak heuristic (stair terms in name/instruction)
    2. OpenStreetMap      -- Overpass lookup for stair features near the route
    3. CV observations    -- camera detections from the request (cv_observations)

All matching is simple nearest-vertex distance -- intentionally NOT map matching.
Overpass calls have an explicit timeout, degrade gracefully, and are briefly
cached so route alternatives sharing a corridor reuse one network call.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from accessroute.common.geo import haversine_meters

# --------------------------------------------------------------------------- #
# Evidence source tags + canonical statuses
# --------------------------------------------------------------------------- #
SRC_MAPBOX_STEPS = "mapbox_steps"
SRC_OSM = "openstreetmap"
SRC_CV = "camera_cv"

STATUS_UNKNOWN = "unknown"
STATUS_POSSIBLE = "possible"
STATUS_LIKELY = "likely"
STATUS_CONFIRMED = "confirmed"
STATUS_NOT_DETECTED = "not_detected"

# Case-insensitive weak terms for the Mapbox instruction heuristic.
STAIR_TERMS = ("stairs", "steps", "stairway", "staircase", "escalator")

# OSM tags treated as stair/barrier evidence. "steps-like" tags imply actual
# stairs (-> likely); the access-barrier tags are weaker (-> possible alone).
OSM_STEPS_LIKE = {("highway", "steps"), ("barrier", "step")}
OSM_BARRIER_TAGS = {
    ("wheelchair", "no"),
    ("ramp", "no"),
    ("ramp:wheelchair", "no"),
}
OSM_ALL_TAGS = OSM_STEPS_LIKE | OSM_BARRIER_TAGS

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Tunable distances/timeouts (env-overridable for dev).
OVERPASS_TIMEOUT_S = float(os.getenv("STAIR_OVERPASS_TIMEOUT_S", "6"))
OSM_MATCH_DISTANCE_M = float(os.getenv("STAIR_OSM_MATCH_M", "25"))
CV_MATCH_DISTANCE_M = float(os.getenv("STAIR_CV_MATCH_M", "25"))
CV_CONFIRM_CONFIDENCE = float(os.getenv("STAIR_CV_CONFIRM_CONF", "0.8"))
CORRIDOR_PAD_M = float(os.getenv("STAIR_CORRIDOR_PAD_M", "30"))
_CACHE_TTL_S = float(os.getenv("STAIR_OSM_CACHE_TTL_S", "600"))  # 10 min

# Confidence floors per status.
_STATUS_CONFIDENCE = {
    STATUS_CONFIRMED: 0.9,
    STATUS_LIKELY: 0.7,
    STATUS_POSSIBLE: 0.45,
    STATUS_UNKNOWN: 0.0,
    STATUS_NOT_DETECTED: 0.0,
}

# Short-lived in-memory Overpass cache: {bbox_key: (monotonic_ts, features)}.
_OSM_CACHE: Dict[Tuple[int, int, int, int], Tuple[float, List[dict]]] = {}


# --------------------------------------------------------------------------- #
# Geometry helpers (simple, no map matching)
# --------------------------------------------------------------------------- #
def _min_distance_to_route_m(pt: Tuple[float, float], route: List[Tuple[float, float]]) -> float:
    """Minimum great-circle distance from a (lat, lng) point to route vertices."""
    if not route:
        return float("inf")
    return min(haversine_meters(pt, v) for v in route)


def _nearest_edge_geojson(pt: Tuple[float, float], route: List[Tuple[float, float]]) -> Dict[str, Any]:
    """LineString [lng,lat] of the route edge nearest a point (affected section)."""
    if not route:
        return {"type": "LineString", "coordinates": []}
    idx = min(range(len(route)), key=lambda i: haversine_meters(pt, route[i]))
    a = max(0, idx - 1)
    b = min(len(route) - 1, idx + 1)
    seg = route[a : b + 1] if b > a else [route[idx]]
    return {"type": "LineString", "coordinates": [[lng, lat] for (lat, lng) in seg]}


def route_bbox(route: List[Tuple[float, float]], pad_m: float) -> Tuple[float, float, float, float]:
    """Padded (south, west, north, east) bounding box for a (lat,lng) route."""
    lats = [p[0] for p in route]
    lngs = [p[1] for p in route]
    mean_lat = sum(lats) / len(lats)
    dlat = pad_m / 111_320.0
    dlng = pad_m / (111_320.0 * max(0.1, math.cos(math.radians(mean_lat))))
    return (min(lats) - dlat, min(lngs) - dlng, max(lats) + dlat, max(lngs) + dlng)


# --------------------------------------------------------------------------- #
# 1. Mapbox step-text heuristic (weak)
# --------------------------------------------------------------------------- #
def detect_mapbox_step_stairs(steps: List[dict]) -> List[dict]:
    """Scan Mapbox step name/instruction for stair terms (case-insensitive)."""
    evidence: List[dict] = []
    for step in steps or []:
        text = f"{step.get('name', '')} {step.get('instruction', '')}".lower()
        matched = next((t for t in STAIR_TERMS if t in text), None)
        if not matched:
            continue
        loc = step.get("location")  # [lng, lat]
        lat = loc[1] if isinstance(loc, (list, tuple)) and len(loc) == 2 else None
        lng = loc[0] if isinstance(loc, (list, tuple)) and len(loc) == 2 else None
        evidence.append(
            {
                "source": SRC_MAPBOX_STEPS,
                "confidence": 0.4,
                "matched_term": matched,
                "osm_tag": None,
                "latitude": lat,
                "longitude": lng,
                "distance_from_route_m": 0.0,  # on the route by construction
                "geometry": step.get("geometry"),
            }
        )
    return evidence


# --------------------------------------------------------------------------- #
# 2. CV stair observations from the request
# --------------------------------------------------------------------------- #
def detect_cv_stairs(
    cv_observations: List[dict],
    route: List[Tuple[float, float]],
    *,
    max_distance_m: float = CV_MATCH_DISTANCE_M,
) -> List[dict]:
    """Associate CV ``stairs`` observations near the route (configurable radius)."""
    evidence: List[dict] = []
    for obs in cv_observations or []:
        if str(obs.get("feature_type", "")).lower() != "stairs":
            continue
        lat, lng = obs.get("latitude"), obs.get("longitude")
        if lat is None or lng is None:
            continue
        dist = _min_distance_to_route_m((lat, lng), route)
        if dist > max_distance_m:
            continue
        evidence.append(
            {
                "source": SRC_CV,
                "confidence": float(obs.get("confidence") or 0.0),
                "matched_term": "stairs",
                "osm_tag": None,
                "latitude": lat,
                "longitude": lng,
                "distance_from_route_m": round(dist, 1),
                "geometry": _nearest_edge_geojson((lat, lng), route),
            }
        )
    return evidence


# --------------------------------------------------------------------------- #
# 3. OpenStreetMap / Overpass stair features
# --------------------------------------------------------------------------- #
def build_overpass_query(bbox: Tuple[float, float, float, float]) -> str:
    """Overpass QL for stair/barrier features inside (s,w,n,e)."""
    s, w, n, e = bbox
    box = f"({s:.6f},{w:.6f},{n:.6f},{e:.6f})"
    clauses = []
    for key, val in sorted(OSM_ALL_TAGS):
        clauses.append(f'  node["{key}"="{val}"]{box};')
        clauses.append(f'  way["{key}"="{val}"]{box};')
    body = "\n".join(clauses)
    return f"[out:json][timeout:25];\n(\n{body}\n);\nout tags center;"


def _bbox_cache_key(bbox: Tuple[float, float, float, float]) -> Tuple[int, int, int, int]:
    # Round to ~1e-3 deg (~100m) so a shared corridor reuses one query.
    return tuple(round(v, 3) for v in bbox)  # type: ignore[return-value]


def _default_overpass_fetch(query: str, timeout: float) -> dict:
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _sanitize_overpass_error(exc: Exception) -> str:
    """Map an exception to a short, safe error name (never leaks secrets/bodies)."""
    if isinstance(exc, (requests.Timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, requests.HTTPError):
        code = getattr(getattr(exc, "response", None), "status_code", None)
        return f"http_{code}" if code else "http_error"
    if isinstance(exc, requests.ConnectionError):
        return "connection_error"
    if isinstance(exc, requests.RequestException):
        return "request_error"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "invalid_response"
    return type(exc).__name__


def query_overpass_stairs(
    route: List[Tuple[float, float]],
    *,
    timeout: float = OVERPASS_TIMEOUT_S,
    pad_m: float = CORRIDOR_PAD_M,
    fetch: Optional[Callable[[str, float], dict]] = None,
    use_cache: bool = True,
) -> Tuple[List[dict], bool, Optional[str]]:
    """Fetch OSM stair features in the route corridor.

    Returns ``(features, completed, error)``:
      - ``completed`` is True when Overpass returned a valid response that parsed
        successfully -- INCLUDING the case of zero matching stair features.
      - ``completed`` is False ONLY for timeout, HTTP failure, connection error,
        or an unparseable response; ``error`` then holds a short, safe reason
        (e.g. "timeout", "http_500", "connection_error", "invalid_response").
    The caller degrades gracefully and must NOT treat absence as "no stairs".
    """
    if not route:
        return [], False, "empty_route"

    bbox = route_bbox(route, pad_m)
    key = _bbox_cache_key(bbox)
    now = time.monotonic()
    if use_cache and key in _OSM_CACHE:
        ts, cached = _OSM_CACHE[key]
        if now - ts < _CACHE_TTL_S:
            return cached, True, None

    fetch = fetch or _default_overpass_fetch
    try:
        data = fetch(build_overpass_query(bbox), timeout)
    except Exception as exc:  # Overpass unreachable -> degrade gracefully.
        return [], False, _sanitize_overpass_error(exc)

    try:
        features = _parse_overpass(data)
    except Exception as exc:
        return [], False, _sanitize_overpass_error(exc)

    if use_cache:
        _OSM_CACHE[key] = (now, features)
    return features, True, None


def _parse_overpass(data: dict) -> List[dict]:
    """Normalize Overpass elements to {lat, lng, tag, key, value, is_steps}."""
    out: List[dict] = []
    for el in data.get("elements", []) or []:
        tags = el.get("tags") or {}
        match = next((kv for kv in OSM_ALL_TAGS if tags.get(kv[0]) == kv[1]), None)
        if not match:
            continue
        if el.get("type") == "node":
            lat, lng = el.get("lat"), el.get("lon")
        else:  # way/relation -> center
            center = el.get("center") or {}
            lat, lng = center.get("lat"), center.get("lon")
        if lat is None or lng is None:
            continue
        out.append(
            {
                "lat": lat,
                "lng": lng,
                "key": match[0],
                "value": match[1],
                "tag": f"{match[0]}={match[1]}",
                "is_steps": match in OSM_STEPS_LIKE,
            }
        )
    return out


def match_osm_to_route(
    features: List[dict],
    route: List[Tuple[float, float]],
    *,
    max_distance_m: float = OSM_MATCH_DISTANCE_M,
) -> List[dict]:
    """Keep OSM features within the corridor and map each to a route section."""
    evidence: List[dict] = []
    for f in features or []:
        pt = (f["lat"], f["lng"])
        dist = _min_distance_to_route_m(pt, route)
        if dist > max_distance_m:
            continue
        evidence.append(
            {
                "source": SRC_OSM,
                "confidence": 0.7 if f["is_steps"] else 0.5,
                "matched_term": None,
                "osm_tag": f["tag"],
                "latitude": f["lat"],
                "longitude": f["lng"],
                "distance_from_route_m": round(dist, 1),
                "geometry": _nearest_edge_geojson(pt, route),
                "_is_steps": f["is_steps"],
            }
        )
    return evidence


# --------------------------------------------------------------------------- #
# Fusion -> canonical verdict
# --------------------------------------------------------------------------- #
def classify_stairs(
    evidence: List[dict],
    *,
    sources_ran: Dict[str, bool],
) -> Tuple[str, float]:
    """Fuse evidence into (status, confidence).

    ``sources_ran`` maps each enabled source -> completed-successfully bool.
    """
    sources_matched = {e["source"] for e in evidence}

    cv_hit = any(
        e["source"] == SRC_CV and (e.get("confidence") or 0.0) >= CV_CONFIRM_CONFIDENCE
        for e in evidence
    )
    osm_steps = any(
        e["source"] == SRC_OSM and e.get("_is_steps") for e in evidence
    )

    if cv_hit:
        status = STATUS_CONFIRMED
    elif len(sources_matched) >= 2:
        status = STATUS_CONFIRMED
    elif osm_steps:
        status = STATUS_LIKELY
    elif sources_matched:  # any single weaker source (mapbox text, OSM barrier)
        status = STATUS_POSSIBLE
    else:
        # No evidence. not_detected ONLY if every enabled source completed.
        all_ok = sources_ran and all(sources_ran.values())
        status = STATUS_NOT_DETECTED if all_ok else STATUS_UNKNOWN

    if status == STATUS_CONFIRMED:
        confidence = max(
            _STATUS_CONFIDENCE[STATUS_CONFIRMED],
            max((e.get("confidence") or 0.0) for e in evidence) if evidence else 0.0,
        )
    else:
        confidence = _STATUS_CONFIDENCE[status]
    return status, round(confidence, 2)


def build_stair_segments(evidence: List[dict], status: str, confidence: float) -> List[dict]:
    """One affected section per located evidence item (geometry preserved)."""
    segments: List[dict] = []
    for e in evidence:
        geom = e.get("geometry")
        if not geom or not geom.get("coordinates"):
            continue
        segments.append(
            {
                "geometry": geom,
                "status": status,
                "confidence": confidence,
                "sources": [e["source"]],
            }
        )
    return segments
