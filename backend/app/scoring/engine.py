"""
WheelWay — Accessibility Scoring Engine.

Two outputs, used for different purposes:

1. accessibility_score(segment, profile) -> float in [0, 100]
   A human-facing score ("this segment is 92/100 accessible"). Smooth,
   continuous, good for UI display and per-segment color-coding on the map.

2. traversal_cost(segment, profile) -> float in [0, inf)
   A routing-facing cost used as the edge weight for the A* router. Lower is
   better. This is NOT just `100 - score` — it also applies hard
   disqualification (infinite cost) for segments that violate a user's hard
   constraints (e.g. stairs when avoid_stairs=True, slope beyond their
   personal max), which a 0-100 score alone can't express cleanly.

Design notes:
- All per-factor penalties are computed as sub-scores in [0, 1] (1 = perfect),
  combined with weights from constants.DEFAULT_WEIGHTS, then scaled to 0-100.
- Slope and cross-slope use piecewise-linear penalty curves anchored on the
  PROWAG thresholds in constants.py, not arbitrary linear scaling — e.g. the
  penalty for 5% running slope (PROWAG soft max) is meaningfully different
  from 8.33% (PROWAG ramp hard max) and from 12% (essentially impassable).
"""

from __future__ import annotations

import math
import time

from app.models.accessibility import Segment, UserMobilityProfile, SurfaceType, SURFACE_BASE_QUALITY
from app.scoring import constants as C


def _piecewise_penalty(value: float, ideal_max: float, hard_max: float, severe: float) -> float:
    """
    Generic piecewise-linear penalty curve, returns a quality multiplier in [0, 1].

      value <= ideal_max        -> 1.0 (no penalty)
      ideal_max < value <= hard_max -> linear taper from 1.0 to 0.4
      hard_max < value <= severe    -> linear taper from 0.4 to 0.05
      value > severe                -> 0.05 (essentially impassable, never exactly
                                       zero so routing can still find it as a last resort
                                       if literally nothing else exists)
    """
    value = abs(value)
    if value <= ideal_max:
        return 1.0
    if value <= hard_max:
        # taper 1.0 -> 0.4
        span = hard_max - ideal_max
        frac = (value - ideal_max) / span if span > 0 else 1.0
        return 1.0 - 0.6 * frac
    if value <= severe:
        span = severe - hard_max
        frac = (value - hard_max) / span if span > 0 else 1.0
        return 0.4 - 0.35 * frac
    return 0.05


def slope_quality(slope_pct: float) -> float:
    """Quality multiplier in [0,1] for running slope, anchored on PROWAG R302.5/R304."""
    return _piecewise_penalty(
        slope_pct, C.SLOPE_IDEAL_MAX, C.SLOPE_HARD_CAP, C.SLOPE_SEVERE
    )


def cross_slope_quality(cross_slope_pct: float) -> float:
    """Quality multiplier in [0,1] for cross slope, anchored on PROWAG R302.6."""
    return _piecewise_penalty(
        cross_slope_pct, C.CROSS_SLOPE_IDEAL_MAX, C.CROSS_SLOPE_EXCEPTION_MAX, C.CROSS_SLOPE_SEVERE
    )


def width_quality(width_m: float, profile: UserMobilityProfile | None = None) -> float:
    """
    Quality multiplier in [0,1] for clear width.
    Below the user's min_width_m (or ADA absolute minimum if no profile),
    quality collapses toward 0 since the segment may simply not fit a
    wheelchair/scooter footprint.
    """
    min_required = profile.min_width_m if profile else C.WIDTH_ADA_MIN
    if width_m >= C.WIDTH_PREFERRED:
        return 1.0
    if width_m >= min_required:
        # linear taper from 1.0 at preferred down to 0.5 at the minimum required
        span = C.WIDTH_PREFERRED - min_required
        frac = (width_m - min_required) / span if span > 0 else 1.0
        return 0.5 + 0.5 * frac
    if width_m <= 0:
        return 0.0
    # below minimum: steep penalty, not necessarily zero (a determined manual
    # chair user might still squeeze through something slightly under spec)
    return max(0.0, 0.5 * (width_m / min_required))


def surface_quality(surface: SurfaceType, surface_condition: float, sensitivity: float = 1.0) -> float:
    """
    Combines surface *type* (material) with surface *condition* (instance
    quality, e.g. cracked vs. smooth concrete) into one [0,1] multiplier.
    `sensitivity` (0-2) lets a user profile amplify/dampen the penalty.
    """
    base = SURFACE_BASE_QUALITY.get(surface, SURFACE_BASE_QUALITY[SurfaceType.UNKNOWN])
    combined = base * surface_condition
    # apply sensitivity around the neutral point of 1.0
    adjusted = 1.0 - (1.0 - combined) * sensitivity
    return max(0.0, min(1.0, adjusted))


def confidence_decay(last_verified_ts: float | None, base_confidence: float) -> float:
    """
    Exponential decay of data confidence since last verification, with a
    floor at 0.5 (we never fully distrust crowdsourced/CV data, just discount it).
    """
    if last_verified_ts is None:
        return base_confidence
    days_elapsed = max(0.0, (time.time() - last_verified_ts) / 86400.0)
    decay_factor = math.pow(0.5, days_elapsed / C.CONFIDENCE_HALF_LIFE_DAYS)
    decayed = 0.5 + (base_confidence - 0.5) * decay_factor
    return max(0.0, min(1.0, decayed))


def accessibility_score(
    segment: Segment,
    profile: UserMobilityProfile | None = None,
    weights: dict | None = None,
) -> float:
    """
    Returns a 0-100 human-facing accessibility score for a segment, optionally
    personalized to a user's mobility profile.
    """
    w = weights or C.DEFAULT_WEIGHTS
    profile = profile or UserMobilityProfile()

    s_slope = slope_quality(segment.slope)
    s_cross = cross_slope_quality(segment.cross_slope)
    s_width = width_quality(segment.width, profile)
    s_surface_cond = segment.surface_condition
    s_surface_type = surface_quality(
        segment.surface, segment.surface_condition, profile.surface_sensitivity
    ) / max(segment.surface_condition, 1e-6)  # isolate the "type" component
    s_surface_type = max(0.0, min(1.0, s_surface_type))

    raw = (
        w["slope"] * s_slope
        + w["cross_slope"] * s_cross
        + w["surface_condition"] * s_surface_cond
        + w["width"] * s_width
        + w["surface_type"] * s_surface_type
    )

    # Hard knockouts that should dominate regardless of weighted average:
    if segment.stairs:
        raw *= 0.05  # stairs are near-impassable for wheelchairs; not a clean 0
    if segment.has_obstruction:
        clearance = segment.obstruction_clearance_m
        if clearance is not None and clearance < profile.min_width_m:
            raw *= 0.2

    # Discount by construction risk and data confidence
    confidence = confidence_decay(segment.last_verified_ts, segment.report_confidence)
    risk_multiplier = 1.0 - 0.7 * segment.construction_risk
    raw *= risk_multiplier
    # low confidence pulls the score toward a neutral 50, rather than trusting
    # an extreme (good or bad) score from stale/unconfirmed data
    raw = raw * confidence + 0.5 * (1 - confidence)

    return round(max(0.0, min(1.0, raw)) * 100, 1)


def is_hard_disqualified(segment: Segment, profile: UserMobilityProfile) -> tuple[bool, str | None]:
    """
    Checks user-specific HARD constraints that should remove a segment from
    consideration entirely, regardless of its score. Returns (disqualified, reason).
    """
    if profile.avoid_stairs and segment.stairs:
        return True, "stairs"
    if abs(segment.slope) > profile.max_slope_pct:
        return True, f"slope {segment.slope}% exceeds user max {profile.max_slope_pct}%"
    if abs(segment.cross_slope) > profile.max_cross_slope_pct:
        return True, f"cross slope {segment.cross_slope}% exceeds user max {profile.max_cross_slope_pct}%"
    if segment.width < profile.min_width_m:
        return True, f"width {segment.width}m below user min {profile.min_width_m}m"
    if profile.avoid_unverified_segments and segment.last_verified_ts is None:
        return True, "unverified segment"
    if not segment.curb_ramp and segment.start_node_id != segment.end_node_id:
        # Only relevant where a curb transition is actually expected; the
        # router/graph builder should set curb_ramp=True for segments where
        # no curb exists at all. Treated as soft, not hard, by default.
        pass
    return False, None


def traversal_cost(
    segment: Segment,
    profile: UserMobilityProfile | None = None,
    weights: dict | None = None,
) -> float:
    """
    Routing-facing cost for A*/Dijkstra edge weight. Lower = better.
    Returns math.inf for hard-disqualified segments so the router simply
    cannot select them.

    Cost model: base distance (length in meters) scaled by an effort
    multiplier derived from the inverted accessibility score. A perfect
    100-score segment costs ~= its physical length; a 50-score segment costs
    roughly 3x its length; near-0-score segments become extremely expensive
    (but not literally infinite, unless hard-disqualified) so the router will
    still prefer them over no route at all when nothing better exists.
    """
    profile = profile or UserMobilityProfile()

    disqualified, _ = is_hard_disqualified(segment, profile)
    if disqualified:
        return math.inf

    score = accessibility_score(segment, profile, weights)  # 0-100
    score_frac = max(score / 100.0, 0.01)  # avoid divide-by-near-zero

    # effort multiplier: 1.0 at score=100, grows as score drops.
    # Using 1/score_frac gives: score=100 -> 1.0x, score=50 -> 2x, score=20 -> 5x, score=5 -> 20x
    effort_multiplier = 1.0 / score_frac

    if profile.max_route_effort is not None and effort_multiplier > profile.max_route_effort:
        return math.inf

    return segment.length_m * effort_multiplier


def explain_segment(segment: Segment, profile: UserMobilityProfile | None = None) -> dict:
    """
    Returns a breakdown dict suitable for feeding to the Claude reasoning
    layer for route explanations, or for debugging/UI display.
    """
    profile = profile or UserMobilityProfile()
    disqualified, reason = is_hard_disqualified(segment, profile)
    return {
        "segment_id": segment.segment_id,
        "accessibility_score": accessibility_score(segment, profile),
        "traversal_cost": traversal_cost(segment, profile),
        "disqualified": disqualified,
        "disqualification_reason": reason,
        "factors": {
            "slope_quality": round(slope_quality(segment.slope), 3),
            "cross_slope_quality": round(cross_slope_quality(segment.cross_slope), 3),
            "width_quality": round(width_quality(segment.width, profile), 3),
            "surface_quality": round(
                surface_quality(segment.surface, segment.surface_condition, profile.surface_sensitivity), 3
            ),
            "data_confidence": round(
                confidence_decay(segment.last_verified_ts, segment.report_confidence), 3
            ),
        },
    }
