"""Shared accessible-routing pipeline for WheelWay.

This is the SINGLE canonical real-route flow. Every real-route consumer calls
``compute_accessible_routes`` -- there is no second copy of the pipeline:

    Flask  POST /real-route   -> compute_accessible_routes
    accessroute orchestrator  -> compute_accessible_routes (then LLM synthesis)
    local demo / mailbox      -> compute_accessible_routes

Canonical flow (NO fabricated geometry, ever):

    Mapbox Walking Directions          (exact API geometry; tools/mapbox_routes_tool)
      -> GeoJSON LineString [lng, lat]
      -> Google Elevation enrichment   (sample + smooth + grade; tools/elevation_tool)
      -> Google Places enrichment      (when configured; tools/places_tool)
      -> WheelWay accessibility scoring (slope-derived; honest)
      -> canonical Pydantic models

Mapbox is the ONLY route-geometry provider. Google Routes is NOT used here.
Google Elevation/Places are optional enrichment: if their key is absent the
Mapbox geometry still succeeds and the enrichment fields are marked unavailable.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from pydantic.v1 import BaseModel

from accessroute.common.geo import decode_polyline
from accessroute.common.http import ServiceDegraded
from accessroute.config import GOOGLE_MAPS_API_KEY, MAPBOX_ACCESS_TOKEN
from accessroute.schemas import LatLng, WheelchairProfile
from accessroute.tools.elevation_tool import (
    grade_segments,
    sample_elevations,
    smooth_elevation_samples,
)
from accessroute.tools.mapbox_routes_tool import compute_mapbox_routes
from accessroute.tools.places_tool import check_destination_accessibility

# Provenance tags so the UI can show what is real vs unavailable.
SRC_MAPBOX = "mapbox"
SRC_ELEVATION = "google_elevation"
SRC_PLACES = "google_places"
SRC_SCORING = "wheelway_scoring"
SRC_CV = "camera_cv"
SRC_UNAVAILABLE = "unavailable"


class ConfigurationError(Exception):
    """Raised when a required credential (the Mapbox token) is missing.

    Maps to HTTP 503 ``configuration_error`` -- we never fabricate geometry.
    """


class NoRouteError(Exception):
    """Raised when Mapbox returns no walking geometry. Maps to HTTP 404."""


# --------------------------------------------------------------------------- #
# Canonical result models
# --------------------------------------------------------------------------- #
class SteepSection(BaseModel):
    segment_index: int
    grade_pct: float
    start: List[float]  # [lng, lat]
    end: List[float]  # [lng, lat]


class AccessibleRoute(BaseModel):
    route_id: str
    geometry: Dict[str, Any]  # GeoJSON LineString, coordinates in [lng, lat]
    distance_m: float
    duration_s: float
    max_slope_pct: Optional[float] = None
    avg_slope_pct: Optional[float] = None
    steep_sections: List[SteepSection] = []
    exceeds_max_slope: Optional[bool] = None
    stairs_detected: Optional[bool] = None  # null when unknown
    accessibility_score: Optional[float] = None
    accessibility_warnings: List[str] = []
    explanation: str = ""
    sources: Dict[str, str] = {}


class DestinationPlace(BaseModel):
    place_name: Optional[str] = None
    wheelchair_accessible_entrance: Optional[bool] = None
    warning: Optional[str] = None
    source: str = SRC_PLACES


class AccessibleRoutesResult(BaseModel):
    mode: str = "real_route"
    origin: Dict[str, float]
    destination: Dict[str, float]
    profile: Dict[str, Any]
    routes: List[AccessibleRoute]
    destination_place: DestinationPlace
    cv_observations: List[Dict[str, Any]] = []
    data_sources: Dict[str, str] = {}
    warnings: List[str] = []
    service_degraded: bool = False


# --------------------------------------------------------------------------- #
# Pure helpers (network-free, unit-testable)
# --------------------------------------------------------------------------- #
def latlng_pairs_to_geojson(coords: List[tuple]) -> Dict[str, Any]:
    """Convert decoded (lat, lng) pairs into a GeoJSON LineString in [lng, lat].

    This is the ONLY place lat/lng order is flipped for the wire format.
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
    """WheelWay accessibility heuristic over REAL grade data. 0-100, higher = better.

    Honest, slope-only -- width/surface/curb data is not available from Mapbox
    geometry + Google elevation, so this reflects gradient only.
    """
    score = 100.0
    # PROWAG ideal running slope is ~5%; penalize grade above that.
    score -= max(0.0, max_grade_pct - 5.0) * 4.0
    if exceeds_limit:
        score -= 30.0
    score -= num_steep_sections * 3.0
    return round(max(0.0, min(100.0, score)), 1)


def _coerce_profile(profile: Any) -> WheelchairProfile:
    if isinstance(profile, WheelchairProfile):
        return profile
    if isinstance(profile, dict):
        return WheelchairProfile(**profile)
    return WheelchairProfile.parse_obj(profile)


def _max_slope_limit(profile: WheelchairProfile) -> float:
    return float(profile.max_incline_grade)


# --------------------------------------------------------------------------- #
# Per-candidate enrichment (runs in a worker thread)
# --------------------------------------------------------------------------- #
def _enrich_candidate(
    index: int,
    candidate,
    profile: WheelchairProfile,
    google_key: str,
) -> tuple:
    """Build one AccessibleRoute. Returns (route, warnings, degraded)."""
    decoded = decode_polyline(candidate.encoded_polyline)  # [(lat, lng), ...]
    geometry = latlng_pairs_to_geojson(decoded)

    route_warnings: List[str] = []
    degraded = False
    slope_limit = _max_slope_limit(profile)

    sources = {
        "geometry": SRC_MAPBOX,
        "distance_m": SRC_MAPBOX,
        "duration_s": SRC_MAPBOX,
        "stairs_detected": SRC_UNAVAILABLE,
    }

    max_grade: Optional[float] = None
    avg_grade: Optional[float] = None
    steep_sections: List[SteepSection] = []
    exceeds_max_slope: Optional[bool] = None
    accessibility_score: Optional[float] = None

    if google_key:
        try:
            samples = sample_elevations(
                candidate.encoded_polyline,
                candidate.distance_meters,
                api_key=google_key,
            )
            samples = smooth_elevation_samples(samples)
            reports, _all_compliant, max_grade_val = grade_segments(samples, profile)
            max_grade = round(max_grade_val, 1)
            grades = [abs(r.grade_percentage) for r in reports]
            avg_grade = round(sum(grades) / len(grades), 1) if grades else 0.0
            for r in reports:
                if abs(r.grade_percentage) > slope_limit:
                    steep_sections.append(
                        SteepSection(
                            segment_index=r.segment_index,
                            grade_pct=round(r.grade_percentage, 1),
                            start=[r.start_location.lng, r.start_location.lat],
                            end=[r.end_location.lng, r.end_location.lat],
                        )
                    )
            exceeds_max_slope = max_grade > slope_limit
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
                    f"Max grade {max_grade}% exceeds your {slope_limit}% limit."
                )
            if steep_sections:
                route_warnings.append(
                    f"{len(steep_sections)} steep section(s) detected along this route."
                )
        except ServiceDegraded as exc:
            degraded = True
            sources["max_slope_pct"] = SRC_UNAVAILABLE
            sources["accessibility_score"] = SRC_UNAVAILABLE
            route_warnings.append(
                "Elevation data unavailable; slope/grade not assessed for this route."
            )
            route_warnings.append(f"Google Elevation API degraded: {exc}")
    else:
        sources["max_slope_pct"] = SRC_UNAVAILABLE
        sources["avg_slope_pct"] = SRC_UNAVAILABLE
        sources["accessibility_score"] = SRC_UNAVAILABLE
        route_warnings.append(
            "Elevation enrichment unavailable (no Google Maps key); slope not assessed."
        )

    # Stairs are not derivable from Mapbox walking geometry -> unknown (null).
    route_warnings.append(
        "Stair detection is not available from routing data; confirm via "
        "satellite view or CV overlay."
    )

    dur_min = round(candidate.duration_seconds / 60.0)
    if max_grade is not None:
        grade_phrase = (
            f"max grade {max_grade}% "
            f"({'exceeds' if exceeds_max_slope else 'within'} your {slope_limit}% limit)"
        )
    else:
        grade_phrase = "grade not assessed (elevation unavailable)"
    explanation = (
        f"{round(candidate.distance_meters)} m walking route, ~{dur_min} min; "
        f"{grade_phrase}. Geometry is the exact Mapbox walking-directions polyline."
    )

    route = AccessibleRoute(
        route_id=f"route-{index + 1}",
        geometry=geometry,
        distance_m=round(candidate.distance_meters, 1),
        duration_s=round(candidate.duration_seconds, 1),
        max_slope_pct=max_grade,
        avg_slope_pct=avg_grade,
        steep_sections=steep_sections,
        exceeds_max_slope=exceeds_max_slope,
        stairs_detected=None,
        accessibility_score=accessibility_score,
        accessibility_warnings=route_warnings,
        explanation=explanation,
        sources=sources,
    )
    return route, route_warnings, degraded


def _compute_accessible_routes_sync(
    origin: LatLng,
    destination: LatLng,
    profile: WheelchairProfile,
    cv_observations: List[Dict[str, Any]],
    mapbox_token: str,
    google_key: str,
) -> AccessibleRoutesResult:
    """Blocking implementation. Wrapped by the async entry point below."""
    if not mapbox_token:
        raise ConfigurationError(
            "MAPBOX_ACCESS_TOKEN is not configured. Real-map walking routing is "
            "unavailable. No route geometry was fabricated."
        )

    # ---- Mapbox walking geometry (ONLY geometry provider) ----
    try:
        candidates = compute_mapbox_routes(
            origin,
            destination,
            access_token=mapbox_token,
            travel_mode="WALK",
            alternatives=True,
        )
    except ServiceDegraded as exc:
        if "no usable route geometry" in str(exc).lower():
            raise NoRouteError(str(exc)) from exc
        raise

    if not candidates:
        raise NoRouteError(
            "Mapbox Directions returned no walking route for this origin/destination."
        )

    warnings: List[str] = []
    service_degraded = False

    routes: List[AccessibleRoute] = []
    for i, candidate in enumerate(candidates):
        route, route_warnings, degraded = _enrich_candidate(
            i, candidate, profile, google_key
        )
        routes.append(route)
        if degraded:
            service_degraded = True
            warnings.extend(
                w for w in route_warnings if w.startswith("Google Elevation API degraded")
            )

    # ---- Google Places enrichment (optional) ----
    destination_place = DestinationPlace(source=SRC_PLACES)
    if google_key:
        try:
            verdict = check_destination_accessibility(destination, api_key=google_key)
            if verdict.service_degraded:
                service_degraded = True
                destination_place.warning = "Places data unavailable."
                destination_place.source = SRC_UNAVAILABLE
            else:
                destination_place.place_name = verdict.display_name
                destination_place.wheelchair_accessible_entrance = (
                    verdict.wheelchair_entrance
                )
                destination_place.warning = verdict.warning
                if verdict.warning:
                    warnings.append(verdict.warning)
        except Exception as exc:  # network dependent
            service_degraded = True
            destination_place.warning = f"Places lookup failed: {exc}"
            destination_place.source = SRC_UNAVAILABLE
    else:
        destination_place.warning = "Places enrichment unavailable (no Google Maps key)."
        destination_place.source = SRC_UNAVAILABLE

    data_sources = {
        "geometry": SRC_MAPBOX,
        "distance_duration": SRC_MAPBOX,
        "slope_grade": SRC_ELEVATION if google_key else SRC_UNAVAILABLE,
        "accessibility_score": SRC_SCORING if google_key else SRC_UNAVAILABLE,
        "destination_place": destination_place.source,
        "stairs_detection": SRC_UNAVAILABLE,
        "path_width_surface": SRC_UNAVAILABLE,
        "cv_observations": SRC_CV,
    }

    return AccessibleRoutesResult(
        mode="real_route",
        origin={"latitude": origin.lat, "longitude": origin.lng},
        destination={"latitude": destination.lat, "longitude": destination.lng},
        profile=profile.dict(),
        routes=routes,
        destination_place=destination_place,
        cv_observations=list(cv_observations or []),
        data_sources=data_sources,
        warnings=warnings,
        service_degraded=service_degraded,
    )


async def compute_accessible_routes(
    origin: LatLng,
    destination: LatLng,
    profile: Any,
    cv_observations: Optional[List[Dict[str, Any]]] = None,
    *,
    mapbox_token: Optional[str] = None,
    google_key: Optional[str] = None,
) -> AccessibleRoutesResult:
    """Canonical real-route pipeline shared by Flask, orchestrator, demo, mailbox.

    Args:
        origin / destination: LatLng coordinates.
        profile: WheelchairProfile (or dict) describing grade limits.
        cv_observations: optional CV detections echoed back for map overlays.
        mapbox_token: overrides ``config.MAPBOX_ACCESS_TOKEN`` (mainly for tests).
        google_key: overrides ``config.GOOGLE_MAPS_API_KEY`` (mainly for tests).

    Returns:
        AccessibleRoutesResult with exact Mapbox geometry plus enrichment.

    Raises:
        ConfigurationError: the Mapbox token is missing (HTTP 503).
        NoRouteError: Mapbox returned no walking geometry (HTTP 404).
        ServiceDegraded: the Mapbox API itself failed (HTTP 502).
    """
    token = mapbox_token if mapbox_token is not None else MAPBOX_ACCESS_TOKEN
    gkey = google_key if google_key is not None else GOOGLE_MAPS_API_KEY
    coerced = _coerce_profile(profile)

    return await asyncio.to_thread(
        _compute_accessible_routes_sync,
        origin,
        destination,
        coerced,
        cv_observations or [],
        token,
        gkey,
    )


__all__ = [
    "AccessibleRoute",
    "AccessibleRoutesResult",
    "ConfigurationError",
    "DestinationPlace",
    "NoRouteError",
    "SteepSection",
    "compute_accessible_routes",
    "latlng_pairs_to_geojson",
    "score_real_route",
]
