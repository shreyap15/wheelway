"""Canonical mobility-profile contract: shared defaults + independence + 400s."""

import pytest

from main import app
from accessroute.schemas import WheelchairProfile
from app.api.real_route import RealRouteProfile

# The one canonical real-route profile shape/defaults (Task 3).
CANONICAL = {
    "wheelchair_type": "manual",
    "avoid_stairs": True,
    "max_slope_pct": 8.33,
    "max_cross_slope_pct": 2.0,
    "min_width_m": 0.91,
    "requires_curb_ramps": True,
    "surface_sensitivity": 0.5,
}


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_flask_profile_defaults_match_canonical():
    p = RealRouteProfile().dict()
    for key, val in CANONICAL.items():
        assert p[key] == val, f"{key}: {p[key]} != {val}"


def test_pipeline_profile_defaults_align():
    # Shared keys carry the same defaults in the pipeline's WheelchairProfile.
    wp = WheelchairProfile(device_type="manual")
    assert wp.avoid_stairs is True
    assert wp.requires_curb_ramps is True
    assert wp.max_incline_grade == 8.33  # <- max_slope_pct
    assert wp.max_cross_slope_pct == 2.0
    assert wp.surface_sensitivity == 0.5


def test_avoid_stairs_and_curb_ramps_independent():
    a = RealRouteProfile(avoid_stairs=False)
    assert a.avoid_stairs is False and a.requires_curb_ramps is True
    b = RealRouteProfile(requires_curb_ramps=False)
    assert b.requires_curb_ramps is False and b.avoid_stairs is True


def test_invalid_range_returns_structured_400(client):
    body = {
        "origin": {"latitude": 37.869, "longitude": -122.259},
        "destination": {"latitude": 37.868, "longitude": -122.258},
        "profile": {"max_slope_pct": 999.0},  # out of range
    }
    resp = client.post("/real-route", json=body)
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "validation_error"
