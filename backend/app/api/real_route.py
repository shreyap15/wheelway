"""
WheelWay — Real-map pedestrian route endpoint (POST /real-route).

This is the REAL-ROUTE flow, distinct from the synthetic A* prototype in
app/routing/ (that one runs on a hand-mocked Berkeley graph and must NOT be
presented as real geometry). Here every route shape comes from Mapbox's
walking-directions API and is rendered verbatim.

The endpoint is a THIN HTTP adapter. All routing/enrichment/scoring lives in
the single shared pipeline ``accessroute.pipeline.compute_accessible_routes``
(also used by the orchestrator, the local demo, and the Agentverse mailbox), so
the pipeline is never duplicated across endpoints or scripts.

    origin/destination
      -> compute_accessible_routes (Mapbox walking geometry, the ONLY geometry
         provider; Google Elevation + Places enrichment when configured)
      -> structured JSON; the frontend draws geometry.coordinates exactly.

CREDENTIALS: requires MAPBOX_ACCESS_TOKEN. Google Maps key is OPTIONAL (enables
Elevation + Places enrichment). If the Mapbox token is absent the endpoint
returns HTTP 503 with a clear configuration error -- it never fabricates
geometry. If only the Google key is absent, Mapbox geometry still succeeds and
enrichment fields are marked unavailable.

Structured errors:
    400 validation_error      -- bad request body
    404 no_route              -- Mapbox returned no walking geometry
    502 routing_unavailable   -- the Mapbox API itself failed
    503 configuration_error   -- MAPBOX_ACCESS_TOKEN missing
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field, ValidationError, field_validator

# --- Make the sibling accessroute/ package importable (it holds the Mapbox +
#     Google integration). repo_root/accessroute is added once, lazily-safe. ---
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ACCESSROUTE_DIR = _REPO_ROOT / "accessroute"
if str(_ACCESSROUTE_DIR) not in sys.path:
    sys.path.insert(0, str(_ACCESSROUTE_DIR))

real_route_bp = Blueprint("real_route", __name__)


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #
class Coordinate(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class RealRouteProfile(BaseModel):
    wheelchair_type: str = "manual"
    avoid_stairs: bool = True
    max_slope_pct: float = Field(8.33, gt=0, le=45)
    min_width_m: float = Field(0.91, gt=0, le=10)


class RealRouteRequest(BaseModel):
    origin: Coordinate
    destination: Coordinate
    profile: RealRouteProfile = RealRouteProfile()
    # Optional CV detections to echo back as map overlays.
    cv_observations: list[dict] = Field(default_factory=list)

    @field_validator("cv_observations")
    @classmethod
    def _cap_observations(cls, v: list[dict]) -> list[dict]:
        return v[:500]


def _config_error_response():
    """Return the structured 503 when the Mapbox token is missing."""
    return (
        jsonify(
            {
                "error": "configuration_error",
                "message": (
                    "MAPBOX_ACCESS_TOKEN is not configured. Real-map pedestrian "
                    "routing is unavailable. No route geometry was fabricated."
                ),
                "missing_env": ["MAPBOX_ACCESS_TOKEN"],
                "how_to_fix": (
                    "Set MAPBOX_ACCESS_TOKEN in accessroute/.env (see "
                    "accessroute/.env.example), then restart the backend. "
                    "GOOGLE_MAPS_API_KEY is optional and enables elevation/places "
                    "enrichment."
                ),
            }
        ),
        503,
    )


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@real_route_bp.post("/real-route")
def real_route():
    """Compute real Mapbox walking routes with elevation + places enrichment."""
    # --- Validate body (400 validation_error) ---
    data = request.get_json(silent=True)
    if data is None:
        return (
            jsonify({"error": "validation_error", "message": "Missing or invalid JSON body"}),
            400,
        )
    try:
        req = RealRouteRequest(**data)
    except ValidationError as exc:
        return (
            jsonify(
                {
                    "error": "validation_error",
                    "message": "Invalid request body.",
                    "details": exc.errors(),
                }
            ),
            400,
        )

    # --- Import the shared pipeline lazily (so app/tests load even if the
    #     accessroute deps are absent in some environment) ---
    try:
        from accessroute.schemas import LatLng, WheelchairProfile
        from accessroute.pipeline import (
            ConfigurationError,
            NoRouteError,
            ServiceDegraded,
            compute_accessible_routes,
        )
    except Exception as exc:  # pragma: no cover - depends on env
        return (
            jsonify(
                {
                    "error": "integration_unavailable",
                    "message": f"The accessroute integration could not be imported: {exc}",
                    "how_to_fix": "pip install -r accessroute/requirements.txt",
                }
            ),
            500,
        )

    origin = LatLng(lat=req.origin.latitude, lng=req.origin.longitude)
    destination = LatLng(lat=req.destination.latitude, lng=req.destination.longitude)

    # Map the frontend profile onto the accessroute WheelchairProfile.
    profile = WheelchairProfile(
        device_type=req.profile.wheelchair_type,
        max_incline_grade=req.profile.max_slope_pct,
        max_decline_grade=max(req.profile.max_slope_pct, 10.0),
        max_width_cm=int(req.profile.min_width_m * 100),
        requires_curb_ramps=req.profile.avoid_stairs,
    )

    try:
        result = asyncio.run(
            compute_accessible_routes(
                origin,
                destination,
                profile,
                cv_observations=req.cv_observations,
            )
        )
    except ConfigurationError:
        return _config_error_response()
    except NoRouteError as exc:
        return (
            jsonify(
                {
                    "error": "no_route",
                    "message": str(exc)
                    or "Mapbox returned no walking route for this origin/destination.",
                    "source": "mapbox",
                }
            ),
            404,
        )
    except ServiceDegraded as exc:
        return (
            jsonify(
                {
                    "error": "routing_unavailable",
                    "message": f"Mapbox Directions API unavailable: {exc}",
                    "source": "mapbox",
                }
            ),
            502,
        )

    return jsonify(result.dict())
