"""Backend contract tests for source=vision_modal observations + alerts."""

import pytest

from main import app
from accessroute import route_state
from app.services import state_store


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_dedupe():
    # Vision dedupe lives in the route_state store; reset between tests.
    route_state.reset_store()
    state_store.reset_store()
    yield
    route_state.reset_store()
    state_store.reset_store()


def _stop_obs(**over):
    base = {
        "device_id": "wheelway-pi-01",
        "source": "vision_modal",
        "feature_type": "dynamic_obstacle",
        "object_label": "person",
        "confidence": 0.91,
        "track_id": 7,
        "bounding_box": {"x_min": 120, "y_min": 90, "x_max": 360, "y_max": 470},
        "looming": 0.18,
        "time_to_collision_s": 1.4,
        "collision_risk": 0.87,
        "in_danger_corridor": True,
        "predicted_trajectory": [{"t_s": 0.0, "x": 0.48, "y": 0.72}],
        "avoidance_action": "STOP",
        "steer_vector": {"x": 0.0, "y": 0.0},
        "frame_width": 640,
        "frame_height": 480,
        "model": "efficientdet_lite0",
        "pipeline_version": "vision-modal-7b9d823",
    }
    base.update(over)
    return base


def test_stop_observation_stored_and_critical_alert(client):
    resp = client.post("/observations", json=_stop_obs())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["source"] == "vision_modal"
    assert body["looming_is_relative"] is True
    assert body["alert"]["type"] == "collision_risk"
    assert body["alert"]["priority"] == "critical"
    assert body["alert"]["dedupe_key"] == "vision-stop:wheelway-pi-01:7"
    assert body["auto_speak"] is True
    # No fabricated metric distance.
    assert "distance_cm" not in body


def test_left_right_severity(client):
    # LEFT, low TTC -> critical
    r = client.post("/observations", json=_stop_obs(avoidance_action="LEFT", track_id=3,
                                                     time_to_collision_s=1.0, collision_risk=0.9))
    assert r.get_json()["alert"]["type"] == "avoid_left"
    assert r.get_json()["alert"]["priority"] == "critical"
    # RIGHT, high TTC + modest risk -> warning
    r2 = client.post("/observations", json=_stop_obs(avoidance_action="RIGHT", track_id=4,
                                                      time_to_collision_s=5.0, collision_risk=0.55))
    assert r2.get_json()["alert"]["type"] == "avoid_right"
    assert r2.get_json()["alert"]["priority"] == "warning"


def test_clear_produces_no_alert(client):
    r = client.post("/observations", json=_stop_obs(avoidance_action="CLEAR", track_id=None,
                                                     bounding_box=None))
    assert r.status_code == 201
    assert r.get_json()["alert"] is None


def test_dedupe_suppresses_repeat_alert(client):
    a = client.post("/observations", json=_stop_obs()).get_json()
    b = client.post("/observations", json=_stop_obs()).get_json()
    assert a["alert"] is not None
    assert b["alert"] is None  # same vision-stop key suppressed within TTL


def test_infinite_ttc_rejected_as_null(client):
    # JSON can't carry inf; the bridge sends null. A negative TTC is a hard error.
    ok = client.post("/observations", json=_stop_obs(time_to_collision_s=None))
    assert ok.status_code == 201
    assert ok.get_json()["time_to_collision_s"] is None
    bad = client.post("/observations", json=_stop_obs(time_to_collision_s=-2.0))
    assert bad.status_code == 400
    assert bad.get_json()["error"] == "validation_error"


def test_invalid_action_and_risk_rejected(client):
    bad_action = client.post("/observations", json=_stop_obs(avoidance_action="REVERSE"))
    assert bad_action.status_code == 400
    bad_risk = client.post("/observations", json=_stop_obs(collision_risk=1.7))
    assert bad_risk.status_code == 400


def test_camera_offline_heartbeat_alert(client):
    hb = {
        "device_id": "wheelway-pi-01",
        "source": "vision_modal",
        "feature_type": "camera_status",
        "camera_online": False,
        "detector_online": False,
        "model": "efficientdet_lite0",
        "pipeline_version": "vision-modal-7b9d823",
    }
    r = client.post("/observations", json=hb)
    assert r.status_code == 201
    assert r.get_json()["alert"]["type"] == "vision_offline"
    assert r.get_json()["alert"]["dedupe_key"] == "vision-offline:wheelway-pi-01"


def test_legacy_observation_still_works(client):
    # Backward compatibility: a non-vision observation is untouched.
    r = client.post("/observations", json={"device_id": "simulated-pi", "distance_cm": 42})
    assert r.status_code == 201
    body = r.get_json()
    assert body["distance_cm"] == 42
    assert "alert" not in body  # only vision observations get the alert enrichment


def test_trajectory_is_bounded(client):
    long_traj = [{"t_s": i * 0.1, "x": 0.5, "y": 0.5} for i in range(100)]
    r = client.post("/observations", json=_stop_obs(predicted_trajectory=long_traj))
    assert r.status_code == 201
    from app.models.vision import MAX_TRAJECTORY_POINTS
    assert len(r.get_json()["predicted_trajectory"]) <= MAX_TRAJECTORY_POINTS
