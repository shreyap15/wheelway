#!/usr/bin/env python
"""Agentverse / ASI:One mailbox entry point for WheelWay accessible routing.

Runs a single mailbox-enabled uAgent that answers RouteEvaluationRequest
messages by calling the SAME shared pipeline the Flask /real-route endpoint and
the local demo use -- ``accessroute.pipeline.compute_accessible_routes``. There
is no second copy of the routing/elevation/scoring logic here.

    Client (ASI:One / Agentverse) -> mailbox agent
      -> compute_accessible_routes  (Mapbox geometry + Google enrichment)
      -> FinalRoute reply

Usage:
    python scripts/run_mailbox.py

Requires MAPBOX_ACCESS_TOKEN (and, optionally, GOOGLE_MAPS_API_KEY for
elevation/places enrichment). With no Mapbox token the agent replies with a
graceful, non-fabricated failure.
"""

from _bootstrap import ensure_project_root

ensure_project_root()

from uagents import Agent, Context

from accessroute.config import ORCHESTRATOR
from accessroute.pipeline import (
    ConfigurationError,
    NoRouteError,
    ServiceDegraded,
    compute_accessible_routes,
)
from accessroute.schemas import FinalRoute, RouteEvaluationRequest

# Mailbox=True registers the agent with Agentverse so ASI:One can reach it
# without a public endpoint. The seed keeps the address stable across restarts.
mailbox_agent = Agent(
    name="wheelway_mailbox",
    seed="wheelway mailbox agent seed v1",
    port=ORCHESTRATOR.port,
    mailbox=True,
)


@mailbox_agent.on_event("startup")
async def on_startup(ctx: Context):
    ctx.logger.info(f"WheelWay mailbox agent ready at address: {mailbox_agent.address}")


def _build_final_route(msg: RouteEvaluationRequest, result) -> FinalRoute:
    """Collapse the shared pipeline result into a single FinalRoute reply."""
    # Prefer a route that does not exceed the slope limit; otherwise the first.
    chosen = next(
        (r for r in result.routes if r.exceeds_max_slope is False),
        result.routes[0] if result.routes else None,
    )
    if chosen is None:
        return FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose="No walking route geometry was returned.",
            warnings=result.warnings,
            service_degraded=result.service_degraded,
        )

    chosen_index = result.routes.index(chosen)
    return FinalRoute(
        session_id=msg.session_id,
        success=True,
        chosen_route_index=chosen_index,
        directions_prose=chosen.explanation,
        warnings=chosen.accessibility_warnings + result.warnings,
        total_distance_meters=chosen.distance_m,
        travel_mode=msg.travel_mode,
        service_degraded=result.service_degraded,
    )


@mailbox_agent.on_message(model=RouteEvaluationRequest)
async def handle_request(ctx: Context, sender: str, msg: RouteEvaluationRequest):
    """Answer a route request using the shared accessible-routing pipeline."""
    ctx.logger.info(f"Mailbox received RouteEvaluationRequest session={msg.session_id}")
    try:
        result = await compute_accessible_routes(msg.origin, msg.destination, msg.profile)
    except ConfigurationError as exc:
        await ctx.send(sender, FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose=f"Routing unavailable: {exc}",
            warnings=[str(exc)],
            service_degraded=True,
        ))
        return
    except NoRouteError as exc:
        await ctx.send(sender, FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose="No wheelchair-accessible walking route was found.",
            warnings=[str(exc)],
            service_degraded=False,
        ))
        return
    except ServiceDegraded as exc:
        await ctx.send(sender, FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose=f"Routing service degraded: {exc}",
            warnings=[str(exc)],
            service_degraded=True,
        ))
        return

    await ctx.send(sender, _build_final_route(msg, result))


def main():
    mailbox_agent.run()


if __name__ == "__main__":
    main()
