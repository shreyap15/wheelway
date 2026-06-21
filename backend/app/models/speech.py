"""Speech request model for POST /speak.

Compatible with the shared alert contract but requires ONLY text + priority;
dedupe_key (and other alert fields) are optional and ignored if extra.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

MAX_TEXT_LEN = 1000
PRIORITIES = {"info", "warning", "critical"}
DEFAULT_MODEL = "aura-asteria-en"


class SpeechRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT_LEN)
    priority: str = "info"
    # Optional: dedupe + alert-contract passthrough fields.
    dedupe_key: Optional[str] = None
    route_session_id: Optional[str] = None
    alert_id: Optional[str] = None
    type: Optional[str] = None
    # Optional voice/model settings.
    model: str = DEFAULT_MODEL

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text must be non-empty")
        return v

    @field_validator("priority")
    @classmethod
    def _valid_priority(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"priority must be one of {sorted(PRIORITIES)}")
        return v

    @field_validator("model")
    @classmethod
    def _safe_model(cls, v: str) -> str:
        # Guard against header/param injection via the optional model setting.
        if not v or len(v) > 64 or not all(c.isalnum() or c in "-_." for c in v):
            raise ValueError("invalid model")
        return v
