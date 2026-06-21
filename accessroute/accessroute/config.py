"""Configuration for the accessroute multi-agent system.

Loads environment variables via python-dotenv and exposes API keys,
ASI:One settings, and agent seed/port configuration.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the package root (one level above accessroute/)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
MAPBOX_ACCESS_TOKEN: str = os.getenv("MAPBOX_ACCESS_TOKEN", "")
ASI_ONE_API_KEY: str = os.getenv("ASI_ONE_API_KEY", "")

# Demo/testing grade limits for steep campuses (e.g. Berkeley hills ~21% peaks).
DEMO_MAX_INCLINE_GRADE: float = float(os.getenv("DEMO_MAX_INCLINE_GRADE", "25.0"))
DEMO_MAX_DECLINE_GRADE: float = float(os.getenv("DEMO_MAX_DECLINE_GRADE", "25.0"))

# ---------------------------------------------------------------------------
# ASI:One LLM endpoint (OpenAI-compatible)
# ---------------------------------------------------------------------------
ASI_ONE_BASE_URL: str = "https://api.asi1.ai/v1/chat/completions"
ASI_ONE_MODEL: str = "asi1-mini"

# ---------------------------------------------------------------------------
# Agent seeds and ports
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentConfig:
    """Immutable configuration for a single uAgent."""
    name: str
    seed: str
    port: int


ORCHESTRATOR = AgentConfig(
    name="orchestrator",
    seed="accessroute orchestrator seed v1",
    port=8000,
)

ROUTE_AGENT = AgentConfig(
    name="route_agent",
    seed="accessroute route agent seed v1",
    port=8001,
)

ELEVATION_AGENT = AgentConfig(
    name="elevation_agent",
    seed="accessroute elevation agent seed v1",
    port=8002,
)

PLACES_AGENT = AgentConfig(
    name="places_agent",
    seed="accessroute places agent seed v1",
    port=8003,
)

# Convenience dict for iteration
AGENTS: dict[str, AgentConfig] = {
    "orchestrator": ORCHESTRATOR,
    "route_agent": ROUTE_AGENT,
    "elevation_agent": ELEVATION_AGENT,
    "places_agent": PLACES_AGENT,
}


def demo_wheelchair_profile(device_type: str = "power") -> "WheelchairProfile":
    """Relaxed wheelchair profile for local demo runs on steep terrain."""
    from accessroute.schemas import WheelchairProfile

    return WheelchairProfile(
        device_type=device_type,
        max_incline_grade=DEMO_MAX_INCLINE_GRADE,
        max_decline_grade=DEMO_MAX_DECLINE_GRADE,
    )
