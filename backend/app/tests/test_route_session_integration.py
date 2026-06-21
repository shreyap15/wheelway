"""Integration tests: route sessions, alerts, events, shared dedupe, Fetch.ai
reads, degraded modes. Pipeline + external calls mocked (no paid calls)."""

import pytest

import accessroute.pipeline as pipeline
from accessroute import route_state, route_state_query
from app.services import dedupe_service, state_store
from app.services.dedupe_service import StateStoreDedupe
from app.services.state_store import MemoryBackend, RedisBackend


class _FakeResult:
    def __init__(self, d):
        self._d = d

    def dict(self):
        return self._d


def _result(routes, destination_place=None, service_degraded=False):
    return {
        "mode": "real_route",
        "origin": {"latitude": 37.869, "longitude": -122.259},
        "destination": {"latitude": 37.868, "longitude": -122.258},
        "profile": {"max_incline_grade": 8.33},
        "routes": routes,
        "destination_place": destination_place or {},
        "service_degraded": service_degraded,
        "warnings": [],
        "data_sources": {},
    }


def _route(rid, *, exceed=0.0, stairs="not_detected", score=90.0, rec=False, rank=1, dist=400.0):
    return {
        "route_id": rid,
        "geometry": {"type": "LineString", "coordinates": [[-122.259, 37.869], [-122.258, 37.868]]},
        "distance_m": dist,
        "duration_s": 300.0,
        "max_slope_pct": 12.0 if exceed else 3.0,
        "exceeds_limit_distance_m": exceed,
        "exceeds_limit_percentage": 15.0 if exceed else 0.0,
        "accessibility_score": score,
        "stairs_status": stairs,
        "recommended": rec,
        "accessibility_rank": rank,
        "selection_reasons": ["because"],
    }


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    state_store.reset_store()
    dedupe_service.reset_dedupe()
    route_state.reset_store()
    yield
    state_store.reset_store()
    dedupe_service.reset_dedupe()
    route_state.reset_store()


@pytest.fixture
def client(monkeypatch):
    from main import app  # installs the route-state adapter

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _patch_pipeline(monkeypatch, result):
    async def fake_compute(*a, **k):
        return _FakeResult(result)

    monkeypatch.setattr(pipeline, "compute_accessible_routes", fake_compute)


VALID_BODY = {
    "origin": {"latitude": 37.869, "longitude": -122.259},
    "destination": {"latitude": 37.868, "longitude": -122.258},
    "profile": {"max_slope_pct": 8.33},
}


# --------------------------------------------------------------------------- #
# /real-route session + alerts
# --------------------------------------------------------------------------- #
def test_real_route_returns_and_stores_session(client, monkeypatch):
    _patch_pipeline(monkeypatch, _result([_route("route-1", rec=True)]))
    data = client.post("/real-route", json=VALID_BODY).get_json()
    sid = data["route_session_id"]
    assert sid and sid.startswith("rs-")
    # Stored + readable through the shared abstraction.
    assert route_state.get_session(sid)["route_session_id"] == sid


def test_meaningful_alerts_and_auto_speak(client, monkeypatch):
    selected = _route("route-1", exceed=50.0, stairs="confirmed", rec=True)
    other = _route("route-2", exceed=0.0, rank=2)
    _patch_pipeline(
        monkeypatch,
        _result([selected, other], destination_place={"place_name": "Library", "wheelchair_accessible_entrance": True}),
    )
    data = client.post("/real-route", json=VALID_BODY).get_json()
    types = {a["type"] for a in data["alerts"]}
    assert "steep_slope" in types and "stairs" in types and "destination" in types
    auto = {a["type"] for a in data["auto_speak_alerts"]}
    assert "stairs" in auto and "steep_slope" in auto
    assert "destination" not in auto  # info is text-only

    events = {e["type"] for e in route_state.recent_events()}
    assert "route.created" in events and "alert.created" in events


def test_no_compliant_route_alert(client, monkeypatch):
    _patch_pipeline(
        monkeypatch,
        _result([_route("route-1", exceed=40.0, rec=True), _route("route-2", exceed=60.0, rank=2)]),
    )
    data = client.post("/real-route", json=VALID_BODY).get_json()
    assert any(a["type"] == "no_compliant_route" for a in data["alerts"])


def test_alternative_selection_updates_same_session(client, monkeypatch):
    _patch_pipeline(
        monkeypatch,
        _result([_route("route-1", rec=True), _route("route-2", rank=2)]),
    )
    sid = client.post("/real-route", json=VALID_BODY).get_json()["route_session_id"]

    resp = client.post(f"/route-sessions/{sid}/select", json={"route_id": "route-2"})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["selected_route_id"] == "route-2"
    # SAME session updated (not a new one).
    assert route_state.get_session(sid)["selected_route_id"] == "route-2"
    assert any(a["type"] == "reroute" for a in body["alerts"])


def test_select_invalid_route_400(client, monkeypatch):
    _patch_pipeline(monkeypatch, _result([_route("route-1", rec=True)]))
    sid = client.post("/real-route", json=VALID_BODY).get_json()["route_session_id"]
    assert client.post(f"/route-sessions/{sid}/select", json={"route_id": "nope"}).status_code == 400


def test_select_unknown_session_404(client):
    assert client.post("/route-sessions/rs-missing/select", json={"route_id": "r"}).status_code == 404


def test_deepgram_unavailable_does_not_break_routing(client, monkeypatch):
    # No DEEPGRAM key; /real-route must still return geometry + session.
    _patch_pipeline(monkeypatch, _result([_route("route-1", rec=True)]))
    data = client.post("/real-route", json=VALID_BODY).get_json()
    assert data["routes"][0]["geometry"]["coordinates"][0] == [-122.259, 37.869]
    assert data["route_session_id"]


# --------------------------------------------------------------------------- #
# Shared dedupe (Deepgram <-> route alerts)
# --------------------------------------------------------------------------- #
def test_shared_dedupe_memory_once_then_suppressed():
    d = StateStoreDedupe()  # -> state_store (memory, no REDIS_URL)
    assert d.claim_dedupe_key("k1", 60) is True
    assert d.claim_dedupe_key("k1", 60) is False


def test_shared_dedupe_uses_redis_backend_when_connected():
    class FakeRedis:
        def __init__(self):
            self.kv = {}

        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.kv:
                return None
            self.kv[key] = value
            return True

    state_store.set_store(RedisBackend(FakeRedis()))
    assert state_store.storage_mode() == "redis"
    d = StateStoreDedupe()
    assert d.claim_dedupe_key("dup", 60) is True
    assert d.claim_dedupe_key("dup", 60) is False  # held in redis NX


def test_duplicate_alert_suppressed_via_shared_dedupe():
    # Same dedupe key claimed once across the shared store.
    assert state_store.claim_dedupe_key("stairs:rs-1:route-2", 60) is True
    assert state_store.claim_dedupe_key("stairs:rs-1:route-2", 60) is False


# --------------------------------------------------------------------------- #
# Fetch.ai reads through the abstraction
# --------------------------------------------------------------------------- #
def test_fetchai_reads_active_route_through_abstraction(client, monkeypatch):
    selected = _route("route-1", exceed=20.0, stairs="likely", rec=True)
    _patch_pipeline(
        monkeypatch,
        _result([selected], destination_place={"place_name": "Cafe", "wheelchair_accessible_entrance": True}),
    )
    sid = client.post("/real-route", json=VALID_BODY).get_json()["route_session_id"]

    answers = route_state_query.answer_route_questions(sid)
    assert answers["found"] is True
    assert answers["selected_route_id"] == "route-1"
    assert answers["stair_status"] == "likely"
    assert answers["steepest_section"]["exceeds_limit_distance_m"] == 20.0
    assert answers["accessible_entrance"]["place_name"] == "Cafe"
    assert any(a["route_session_id"] == sid for a in answers["active_alerts"])


def test_fetchai_unknown_session_graceful():
    assert route_state_query.answer_route_questions("rs-none")["found"] is False
