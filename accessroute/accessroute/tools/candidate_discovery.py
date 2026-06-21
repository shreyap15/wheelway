"""Controlled real-route alternative discovery for WheelWay.

When Mapbox returns too few DISTINCT walking routes, we ask Mapbox for a small,
capped number of additional routes forced through validated detour waypoints.
Every returned line is exact Mapbox geometry -- nothing is fabricated. Waypoints
are validated implicitly by Mapbox routing (it snaps each via point to the
nearest pedestrian-network location); a candidate is rejected if routing fails,
the result is nearly identical, or the detour is extreme.

Pure helpers (waypoint math, signatures) are network-free and unit-testable; the
single network seam ``route_fn`` is injected in tests.
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional, Tuple

from accessroute.common.geo import decode_polyline, haversine_meters
from accessroute.schemas import LatLng

_EARTH_R = 6_371_000.0

# Defaults (all caller-overridable).
DEFAULT_MAX_REQUESTS = 3
DEFAULT_OFFSET_M = 60.0
DEFAULT_TIMEOUT_S = 8
DEFAULT_DETOUR_CAP_RATIO = 2.5  # reject routes >2.5x the baseline distance
SIMILAR_OVERLAP = 0.9           # reject near-identical geometry


def _offset_point(lat: float, lng: float, bearing_deg: float, dist_m: float) -> Tuple[float, float]:
    """Point ``dist_m`` from (lat,lng) along ``bearing_deg`` (great-circle)."""
    br = math.radians(bearing_deg)
    ad = dist_m / _EARTH_R
    la = math.radians(lat)
    lo = math.radians(lng)
    la2 = math.asin(math.sin(la) * math.cos(ad) + math.cos(la) * math.sin(ad) * math.cos(br))
    lo2 = lo + math.atan2(
        math.sin(br) * math.sin(ad) * math.cos(la),
        math.cos(ad) - math.sin(la) * math.sin(la2),
    )
    return math.degrees(la2), math.degrees(lo2)


def _bearing(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    dlo = lo2 - lo1
    y = math.sin(dlo) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _local_bearing(route: List[Tuple[float, float]], anchor: Tuple[float, float]) -> float:
    """Direction of travel near the anchor (uses its nearest route neighbours)."""
    if len(route) < 2:
        return 0.0
    idx = min(range(len(route)), key=lambda i: haversine_meters(anchor, route[i]))
    a = route[max(0, idx - 1)]
    b = route[min(len(route) - 1, idx + 1)]
    return _bearing(a, b)


def signature(decoded: List[Tuple[float, float]]) -> frozenset:
    """Rounded coordinate set (~11 m) for near-duplicate detection."""
    return frozenset((round(lat, 4), round(lng, 4)) for (lat, lng) in decoded)


def overlap(sig_a: frozenset, sig_b: frozenset) -> float:
    union = len(sig_a | sig_b) or 1
    return len(sig_a & sig_b) / union


def generate_waypoints(
    route: List[Tuple[float, float]],
    slope_segments: Optional[list] = None,
    *,
    offset_m: float = DEFAULT_OFFSET_M,
    max_points: int = DEFAULT_MAX_REQUESTS,
) -> List[LatLng]:
    """Prioritized detour waypoints offset perpendicular to the route.

    Anchors, highest priority first: start & end of the longest exceeds-limit
    slope section (force a detour around the steep stretch), then the route
    midpoint. Each anchor is offset to BOTH sides until ``max_points`` reached.
    No fabricated geometry -- these are only seed points for Mapbox to snap.
    """
    if len(route) < 2:
        return []

    anchors: List[Tuple[float, float]] = []
    for seg in slope_segments or []:
        if getattr(seg, "classification", None) != "exceeds_limit":
            continue
        coords = (seg.geometry or {}).get("coordinates") or []
        if len(coords) >= 2:
            anchors.append((coords[0][1], coords[0][0]))   # [lng,lat] -> (lat,lng)
            anchors.append((coords[-1][1], coords[-1][0]))
            break  # only the first (longest is built earliest by build order)
    mid = route[len(route) // 2]
    anchors.append((mid[0], mid[1]))

    waypoints: List[LatLng] = []
    for anchor in anchors:
        br = _local_bearing(route, anchor)
        for side in (90.0, -90.0):
            lat2, lng2 = _offset_point(anchor[0], anchor[1], (br + side) % 360.0, offset_m)
            waypoints.append(LatLng(lat=lat2, lng=lng2))
            if len(waypoints) >= max_points:
                return waypoints
    return waypoints


def discover_additional_candidates(
    origin: LatLng,
    destination: LatLng,
    best_decoded: List[Tuple[float, float]],
    slope_segments: Optional[list],
    *,
    existing_signatures: List[frozenset],
    baseline_distance_m: float,
    route_fn: Callable[[LatLng, List[LatLng], LatLng], list],
    max_requests: int = DEFAULT_MAX_REQUESTS,
    detour_cap_ratio: float = DEFAULT_DETOUR_CAP_RATIO,
) -> Tuple[list, int]:
    """Make up to ``max_requests`` via-routed Mapbox requests; return distinct
    new candidates and the number of requests actually made.

    ``route_fn(origin, [waypoint], destination) -> list[RouteCandidate]`` is the
    only network seam (injected in tests). Each call is one request; the cap
    bounds total requests (no retry storm). Failures are skipped gracefully.
    """
    waypoints = generate_waypoints(best_decoded, slope_segments, max_points=max_requests)
    sigs = list(existing_signatures)
    new_candidates: list = []
    requests_made = 0

    for wp in waypoints:
        if requests_made >= max_requests:
            break
        requests_made += 1
        try:
            cands = route_fn(origin, [wp], destination)
        except Exception:
            continue  # routing failed for this waypoint -> skip, no retry
        if not cands:
            continue
        cand = cands[0]
        if baseline_distance_m > 0 and cand.distance_meters > baseline_distance_m * detour_cap_ratio:
            continue  # extreme detour -> reject
        sig = signature(decode_polyline(cand.encoded_polyline))
        if any(overlap(sig, s) >= SIMILAR_OVERLAP for s in sigs):
            continue  # nearly identical to an existing route -> reject
        sigs.append(sig)
        new_candidates.append(cand)

    return new_candidates, requests_made
