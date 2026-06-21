"""
WheelWay — Route API endpoint tests.

Exercises the Flask /route endpoint end-to-end against the curated Lower Sproul
mock graph, confirming the A* router is reachable over HTTP and that the
accessibility constraints (stairs / steep-hill avoidance) survive the
serialization boundary.
"""

import pytest

from main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_route_simple_path_found(client):
    resp = client.post(
        "/route", json={"start_node_id": "sather_gate", "end_node_id": "sproul_plaza"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    assert len(body["steps"]) >= 1
    assert body["total_distance_m"] > 0
    # per-segment explanation layer survives serialization
    for step in body["steps"]:
        assert 0 <= step["accessibility_score"] <= 100


def test_route_steps_include_linestring_geometry(client):
    # Each selected segment must serialize a GeoJSON LineString so the frontend
    # can draw the real path instead of connecting node endpoints.
    resp = client.post(
        "/route", json={"start_node_id": "sather_gate", "end_node_id": "bancroft_tele"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    for step in body["steps"]:
        geom = step["segment"]["geometry"]
        assert geom is not None
        assert geom["type"] == "LineString"
        assert len(geom["coordinates"]) >= 2
        # coordinates are GeoJSON [lon, lat] pairs near UC Berkeley / Sproul Plaza
        for lon, lat in geom["coordinates"]:
            assert -122.27 < lon < -122.25
            assert 37.86 < lat < 37.88


def test_route_avoids_stairs(client):
    # sproul_plaza -> student_union has a direct STAIRS segment; the default
    # manual profile must route around it (via the accessible ramp).
    resp = client.post(
        "/route", json={"start_node_id": "sproul_plaza", "end_node_id": "student_union"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    assert all(step["segment"]["stairs"] is False for step in body["steps"])


def test_route_avoids_steep_hill_for_manual_chair(client):
    # student_union -> eshleman direct segment is a 10.5% incline, above the
    # 8.33% manual-chair ceiling; the router must detour around it.
    resp = client.post(
        "/route", json={"start_node_id": "student_union", "end_node_id": "eshleman"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    for step in body["steps"]:
        assert step["segment"]["slope"] <= 8.33


def test_route_missing_body_is_400(client):
    resp = client.post("/route", data="not json", content_type="text/plain")
    assert resp.status_code == 400


def test_route_unknown_node_is_404(client):
    resp = client.post(
        "/route", json={"start_node_id": "nowhere", "end_node_id": "sather_gate"}
    )
    assert resp.status_code == 404
    assert resp.get_json()["found"] is False


def test_route_k_alternatives(client):
    resp = client.post(
        "/route?k=2",
        json={"start_node_id": "sather_gate", "end_node_id": "bancroft_tele"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "routes" in body
    assert 1 <= len(body["routes"]) <= 2
    assert all(r["found"] for r in body["routes"])
