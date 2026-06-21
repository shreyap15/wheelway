"""Server-side Deepgram text-to-speech for WheelWay voice alerts.

Owns the Deepgram call ONLY. The API key (``DEEPGRAM_API_KEY``) stays server-side
and is never returned to clients. Synthesis has an explicit timeout and maps
failures to typed errors the /speak endpoint translates to 503/502.
"""

from __future__ import annotations

import os
from typing import Optional

import requests

DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"
DEFAULT_MODEL = "aura-asteria-en"
DEFAULT_TIMEOUT_S = 8
AUDIO_MIME = "audio/mpeg"  # mp3


class DeepgramNotConfigured(Exception):
    """Raised when DEEPGRAM_API_KEY is absent -> HTTP 503."""


class DeepgramSynthesisError(Exception):
    """Raised when the Deepgram request fails/times out -> HTTP 502."""


def get_api_key() -> Optional[str]:
    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    return key or None


def deepgram_configured() -> bool:
    return get_api_key() is not None


def synthesize(
    text: str,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT_S,
    session: Optional[requests.Session] = None,
) -> bytes:
    """Synthesize ``text`` to mp3 bytes via Deepgram.

    Raises DeepgramNotConfigured when no key is set, DeepgramSynthesisError on
    any transport/HTTP failure or empty audio. Single attempt + explicit timeout
    (no retry storm).
    """
    key = get_api_key()
    if not key:
        raise DeepgramNotConfigured("DEEPGRAM_API_KEY is not configured.")

    http = session or requests
    headers = {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
        "Accept": AUDIO_MIME,
    }
    try:
        resp = http.post(
            DEEPGRAM_SPEAK_URL,
            params={"model": model},
            json={"text": text},
            headers=headers,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise DeepgramSynthesisError("Deepgram request timed out.") from exc
    except requests.RequestException as exc:
        raise DeepgramSynthesisError(f"Deepgram request failed: {type(exc).__name__}") from exc

    if not getattr(resp, "ok", False):
        # Never echo the upstream body verbatim (may contain request context).
        raise DeepgramSynthesisError(f"Deepgram synthesis HTTP {resp.status_code}.")

    audio = resp.content
    if not audio:
        raise DeepgramSynthesisError("Deepgram returned empty audio.")
    return audio
