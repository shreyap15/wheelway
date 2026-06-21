#!/usr/bin/env python
"""In-process smoke test for the accessroute multi-agent pipeline.

Runs all four agents (orchestrator, route, elevation, places) plus a
client agent in a single Bureau. The client sends a hardcoded Berkeley
campus RouteEvaluationRequest on startup and logs the FinalRoute reply,
then shuts down the Bureau so the process exits cleanly.

This script is the GUARANTEED local test -- it does not require Almanac
address resolution or a running bureau in a separate process.

With no API keys set, the demo returns success=False by design
(graceful degradation).

Usage:
    python scripts/run_demo.py
"""

import asyncio
import os
import signal

from _bootstrap import ensure_project_root

ensure_project_root()

from uagents import Agent, Context

from accessroute.bureau_main import build_bureau
from accessroute.addresses import ORCHESTRATOR_ADDRESS
from accessroute.config import demo_wheelchair_profile
from accessroute.schemas import FinalRoute, LatLng, RouteEvaluationRequest

# Client agent (ephemeral, no fixed port needed)
client = Agent(
    name="demo_client",
    seed="accessroute demo client seed v1",
)


@client.on_event("startup")
async def send_request(ctx: Context):
    """Send a hardcoded route evaluation request on startup."""
    request = RouteEvaluationRequest(
        session_id="demo-session-001",
        origin=LatLng(lat=37.8715, lng=-122.2595),
        destination=LatLng(lat=37.8756, lng=-122.2588),
        profile=demo_wheelchair_profile(device_type="power"),
        travel_mode="WALK",
    )

    ctx.logger.info(
        f"Sending RouteEvaluationRequest to orchestrator at {ORCHESTRATOR_ADDRESS}"
    )

    try:
        reply, status = await ctx.send_and_receive(
            ORCHESTRATOR_ADDRESS,
            request,
            response_type=FinalRoute,
            timeout=45,
        )
    except Exception as exc:
        ctx.logger.error(f"send_and_receive failed: {exc}")
        reply = None
        status = None

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

    # Shut down cleanly: stop the event loop so the Bureau exits
    ctx.logger.info("Demo complete. Shutting down.")
    await asyncio.sleep(0.5)
    os.kill(os.getpid(), signal.SIGINT)


def main():
    bureau = build_bureau()
    bureau.add(client)
    bureau.run()


if __name__ == "__main__":
    main()
