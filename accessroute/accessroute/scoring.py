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
    raise NotImplementedError("prune_noncompliant: to be implemented by orchestrator builder")


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

    Args:
        candidate: The route candidate with distance, duration, steps.
        verdict: The elevation verdict with grade information.

    Returns:
        A float score where lower is better.
    """
    raise NotImplementedError("score_route: to be implemented by orchestrator builder")


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
    raise NotImplementedError("choose_best: to be implemented by orchestrator builder")
