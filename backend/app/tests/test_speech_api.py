"""Tests for the Deepgram /speak endpoint + service. All Deepgram calls mocked."""

import pytest
import requests

from app.services import deepgram_service
from app.services.dedupe_service import InMemoryDedupe, reset_dedupe
from app.services.deepgram_service import (
    DeepgramNotConfigured,
    DeepgramSynthesisError,
    synthesize,
)


@pytest.fixture
def client():
    from main import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    from app.services import state_store

    monkeypatch.delenv("REDIS_URL", raising=False)
    state_store.reset_store()
    reset_dedupe()
    yield
    state_store.reset_store()
    reset_dedupe()


VALID = {"text": "Steep slope begins in 20 meters.", "priority": "warning"}


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
def test_missing_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    resp = client.post("/speak", json=VALID)
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "deepgram_not_configured"


def test_successful_audio_response(client, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(deepgram_service, "synthesize", lambda text, **k: b"FAKE_MP3")
    resp = client.post("/speak", json=VALID)
    assert resp.status_code == 200
    assert resp.mimetype == "audio/mpeg"
    assert resp.data == b"FAKE_MP3"
    assert resp.headers["X-Alert-Priority"] == "warning"


def test_upstream_failure_returns_502(client, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")

    def boom(text, **k):
        raise DeepgramSynthesisError("Deepgram request timed out.")

    monkeypatch.setattr(deepgram_service, "synthesize", boom)
    resp = client.post("/speak", json=VALID)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "synthesis_failed"


def test_empty_text_is_400(client, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    resp = client.post("/speak", json={"text": "   ", "priority": "info"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_request"


def test_oversized_text_is_400(client, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    resp = client.post("/speak", json={"text": "x" * 1001, "priority": "info"})
    assert resp.status_code == 400


def test_invalid_priority_is_400(client, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    resp = client.post("/speak", json={"text": "hi", "priority": "URGENT"})
    assert resp.status_code == 400


def test_dedupe_suppresses_repeat(client, monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(deepgram_service, "synthesize", lambda text, **k: b"FAKE_MP3")
    body = {**VALID, "dedupe_key": "steep:route-123:seg-7"}
    first = client.post("/speak", json=body)
    second = client.post("/speak", json=body)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["error"] == "duplicate_suppressed"


def test_validation_checked_before_synthesis(client, monkeypatch):
    # Bad body must not reach Deepgram.
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    called = {"n": 0}
    monkeypatch.setattr(deepgram_service, "synthesize", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or b"x")
    client.post("/speak", json={"priority": "info"})  # missing text
    assert called["n"] == 0


# --------------------------------------------------------------------------- #
# Service (no network)
# --------------------------------------------------------------------------- #
class _Resp:
    def __init__(self, ok=True, status=200, content=b"MP3"):
        self.ok = ok
        self.status_code = status
        self.content = content


class _Session:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def post(self, *a, **k):
        if self._exc:
            raise self._exc
        return self._resp


def test_service_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(DeepgramNotConfigured):
        synthesize("hi")


def test_service_success(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    audio = synthesize("hi", session=_Session(resp=_Resp(content=b"MP3DATA")))
    assert audio == b"MP3DATA"


def test_service_timeout_maps_to_error(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    with pytest.raises(DeepgramSynthesisError):
        synthesize("hi", session=_Session(exc=requests.Timeout()))


def test_service_http_error_maps_to_error(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    with pytest.raises(DeepgramSynthesisError):
        synthesize("hi", session=_Session(resp=_Resp(ok=False, status=500)))


def test_inmemory_dedupe_ttl():
    clock = {"t": 0.0}
    d = InMemoryDedupe(time_fn=lambda: clock["t"])
    assert d.claim_dedupe_key("k", 30) is True
    assert d.claim_dedupe_key("k", 30) is False
    clock["t"] = 31
    assert d.claim_dedupe_key("k", 30) is True
