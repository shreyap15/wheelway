"""
WheelWay — /real-route endpoint tests.

These run WITHOUT Google credentials, so they verify the honest-failure path
(structured 503 config error, never fabricated geometry) plus request
validation and the pure lat/lng -> GeoJSON helpers. The live-API path requires
GOOGLE_MAPS_API_KEY and is exercised manually (see report).
"""

import os

import pytest

from main import app
from app.api.real_route import latlng_pairs_to_geojson, score_real_route


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _no_google_key(monkeypatch):
    # Force the credentials-absent path regardless of the host environment.
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr("accessroute.config.GOOGLE_MAPS_API_KEY", "", raising=False)


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


def test_real_route_missing_key_returns_config_error(client):
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "configuration_error"
    assert "GOOGLE_MAPS_API_KEY" in body["missing_env"]
    # Must not fabricate any geometry on the failure path.
    assert "routes" not in body


def test_real_route_invalid_body_is_400(client):
    resp = client.post("/real-route", json={"origin": {"latitude": 37.0}})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Invalid request"


def test_real_route_no_json_is_400(client):
    resp = client.post("/real-route", data="nope", content_type="text/plain")
    assert resp.status_code == 400


def test_latlng_pairs_to_geojson_uses_lng_lat_order():
    # Decoded polyline is (lat, lng); GeoJSON must be [lng, lat].
    geo = latlng_pairs_to_geojson([(37.869, -122.259), (37.868, -122.258)])
    assert geo["type"] == "LineString"
    assert geo["coordinates"] == [[-122.259, 37.869], [-122.258, 37.868]]
    # longitude first, latitude second
    for lng, lat in geo["coordinates"]:
        assert -123 < lng < -122
        assert 37 < lat < 38


def test_score_real_route_monotonic():
    flat = score_real_route(2.0, exceeds_limit=False, num_steep_sections=0)
    steep = score_real_route(15.0, exceeds_limit=True, num_steep_sections=4)
    assert flat == 100.0
    assert 0.0 <= steep < flat
