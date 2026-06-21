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
import logging
from typing import Any, Dict, List, Optional

from pydantic.v1 import BaseModel

from accessroute.common.geo import decode_polyline, haversine_meters
from accessroute.common.http import ServiceDegraded
from accessroute.config import GOOGLE_MAPS_API_KEY, MAPBOX_ACCESS_TOKEN
from accessroute.schemas import LatLng, WheelchairProfile
from accessroute.tools.elevation_tool import (
    build_slope_segments,
    grade_segments,
    sample_elevations,
    smooth_elevation_samples,
)
from accessroute.tools.mapbox_routes_tool import (
    compute_mapbox_route_via,
    compute_mapbox_routes,
)
from accessroute.tools.places_tool import check_destination_accessibility
from accessroute.tools import candidate_discovery, stairs_tool

logger = logging.getLogger(__name__)

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


class SlopeSegment(BaseModel):
    """A merged local slope section for per-segment route coloring.

    Built from the same smoothed elevation samples as ``max_slope_pct`` /
    ``avg_slope_pct`` (never from guessed coordinates). ``grade_pct`` is signed
    (uphill positive, downhill negative); ``classification`` drives the map color.
    """

    geometry: Dict[str, Any]  # GeoJSON LineString, coordinates in [lng, lat]
    start_index: int
    end_index: int
    grade_pct: float
    absolute_grade_pct: float
    elevation_start_m: float
    elevation_end_m: float
    classification: str
    exceeds_user_limit: bool


class StairEvidence(BaseModel):
    """One piece of stair evidence from a single source (never authoritative)."""

    source: str  # mapbox_steps | openstreetmap | camera_cv
    confidence: Optional[float] = None
    matched_term: Optional[str] = None  # Mapbox/CV term
    osm_tag: Optional[str] = None  # e.g. "highway=steps"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_from_route_m: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None


class StairSegment(BaseModel):
    """A route section affected by stair evidence."""

    geometry: Dict[str, Any]  # GeoJSON LineString, coordinates in [lng, lat]
    status: str
    confidence: float
    sources: List[str] = []


class AccessibleRoute(BaseModel):
    route_id: str
    geometry: Dict[str, Any]  # GeoJSON LineString, coordinates in [lng, lat]
    distance_m: float
    duration_s: float
    max_slope_pct: Optional[float] = None
    avg_slope_pct: Optional[float] = None
    steep_sections: List[SteepSection] = []
    slope_segments: List[SlopeSegment] = []
    exceeds_max_slope: Optional[bool] = None
    # Distance-aware slope metrics (None when elevation unavailable). A 2 m spike
    # and a 200 m hill differ here even when max grade is identical.
    exceeds_limit_distance_m: Optional[float] = None
    challenging_distance_m: Optional[float] = None
    exceeds_limit_percentage: Optional[float] = None
    # Accessibility-first ranking outputs.
    accessibility_rank: Optional[int] = None
    recommended: bool = False
    selection_reasons: List[str] = []
    # Canonical multi-source stair verdict (replaces boolean-only behavior).
    stairs_status: str = "unknown"  # unknown|possible|likely|confirmed|not_detected
    stairs_confidence: float = 0.0
    stairs_sources: List[StairEvidence] = []
    stairs_segments: List[StairSegment] = []
    # Dev-only per-source diagnostics (sanitized; no secrets/external bodies).
    stairs_debug: Dict[str, Any] = {}
    # Back-compat: True only when confirmed, False only when not_detected, else null.
    stairs_detected: Optional[bool] = None
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
    # Candidate-generation provenance (Task 1C).
    candidate_generation_method: str = "mapbox_alternatives"
    raw_mapbox_candidate_count: int = 0
    distinct_candidate_count: int = 0
    additional_requests_made: int = 0
    only_one_route_available: bool = False


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


# Stair statuses that count as a violation for a stair-avoiding user.
_STAIR_VIOLATION = {stairs_tool.STATUS_CONFIRMED, stairs_tool.STATUS_LIKELY}


def _segment_length_m(geometry: Dict[str, Any]) -> float:
    """Great-circle length of a GeoJSON LineString ([lng, lat] coords)."""
    coords = (geometry or {}).get("coordinates") or []
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        total += haversine_meters((a[1], a[0]), (b[1], b[0]))
    return total


def slope_distance_metrics(
    slope_segments: List[SlopeSegment], total_distance_m: float
) -> tuple:
    """(exceeds_limit_distance_m, challenging_distance_m, exceeds_limit_percentage).

    Computed from the SAME slope_segments the UI colors -- distance-aware, so a
    brief spike and a long hill are not conflated. Returns (None, None, None)
    when no slope data is available (never fabricated).
    """
    if not slope_segments:
        return None, None, None
    exceed = 0.0
    challenging = 0.0
    for seg in slope_segments:
        length = _segment_length_m(seg.geometry)
        if seg.classification == "exceeds_limit":
            exceed += length
        elif seg.classification == "challenging":
            challenging += length
    pct = round(exceed / total_distance_m * 100, 1) if total_distance_m > 0 else 0.0
    return round(exceed, 1), round(challenging, 1), pct


def _geo_signature(geometry: Dict[str, Any]) -> frozenset:
    """Rounded coordinate set (~11 m) for near-duplicate detection."""
    coords = (geometry or {}).get("coordinates") or []
    return frozenset((round(c[0], 4), round(c[1], 4)) for c in coords)


def _dedup_routes(enriched: List[tuple]) -> List[tuple]:
    """Drop near-identical routes (>=95% coordinate overlap); keep distinct ones."""
    kept: List[tuple] = []
    kept_sigs: List[frozenset] = []
    for item in enriched:
        sig = _geo_signature(item[0].geometry)
        dup = False
        for prev in kept_sigs:
            union = len(sig | prev) or 1
            if len(sig & prev) / union >= 0.95:
                dup = True
                break
        if not dup:
            kept.append(item)
            kept_sigs.append(sig)
    return kept


def _route_sort_key(route: AccessibleRoute, status: str, avoid_stairs: bool) -> tuple:
    """Accessibility-first ordering key (ascending = better).

    Priority: (1) no confirmed/likely stairs, (2) no section over the limit,
    (3) least distance over the limit, (4) lowest max grade, (5) highest score,
    (6) shorter distance, (7) shorter duration.
    """
    stair_violation = 1 if (avoid_stairs and status in _STAIR_VIOLATION) else 0
    exceed_dist = route.exceeds_limit_distance_m or 0.0
    has_exceed = 1 if exceed_dist > 0 else 0
    max_grade = route.max_slope_pct if route.max_slope_pct is not None else 0.0
    score = route.accessibility_score if route.accessibility_score is not None else -1.0
    return (
        stair_violation,
        has_exceed,
        exceed_dist,
        max_grade,
        -score,
        route.distance_m,
        route.duration_s,
    )


def _rank_routes(enriched: List[tuple], avoid_stairs: bool) -> List[AccessibleRoute]:
    """Accessibility-first ranking. Preserves EVERY distinct route (no dropping);
    sets accessibility_rank and recommended. Geometry/slope data untouched."""
    ordered = sorted(
        enriched, key=lambda it: _route_sort_key(it[0], it[1], avoid_stairs)
    )
    routes: List[AccessibleRoute] = []
    for rank, (route, _status) in enumerate(ordered, start=1):
        route.accessibility_rank = rank
        route.recommended = rank == 1
        routes.append(route)
    return routes


def _annotate_selection(
    routes: List[AccessibleRoute],
    *,
    slope_limit: float,
    avoid_stairs: bool,
    single_route: bool,
    warnings: List[str],
    discovered_ids: frozenset = frozenset(),
) -> None:
    """Attach human-facing selection_reasons (and result warnings). Honest:
    never claims ADA compliance; states when no compliant route exists."""
    if not routes:
        return
    rec = routes[0]
    others = routes[1:]
    metrics_known = rec.exceeds_limit_distance_m is not None
    all_exceed = metrics_known and all((r.exceeds_limit_distance_m or 0) > 0 for r in routes)

    reasons: List[str] = []
    if single_route:
        reasons.append(
            "Only one distinct pedestrian route was available from the routing network."
        )
    if rec.route_id in discovered_ids:
        reasons.append(
            "Recommended route takes a longer detour to reduce travel above your "
            "selected slope limit."
        )

    if metrics_known and all_exceed:
        msg = (
            f"No route under your selected {slope_limit}% slope limit was available. "
            "Showing the least steep option."
        )
        if msg not in warnings:
            warnings.append(msg)
        reasons.append(
            f"Least steep option: {rec.exceeds_limit_distance_m:.0f} m above your "
            f"{slope_limit}% limit (lowest of the alternatives)."
        )
    elif metrics_known and (rec.exceeds_limit_distance_m or 0) == 0:
        reason = f"Recommended: avoids slopes above your {slope_limit}% limit"
        red = [r for r in others if (r.exceeds_limit_distance_m or 0) > 0]
        if red:
            shortest_red = min(red, key=lambda r: r.distance_m)
            delta = round(rec.distance_m - shortest_red.distance_m)
            reason += f"; {delta} m longer than the shortest alternative." if delta > 0 else "."
        else:
            reason += "."
        reasons.append(reason)

    if avoid_stairs and rec.stairs_status in _STAIR_VIOLATION:
        reasons.append("Stairs detected on every alternative; none are stair-free.")
    elif avoid_stairs and any(r.stairs_status in _STAIR_VIOLATION for r in others):
        reasons.append("Avoids alternatives with detected stairs.")

    rec.selection_reasons = reasons

    # Per-alternative comparison reasons for the route cards.
    for r in others:
        rr: List[str] = []
        if metrics_known:
            ex = r.exceeds_limit_distance_m or 0
            rr.append(
                f"Includes {ex:.0f} m above your {slope_limit}% limit."
                if ex > 0
                else "Stays under your slope limit."
            )
        dmin = (rec.duration_s - r.duration_s) / 60.0
        if dmin > 0.1:
            rr.append(f"{dmin:.1f} min faster than recommended.")
        elif dmin < -0.1:
            rr.append(f"{abs(dmin):.1f} min slower than recommended.")
        if avoid_stairs and r.stairs_status in _STAIR_VIOLATION:
            rr.append("Stairs detected.")
        r.selection_reasons = rr


# --------------------------------------------------------------------------- #
# Per-candidate enrichment (runs in a worker thread)
# --------------------------------------------------------------------------- #
def _enrich_candidate(
    index: int,
    candidate,
    profile: WheelchairProfile,
    google_key: str,
    cv_observations: Optional[List[Dict[str, Any]]] = None,
    osm_features: Optional[List[dict]] = None,
    osm_available: bool = False,
    osm_error: Optional[str] = None,
) -> tuple:
    """Build one AccessibleRoute. Returns (route, warnings, degraded)."""
    decoded = decode_polyline(candidate.encoded_polyline)  # [(lat, lng), ...]
    geometry = latlng_pairs_to_geojson(decoded)
    # Explicit, independent preference (default True when absent for old payloads).
    avoid_stairs = bool(getattr(profile, "avoid_stairs", True))

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
    slope_segments: List[SlopeSegment] = []
    exceeds_max_slope: Optional[bool] = None
    accessibility_score: Optional[float] = None
    exceeds_limit_distance_m: Optional[float] = None
    challenging_distance_m: Optional[float] = None
    exceeds_limit_percentage: Optional[float] = None

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
            # Local slope sections from the SAME smoothed samples/reports above.
            slope_segments = [
                SlopeSegment(**section)
                for section in build_slope_segments(samples, reports, slope_limit)
            ]
            (
                exceeds_limit_distance_m,
                challenging_distance_m,
                exceeds_limit_percentage,
            ) = slope_distance_metrics(slope_segments, candidate.distance_meters)
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
            sources["slope_segments"] = (
                SRC_ELEVATION if slope_segments else SRC_UNAVAILABLE
            )
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
            sources["slope_segments"] = SRC_UNAVAILABLE
            sources["accessibility_score"] = SRC_UNAVAILABLE
            route_warnings.append(
                "Elevation data unavailable; slope/grade not assessed for this route."
            )
            route_warnings.append(f"Google Elevation API degraded: {exc}")
    else:
        sources["max_slope_pct"] = SRC_UNAVAILABLE
        sources["avg_slope_pct"] = SRC_UNAVAILABLE
        sources["slope_segments"] = SRC_UNAVAILABLE
        sources["accessibility_score"] = SRC_UNAVAILABLE
        route_warnings.append(
            "Elevation enrichment unavailable (no Google Maps key); slope not assessed."
        )

    # ---- Multi-source stair detection (Mapbox text + OSM + CV) ----
    # Each source tracks completion INDEPENDENTLY: "ran" (attempted) vs
    # "completed" (produced a valid result). An empty result is NOT a failure.
    stair_evidence: List[dict] = []
    sources_ran: Dict[str, bool] = {}

    # -- Mapbox steps: completed once the parsed step list is read (even if 0). --
    mb_error: Optional[str] = None
    try:
        mb_ev = stairs_tool.detect_mapbox_step_stairs(getattr(candidate, "steps", []) or [])
        mb_completed = True
    except Exception as exc:  # parsing the step list actually failed
        mb_ev = []
        mb_completed = False
        mb_error = type(exc).__name__
    stair_evidence.extend(mb_ev)
    sources_ran[stairs_tool.SRC_MAPBOX_STEPS] = mb_completed

    # -- Camera CV: an empty observation list still completes with zero evidence.
    #    "data present" is tracked separately from "matching completed". --
    cv_observation_count = len(cv_observations or [])
    cv_error: Optional[str] = None
    try:
        cv_ev = stairs_tool.detect_cv_stairs(cv_observations or [], decoded)
        cv_completed = True
    except Exception as exc:  # local matching actually failed
        cv_ev = []
        cv_completed = False
        cv_error = type(exc).__name__
    stair_evidence.extend(cv_ev)
    sources_ran[stairs_tool.SRC_CV] = cv_completed

    # -- OpenStreetMap: completed iff Overpass returned a valid (possibly empty)
    #    response. Network/HTTP/parse failures -> not completed (+ error). --
    osm_ev: List[dict] = []
    if osm_available:
        osm_ev = stairs_tool.match_osm_to_route(osm_features or [], decoded)
        stair_evidence.extend(osm_ev)
    sources_ran[stairs_tool.SRC_OSM] = osm_available

    stairs_debug = {
        stairs_tool.SRC_MAPBOX_STEPS: {
            "ran": True,
            "completed": mb_completed,
            "evidence_count": len(mb_ev),
            "error": mb_error,
        },
        stairs_tool.SRC_OSM: {
            "ran": True,
            "completed": osm_available,
            "evidence_count": len(osm_ev),
            "error": osm_error,
        },
        stairs_tool.SRC_CV: {
            "ran": True,
            "completed": cv_completed,
            "evidence_count": len(cv_ev),
            "observation_count": cv_observation_count,
            "error": cv_error,
        },
    }
    for src, info in stairs_debug.items():
        logger.info(
            "[stairs] source=%s completed=%s evidence=%d error=%s",
            src,
            info["completed"],
            info["evidence_count"],
            info.get("error"),
        )

    stairs_status, stairs_confidence = stairs_tool.classify_stairs(
        stair_evidence, sources_ran=sources_ran
    )
    stair_segments = [
        StairSegment(**seg)
        for seg in stairs_tool.build_stair_segments(
            stair_evidence, stairs_status, stairs_confidence
        )
    ]
    stairs_sources = [StairEvidence(**e) for e in stair_evidence]
    # Honest boolean: only assert presence/absence when actually established.
    if stairs_status == stairs_tool.STATUS_CONFIRMED:
        stairs_detected = True
    elif stairs_status == stairs_tool.STATUS_NOT_DETECTED:
        stairs_detected = False
    else:
        stairs_detected = None

    matched_src = sorted({e["source"] for e in stair_evidence})
    sources["stairs_detection"] = "+".join(matched_src) if matched_src else "+".join(
        s for s, ok in sources_ran.items() if ok
    )

    if stairs_status == stairs_tool.STATUS_CONFIRMED:
        route_warnings.append(
            f"Confirmed stairs detected on this route ({', '.join(matched_src)})."
        )
    elif stairs_status == stairs_tool.STATUS_LIKELY:
        route_warnings.append("Likely stairs based on OpenStreetMap data.")
    elif stairs_status == stairs_tool.STATUS_POSSIBLE:
        route_warnings.append("Possible stairs mentioned in route instructions.")
    elif stairs_status == stairs_tool.STATUS_UNKNOWN:
        route_warnings.append(
            "Stair status unknown for this route; some detection sources were unavailable."
        )

    # NOTE: stairs are handled by accessibility-first ranking (_route_sort_key),
    # not by mutating the slope-only accessibility_score, so the score stays an
    # honest gradient measure.

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
        slope_segments=slope_segments,
        exceeds_max_slope=exceeds_max_slope,
        exceeds_limit_distance_m=exceeds_limit_distance_m,
        challenging_distance_m=challenging_distance_m,
        exceeds_limit_percentage=exceeds_limit_percentage,
        stairs_status=stairs_status,
        stairs_confidence=stairs_confidence,
        stairs_sources=stairs_sources,
        stairs_segments=stair_segments,
        stairs_debug=stairs_debug,
        stairs_detected=stairs_detected,
        accessibility_score=accessibility_score,
        accessibility_warnings=route_warnings,
        explanation=explanation,
        sources=sources,
    )
    return route, route_warnings, degraded, stairs_status


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

    # ---- OpenStreetMap stair corridor: ONE Overpass call covering every
    #      alternative's bbox (independent optional enrichment; explicit timeout;
    #      cached; never blocks the Mapbox geometry). ----
    union_coords: List[tuple] = []
    for c in candidates:
        union_coords.extend(decode_polyline(c.encoded_polyline))
    osm_features, osm_available, osm_error = stairs_tool.query_overpass_stairs(union_coords)
    if not osm_available:
        logger.info("[stairs] source=openstreetmap completed=false error=%s", osm_error)
        warnings.append(
            "OpenStreetMap stair data unavailable; stair status may be unknown for some routes."
        )

    avoid_stairs = bool(getattr(profile, "avoid_stairs", True))

    def _enrich(idx: int, cand) -> tuple:
        route, route_warnings, degraded, status = _enrich_candidate(
            idx,
            cand,
            profile,
            google_key,
            cv_observations=cv_observations,
            osm_features=osm_features,
            osm_available=osm_available,
            osm_error=osm_error,
        )
        nonlocal service_degraded
        if degraded:
            service_degraded = True
            warnings.extend(
                w for w in route_warnings if w.startswith("Google Elevation API degraded")
            )
        return route, status

    raw_count = len(candidates)
    enriched: List[tuple] = [_enrich(i, c) for i, c in enumerate(candidates)]

    # Preserve every distinct route; only collapse near-identical duplicates.
    distinct_primary = _dedup_routes(enriched)

    # ---- Controlled alternative discovery when Mapbox gave < 2 distinct routes.
    additional_requests = 0
    generation_method = "mapbox_alternatives"
    if len(distinct_primary) < 2:
        best_route = distinct_primary[0][0]
        best_decoded = [
            (c[1], c[0]) for c in best_route.geometry.get("coordinates", [])
        ]
        existing_sigs = [
            candidate_discovery.signature(
                [(c[1], c[0]) for c in r.geometry.get("coordinates", [])]
            )
            for r, _ in enriched
        ]
        try:
            new_cands, additional_requests = candidate_discovery.discover_additional_candidates(
                origin,
                destination,
                best_decoded,
                best_route.slope_segments,
                existing_signatures=existing_sigs,
                baseline_distance_m=best_route.distance_m,
                route_fn=lambda o, w, d: compute_mapbox_route_via(
                    o, w, d, access_token=mapbox_token
                ),
            )
        except Exception as exc:  # discovery is best-effort; never block the route
            logger.info("[candidates] discovery_error=%s", type(exc).__name__)
            new_cands = []
        for j, cand in enumerate(new_cands):
            enriched.append(_enrich(raw_count + j, cand))
        if new_cands:
            generation_method = "mapbox_alternatives+waypoint_discovery"

    # Final dedup over primary + discovered, then accessibility-first ranking.
    distinct = _dedup_routes(enriched)
    single_route = len(distinct) == 1
    if single_route and additional_requests == 0:
        generation_method = "single_route"
    logger.info(
        "[candidates] raw=%d distinct=%d additional_requests=%d method=%s",
        raw_count,
        len(distinct),
        additional_requests,
        generation_method,
    )

    discovered_ids = frozenset(r.route_id for r, _ in enriched[raw_count:])
    routes = _rank_routes(distinct, avoid_stairs)
    _annotate_selection(
        routes,
        slope_limit=_max_slope_limit(profile),
        avoid_stairs=avoid_stairs,
        single_route=single_route,
        warnings=warnings,
        discovered_ids=discovered_ids,
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
        "slope_segments": SRC_ELEVATION if google_key else SRC_UNAVAILABLE,
        "accessibility_score": SRC_SCORING if google_key else SRC_UNAVAILABLE,
        "destination_place": destination_place.source,
        "stairs_detection": "+".join(
            ["mapbox_steps", "camera_cv"] + (["openstreetmap"] if osm_available else [])
        ),
        # Real-route mode CANNOT measure these -> explicitly unavailable (never
        # scored as if measured).
        "path_width": SRC_UNAVAILABLE,
        "cross_slope": SRC_UNAVAILABLE,
        "curb_ramps": SRC_UNAVAILABLE,
        "surface_condition": SRC_UNAVAILABLE,
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
        candidate_generation_method=generation_method,
        raw_mapbox_candidate_count=raw_count,
        distinct_candidate_count=len(distinct),
        additional_requests_made=additional_requests,
        only_one_route_available=single_route,
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
    "SlopeSegment",
    "StairEvidence",
    "StairSegment",
    "SteepSection",
    "compute_accessible_routes",
    "latlng_pairs_to_geojson",
    "score_real_route",
]
