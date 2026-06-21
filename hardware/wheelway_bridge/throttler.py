"""Decide WHEN to publish -- never one POST per object per frame (§5).

Stateful, pure (no I/O), unit-testable. ``decide`` is called every loop with the
current command + top-risk summary; it emits only on a meaningful change, plus a
periodic heartbeat. Ordinary frame churn (same action, same top track, same TTC
band, same corridor state) does NOT emit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set


def ttc_band(ttc: Optional[float], warning_ttc: float, critical_ttc: float) -> str:
    """Bucket TTC into none/warning/critical so threshold *crossings* trigger emit."""
    if ttc is None:
        return "none"
    if ttc <= critical_ttc:
        return "critical"
    if ttc <= warning_ttc:
        return "warning"
    return "none"


@dataclass
class Throttler:
    warning_ttc: float = 3.0
    critical_ttc: float = 1.5
    heartbeat_s: float = 5.0
    high_risk: float = 0.7

    _last_action: Optional[str] = None
    _last_top_id: Optional[int] = None
    _last_band: str = "none"
    _last_in_corridor: bool = False
    _seen_high_risk_ids: Set[int] = field(default_factory=set)
    _last_emit_t: float = -1e9
    _last_heartbeat_t: float = -1e9

    def decide(
        self,
        now: float,
        *,
        action: str,
        top_track_id: Optional[int],
        ttc: Optional[float],
        risk: Optional[float],
        in_corridor: bool,
    ) -> List[str]:
        """Return a list of trigger reasons (empty list == do not emit)."""
        reasons: List[str] = []
        band = ttc_band(ttc, self.warning_ttc, self.critical_ttc)

        if action != self._last_action:
            reasons.append("command_changed")
        if action == "STOP" and self._last_action != "STOP":
            reasons.append("stop")
        if top_track_id is not None and top_track_id != self._last_top_id:
            reasons.append("top_track_changed")
        if band != self._last_band:
            reasons.append(f"ttc_{band}")
        if in_corridor != self._last_in_corridor:
            reasons.append("corridor_changed")
        if (
            top_track_id is not None
            and risk is not None
            and risk >= self.high_risk
            and top_track_id not in self._seen_high_risk_ids
        ):
            reasons.append("new_high_risk_track")

        # Update state.
        self._last_action = action
        self._last_top_id = top_track_id
        self._last_band = band
        self._last_in_corridor = in_corridor
        if top_track_id is not None and risk is not None and risk >= self.high_risk:
            self._seen_high_risk_ids.add(top_track_id)
        # Bound the memory of seen ids.
        if len(self._seen_high_risk_ids) > 256:
            self._seen_high_risk_ids = set(list(self._seen_high_risk_ids)[-128:])

        if reasons:
            self._last_emit_t = now
        return reasons

    def due_for_heartbeat(self, now: float) -> bool:
        if now - self._last_heartbeat_t >= self.heartbeat_s:
            self._last_heartbeat_t = now
            return True
        return False
