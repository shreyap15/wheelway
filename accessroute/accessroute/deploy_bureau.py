"""Production Bureau launcher for cloud deployment and Agentverse registration.

Usage:
    python -m accessroute.deploy_bureau

Environment variables:
    PORT / RENDER_EXTERNAL_URL / AGENT_PUBLIC_URL  - cloud host binding + public URL
    USE_MAILBOX=true                               - Agentverse mailbox mode (no public URL)
    MAPBOX_ACCESS_TOKEN, GOOGLE_MAPS_API_KEY       - routing + elevation APIs
    ASI_ONE_API_KEY                                - optional LLM prose synthesis
    AGENTVERSE_NAME                                - display name (max 30 chars)
"""

from uagents import Bureau

from accessroute.agents.elevation_agent import elevation_agent
from accessroute.agents.orchestrator import orchestrator
from accessroute.agents.places_agent import places_agent
from accessroute.agents.route_agent import route_agent
from accessroute.addresses import ORCHESTRATOR_ADDRESS
from accessroute.deploy_config import get_deploy_settings


def build_production_bureau() -> Bureau:
    """Build a Bureau configured for public cloud deployment."""
    settings = get_deploy_settings()

    endpoint = None if settings.use_mailbox else settings.submit_endpoint
    bureau = Bureau(port=settings.port, endpoint=endpoint)
    bureau.add(orchestrator)
    bureau.add(route_agent)
    bureau.add(elevation_agent)
    bureau.add(places_agent)
    return bureau


def _print_agentverse_registration(settings) -> None:
    print("\n=== Agentverse registration details ===")
    print(f"Agent Name:          {settings.agentverse_name}")
    print(f"Orchestrator address:{ORCHESTRATOR_ADDRESS}")
    if settings.submit_endpoint:
        print(f"Agent Endpoint URL:  {settings.submit_endpoint}")
        print("Register this HTTPS /submit URL in Agentverse → Add Agent.")
    elif settings.use_mailbox:
        print("Mailbox mode:        USE_MAILBOX=true")
        print("Open the Local Agent Inspector URL from the logs and connect via Mailbox.")
    else:
        print("No public URL detected yet.")
        print("Set RENDER_EXTERNAL_URL or AGENT_PUBLIC_URL after your cloud deploy finishes.")
    print("=======================================\n")


if __name__ == "__main__":
    deploy_settings = get_deploy_settings()
    _print_agentverse_registration(deploy_settings)
    build_production_bureau().run()
