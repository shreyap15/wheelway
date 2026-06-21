"""Unit tests for controlled alternative discovery (pure + injected route_fn)."""

import polyline as _polyline

from accessroute.schemas import LatLng, RouteCandidate
from accessroute.tools import candidate_discovery as cd

ROUTE = [(37.8690, -122.2590), (37.8695, -122.2588), (37.8700, -122.2586)]


def _cand(coords, distance):
    return RouteCandidate(
        route_index=0,
        encoded_polyline=_polyline.encode(coords),
        distance_meters=distance,
        duration_seconds=distance,
        num_steps=1,
        travel_mode="WALK",
    )


def test_generate_waypoints_offsets_and_caps():
    wps = cd.generate_waypoints(ROUTE, slope_segments=None, max_points=2)
    assert len(wps) == 2
    # Offset points are NOT exactly on the original route vertices.
    for wp in wps:
        assert all(abs(wp.lat - p[0]) > 1e-6 or abs(wp.lng - p[1]) > 1e-6 for p in ROUTE)


def test_discovery_capped_at_max_requests():
    calls = {"n": 0}

    def route_fn(o, w, d):
        calls["n"] += 1
        return []  # nothing distinct

    new, made = cd.discover_additional_candidates(
        LatLng(lat=ROUTE[0][0], lng=ROUTE[0][1]),
        LatLng(lat=ROUTE[-1][0], lng=ROUTE[-1][1]),
        ROUTE,
        None,
        existing_signatures=[cd.signature(ROUTE)],
        baseline_distance_m=300.0,
        route_fn=route_fn,
        max_requests=3,
    )
    assert new == []
    assert made <= 3
    assert calls["n"] <= 3


def test_discovery_rejects_extreme_detour():
    far = [(37.90, -122.30), (37.95, -122.35)]  # very different + huge distance

    def route_fn(o, w, d):
        return [_cand(far, distance=5000.0)]  # 5 km vs 300 m baseline

    new, made = cd.discover_additional_candidates(
        LatLng(lat=ROUTE[0][0], lng=ROUTE[0][1]),
        LatLng(lat=ROUTE[-1][0], lng=ROUTE[-1][1]),
        ROUTE,
        None,
        existing_signatures=[cd.signature(ROUTE)],
        baseline_distance_m=300.0,
        route_fn=route_fn,
        max_requests=1,
    )
    assert new == []  # rejected: > 2.5x baseline


def test_discovery_rejects_near_identical():
    def route_fn(o, w, d):
        return [_cand(ROUTE, distance=320.0)]  # same geometry as existing

    new, made = cd.discover_additional_candidates(
        LatLng(lat=ROUTE[0][0], lng=ROUTE[0][1]),
        LatLng(lat=ROUTE[-1][0], lng=ROUTE[-1][1]),
        ROUTE,
        None,
        existing_signatures=[cd.signature(ROUTE)],
        baseline_distance_m=300.0,
        route_fn=route_fn,
        max_requests=1,
    )
    assert new == []  # rejected: near-identical to existing route


def test_discovery_accepts_distinct_route():
    distinct = [(37.8690, -122.2590), (37.8650, -122.2650), (37.8700, -122.2586)]

    def route_fn(o, w, d):
        return [_cand(distinct, distance=420.0)]

    new, made = cd.discover_additional_candidates(
        LatLng(lat=ROUTE[0][0], lng=ROUTE[0][1]),
        LatLng(lat=ROUTE[-1][0], lng=ROUTE[-1][1]),
        ROUTE,
        None,
        existing_signatures=[cd.signature(ROUTE)],
        baseline_distance_m=300.0,
        route_fn=route_fn,
        max_requests=1,
    )
    assert len(new) == 1
