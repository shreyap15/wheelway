"""Bureau launcher for the accessroute multi-agent system.

Creates a uAgents Bureau containing all four agents (orchestrator,
route, elevation, places) and runs them together.

Usage:
    python -m accessroute.bureau_main
"""

from uagents import Bureau

from accessroute.agents.orchestrator import orchestrator
from accessroute.agents.route_agent import route_agent
from accessroute.agents.elevation_agent import elevation_agent
from accessroute.agents.places_agent import places_agent


def build_bureau() -> Bureau:
    """Build and return a Bureau with all accessroute agents.

    Returns:
        A configured Bureau instance ready to run.
    """
    bureau = Bureau()
    bureau.add(orchestrator)
    bureau.add(route_agent)
    bureau.add(elevation_agent)
    bureau.add(places_agent)
    return bureau


if __name__ == "__main__":
    bureau = build_bureau()
    bureau.run()
