"""Elevation agent: checks route elevation profiles against wheelchair constraints.

Listens for ElevationCheckRequest messages from the orchestrator,
calls the elevation_tool, and replies with ElevationVerdict.
"""

import logging

from uagents import Agent, Context

from accessroute.config import ELEVATION_AGENT, GOOGLE_MAPS_API_KEY
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
    ctx.logger.info(f"Elevation agent started at address: {ctx.address}")


@elevation_agent.on_message(model=ElevationCheckRequest)
async def handle_elevation_request(ctx: Context, sender: str, msg: ElevationCheckRequest):
    """Handle an elevation check request from the orchestrator.

    1. Call sample_elevations() with the encoded polyline.
    2. Call grade_segments() with the samples and the user's profile.
    3. Wrap results in ElevationVerdict.
    4. Reply to the sender (orchestrator).
    5. On ServiceDegraded, reply with service_degraded=True.
    """
    # Stub: to be implemented by elevation-agent builder
    pass
