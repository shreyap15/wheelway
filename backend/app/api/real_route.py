"""
WheelWay — Real-map pedestrian route endpoint (POST /real-route).

This is the REAL-ROUTE flow, distinct from the synthetic A* prototype in
app/routing/ (that one runs on a hand-mocked Berkeley graph and must NOT be
presented as real geometry). Here every route shape comes from Google's
pedestrian routing API and is rendered verbatim.

Pipeline (all reusing the existing accessroute/ Google integration — no
duplicated HTTP clients):

  origin/destination
    -> accessroute.tools.routes_tool.compute_routes   (Google Routes API, WALK)
    -> accessroute.common.geo.decode_polyline         (encoded -> [(lat,lng)])
    -> GeoJSON LineString in [lng, lat] order
    -> accessroute.tools.elevation_tool.sample_elevations + grade_segments
                                                       (Google Elevation API)
    -> wheelway_scoring accessibility score from real grades
    -> accessroute.tools.places_tool.check_destination_accessibility
                                                       (Google Places API New)
    -> structured JSON; the frontend draws geometry.coordinates exactly.

DATA PROVENANCE: every field is tagged with one of:
  google_routes | google_elevation | google_places | wheelway_scoring |
  camera_cv | mocked | unavailable
so the UI can show where each value came from. No mocked accessibility values
are silently mixed into real route geometry.

CREDENTIALS: requires GOOGLE_MAPS_API_KEY (Routes + Elevation + Places APIs
enabled). If it is absent the endpoint returns HTTP 503 with a clear
configuration error naming the variable — it never fabricates geometry.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field, ValidationError, field_validator

# --- Make the sibling accessroute/ package importable (it holds the Google
#     integration). repo_root/accessroute is added once, lazily-safe. ---
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ACCESSROUTE_DIR = _REPO_ROOT / "accessroute"
if str(_ACCESSROUTE_DIR) not in sys.path:
    sys.path.insert(0, str(_ACCESSROUTE_DIR))

real_route_bp = Blueprint("real_route", __name__)

# Provenance tag constants
SRC_ROUTES = "google_routes"
SRC_ELEVATION = "google_elevation"
SRC_PLACES = "google_places"
SRC_SCORING = "wheelway_scoring"
SRC_CV = "camera_cv"
SRC_MOCKED = "mocked"
SRC_UNAVAILABLE = "unavailable"

# Canonical CV observation format (requirement 8). Documented here so the CV
# teammate and the frontend agree on the shape. The endpoint echoes any
# observations posted in the request and otherwise returns an empty list.
CV_OBSERVATION_EXAMPLE = {
    "latitude": 0.0,
    "longitude": 0.0,
    "feature_type": "obstruction",
    "confidence": 0.0,
    "distance_cm": 0.0,
    "timestamp": "",
    "source": SRC_CV,
}


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
    # Optional CV detections to echo back as map overlays (requirement 8).
    cv_observations: list[dict] = Field(default_factory=list)

    @field_validator("cv_observations")
    @classmethod
    def _cap_observations(cls, v: list[dict]) -> list[dict]:
        return v[:500]


# --------------------------------------------------------------------------- #
# Pure helpers (network-free, unit-testable)
# --------------------------------------------------------------------------- #
def latlng_pairs_to_geojson(coords: list[tuple[float, float]]) -> dict:
    """
    Convert decoded polyline (lat, lng) pairs into a GeoJSON LineString with
    coordinates in [longitude, latitude] order. This is the ONLY place lat/lng
    order is flipped for the wire format.
    """
    return {
        "type": "LineString",
        "coordinates": [[lng, lat] for (lat, lng) in coords],
    }


def score_real_route(
    max_grade_pct: float,
    exceeds_limit: bool,
    num_steep_sections: int,
) -> float:
    """
    wheelway_scoring heuristic over REAL grade data (derived from
    google_elevation). 0-100, higher = more accessible. Honest, slope-only —
    width/surface/curb data is NOT available from the routing+elevation APIs,
    so this score reflects gradient only.
    """
    score = 100.0
    # PROWAG ideal running slope is ~5%; penalize grade above that.
    score -= max(0.0, max_grade_pct - 5.0) * 4.0
    if exceeds_limit:
        score -= 30.0
    score -= num_steep_sections * 3.0
    return round(max(0.0, min(100.0, score)), 1)


def _config_error_response():
    """Return the structured 503 when Google credentials are missing."""
    return (
        jsonify(
            {
                "error": "configuration_error",
                "message": (
                    "Google Maps Platform API key is not configured. Real-map "
                    "pedestrian routing is unavailable. No route geometry was "
                    "fabricated."
                ),
                "missing_env": ["GOOGLE_MAPS_API_KEY"],
                "required_apis": [
                    "Routes API (computeRoutes, WALK)",
                    "Elevation API",
                    "Places API (New) searchNearby",
                ],
                "how_to_fix": (
                    "Set GOOGLE_MAPS_API_KEY in accessroute/.env (see "
                    "accessroute/.env.example) with Routes, Elevation, and "
                    "Places APIs enabled, then restart the backend."
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
    """Compute real pedestrian routes with elevation + places enrichment."""
    # --- Validate body ---
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Missing or invalid JSON body"}), 400
    try:
        req = RealRouteRequest(**data)
    except ValidationError as exc:
        return jsonify({"error": "Invalid request", "details": exc.errors()}), 400

    # --- Credentials gate (fail loud, never fake geometry) ---
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        # Try the accessroute config too (it loads accessroute/.env).
        try:
            from accessroute.config import GOOGLE_MAPS_API_KEY as _AR_KEY
            api_key = _AR_KEY or ""
        except Exception:
            api_key = ""
    if not api_key:
        return _config_error_response()

    # --- Import the existing Google integration (lazy so app/tests load even
    #     if accessroute deps are absent) ---
    try:
        from accessroute.schemas import LatLng, WheelchairProfile
        from accessroute.common.geo import decode_polyline
        from accessroute.common.http import ServiceDegraded
        from accessroute.tools.routes_tool import compute_routes
        from accessroute.tools.elevation_tool import sample_elevations, grade_segments
        from accessroute.tools.places_tool import check_destination_accessibility
    except Exception as exc:  # pragma: no cover - depends on env
        return (
            jsonify(
                {
                    "error": "integration_unavailable",
                    "message": (
                        "The accessroute Google integration could not be "
                        f"imported: {exc}"
                    ),
                    "how_to_fix": (
                        "Install accessroute deps: "
                        "pip install -r accessroute/requirements.txt"
                    ),
                }
            ),
            500,
        )

    origin = LatLng(lat=req.origin.latitude, lng=req.origin.longitude)
    destination = LatLng(lat=req.destination.latitude, lng=req.destination.longitude)

    # Map the frontend profile onto the accessroute WheelchairProfile.
    elevation_profile = WheelchairProfile(
        device_type=req.profile.wheelchair_type,
        max_incline_grade=req.profile.max_slope_pct,
        max_decline_grade=max(req.profile.max_slope_pct, 10.0),
        max_width_cm=int(req.profile.min_width_m * 100),
    )

    warnings: list[str] = []
    service_degraded = False

    # --- Google Routes (WALK, alternatives) ---
    try:
        candidates = compute_routes(
            origin, destination, api_key=api_key, travel_mode="WALK", alternatives=True
        )
    except ServiceDegraded as exc:
        return (
            jsonify(
                {
                    "error": "routing_unavailable",
                    "message": f"Google Routes API unavailable: {exc}",
                    "source": SRC_ROUTES,
                }
            ),
            502,
        )

    if not candidates:
        return (
            jsonify(
                {
                    "error": "no_route",
                    "message": "Google Routes returned no walking route for this origin/destination.",
                    "source": SRC_ROUTES,
                }
            ),
            404,
        )

    routes_out = []
    for i, cand in enumerate(candidates):
        # Decode the REAL encoded polyline -> GeoJSON [lng, lat].
        decoded = decode_polyline(cand.encoded_polyline)  # [(lat, lng), ...]
        geometry = latlng_pairs_to_geojson(decoded)

        route_warnings: list[str] = []
        sources = {
            "geometry": SRC_ROUTES,
            "distance_m": SRC_ROUTES,
            "duration_s": SRC_ROUTES,
            "stairs_detected": SRC_UNAVAILABLE,
        }

        # --- Google Elevation: real grades along the polyline ---
        max_grade = None
        avg_grade = None
        steep_sections = []
        exceeds_max_slope = None
        accessibility_score = None
        try:
            samples = sample_elevations(
                cand.encoded_polyline, cand.distance_meters, api_key=api_key
            )
            reports, _all_compliant, max_grade_val = grade_segments(
                samples, elevation_profile
            )
            max_grade = round(max_grade_val, 1)
            grades = [abs(r.grade_percentage) for r in reports]
            avg_grade = round(sum(grades) / len(grades), 1) if grades else 0.0
            for r in reports:
                if abs(r.grade_percentage) > req.profile.max_slope_pct:
                    steep_sections.append(
                        {
                            "segment_index": r.segment_index,
                            "grade_pct": round(r.grade_percentage, 1),
                            "start": [r.start_location.lng, r.start_location.lat],
                            "end": [r.end_location.lng, r.end_location.lat],
                        }
                    )
            exceeds_max_slope = max_grade > req.profile.max_slope_pct
            accessibility_score = score_real_route(
                max_grade, exceeds_max_slope, len(steep_sections)
            )
            sources["max_slope_pct"] = SRC_ELEVATION
            sources["avg_slope_pct"] = SRC_ELEVATION
            sources["steep_sections"] = SRC_ELEVATION
            sources["exceeds_max_slope"] = SRC_SCORING
            sources["accessibility_score"] = SRC_SCORING
            if exceeds_max_slope:
                route_warnings.append(
                    f"Max grade {max_grade}% exceeds your {req.profile.max_slope_pct}% limit."
                )
            if steep_sections:
                route_warnings.append(
                    f"{len(steep_sections)} steep section(s) detected along this route."
                )
        except ServiceDegraded as exc:
            service_degraded = True
            sources["max_slope_pct"] = SRC_UNAVAILABLE
            sources["accessibility_score"] = SRC_UNAVAILABLE
            route_warnings.append(
                "Elevation data unavailable; slope/grade not assessed for this route."
            )
            warnings.append(f"Google Elevation API degraded: {exc}")

        # Stairs: NOT derivable from the current Routes field mask. Honest false.
        route_warnings.append(
            "Stair detection is not available from routing data; confirm via "
            "satellite view or CV overlay."
        )

        # Deterministic explanation (no LLM dependency required).
        dur_min = round(cand.duration_seconds / 60.0)
        if max_grade is not None:
            grade_phrase = (
                f"max grade {max_grade}% "
                f"({'exceeds' if exceeds_max_slope else 'within'} your "
                f"{req.profile.max_slope_pct}% limit)"
            )
        else:
            grade_phrase = "grade not assessed (elevation unavailable)"
        explanation = (
            f"{round(cand.distance_meters)} m walking route, ~{dur_min} min; "
            f"{grade_phrase}. Geometry is the real Google Routes pedestrian "
            f"polyline."
        )

        routes_out.append(
            {
                "route_id": f"route-{i + 1}",
                "geometry": geometry,
                "distance_m": round(cand.distance_meters, 1),
                "duration_s": round(cand.duration_seconds, 1),
                "max_slope_pct": max_grade,
                "avg_slope_pct": avg_grade,
                "stairs_detected": False,
                "steep_sections": steep_sections,
                "exceeds_max_slope": exceeds_max_slope,
                "accessibility_score": accessibility_score,
                "accessibility_warnings": route_warnings,
                "explanation": explanation,
                "sources": sources,
            }
        )

    # --- Google Places: enrich destination ---
    destination_place = {
        "place_name": None,
        "address": None,
        "category": None,
        "wheelchair_accessible_entrance": None,
        "warning": None,
        "source": SRC_PLACES,
        "data_classification": {},
    }
    try:
        verdict = check_destination_accessibility(destination, api_key=api_key)
        if verdict.service_degraded:
            service_degraded = True
            destination_place["warning"] = "Places data unavailable."
            destination_place["source"] = SRC_UNAVAILABLE
            destination_place["data_classification"] = {
                "place_name": SRC_UNAVAILABLE,
                "wheelchair_accessible_entrance": SRC_UNAVAILABLE,
            }
        else:
            destination_place["place_name"] = verdict.display_name
            destination_place["wheelchair_accessible_entrance"] = verdict.wheelchair_entrance
            destination_place["warning"] = verdict.warning
            destination_place["data_classification"] = {
                # API-provided vs unavailable/unknown — never invented.
                "place_name": "api_provided" if verdict.display_name else "unavailable",
                "wheelchair_accessible_entrance": (
                    "api_provided"
                    if verdict.wheelchair_entrance is not None
                    else "unavailable_unknown"
                ),
                # Address + category not requested in the Places field mask.
                "address": "unavailable",
                "category": "unavailable",
            }
            if verdict.warning:
                warnings.append(verdict.warning)
    except Exception as exc:  # pragma: no cover - network dependent
        service_degraded = True
        destination_place["warning"] = f"Places lookup failed: {exc}"
        destination_place["source"] = SRC_UNAVAILABLE

    response = {
        "mode": "real_route",
        "origin": req.origin.model_dump(),
        "destination": req.destination.model_dump(),
        "profile": req.profile.model_dump(),
        "routes": routes_out,
        "destination_place": destination_place,
        # CV overlay passthrough (requirement 8): echo posted detections, tagged.
        "cv_observations": req.cv_observations,
        "cv_observation_format": CV_OBSERVATION_EXAMPLE,
        "data_sources": {
            "geometry": SRC_ROUTES,
            "distance_duration": SRC_ROUTES,
            "slope_grade": SRC_ELEVATION,
            "accessibility_score": SRC_SCORING,
            "destination_place": SRC_PLACES,
            "stairs_detection": SRC_UNAVAILABLE,
            "path_width_surface": SRC_UNAVAILABLE,
            "cv_observations": SRC_CV,
        },
        "warnings": warnings,
        "service_degraded": service_degraded,
    }
    return jsonify(response)
