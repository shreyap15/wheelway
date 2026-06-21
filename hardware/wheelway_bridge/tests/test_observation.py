"""Adapter tests: upstream stand-ins -> canonical WheelWay observation."""

from types import SimpleNamespace

from wheelway_bridge import observation as obs


def _track(tid=7, label="person", score=0.91, s=100.0, vs=20.0, bbox=(120, 90, 360, 470)):
    # state = [x, y, s, vx, vy, vs]
    state = [240.0, 280.0, s, 1.0, 1.0, vs]
    return SimpleNamespace(id=tid, label=label, score=score, state=state, bbox=bbox)


def _risk(ttc=1.4, risk=0.87, in_corridor=True, lateral_offset=0.1):
    return SimpleNamespace(ttc=ttc, risk=risk, in_corridor=in_corridor,
                           lateral_offset=lateral_offset, pred_center=(240.0, 280.0))


def _cmd(action="STOP", steer=0.0):
    return SimpleNamespace(action=action, steer=steer, speed=0.0, reason="head-on TTC=0.80s risk=0.90")


def _traj(n=10):
    return [[240.0 + i, 280.0 + 2 * i, 100.0 + i] for i in range(n)]


def test_stop_payload():
    o = obs.build_observation(
        command=_cmd("STOP", 0.0), tracks=[_track()], risks=[_risk()], trajectories=[_traj()],
        frame_width=640, frame_height=480, device_id="wheelway-pi-01",
        model="efficientdet_lite0", pipeline_version="vision-modal-7b9d823",
    )
    assert o["source"] == "vision_modal"
    assert o["avoidance_action"] == "STOP"
    assert o["object_label"] == "person"
    assert o["track_id"] == 7
    assert o["confidence"] == 0.91
    assert o["collision_risk"] == 0.87
    assert o["time_to_collision_s"] == 1.4
    assert o["in_danger_corridor"] is True
    assert o["looming_is_relative"] is True
    assert o["looming"] == 0.2  # vs/s = 20/100
    assert o["bounding_box"] == {"x_min": 120, "y_min": 90, "x_max": 360, "y_max": 470}
    assert o["model"] == "efficientdet_lite0"
    assert o["pipeline_version"] == "vision-modal-7b9d823"
    # User-facing reason must not contain raw physics terms.
    assert "TTC" not in o["avoidance_reason"] and "risk=" not in o["avoidance_reason"]


def test_left_right_payloads():
    left = obs.build_observation(
        command=_cmd("LEFT", -0.8), tracks=[_track()], risks=[_risk(ttc=2.0, risk=0.6)],
        trajectories=[_traj()], frame_width=640, frame_height=480)
    assert left["avoidance_action"] == "LEFT"
    assert left["steer_vector"] == {"x": -0.8, "y": 0.0}
    assert "right" in left["avoidance_reason"]  # LEFT == obstacle on the right

    right = obs.build_observation(
        command=_cmd("RIGHT", 0.8), tracks=[_track()], risks=[_risk()], trajectories=[_traj()],
        frame_width=640, frame_height=480)
    assert right["avoidance_action"] == "RIGHT"
    assert "left" in right["avoidance_reason"]


def test_infinite_or_negative_ttc_becomes_null():
    inf = obs.build_observation(command=_cmd("LEFT"), tracks=[_track()],
                                risks=[_risk(ttc=float("inf"))], trajectories=[_traj()],
                                frame_width=640, frame_height=480)
    assert inf["time_to_collision_s"] is None
    neg = obs.build_observation(command=_cmd("LEFT"), tracks=[_track()],
                                risks=[_risk(ttc=-1.0)], trajectories=[_traj()],
                                frame_width=640, frame_height=480)
    assert neg["time_to_collision_s"] is None


def test_trajectory_is_bounded_and_normalized():
    o = obs.build_observation(command=_cmd("STOP"), tracks=[_track()], risks=[_risk()],
                              trajectories=[_traj(40)], frame_width=640, frame_height=480)
    traj = o["predicted_trajectory"]
    assert 0 < len(traj) <= obs.MAX_TRAJECTORY_POINTS
    for p in traj:
        assert 0.0 <= p["x"] <= 1.0 and 0.0 <= p["y"] <= 1.0
        assert p["t_s"] >= 0.0


def test_looming_zero_when_receding():
    o = obs.build_observation(command=_cmd("CLEAR"), tracks=[_track(vs=-5.0)],
                              risks=[_risk(in_corridor=False, risk=0.1)], trajectories=[_traj()],
                              frame_width=640, frame_height=480)
    assert o["looming"] == 0.0


def test_clear_with_no_tracks():
    o = obs.build_observation(command=_cmd("CLEAR"), tracks=[], risks=[], trajectories=[],
                              frame_width=640, frame_height=480)
    assert o["avoidance_action"] == "CLEAR"
    assert o["track_id"] is None
    assert o["bounding_box"] is None
    assert o["predicted_trajectory"] == []


def test_scene_enrichment_and_other_risks():
    scene = SimpleNamespace(ok=True, scene="A person is crossing ahead.", age=lambda: 0.8)
    o = obs.build_observation(
        command=_cmd("STOP"), tracks=[_track(7), _track(9, "bicycle")],
        risks=[_risk(risk=0.9), _risk(risk=0.7)], trajectories=[_traj(), _traj()],
        frame_width=640, frame_height=480, scene=scene)
    assert o["scene_summary"] == "A person is crossing ahead."
    assert o["scene_summary_age_s"] == 0.8
    assert "other_active_risks" in o and len(o["other_active_risks"]) == 1
    assert o["other_active_risks"][0]["object_label"] == "bicycle"
