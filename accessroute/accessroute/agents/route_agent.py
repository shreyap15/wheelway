"""Route agent: fetches walking route candidates from Mapbox Directions.

Listens for RouteEvaluationRequest messages from the orchestrator, calls the
shared Mapbox walking engine (accessroute.main.build_route_candidates), and
replies with RouteCandidates. Mapbox is the only route-geometry provider; the
legacy Google Routes tool has been removed.

NOTE: the orchestrator now calls the Mapbox engine in-process and no longer
messages this agent in the canonical flow. The agent is retained for
Agentverse/Bureau deployments that still route via uAgents messaging.
"""

import logging

from uagents import Agent, Context

from accessroute.config import ROUTE_AGENT
from accessroute.main import build_route_candidates, degraded_route_candidates
from accessroute.schemas import RouteEvaluationRequest, RouteCandidates
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

    1. Call build_route_candidates() (Mapbox walking directions).
    2. Reply to the sender (orchestrator) with RouteCandidates.
    3. On ServiceDegraded, reply with service_degraded=True.
    """
    try:
        result: RouteCandidates = build_route_candidates(msg)
    except ServiceDegraded as exc:
        ctx.logger.warning(f"Mapbox routing degraded for session {msg.session_id}: {exc}")
        result = degraded_route_candidates(msg)

    await ctx.send(sender, result)
