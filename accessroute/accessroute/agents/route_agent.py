"""Route agent: fetches walking/transit route candidates from Google Routes API.

Listens for RouteEvaluationRequest messages from the orchestrator,
calls the routes_tool, and replies with RouteCandidates.
"""

import logging

from uagents import Agent, Context

from accessroute.config import ROUTE_AGENT, GOOGLE_MAPS_API_KEY
from accessroute.schemas import RouteEvaluationRequest, RouteCandidates
from accessroute.tools.routes_tool import compute_routes
from accessroute.common.http import ServiceDegraded

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
    addr = getattr(ctx, "address", None) or route_agent.address
    ctx.logger.info(f"Route agent started at address: {addr}")


@route_agent.on_message(model=RouteEvaluationRequest)
async def handle_route_request(ctx: Context, sender: str, msg: RouteEvaluationRequest):
    """Handle a route evaluation request from the orchestrator.

    1. Call compute_routes() with the origin, destination, and travel_mode.
    2. Wrap results in RouteCandidates.
    3. Reply to the sender (orchestrator).
    4. On ServiceDegraded, reply with service_degraded=True.
    """
    try:
        candidates = compute_routes(
            msg.origin,
            msg.destination,
            api_key=GOOGLE_MAPS_API_KEY,
            travel_mode=msg.travel_mode,
        )
        result = RouteCandidates(
            session_id=msg.session_id,
            candidates=candidates,
            travel_mode=msg.travel_mode,
            service_degraded=False,
        )
    except ServiceDegraded as exc:
        ctx.logger.warning(f"Route API degraded for session {msg.session_id}: {exc}")
        result = RouteCandidates(
            session_id=msg.session_id,
            candidates=[],
            travel_mode=msg.travel_mode,
            service_degraded=True,
        )

    await ctx.send(sender, result)
