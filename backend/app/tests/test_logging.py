"""Backend terminal-logging tests.

Verify that meaningful events are logged for the demo terminal, and — critically —
that no secret (API key, Redis URL) ever appears in a log record.
"""

import logging

import pytest

from main import app
from app.services import deepgram_service, state_store

SECRET_KEY = "sk-supersecret-DEEPGRAM-123"
SECRET_REDIS_URL = "redis://user:secretpw@localhost:6399/0"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _all_text(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


def test_storage_logs_mode_without_leaking_redis_url(monkeypatch, caplog):
    monkeypatch.setenv("REDIS_URL", SECRET_REDIS_URL)
    state_store.reset_store()
    with caplog.at_level(logging.INFO, logger="wheelway.storage"):
        mode = state_store.storage_mode()  # unreachable redis -> memory fallback
    text = _all_text(caplog)
    assert mode == "memory"
    assert "[storage] mode=memory" in text
    # The URL and its embedded password must never be logged.
    assert SECRET_REDIS_URL not in text
    assert "secretpw" not in text
    assert "redis://" not in text
    state_store.reset_store()


def test_speak_logs_request_and_failure_without_leaking_key(monkeypatch, caplog, client):
    monkeypatch.setenv("DEEPGRAM_API_KEY", SECRET_KEY)
    monkeypatch.setattr(deepgram_service, "deepgram_configured", lambda: True)

    def _boom(*_a, **_k):
        raise deepgram_service.DeepgramSynthesisError("upstream 500")

    monkeypatch.setattr(deepgram_service, "synthesize", _boom)

    with caplog.at_level(logging.INFO, logger="wheelway.speech"):
        resp = client.post(
            "/speak",
            json={"text": "Steep slope ahead", "priority": "warning", "type": "steep_slope"},
        )
    text = _all_text(caplog)
    assert resp.status_code == 502
    assert "[speech] requested priority=warning" in text
    assert "[speech] failed priority=warning" in text
    # The spoken text, the API key, and exception internals must not leak.
    assert SECRET_KEY not in text
    assert "Steep slope ahead" not in text


def test_speak_logs_duplicate_suppressed(monkeypatch, caplog, client):
    monkeypatch.setattr(deepgram_service, "deepgram_configured", lambda: True)
    monkeypatch.setattr(deepgram_service, "synthesize", lambda *a, **k: b"audio")
    from app.services.dedupe_service import get_dedupe

    # First call claims the key; second is suppressed and logged.
    get_dedupe().claim_dedupe_key("dup-key-1", 30)
    with caplog.at_level(logging.INFO, logger="wheelway.speech"):
        resp = client.post(
            "/speak",
            json={"text": "x", "priority": "info", "dedupe_key": "dup-key-1"},
        )
    assert resp.status_code == 409
    assert "[speech] duplicate_suppressed key=dup-key-1" in _all_text(caplog)
