"""Orchestrator agent: coordinates the multi-agent wheelchair routing pipeline.

Receives a RouteEvaluationRequest from the client, fans out to the
route/elevation/places specialist agents, scores results, synthesizes
directions via LLM, and returns a FinalRoute.

Message flow:
    Client -> Orchestrator: RouteEvaluationRequest
    Orchestrator -> RouteAgent: RouteEvaluationRequest
    RouteAgent -> Orchestrator: RouteCandidates
    Orchestrator -> ElevationAgent: ElevationCheckRequest (per candidate)
    ElevationAgent -> Orchestrator: ElevationVerdict (per candidate)
    Orchestrator -> PlacesAgent: AccessibilityCheckRequest
    PlacesAgent -> Orchestrator: AccessibilityVerdict
    Orchestrator -> Client: FinalRoute
"""

import logging

from uagents import Agent, Context

from accessroute.config import ORCHESTRATOR
from accessroute.schemas import RouteEvaluationRequest, FinalRoute

logger = logging.getLogger(__name__)

orchestrator = Agent(
    name=ORCHESTRATOR.name,
    seed=ORCHESTRATOR.seed,
    port=ORCHESTRATOR.port,
    endpoint=[f"http://127.0.0.1:{ORCHESTRATOR.port}/submit"],
)


@orchestrator.on_event("startup")
async def on_startup(ctx: Context):
    """Log the orchestrator's address on startup."""
    ctx.logger.info(f"Orchestrator started at address: {ctx.address}")


@orchestrator.on_message(model=RouteEvaluationRequest)
async def handle_evaluation_request(ctx: Context, sender: str, msg: RouteEvaluationRequest):
    """Handle a route evaluation request from the client.

    Pipeline:
        1. Forward request to route agent, await RouteCandidates.
        2. For each candidate, send ElevationCheckRequest to elevation agent,
           await ElevationVerdict (using ctx.send_and_receive).
        3. Send AccessibilityCheckRequest to places agent, await verdict.
        4. Score and select the best compliant route via scoring module.
        5. Synthesize human-readable directions via LLM.
        6. Reply to the client with FinalRoute.

    Sync calls use:
        reply, status = await ctx.send_and_receive(addr, msg, response_type=SomeModel)

    On any ServiceDegraded, accumulate warnings and set service_degraded=True.
    If no compliant routes exist, return success=False with explanation.
    """
    # Stub: to be implemented by orchestrator builder
    pass
