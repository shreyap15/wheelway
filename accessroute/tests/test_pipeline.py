"""Tests for the shared accessible-routing pipeline (accessroute.pipeline).

This is the SINGLE real-route flow reused by Flask /real-route, the orchestrator,
the local demo, and the Agentverse mailbox. All paid API calls are mocked.
"""

import asyncio
from pathlib import Path

import polyline as _polyline
import pytest

from accessroute import pipeline
from accessroute.common.http import ServiceDegraded
from accessroute.schemas import (
    AccessibilityVerdict,
    LatLng,
    RouteCandidate,
    WheelchairProfile,
)


def _run(coro):
    return asyncio.run(coro)


ORIGIN = LatLng(lat=37.8715, lng=-122.2595)
DEST = LatLng(lat=37.8756, lng=-122.2588)

# Encoded polyline (lat, lng) used for the fake Mapbox candidate.
ENCODED = _polyline.encode([(37.8715, -122.2595), (37.8756, -122.2588)])


def _fake_candidate():
    return RouteCandidate(
        route_index=0,
        encoded_polyline=ENCODED,
        distance_meters=612.4,
        duration_seconds=480.0,
        num_steps=2,
        travel_mode="WALK",
    )


def _patch_mapbox(monkeypatch, candidates=None, exc=None):
    def fake(*args, **kwargs):
        if exc is not None:
            raise exc
        return candidates if candidates is not None else [_fake_candidate()]

    monkeypatch.setattr(pipeline, "compute_mapbox_routes", fake)


def _profile():
    return WheelchairProfile(device_type="manual", max_incline_grade=8.33)


def test_geometry_is_lng_lat_geojson(monkeypatch):
    """Mapbox geometry is returned verbatim as GeoJSON [lng, lat]."""
    _patch_mapbox(monkeypatch)
    result = _run(
        pipeline.compute_accessible_routes(
            ORIGIN, DEST, _profile(), mapbox_token="t", google_key=""
        )
    )
    geo = result.routes[0].geometry
    assert geo["type"] == "LineString"
    assert geo["coordinates"] == [[-122.2595, 37.8715], [-122.2588, 37.8756]]
    # longitude first, latitude second
    for lng, lat in geo["coordinates"]:
        assert -123 < lng < -122 and 37 < lat < 38
    assert result.routes[0].sources["geometry"] == "mapbox"


def test_success_when_google_enrichment_unavailable(monkeypatch):
    """No Google key -> Mapbox geometry still succeeds; enrichment marked unavailable."""
    _patch_mapbox(monkeypatch)
    result = _run(
        pipeline.compute_accessible_routes(
            ORIGIN, DEST, _profile(), mapbox_token="t", google_key=""
        )
    )
    route = result.routes[0]
    assert route.geometry["coordinates"]  # real geometry present
    assert route.distance_m == pytest.approx(612.4)
    assert route.max_slope_pct is None
    assert route.accessibility_score is None
    assert route.stairs_detected is None  # unknown -> null
    assert result.data_sources["slope_grade"] == "unavailable"
    assert result.destination_place.source == "unavailable"


def test_elevation_and_places_enrichment(monkeypatch):
    """With a Google key, real grade math + places enrichment populate the route."""
    _patch_mapbox(monkeypatch)
    # ~100 m north with a 10 m rise -> ~10% grade (exceeds 8.33% limit).
    samples = [
        {"elevation": 100.0, "lat": 37.8715, "lng": -122.2595},
        {"elevation": 110.0, "lat": 37.8724, "lng": -122.2595},
    ]
    monkeypatch.setattr(pipeline, "sample_elevations", lambda *a, **k: samples)
    monkeypatch.setattr(
        pipeline,
        "check_destination_accessibility",
        lambda *a, **k: AccessibilityVerdict(
            session_id="",
            display_name="Test Hall",
            wheelchair_entrance=True,
            service_degraded=False,
        ),
    )
    result = _run(
        pipeline.compute_accessible_routes(
            ORIGIN, DEST, _profile(), mapbox_token="t", google_key="g"
        )
    )
    route = result.routes[0]
    assert route.max_slope_pct is not None and route.max_slope_pct > 8.33
    assert route.exceeds_max_slope is True
    assert len(route.steep_sections) >= 1
    assert route.accessibility_score is not None
    assert result.destination_place.place_name == "Test Hall"
    assert result.destination_place.wheelchair_accessible_entrance is True


def test_missing_mapbox_token_raises_config_error(monkeypatch):
    """No Mapbox token -> ConfigurationError, and NO geometry is fabricated."""
    _patch_mapbox(monkeypatch)  # would succeed if reached
    with pytest.raises(pipeline.ConfigurationError):
        _run(
            pipeline.compute_accessible_routes(
                ORIGIN, DEST, _profile(), mapbox_token="", google_key=""
            )
        )


def test_no_route_raises_no_route_error(monkeypatch):
    _patch_mapbox(
        monkeypatch,
        exc=ServiceDegraded("Mapbox Directions returned no usable route geometry"),
    )
    with pytest.raises(pipeline.NoRouteError):
        _run(
            pipeline.compute_accessible_routes(
                ORIGIN, DEST, _profile(), mapbox_token="t", google_key=""
            )
        )


def test_mapbox_api_failure_propagates_service_degraded(monkeypatch):
    """A real Mapbox API failure surfaces as ServiceDegraded (HTTP 502), not geometry."""
    _patch_mapbox(monkeypatch, exc=ServiceDegraded("Mapbox Directions HTTP 500"))
    with pytest.raises(ServiceDegraded):
        _run(
            pipeline.compute_accessible_routes(
                ORIGIN, DEST, _profile(), mapbox_token="t", google_key=""
            )
        )


def test_latlng_pairs_to_geojson_order():
    geo = pipeline.latlng_pairs_to_geojson([(37.869, -122.259), (37.868, -122.258)])
    assert geo["coordinates"] == [[-122.259, 37.869], [-122.258, 37.868]]


def test_flask_and_mailbox_reuse_shared_service():
    """Flask /real-route and the Agentverse mailbox import the SAME pipeline fn."""
    repo = Path(__file__).resolve().parents[2]
    flask_src = (repo / "backend/app/api/real_route.py").read_text()
    mailbox_src = (repo / "accessroute/scripts/run_mailbox.py").read_text()
    for src in (flask_src, mailbox_src):
        assert "from accessroute.pipeline import" in src
        assert "compute_accessible_routes" in src
