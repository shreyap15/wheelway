"""Throttler tests: emit only on meaningful change, plus heartbeat."""

from wheelway_bridge.throttler import Throttler, ttc_band


def _t():
    return Throttler(warning_ttc=3.0, critical_ttc=1.5, heartbeat_s=5.0, high_risk=0.7)


def test_ttc_band_buckets():
    assert ttc_band(None, 3.0, 1.5) == "none"
    assert ttc_band(5.0, 3.0, 1.5) == "none"
    assert ttc_band(2.0, 3.0, 1.5) == "warning"
    assert ttc_band(1.0, 3.0, 1.5) == "critical"


def test_command_change_emits_then_repeats_are_silent():
    th = _t()
    r1 = th.decide(0.0, action="STOP", top_track_id=7, ttc=1.0, risk=0.9, in_corridor=True)
    assert "command_changed" in r1 and "stop" in r1
    # Identical subsequent frames: no new emission (ordinary frame churn).
    r2 = th.decide(0.05, action="STOP", top_track_id=7, ttc=1.0, risk=0.9, in_corridor=True)
    assert r2 == []
    r3 = th.decide(0.10, action="STOP", top_track_id=7, ttc=1.0, risk=0.9, in_corridor=True)
    assert r3 == []


def test_clear_transition_emits():
    th = _t()
    th.decide(0.0, action="STOP", top_track_id=7, ttc=1.0, risk=0.9, in_corridor=True)
    r = th.decide(0.2, action="CLEAR", top_track_id=None, ttc=None, risk=None, in_corridor=False)
    assert "command_changed" in r


def test_ttc_band_crossing_emits():
    th = _t()
    th.decide(0.0, action="LEFT", top_track_id=7, ttc=2.0, risk=0.6, in_corridor=True)  # warning
    r = th.decide(0.3, action="LEFT", top_track_id=7, ttc=1.0, risk=0.6, in_corridor=True)  # critical
    assert "ttc_critical" in r


def test_top_track_change_emits():
    th = _t()
    th.decide(0.0, action="LEFT", top_track_id=7, ttc=2.0, risk=0.6, in_corridor=True)
    r = th.decide(0.3, action="LEFT", top_track_id=9, ttc=2.0, risk=0.6, in_corridor=True)
    assert "top_track_changed" in r


def test_heartbeat_interval():
    th = _t()
    assert th.due_for_heartbeat(0.0) is True   # first is due
    assert th.due_for_heartbeat(1.0) is False
    assert th.due_for_heartbeat(6.0) is True
