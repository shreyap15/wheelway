"""
WheelWay — Route API endpoint tests.

Exercises the Flask /route endpoint end-to-end against the mock graph,
confirming the A* router is actually reachable over HTTP and that the
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
    resp = client.post("/route", json={"start_node_id": "A1", "end_node_id": "A2"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    assert len(body["steps"]) >= 1
    assert body["total_distance_m"] > 0
    # per-segment explanation layer survives serialization
    for step in body["steps"]:
        assert 0 <= step["accessibility_score"] <= 100


def test_route_avoids_stairs(client):
    # C1 -> C2 has a direct stairs segment; default manual profile must route around it.
    resp = client.post("/route", json={"start_node_id": "C1", "end_node_id": "C2"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    assert all(step["segment"]["stairs"] is False for step in body["steps"])


def test_route_avoids_steep_hill_for_manual_chair(client):
    # B2 -> B3 direct segment is an 11.5% hill, above the 8.33% manual-chair ceiling.
    resp = client.post("/route", json={"start_node_id": "B2", "end_node_id": "B3"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["found"] is True
    for step in body["steps"]:
        assert step["segment"]["slope"] <= 8.33


def test_route_missing_body_is_400(client):
    resp = client.post("/route", data="not json", content_type="text/plain")
    assert resp.status_code == 400


def test_route_unknown_node_is_404(client):
    resp = client.post("/route", json={"start_node_id": "Z9", "end_node_id": "A1"})
    assert resp.status_code == 404
    assert resp.get_json()["found"] is False


def test_route_k_alternatives(client):
    resp = client.post("/route?k=2", json={"start_node_id": "A1", "end_node_id": "D4"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "routes" in body
    assert 1 <= len(body["routes"]) <= 2
    assert all(r["found"] for r in body["routes"])
