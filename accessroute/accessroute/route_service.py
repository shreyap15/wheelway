"""Shared Mapbox route candidate fetching for the in-process Bureau pipeline."""

import asyncio

from accessroute.common.http import ServiceDegraded
from accessroute.schemas import RouteCandidates, RouteEvaluationRequest
from accessroute.tools.mapbox_routes_tool import compute_mapbox_routes


def build_route_candidates(
    msg: RouteEvaluationRequest,
    access_token: str,
) -> RouteCandidates:
    """Build RouteCandidates from Mapbox walking directions."""
    if msg.travel_mode.upper() != "WALK":
        raise ServiceDegraded(
            "Only WALK travel_mode is supported by the Mapbox walking pipeline"
        )

    candidates = compute_mapbox_routes(
        msg.origin,
        msg.destination,
        access_token=access_token,
        travel_mode=msg.travel_mode,
        alternatives=True,
    )
    return RouteCandidates(
        session_id=msg.session_id,
        candidates=candidates,
        travel_mode=msg.travel_mode,
        service_degraded=False,
    )


async def fetch_route_candidates_async(
    msg: RouteEvaluationRequest,
    access_token: str,
) -> RouteCandidates:
    """Async wrapper that keeps blocking Mapbox HTTP off the agent event loop."""
    return await asyncio.to_thread(build_route_candidates, msg, access_token)


def degraded_route_candidates(msg: RouteEvaluationRequest) -> RouteCandidates:
    """Return an empty degraded candidate set when routing is unavailable."""
    return RouteCandidates(
        session_id=msg.session_id,
        candidates=[],
        travel_mode=msg.travel_mode,
        service_degraded=True,
    )


__all__ = [
    "ServiceDegraded",
    "build_route_candidates",
    "degraded_route_candidates",
    "fetch_route_candidates_async",
]
