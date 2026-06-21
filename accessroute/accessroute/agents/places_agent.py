"""Places agent: checks destination wheelchair accessibility via Google Places API.

Listens for AccessibilityCheckRequest messages from the orchestrator,
calls the places_tool, and replies with AccessibilityVerdict.
"""

import logging

from uagents import Agent, Context

from accessroute.config import PLACES_AGENT, GOOGLE_MAPS_API_KEY
from accessroute.schemas import AccessibilityCheckRequest, AccessibilityVerdict
from accessroute.tools.places_tool import check_destination_accessibility

logger = logging.getLogger(__name__)

places_agent = Agent(
    name=PLACES_AGENT.name,
    seed=PLACES_AGENT.seed,
    port=PLACES_AGENT.port,
    endpoint=[f"http://127.0.0.1:{PLACES_AGENT.port}/submit"],
)


@places_agent.on_event("startup")
async def on_startup(ctx: Context):
    """Log the agent's address on startup."""
    ctx.logger.info(f"Places agent started at address: {ctx.address}")


@places_agent.on_message(model=AccessibilityCheckRequest)
async def handle_accessibility_request(ctx: Context, sender: str, msg: AccessibilityCheckRequest):
    """Handle an accessibility check request from the orchestrator.

    1. Call check_destination_accessibility() with the destination coords.
    2. Reply to the sender (orchestrator) with AccessibilityVerdict.
    3. On ServiceDegraded, reply with service_degraded=True and a warning.
    """
    verdict = check_destination_accessibility(
        msg.destination,
        api_key=GOOGLE_MAPS_API_KEY,
        radius_meters=msg.radius_meters,
    )

    # Tool returns session_id="" ; fill with the real session_id from request
    verdict_with_session = AccessibilityVerdict(
        session_id=msg.session_id,
        place_id=verdict.place_id,
        display_name=verdict.display_name,
        wheelchair_entrance=verdict.wheelchair_entrance,
        warning=verdict.warning,
        service_degraded=verdict.service_degraded,
    )

    await ctx.send(sender, verdict_with_session)
