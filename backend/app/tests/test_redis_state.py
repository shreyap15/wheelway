"""Live-state layer tests: Redis backend (fake client), memory fallback, TTLs,
stream events, dedupe, health, and route-request survival during a Redis outage.

No real Redis package or server is required -- the Redis path runs against an
in-test FakeRedis implementing only the ops the backend uses.
"""

import pytest

from app.models.events import (
    EVENT_ALERT_CREATED,
    EVENT_OBSERVATION_CREATED,
    EVENT_ROUTE_RECALCULATED,
    EVENT_ROUTE_SELECTED,
    make_alert,
)
from app.models.observations import make_observation
from app.services import redis_service, state_store
from app.services.state_store import (
    ALERT_KEY,
    DEDUPE_KEY,
    OBS_KEY,
    OBS_TTL_SECONDS,
    ALERT_TTL_SECONDS,
    MemoryBackend,
    RedisBackend,
)


class FakeRedis:
    """Minimal Redis stand-in covering the ops RedisBackend uses."""

    def __init__(self, fail=False):
        self.fail = fail
        self.kv = {}
        self.expires = {}
        self.lists = {}
        self.streams = {}
        self._seq = 0

    def ping(self):
        if self.fail:
            raise ConnectionError("redis down")
        return True

    def setex(self, key, ttl, value):
        self.kv[key] = value
        self.expires[key] = ttl

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True

    def get(self, key):
        return self.kv.get(key)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        if key in self.lists:
            self.lists[key] = self.lists[key][start : end + 1]

    def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        end = len(lst) - 1 if end == -1 else end
        return lst[start : end + 1]

    def xadd(self, stream, fields, maxlen=None, approximate=True):
        self._seq += 1
        sid = f"{self._seq}-0"
        self.streams.setdefault(stream, []).append((sid, dict(fields)))
        if maxlen:
            self.streams[stream] = self.streams[stream][-maxlen:]
        return sid

    def xrevrange(self, stream, count=None):
        items = list(reversed(self.streams.get(stream, [])))
        return items[:count] if count else items


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    state_store.reset_store()
    yield
    state_store.reset_store()


# --------------------------------------------------------------------------- #
# Redis backend
# --------------------------------------------------------------------------- #
def test_redis_success_save_and_list():
    store = RedisBackend(FakeRedis())
    obs = make_observation({"device_id": "pi-1", "distance_cm": 42})
    store.save_observation(obs)
    listed = store.list_active_observations()
    assert listed and listed[-1]["id"] == obs["id"]


def test_ttl_assignment_on_observation_and_dedupe():
    fake = FakeRedis()
    store = RedisBackend(fake)
    obs = make_observation({"device_id": "pi-1"})
    store.save_observation(obs)
    assert fake.expires[OBS_KEY.format(id=obs["id"])] == OBS_TTL_SECONDS

    assert store.claim_dedupe_key("k1", 30) is True
    assert fake.expires[DEDUPE_KEY.format(key="k1")] == 30


def test_alert_storage_and_ttl():
    fake = FakeRedis()
    store = RedisBackend(fake)
    alert = make_alert(type="stairs", text="Stairs ahead", priority="warning")
    store.save_alert(alert)
    assert store.get_alert(alert["alert_id"])["text"] == "Stairs ahead"
    assert fake.expires[ALERT_KEY.format(id=alert["alert_id"])] == ALERT_TTL_SECONDS


def test_active_route_storage():
    store = RedisBackend(FakeRedis())
    store.save_active_route("sess-1", {"route_id": "route-1"})
    assert store.get_active_route("sess-1") == {"route_id": "route-1"}
    assert store.get_active_route("missing") is None


def test_stream_event_creation_for_each_action():
    store = RedisBackend(FakeRedis())
    store.save_observation(make_observation({"device_id": "pi"}))
    store.save_active_route("s1", {"x": 1})
    store.save_active_route("s1", {"x": 2}, event_type=EVENT_ROUTE_RECALCULATED)
    store.save_alert(make_alert(type="obstacle", text="!"))
    types = {e["type"] for e in store.list_events()}
    assert {
        EVENT_OBSERVATION_CREATED,
        EVENT_ROUTE_SELECTED,
        EVENT_ROUTE_RECALCULATED,
        EVENT_ALERT_CREATED,
    } <= types


def test_dedupe_redis_succeeds_once():
    store = RedisBackend(FakeRedis())
    assert store.claim_dedupe_key("dup", 60) is True
    assert store.claim_dedupe_key("dup", 60) is False  # held until TTL


# --------------------------------------------------------------------------- #
# Memory backend
# --------------------------------------------------------------------------- #
def test_memory_fallback_selected_without_redis():
    state_store.reset_store()
    assert state_store.storage_mode() == "memory"


def test_dedupe_memory_succeeds_once_then_after_expiry():
    clock = {"t": 1000.0}
    store = MemoryBackend(time_fn=lambda: clock["t"])
    assert store.claim_dedupe_key("k", 30) is True
    assert store.claim_dedupe_key("k", 30) is False  # still held
    clock["t"] += 31  # past TTL
    assert store.claim_dedupe_key("k", 30) is True


def test_memory_observation_ttl_expiry():
    clock = {"t": 0.0}
    store = MemoryBackend(time_fn=lambda: clock["t"])
    store.save_observation(make_observation({"device_id": "pi"}), ttl=10)
    assert len(store.list_active_observations()) == 1
    clock["t"] = 11
    assert store.list_active_observations() == []  # expired


# --------------------------------------------------------------------------- #
# Backend selection + outage
# --------------------------------------------------------------------------- #
def test_redis_selected_when_configured_and_reachable(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis_service, "create_client", lambda: FakeRedis())
    state_store.reset_store()
    assert state_store.storage_mode() == "redis"


def test_redis_outage_falls_back_to_memory(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis_service, "create_client", lambda: FakeRedis(fail=True))
    state_store.reset_store()
    # Unreachable Redis -> memory, and the store still works (route requests that
    # touch live-state never break).
    assert state_store.storage_mode() == "memory"
    state_store.save_observation(make_observation({"device_id": "pi"}))
    assert len(state_store.list_active_observations()) == 1


def test_invalid_alert_type_rejected():
    with pytest.raises(ValueError):
        make_alert(type="nope", text="x")


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
@pytest.fixture
def client():
    from main import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_reports_storage_status(client):
    body = client.get("/health").get_json()
    assert body["status"] == "ok"
    assert body["redis_configured"] is False
    assert body["redis_connected"] is False
    assert body["storage_mode"] == "memory"
    assert "REDIS_URL" not in body  # never exposed


def test_observations_roundtrip_and_event(client):
    state_store.set_store(MemoryBackend())
    posted = client.post("/observations", json={"device_id": "pi", "distance_cm": 55})
    assert posted.status_code == 201
    assert posted.get_json()["device_id"] == "pi"

    listed = client.get("/observations").get_json()
    assert any(o["device_id"] == "pi" for o in listed)

    events = client.get("/events").get_json()
    assert any(e["type"] == EVENT_OBSERVATION_CREATED for e in events)


def test_observations_missing_body_is_400(client):
    assert client.post("/observations", data="x", content_type="text/plain").status_code == 400
