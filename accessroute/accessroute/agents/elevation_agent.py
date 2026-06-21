"""Elevation agent: checks route elevation profiles against wheelchair constraints.

Listens for ElevationCheckRequest messages from the orchestrator,
calls the elevation_tool, and replies with ElevationVerdict.
"""

import asyncio
import logging

from uagents import Agent, Context

from accessroute.config import ELEVATION_AGENT, GOOGLE_MAPS_API_KEY
from accessroute.schemas import (
    ElevationCheckRequest,
    ElevationVerdict,
    WheelchairProfile,
)
from accessroute.tools.elevation_tool import sample_elevations, grade_segments
from accessroute.common.http import ServiceDegraded

logger = logging.getLogger(__name__)

elevation_agent = Agent(
    name=ELEVATION_AGENT.name,
    seed=ELEVATION_AGENT.seed,
    port=ELEVATION_AGENT.port,
    endpoint=[f"http://127.0.0.1:{ELEVATION_AGENT.port}/submit"],
)


@elevation_agent.on_event("startup")
async def on_startup(ctx: Context):
    """Log the agent's address on startup."""
    addr = getattr(ctx, "address", None) or elevation_agent.address
    ctx.logger.info(f"Elevation agent started at address: {addr}")


def _process_elevation_request(msg: ElevationCheckRequest) -> tuple[ElevationVerdict, int]:
    """Run blocking elevation API work off the agent event loop."""
    samples = sample_elevations(
        msg.encoded_polyline,
        msg.distance_meters,
        api_key=GOOGLE_MAPS_API_KEY,
    )
    profile = (
        msg.profile
        if isinstance(msg.profile, WheelchairProfile)
        else WheelchairProfile.parse_obj(msg.profile)
    )
    reports, compliant, maxg = grade_segments(samples, profile)
    result = ElevationVerdict(
        session_id=msg.session_id,
        route_index=msg.route_index,
        segments=[report.dict() for report in reports],
        is_route_compliant=compliant,
        max_grade_percentage=maxg,
        service_degraded=False,
    )
    return result, len(samples)


@elevation_agent.on_message(model=ElevationCheckRequest)
async def handle_elevation_request(ctx: Context, sender: str, msg: ElevationCheckRequest):
    """Handle an elevation check request from the orchestrator.

    1. Call sample_elevations() with the encoded polyline.
    2. Call grade_segments() with the samples and the user's profile.
    3. Wrap results in ElevationVerdict.
    4. Reply to the sender (orchestrator).
    5. On ServiceDegraded, reply with service_degraded=True.
    """
    ctx.logger.info("[DEBUG] Processing elevation for route index %s", msg.route_index)
    try:
        result, sample_count = await asyncio.to_thread(_process_elevation_request, msg)
        ctx.logger.info(
            "[DEBUG] sample_elevations returned %d samples",
            sample_count,
        )
    except ServiceDegraded as exc:
        ctx.logger.warning(f"Elevation API degraded for session {msg.session_id}: {exc}")
        result = ElevationVerdict(
            session_id=msg.session_id,
            route_index=msg.route_index,
            segments=[],
            is_route_compliant=False,
            max_grade_percentage=0.0,
            service_degraded=True,
        )
    except Exception as exc:
        ctx.logger.error(
            "Elevation processing failed for route %s: %s",
            msg.route_index,
            exc,
        )
        result = ElevationVerdict(
            session_id=msg.session_id,
            route_index=msg.route_index,
            segments=[],
            is_route_compliant=False,
            max_grade_percentage=0.0,
            service_degraded=True,
        )

    await ctx.send(sender, result)
