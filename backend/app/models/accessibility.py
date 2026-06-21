"""
WheelWay — Core accessibility data models.

This is the canonical schema for a "traversable segment" in the accessibility
graph. Every other subsystem (computer vision pipeline, OSM ingestion, Redis
storage, API responses) should produce or consume objects shaped like these.

References used to set thresholds (see scoring/constants.py for citations):
  - U.S. Access Board PROWAG Final Rule (2023), effective Oct 7, 2023
  - ADA Standards for Accessible Design (2010)
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class SurfaceType(str, Enum):
    CONCRETE = "concrete"
    ASPHALT = "asphalt"
    PAVERS = "pavers"
    GRAVEL = "gravel"
    DIRT = "dirt"
    BRICK = "brick"
    GRASS = "grass"
    METAL_GRATE = "metal_grate"
    UNKNOWN = "unknown"


# Relative traction/firmness penalty multipliers by surface type.
# 1.0 = no penalty (ideal firm/stable/slip-resistant surface per PROWAG R302.7).
# Lower = more penalty. These are heuristic, tunable in constants.py.
SURFACE_BASE_QUALITY = {
    SurfaceType.CONCRETE: 1.0,
    SurfaceType.ASPHALT: 0.95,
    SurfaceType.PAVERS: 0.75,
    SurfaceType.BRICK: 0.65,
    SurfaceType.METAL_GRATE: 0.55,
    SurfaceType.GRAVEL: 0.35,
    SurfaceType.DIRT: 0.25,
    SurfaceType.GRASS: 0.2,
    SurfaceType.UNKNOWN: 0.5,
}


class WheelchairType(str, Enum):
    MANUAL = "manual"
    POWERED = "powered"
    SCOOTER = "scooter"
    WALKER = "walker"


class Segment(BaseModel):
    """
    A single traversable edge in the accessibility graph (e.g. one block of
    sidewalk, one curb ramp, one crosswalk).
    """

    segment_id: str
    start_node_id: str
    end_node_id: str

    length_m: float = Field(..., gt=0, description="Segment length in meters")

    # --- Physical geometry ---
    slope: float = Field(
        0.0,
        description="Running slope (grade) as a percentage, e.g. 4.2 = 4.2%. "
        "Measured parallel to direction of travel.",
    )
    cross_slope: float = Field(
        0.0,
        description="Cross slope as a percentage, measured perpendicular to "
        "direction of travel. PROWAG caps this at 2% for sidewalks.",
    )
    width: float = Field(
        1.524,  # 60 in = PROWAG-preferred passing width
        gt=0,
        description="Clear width in meters. PROWAG minimum is 1.0m (~36-40in) "
        "for pedestrian access routes, 1.22m (48in) preferred passing width.",
    )

    # --- Surface ---
    surface: SurfaceType = SurfaceType.UNKNOWN
    surface_condition: float = Field(
        0.9,
        ge=0,
        le=1,
        description="0-1 quality score for the surface instance (cracks, "
        "potholes, heaving). 1.0 = pristine. Distinct from surface *type*.",
    )

    # --- Discrete accessibility features ---
    curb_ramp: bool = True
    stairs: bool = False
    has_obstruction: bool = False
    obstruction_clearance_m: Optional[float] = Field(
        None, description="Clear width remaining around a known obstruction, if any."
    )

    # --- Dynamic / real-time signals ---
    construction_risk: float = Field(
        0.0, ge=0, le=1, description="0-1 likelihood this segment is currently blocked"
    )
    last_verified_ts: Optional[float] = Field(
        None, description="Unix timestamp this segment's data was last confirmed "
        "(by CV pass, user report, or crowdsource). Used for confidence decay."
    )
    report_confidence: float = Field(
        1.0, ge=0, le=1, description="0-1 confidence in this segment's data, "
        "decays over time since last_verified_ts and increases with corroborating reports."
    )

    @field_validator("slope", "cross_slope")
    @classmethod
    def reasonable_grade(cls, v: float) -> float:
        # Sanity bound — anything beyond ~40% is almost certainly a sensor/data error,
        # not a real walkable segment.
        if abs(v) > 40:
            raise ValueError(f"Slope {v}% is outside plausible sidewalk range")
        return v


class UserMobilityProfile(BaseModel):
    """Per-user constraints used to personalize scoring/routing."""

    wheelchair_type: WheelchairType = WheelchairType.MANUAL
    max_slope_pct: float = Field(8.33, description="Hard ceiling, default = ADA ramp max (1:12)")
    max_cross_slope_pct: float = Field(2.0, description="Hard ceiling, PROWAG default")
    min_width_m: float = Field(0.91, description="Hard ceiling, ADA min clear width (36in)")
    avoid_stairs: bool = True
    avoid_unverified_segments: bool = False
    surface_sensitivity: float = Field(
        1.0, ge=0, le=2,
        description="Multiplier on how harshly surface quality is penalized. "
        ">1 for manual wheelchair users who feel rough surfaces more acutely.",
    )
    max_route_effort: Optional[float] = Field(
        None, description="Optional hard cap on cumulative route effort score"
    )


class RouteRequest(BaseModel):
    start_node_id: str
    end_node_id: str
    profile: UserMobilityProfile = UserMobilityProfile()
