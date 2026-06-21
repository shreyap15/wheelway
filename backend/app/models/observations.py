"""Observation model helpers for the live-state layer.

Observations stay plain dicts on the wire (preserving the existing request
contract); these helpers only normalize/augment them with an id + timestamp.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_observation(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a normalized observation dict with a stable id + timestamp.

    Preserves every field the caller supplied (current contract) and only fills
    ``id`` and ``timestamp`` when missing.
    """
    obs = dict(data or {})
    obs.setdefault("id", uuid.uuid4().hex)
    obs.setdefault("timestamp", _now_iso())
    return obs
