"""Frozen message contract for the accessroute multi-agent system.

ALL uagents.Model classes live here so that sender and receiver share
identical schema digests. DO NOT define Model subclasses elsewhere.

These schemas are the FROZEN CONTRACT -- do not rename fields or classes.
Downstream agents depend on exact names and types.
"""

from typing import Any, Dict, List, Optional

from uagents import Model
from pydantic.v1 import Field


class LatLng(Model):
    """A geographic coordinate pair."""
    lat: float
    lng: float


class WheelchairProfile(Model):
    """User mobility profile describing wheelchair capabilities and constraints."""
    device_type: str = Field(
        ...,
        description="Type of wheelchair, e.g. 'manual', 'power', 'scooter'.",
    )
    max_width_cm: int = Field(
        default=75,
        description="Maximum device width in centimeters for narrow-path filtering.",
    )
    max_incline_grade: float = Field(
        default=8.33,
        description="Maximum uphill grade percentage the user can handle (ADA max is 8.33%).",
    )
    max_decline_grade: float = Field(
        default=10.0,
        description="Maximum downhill grade percentage considered safe.",
    )
    requires_curb_ramps: bool = Field(
        default=True,
        description="Whether the user requires curb ramps at intersections.",
    )
    battery_range_km: float = Field(
        default=15.0,
        description="Remaining battery range in km (relevant for power chairs).",
    )


class RouteEvaluationRequest(Model):
    """Top-level request sent by the client to the orchestrator.

    Contains origin/destination, the user's wheelchair profile,
    and the preferred travel mode.
    """
    session_id: str
    origin: LatLng
    destination: LatLng
    profile: WheelchairProfile
    travel_mode: str = Field(
        default="WALK",
        description="Google Routes API travel mode: 'WALK' or 'TRANSIT'.",
    )


class SegmentElevationReport(Model):
    """Elevation analysis for a single segment of a route polyline."""
    segment_index: int
    start_location: LatLng
    end_location: LatLng
    distance_meters: float
    elevation_change_meters: float
    grade_percentage: float
    is_compliant: bool


class RouteCandidate(Model):
    """A single route option returned by the Google Routes API."""
    route_index: int
    encoded_polyline: str
    distance_meters: float
    duration_seconds: float
    num_steps: int
    travel_mode: str


class RouteCandidates(Model):
    """Collection of route candidates from the route agent to the orchestrator."""
    session_id: str
    candidates: List[RouteCandidate]
    travel_mode: str
    service_degraded: bool = False


class ElevationCheckRequest(Model):
    """Request from the orchestrator to the elevation agent for one route."""

    class Config:
        # Pydantic v1 uses ``title`` to pin the JSON-schema name for digest stability.
        title = "ElevationCheckRequest"

    session_id: str
    route_index: int
    encoded_polyline: str
    distance_meters: float
    profile: Dict[str, Any]


class ElevationVerdict(Model):
    """Elevation agent's verdict on one route's accessibility."""

    class Config:
        title = "ElevationVerdict"

    session_id: str
    route_index: int
    segments: List[Dict[str, Any]]
    is_route_compliant: bool
    max_grade_percentage: float
    service_degraded: bool = False


class AccessibilityCheckRequest(Model):
    """Request from the orchestrator to the places agent for destination info."""
    session_id: str
    destination: LatLng
    radius_meters: float = 50.0


class AccessibilityVerdict(Model):
    """Places agent's verdict on destination wheelchair accessibility."""
    session_id: str
    place_id: Optional[str] = None
    display_name: Optional[str] = None
    wheelchair_entrance: Optional[bool] = None
    warning: Optional[str] = None
    service_degraded: bool = False


class FinalRoute(Model):
    """Final response from the orchestrator to the client."""
    session_id: str
    success: bool
    chosen_route_index: Optional[int] = None
    directions_prose: str
    warnings: List[str]
    total_distance_meters: Optional[float] = None
    travel_mode: Optional[str] = None
    service_degraded: bool = False
