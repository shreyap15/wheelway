"""Direct in-process specialist execution (no uAgents network loops).

The orchestrator now calls the Mapbox routing engine and the elevation service
as plain async functions instead of round-tripping through route/elevation
agents via ``ctx.send_and_receive``. These tests exercise those direct calls.
"""

import asyncio

import polyline as _polyline

from accessroute import main as route_main
from accessroute import elevation_service
from accessroute.schemas import (
    ElevationCheckRequest,
    LatLng,
    RouteCandidate,
    RouteEvaluationRequest,
    WheelchairProfile,
)

ENCODED = _polyline.encode([(37.8715, -122.2595), (37.8756, -122.2588)])


def _run(coro):
    return asyncio.run(coro)


def test_fetch_route_candidates_async_is_direct(monkeypatch):
    """Routing runs in-process via the Mapbox engine, with no agent messaging."""
    monkeypatch.setattr(
        route_main,
        "compute_mapbox_routes",
        lambda *a, **k: [
            RouteCandidate(
                route_index=0,
                encoded_polyline=ENCODED,
                distance_meters=600.0,
                duration_seconds=480.0,
                num_steps=2,
                travel_mode="WALK",
            )
        ],
    )
    msg = RouteEvaluationRequest(
        session_id="s1",
        origin=LatLng(lat=37.8715, lng=-122.2595),
        destination=LatLng(lat=37.8756, lng=-122.2588),
        profile=WheelchairProfile(device_type="power"),
        travel_mode="WALK",
    )
    result = _run(route_main.fetch_route_candidates_async(msg, "token"))
    assert result.service_degraded is False
    assert len(result.candidates) == 1
    assert result.candidates[0].encoded_polyline == ENCODED


def test_check_route_elevation_async_is_direct(monkeypatch):
    """Elevation grading runs in-process (sample -> smooth -> grade)."""
    samples = [
        {"elevation": 100.0, "lat": 37.8715, "lng": -122.2595},
        {"elevation": 104.0, "lat": 37.8724, "lng": -122.2595},
    ]
    monkeypatch.setattr(elevation_service, "sample_elevations", lambda *a, **k: samples)
    req = ElevationCheckRequest(
        session_id="s1",
        route_index=0,
        encoded_polyline=ENCODED,
        distance_meters=100.0,
        profile=WheelchairProfile(device_type="power").dict(),
    )
    verdict = _run(elevation_service.check_route_elevation_async(req, "gkey"))
    assert verdict.route_index == 0
    assert verdict.service_degraded is False
    assert verdict.max_grade_percentage > 0
