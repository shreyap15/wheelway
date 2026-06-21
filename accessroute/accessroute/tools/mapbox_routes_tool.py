"""Mapbox Directions API tool for fetching walking route candidates.

Generates route geometry using Mapbox's walking profile and encodes paths as
Google-standard polylines so downstream Google Elevation sampling works unchanged.
"""

from __future__ import annotations

from accessroute.common.geo import encode_polyline, geojson_linestring_to_latlng
from accessroute.common.http import ServiceDegraded, request_with_retry
from accessroute.schemas import LatLng, RouteCandidate

MAPBOX_BASE_URL = "https://api.mapbox.com"
PROFILE_ALIASES = {
    "pedestrian": "walking",
    "sidewalk": "walking",
    "walk": "walking",
    "walking": "walking",
    "foot": "walking",
    "WALK": "walking",
}


def _normalize_profile(travel_mode: str | None) -> str:
    return PROFILE_ALIASES.get((travel_mode or "walking").upper(), "walking")


def _coordinates_param(origin: LatLng, destination: LatLng) -> str:
    return (
        f"{origin.lng:.7f},{origin.lat:.7f};"
        f"{destination.lng:.7f},{destination.lat:.7f}"
    )


def _parse_mapbox_routes(payload: dict, travel_mode: str) -> list[RouteCandidate]:
    routes = payload.get("routes") or []
    candidates: list[RouteCandidate] = []

    for route_index, route in enumerate(routes):
        geometry = route.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            continue

        latlng_coords = geojson_linestring_to_latlng(coordinates)
        encoded_polyline = encode_polyline(latlng_coords)
        distance_meters = float(route.get("distance") or 0.0)
        duration_seconds = float(route.get("duration") or 0.0)

        num_steps = 0
        for leg in route.get("legs") or []:
            num_steps += len(leg.get("steps") or [])

        candidates.append(
            RouteCandidate(
                route_index=route_index,
                encoded_polyline=encoded_polyline,
                distance_meters=distance_meters,
                duration_seconds=duration_seconds,
                num_steps=num_steps,
                travel_mode=travel_mode,
            )
        )

    return candidates


def compute_mapbox_routes(
    origin: LatLng,
    destination: LatLng,
    *,
    access_token: str,
    travel_mode: str = "WALK",
    alternatives: bool = True,
    timeout: int = 30,
) -> list[RouteCandidate]:
    """Fetch walking route candidates from the Mapbox Directions API.

    Uses ``mapbox/walking`` (foot profile) with GeoJSON geometry, then encodes
    each route as a Google-standard polyline for elevation sampling.
    """
    if not access_token:
        raise ServiceDegraded("MAPBOX_ACCESS_TOKEN is not configured")

    profile = _normalize_profile(travel_mode)
    url = (
        f"{MAPBOX_BASE_URL}/directions/v5/mapbox/{profile}/"
        f"{_coordinates_param(origin, destination)}"
    )
    params = {
        "access_token": access_token,
        "geometries": "geojson",
        "overview": "full",
        "steps": "true",
        "alternatives": "true" if alternatives else "false",
    }

    resp = request_with_retry("GET", url, params=params, timeout=timeout)
    if not resp.ok:
        raise ServiceDegraded(
            f"Mapbox Directions HTTP {resp.status_code}: {resp.text[:200]}"
        )

    payload = resp.json()
    if payload.get("code") not in (None, "Ok"):
        message = payload.get("message") or payload.get("code") or "unknown Mapbox error"
        raise ServiceDegraded(f"Mapbox Directions failed: {message}")

    candidates = _parse_mapbox_routes(payload, travel_mode=travel_mode)
    if not candidates:
        raise ServiceDegraded("Mapbox Directions returned no usable route geometry")

    return candidates
