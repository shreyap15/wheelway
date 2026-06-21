"""Elevation agent: checks route elevation profiles against wheelchair constraints.

Listens for ElevationCheckRequest messages from the orchestrator,
calls the elevation_tool, and replies with ElevationVerdict.
"""

import logging

from uagents import Agent, Context

from accessroute.config import ELEVATION_AGENT, GOOGLE_MAPS_API_KEY
from accessroute.elevation_service import (
    ServiceDegraded,
    check_route_elevation_async,
    degraded_elevation_verdict,
)
from accessroute.schemas import ElevationCheckRequest, ElevationVerdict

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


@elevation_agent.on_message(model=ElevationCheckRequest, replies=ElevationVerdict)
async def handle_elevation_request(ctx: Context, sender: str, msg: ElevationCheckRequest):
    """Handle an elevation check request from the orchestrator."""
    ctx.logger.info("[DEBUG] Processing elevation for route index %s", msg.route_index)
    try:
        result = await check_route_elevation_async(msg, GOOGLE_MAPS_API_KEY)
        ctx.logger.info(
            "[DEBUG] sample_elevations returned %d segments graded, compliant=%s, max_grade=%.2f",
            len(result.segments),
            result.is_route_compliant,
            result.max_grade_percentage,
        )
    except ServiceDegraded as exc:
        ctx.logger.warning(f"Elevation API degraded for session {msg.session_id}: {exc}")
        result = degraded_elevation_verdict(msg)
    except Exception as exc:
        ctx.logger.error(
            "Elevation processing failed for route %s: %s",
            msg.route_index,
            exc,
        )
        result = degraded_elevation_verdict(msg)

    await ctx.send(sender, result)
