"""Native Mapbox directions engine for the accessroute in-process pipeline.

Contacts the Mapbox Directions API, converts GeoJSON walking geometry into
Google-standard encoded polylines, and packages results as RouteCandidates for
the orchestrator and elevation pipeline.
"""

import asyncio

from accessroute.common.http import ServiceDegraded
from accessroute.config import MAPBOX_ACCESS_TOKEN
from accessroute.schemas import RouteCandidates, RouteEvaluationRequest
from accessroute.tools.mapbox_routes_tool import compute_mapbox_routes


def build_route_candidates(
    msg: RouteEvaluationRequest,
    access_token: str | None = None,
) -> RouteCandidates:
    """Call Mapbox Directions and return a RouteCandidates model."""
    token = access_token or MAPBOX_ACCESS_TOKEN
    if msg.travel_mode.upper() != "WALK":
        raise ServiceDegraded(
            "Only WALK travel_mode is supported by the Mapbox walking pipeline"
        )

    candidates = compute_mapbox_routes(
        msg.origin,
        msg.destination,
        access_token=token,
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
    access_token: str | None = None,
) -> RouteCandidates:
    """Async wrapper that keeps blocking Mapbox HTTP off the agent event loop."""
    token = access_token or MAPBOX_ACCESS_TOKEN
    return await asyncio.to_thread(build_route_candidates, msg, token)


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
