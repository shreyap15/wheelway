"""EventSink tests: DI wiring, throttled emission, no-op standalone behavior."""

from types import SimpleNamespace

from wheelway_bridge.sink import NoOpEventSink, WheelwayEventSink, build_sink_from_env
from wheelway_bridge.status import DeviceStatus
from wheelway_bridge.throttler import Throttler


class _FakePublisher:
    enabled = True

    def __init__(self):
        self.submissions = []
        self.online = False

    def submit(self, obs, critical=False):
        self.submissions.append((obs, critical))
        return True

    def start(self):
        pass

    def stop(self):
        pass


def _track(tid=7, s=100.0, vs=30.0):
    return SimpleNamespace(id=tid, label="person", score=0.9, state=[240, 280, s, 1, 1, vs],
                           bbox=(120, 90, 360, 470))


def _risk(ttc=1.0, risk=0.9, in_corridor=True):
    return SimpleNamespace(ttc=ttc, risk=risk, in_corridor=in_corridor, lateral_offset=0.0,
                           pred_center=(240, 280))


def _cmd(action):
    return SimpleNamespace(action=action, steer=0.0, speed=0.0, reason="x")


def _sink(pub, t=[0.0]):
    # deterministic clock; heartbeat large so it doesn't interfere with hazard asserts
    clock = {"v": 0.0}
    def now():
        return clock["v"]
    sink = WheelwayEventSink(
        pub, Throttler(heartbeat_s=1e9), DeviceStatus("dev", now_fn=now),
        device_id="wheelway-pi-01", now_fn=now,
    )
    return sink, clock


def test_stop_emits_one_critical_observation():
    pub = _FakePublisher()
    sink, clock = _sink(pub)
    sink.publish(command=_cmd("STOP"), tracks=[_track()], risks=[_risk()], trajectories=[[[240, 280, 100]]],
                 frame_width=640, frame_height=480)
    # one hazard submission (heartbeat suppressed by huge interval after first)
    hazards = [s for s in pub.submissions if s[0].get("feature_type") == "dynamic_obstacle"]
    assert len(hazards) == 1
    obs, critical = hazards[0]
    assert obs["avoidance_action"] == "STOP" and critical is True


def test_repeated_frames_do_not_re_emit():
    pub = _FakePublisher()
    sink, clock = _sink(pub)
    for i in range(5):
        clock["v"] = i * 0.05
        sink.publish(command=_cmd("STOP"), tracks=[_track()], risks=[_risk()],
                     trajectories=[[[240, 280, 100]]], frame_width=640, frame_height=480)
    hazards = [s for s in pub.submissions if s[0].get("feature_type") == "dynamic_obstacle"]
    assert len(hazards) == 1  # only the first (command change) emits


def test_command_change_emits_again():
    pub = _FakePublisher()
    sink, clock = _sink(pub)
    sink.publish(command=_cmd("STOP"), tracks=[_track()], risks=[_risk()],
                 trajectories=[[[240, 280, 100]]], frame_width=640, frame_height=480)
    clock["v"] = 1.0
    sink.publish(command=_cmd("CLEAR"), tracks=[], risks=[], trajectories=[],
                 frame_width=640, frame_height=480)
    hazards = [s for s in pub.submissions if s[0].get("feature_type") == "dynamic_obstacle"]
    assert {h[0]["avoidance_action"] for h in hazards} == {"STOP", "CLEAR"}


def test_noop_sink_does_nothing():
    sink = NoOpEventSink()
    sink.start()
    sink.publish(command=_cmd("STOP"), tracks=[_track()], risks=[_risk()],
                 trajectories=[[[1, 2, 3]]], frame_width=10, frame_height=10)
    sink.stop()  # no exception, no side effects


def test_build_sink_from_env_disabled():
    sink = build_sink_from_env({"WHEELWAY_PUBLISH_ENABLED": "false"})
    assert isinstance(sink, NoOpEventSink)


def test_build_sink_from_env_enabled_no_secret_logged():
    sink = build_sink_from_env({
        "WHEELWAY_PUBLISH_ENABLED": "true",
        "WHEELWAY_BACKEND_URL": "http://10.0.0.5:5000",
        "WHEELWAY_DEVICE_TOKEN": "supersecrettoken",
        "WHEELWAY_DEVICE_ID": "wheelway-pi-01",
    })
    assert isinstance(sink, WheelwayEventSink)
    # Token is stored privately, never exposed on the public object surface.
    assert "supersecrettoken" not in repr(vars(sink))
