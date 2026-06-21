"""Route scoring and selection logic for the orchestrator.

Prunes non-compliant routes, scores remaining candidates, and selects
the best route. Lower scores are better.
"""

from typing import Optional

from accessroute.schemas import ElevationVerdict, RouteCandidate


def prune_noncompliant(verdicts: list[ElevationVerdict]) -> list[int]:
    """Return indices of routes that pass elevation compliance.

    A route passes if its ElevationVerdict.is_route_compliant is True.

    Args:
        verdicts: Elevation verdicts for all candidate routes.

    Returns:
        List of route_index values for compliant routes.
    """
    return [v.route_index for v in verdicts if v.is_route_compliant]


def score_route(
    candidate: RouteCandidate,
    verdict: ElevationVerdict,
) -> float:
    """Score a single route candidate (lower is better).

    Scoring priorities (in order):
        1. Safety: penalize higher max_grade_percentage.
        2. Distance: prefer shorter routes.
        3. Turns/complexity: penalize higher num_steps.

    The exact weighting formula is left to the implementing agent,
    but the priority order above MUST be respected.

    Weighting formula (lexicographic-style weighted sum so safety dominates):
        score = max_grade_percentage * 1000
               + distance_meters * 1.0
               + num_steps * 10

    With the * 1000 weight on grade, a route with even 1% higher max grade
    needs to be ~1 km shorter to compensate -- effectively making safety
    the primary sorting key, followed by distance, then complexity.

    Args:
        candidate: The route candidate with distance, duration, steps.
        verdict: The elevation verdict with grade information.

    Returns:
        A float score where lower is better.
    """
    return (
        verdict.max_grade_percentage * 1000.0
        + candidate.distance_meters * 1.0
        + candidate.num_steps * 10.0
    )


def choose_best(
    candidates: list[RouteCandidate],
    verdicts: list[ElevationVerdict],
) -> Optional[int]:
    """Select the best route from compliant candidates.

    1. Prune non-compliant routes via prune_noncompliant().
    2. Score remaining candidates via score_route().
    3. Return the route_index of the lowest-scoring candidate.
    4. Return None if no compliant routes exist.

    Args:
        candidates: All route candidates.
        verdicts: Elevation verdicts (matched by route_index).

    Returns:
        The route_index of the best route, or None if none are compliant.
    """
    compliant_indices = set(prune_noncompliant(verdicts))
    if not compliant_indices:
        return None

    # Build lookup of verdicts by route_index
    verdict_map = {v.route_index: v for v in verdicts}

    best_index: Optional[int] = None
    best_score: float = float("inf")

    for candidate in candidates:
        if candidate.route_index not in compliant_indices:
            continue
        verdict = verdict_map.get(candidate.route_index)
        if verdict is None:
            continue
        s = score_route(candidate, verdict)
        if s < best_score:
            best_score = s
            best_index = candidate.route_index

    return best_index
