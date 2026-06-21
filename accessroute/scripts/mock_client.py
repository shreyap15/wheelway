"""Mock client for testing the accessroute multi-agent system.

Sends a hardcoded RouteEvaluationRequest (Berkeley campus route)
to the orchestrator and logs the FinalRoute reply.

Usage:
    python scripts/mock_client.py

Requires the bureau to be running (python -m accessroute.bureau_main).
"""

from _bootstrap import ensure_project_root

ensure_project_root()

from uagents import Agent, Context

from accessroute.addresses import ORCHESTRATOR_ADDRESS
from accessroute.schemas import (
    FinalRoute,
    LatLng,
    RouteEvaluationRequest,
    WheelchairProfile,
)

# Client agent (ephemeral, no fixed port needed)
client = Agent(
    name="mock_client",
    seed="accessroute mock client seed v1",
)


@client.on_event("startup")
async def send_request(ctx: Context):
    """Send a hardcoded route evaluation request on startup.

    Route: UC Berkeley campus
        Origin:      37.8715, -122.2595  (Sather Gate area)
        Destination: 37.8756, -122.2588  (north campus)
    """
    request = RouteEvaluationRequest(
        session_id="mock-session-001",
        origin=LatLng(lat=37.8715, lng=-122.2595),
        destination=LatLng(lat=37.8756, lng=-122.2588),
        profile=WheelchairProfile(device_type="power"),
        travel_mode="WALK",
    )

    ctx.logger.info(f"Sending RouteEvaluationRequest to orchestrator at {ORCHESTRATOR_ADDRESS}")

    reply, status = await ctx.send_and_receive(
        ORCHESTRATOR_ADDRESS,
        request,
        response_type=FinalRoute,
    )

    if isinstance(reply, FinalRoute):
        ctx.logger.info("=== FINAL ROUTE RESPONSE ===")
        ctx.logger.info(f"Success: {reply.success}")
        ctx.logger.info(f"Route index: {reply.chosen_route_index}")
        ctx.logger.info(f"Distance: {reply.total_distance_meters}m")
        ctx.logger.info(f"Travel mode: {reply.travel_mode}")
        ctx.logger.info(f"Service degraded: {reply.service_degraded}")
        ctx.logger.info(f"Warnings: {reply.warnings}")
        ctx.logger.info(f"Directions:\n{reply.directions_prose}")
    else:
        ctx.logger.error(f"No FinalRoute received, status={status}")


@client.on_message(model=FinalRoute)
async def handle_response(ctx: Context, sender: str, msg: FinalRoute):
    """Handle the FinalRoute response from the orchestrator."""
    ctx.logger.info(f"=== FINAL ROUTE RESPONSE ===")
    ctx.logger.info(f"Success: {msg.success}")
    ctx.logger.info(f"Route index: {msg.chosen_route_index}")
    ctx.logger.info(f"Distance: {msg.total_distance_meters}m")
    ctx.logger.info(f"Travel mode: {msg.travel_mode}")
    ctx.logger.info(f"Warnings: {msg.warnings}")
    ctx.logger.info(f"Directions:\n{msg.directions_prose}")


if __name__ == "__main__":
    client.run()
