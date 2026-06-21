"""Shared elevation checking logic for orchestrator and elevation agent."""

import asyncio

from accessroute.common.http import ServiceDegraded
from accessroute.schemas import ElevationCheckRequest, ElevationVerdict, WheelchairProfile
from accessroute.tools.elevation_tool import (
    grade_segments,
    sample_elevations,
    smooth_elevation_samples,
)


def _parse_profile(profile) -> WheelchairProfile:
    if isinstance(profile, WheelchairProfile):
        return profile
    return WheelchairProfile.parse_obj(profile)


def check_route_elevation(req: ElevationCheckRequest, api_key: str) -> ElevationVerdict:
    """Sample elevations, grade the route, and return a primitive-friendly verdict."""
    samples = sample_elevations(
        req.encoded_polyline,
        req.distance_meters,
        api_key=api_key,
    )
    samples = smooth_elevation_samples(samples)
    reports, compliant, max_grade = grade_segments(samples, _parse_profile(req.profile))
    return ElevationVerdict(
        session_id=req.session_id,
        route_index=req.route_index,
        segments=[report.dict() for report in reports],
        is_route_compliant=compliant,
        max_grade_percentage=max_grade,
        service_degraded=False,
    )


async def check_route_elevation_async(
    req: ElevationCheckRequest,
    api_key: str,
) -> ElevationVerdict:
    """Async wrapper that keeps blocking HTTP off the agent event loop."""
    return await asyncio.to_thread(check_route_elevation, req, api_key)


def degraded_elevation_verdict(req: ElevationCheckRequest) -> ElevationVerdict:
    """Return a safe degraded verdict when elevation data is unavailable."""
    return ElevationVerdict(
        session_id=req.session_id,
        route_index=req.route_index,
        segments=[],
        is_route_compliant=False,
        max_grade_percentage=0.0,
        service_degraded=True,
    )


__all__ = [
    "ServiceDegraded",
    "check_route_elevation",
    "check_route_elevation_async",
    "degraded_elevation_verdict",
]
