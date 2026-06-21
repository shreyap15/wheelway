"""Backward-compatible re-exports of the Mapbox routing engine in accessroute.main."""

from accessroute.main import (
    ServiceDegraded,
    build_route_candidates,
    degraded_route_candidates,
    fetch_route_candidates_async,
)

__all__ = [
    "ServiceDegraded",
    "build_route_candidates",
    "degraded_route_candidates",
    "fetch_route_candidates_async",
]
