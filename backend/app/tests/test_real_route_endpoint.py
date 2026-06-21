"""
WheelWay — /real-route endpoint tests.

These verify the thin Flask adapter over the shared pipeline:
  - request validation (400 validation_error),
  - the honest-failure path with no Mapbox token (503 configuration_error,
    never fabricated geometry),
  - a mocked success path (200) proving the endpoint returns exact Mapbox
    geometry as GeoJSON [lng, lat] and reuses accessroute.pipeline.

All paid API calls are mocked; no network access is required.
"""

import polyline as _polyline
import pytest

from main import app
from accessroute import pipeline
from accessroute.schemas import RouteCandidate

ENCODED = _polyline.encode([(37.869, -122.259), (37.868, -122.258)])


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


VALID_BODY = {
    "origin": {"latitude": 37.869, "longitude": -122.259},
    "destination": {"latitude": 37.868, "longitude": -122.258},
    "profile": {
        "wheelchair_type": "manual",
        "avoid_stairs": True,
        "max_slope_pct": 8.33,
        "min_width_m": 0.91,
    },
}


def _patch_mapbox(monkeypatch, candidates=None, exc=None):
    def fake(*args, **kwargs):
        if exc is not None:
            raise exc
        return candidates if candidates is not None else [
            RouteCandidate(
                route_index=0,
                encoded_polyline=ENCODED,
                distance_meters=300.0,
                duration_seconds=240.0,
                num_steps=2,
                travel_mode="WALK",
            )
        ]

    monkeypatch.setattr(pipeline, "compute_mapbox_routes", fake)


def test_real_route_missing_mapbox_token_returns_config_error(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "", raising=False)
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "configuration_error"
    assert "MAPBOX_ACCESS_TOKEN" in body["missing_env"]
    # Must not fabricate any geometry on the failure path.
    assert "routes" not in body


def test_real_route_invalid_body_is_400(client):
    resp = client.post("/real-route", json={"origin": {"latitude": 37.0}})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "validation_error"


def test_real_route_no_json_is_400(client):
    resp = client.post("/real-route", data="nope", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "validation_error"


def test_real_route_success_returns_mapbox_geojson(client, monkeypatch):
    """Mapbox token present, Google enrichment absent -> exact geometry, 200."""
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_mapbox(monkeypatch)

    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "real_route"
    route = data["routes"][0]
    # Geometry is the exact decoded Mapbox polyline in [lng, lat] order.
    assert route["geometry"]["type"] == "LineString"
    assert route["geometry"]["coordinates"] == [[-122.259, 37.869], [-122.258, 37.868]]
    assert route["sources"]["geometry"] == "mapbox"
    assert route["stairs_detected"] is None
    # No Google key -> slope unavailable, but geometry is real (not fabricated).
    assert route["max_slope_pct"] is None


def test_real_route_no_route_is_404(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    _patch_mapbox(
        monkeypatch,
        exc=pipeline.ServiceDegraded("Mapbox Directions returned no usable route geometry"),
    )
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "no_route"


def test_real_route_routing_unavailable_is_502(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    _patch_mapbox(monkeypatch, exc=pipeline.ServiceDegraded("Mapbox Directions HTTP 500"))
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "routing_unavailable"
