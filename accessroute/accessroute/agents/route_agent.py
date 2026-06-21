"""Route agent: fetches walking/transit route candidates from Google Routes API.

Listens for RouteEvaluationRequest messages from the orchestrator,
calls the routes_tool, and replies with RouteCandidates.
"""

import logging

from uagents import Agent, Context

from accessroute.config import ROUTE_AGENT, GOOGLE_MAPS_API_KEY
from accessroute.schemas import RouteEvaluationRequest, RouteCandidates

logger = logging.getLogger(__name__)

route_agent = Agent(
    name=ROUTE_AGENT.name,
    seed=ROUTE_AGENT.seed,
    port=ROUTE_AGENT.port,
    endpoint=[f"http://127.0.0.1:{ROUTE_AGENT.port}/submit"],
)


@route_agent.on_event("startup")
async def on_startup(ctx: Context):
    """Log the agent's address on startup."""
    ctx.logger.info(f"Route agent started at address: {ctx.address}")


@route_agent.on_message(model=RouteEvaluationRequest)
async def handle_route_request(ctx: Context, sender: str, msg: RouteEvaluationRequest):
    """Handle a route evaluation request from the orchestrator.

    1. Call compute_routes() with the origin, destination, and travel_mode.
    2. Wrap results in RouteCandidates.
    3. Reply to the sender (orchestrator).
    4. On ServiceDegraded, reply with service_degraded=True.
    """
    # Stub: to be implemented by route-agent builder
    pass
