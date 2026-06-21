from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

EARTH_RADIUS_M = 6_371_000.0
MAPBOX_BASE_URL = "https://api.mapbox.com"
MAX_DIRECTIONS_WAYPOINTS = 25
MAX_MATCHING_COORDINATES = 100

PROFILE_ALIASES = {
    "pedestrian": "walking",
    "sidewalk": "walking",
    "walk": "walking",
    "walking": "walking",
    "vehicle": "driving",
    "car": "driving",
    "driving": "driving",
    "bicycle": "cycling",
    "bike": "cycling",
    "cycling": "cycling",
}


def _finite_number(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _first_present(values: list[Any]) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_profile(profile: str | None) -> str:
    return PROFILE_ALIASES.get((profile or "walking").lower(), "walking")


def _point(coordinate: list[float] | tuple[float, ...] | dict[str, Any]) -> dict[str, float | None]:
    if isinstance(coordinate, dict):
        elevation = _first_present([
            coordinate.get("elevationM"),
            coordinate.get("elevation_m"),
            coordinate.get("elevation"),
        ])
        return {
            "longitude": _finite_number(
                _first_present([
                    coordinate.get("longitude"),
                    coordinate.get("lng"),
                    coordinate.get("lon"),
                ])
            ),
            "latitude": _finite_number(
                _first_present([coordinate.get("latitude"), coordinate.get("lat")])
            ),
            "elevation_m": None if elevation is None else _finite_number(elevation),
        }

    elevation = coordinate[2] if len(coordinate) > 2 else None
    return {
        "longitude": _finite_number(coordinate[0]),
        "latitude": _finite_number(coordinate[1]),
        "elevation_m": None if elevation is None else _finite_number(elevation),
    }


def _haversine_m(a: dict[str, float | None], b: dict[str, float | None]) -> float:
    lat1 = math.radians(float(a["latitude"]))
    lat2 = math.radians(float(b["latitude"]))
    dlat = math.radians(float(b["latitude"]) - float(a["latitude"]))
    dlon = math.radians(float(b["longitude"]) - float(a["longitude"]))
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _cumulative_distances(points: list[dict[str, float | None]]) -> list[float]:
    distances = [0.0]
    for index in range(1, len(points)):
        distances.append(distances[index - 1] + _haversine_m(points[index - 1], points[index]))
    return distances


def _interpolate_elevation(
    points: list[dict[str, float | None]],
    distances: list[float],
    distance_m: float,
) -> float:
    if not points:
        return 0.0

    if len(points) == 1 or distance_m <= 0:
        return float(points[0]["elevation_m"] or 0.0)

    if distance_m >= distances[-1]:
        return float(points[-1]["elevation_m"] or points[0]["elevation_m"] or 0.0)

    for index in range(1, len(distances)):
        if distance_m > distances[index]:
            continue

        start = points[index - 1]
        end = points[index]
        start_elevation = float(start["elevation_m"] if start["elevation_m"] is not None else end["elevation_m"] or 0.0)
        end_elevation = float(end["elevation_m"] if end["elevation_m"] is not None else start_elevation)
        span_m = distances[index] - distances[index - 1]
        ratio = 0.0 if span_m == 0 else (distance_m - distances[index - 1]) / span_m
        return start_elevation + (end_elevation - start_elevation) * ratio

    return float(points[-1]["elevation_m"] or points[0]["elevation_m"] or 0.0)


def _coordinates_param(points: list[dict[str, float | None]]) -> str:
    return ";".join(
        f"{float(point['longitude']):.7f},{float(point['latitude']):.7f}"
        for point in points
    )


def _request_mapbox_geometry(
    points: list[dict[str, float | None]],
    *,
    access_token: str,
    profile: str,
    mode: str,
    timeout_s: float,
    use_intermediate_waypoints: bool,
) -> dict[str, Any]:
    endpoint = "matching" if mode == "matching" else "directions"
    max_points = MAX_MATCHING_COORDINATES if endpoint == "matching" else MAX_DIRECTIONS_WAYPOINTS
    request_source_points = (
        points
        if endpoint == "matching" or use_intermediate_waypoints
        else [points[0], points[-1]]
    )
    request_points = request_source_points[:max_points]
    query = {
        "access_token": access_token,
        "geometries": "geojson",
        "overview": "full",
        "steps": "false",
    }

    if endpoint == "directions":
        query["alternatives"] = "false"

    url = (
        f"{MAPBOX_BASE_URL}/{endpoint}/v5/mapbox/{_normalize_profile(profile)}/"
        f"{_coordinates_param(request_points)}?{urlencode(query)}"
    )

    try:
        with urlopen(url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
        raise RuntimeError(payload.get("message") or f"Mapbox {endpoint} failed ({error.code})") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Mapbox {endpoint} request failed: {error}") from error

    candidate = (payload.get("matchings") or [None])[0] if endpoint == "matching" else (payload.get("routes") or [None])[0]
    coordinates = ((candidate or {}).get("geometry") or {}).get("coordinates")

    if not coordinates or len(coordinates) < 2:
        raise RuntimeError(f"Mapbox {endpoint} response did not include a LineString")

    return {
        "coordinates": coordinates,
        "distance_m": (candidate or {}).get("distance"),
        "duration_s": (candidate or {}).get("duration"),
    }


def _add_interpolated_z(
    coordinates: list[list[float] | tuple[float, ...]],
    source_points: list[dict[str, float | None]],
) -> list[list[float]]:
    snapped_points = [_point(coordinate) for coordinate in coordinates]
    snapped_distances = _cumulative_distances(snapped_points)
    source_distances = _cumulative_distances(source_points)
    snapped_total_m = snapped_distances[-1] if snapped_distances else 0.0
    source_total_m = source_distances[-1] if source_distances else 0.0
    result = []

    for index, point in enumerate(snapped_points):
        normalized_distance_m = (
            0.0
            if snapped_total_m == 0
            else snapped_distances[index] / snapped_total_m * source_total_m
        )
        result.append([
            float(point["longitude"]),
            float(point["latitude"]),
            _interpolate_elevation(source_points, source_distances, normalized_distance_m),
        ])

    return result


def _segment_length_m(coordinates: list[list[float]]) -> float:
    points = [_point(coordinate) for coordinate in coordinates]
    return sum(_haversine_m(points[index - 1], points[index]) for index in range(1, len(points)))


def _segment_source_coordinates(segment: dict[str, Any]) -> list[Any]:
    return (
        ((segment.get("geometry") or {}).get("coordinates"))
        or segment.get("coordinates")
        or []
    )


def snap_segments_to_streets(
    segments: list[dict[str, Any]],
    *,
    access_token: str | None = None,
    profile: str = "walking",
    mode: str = "directions",
    timeout_s: float = 8.0,
    strict: bool = False,
    use_intermediate_waypoints: bool = False,
) -> list[dict[str, Any]]:
    token = access_token or os.getenv("MAPBOX_ACCESS_TOKEN")
    snapped_segments: list[dict[str, Any]] = []
    cumulative_distance_m = 0.0

    for segment in segments:
        enriched = deepcopy(segment)
        source_points = [_point(coordinate) for coordinate in _segment_source_coordinates(segment)]

        if len(source_points) < 2:
            enriched["coordinates"] = []
            enriched["snapping"] = {
                "snapped": False,
                "reason": "segment has fewer than two coordinates",
            }
            snapped_segments.append(enriched)
            continue

        try:
            if token:
                snapped = _request_mapbox_geometry(
                    source_points,
                    access_token=token,
                    profile=profile,
                    mode=mode,
                    timeout_s=timeout_s,
                    use_intermediate_waypoints=use_intermediate_waypoints,
                )
                coordinates = _add_interpolated_z(snapped["coordinates"], source_points)
                metadata = {
                    "snapped": True,
                    "mode": mode,
                    "profile": _normalize_profile(profile),
                    "sourceCoordinateCount": len(source_points),
                    "snappedCoordinateCount": len(coordinates),
                    "distanceM": snapped["distance_m"],
                    "durationS": snapped["duration_s"],
                }
            else:
                coordinates = _add_interpolated_z(
                    [[point["longitude"], point["latitude"]] for point in source_points],
                    source_points,
                )
                metadata = {
                    "snapped": False,
                    "mode": mode,
                    "profile": _normalize_profile(profile),
                    "sourceCoordinateCount": len(source_points),
                    "snappedCoordinateCount": len(coordinates),
                    "reason": "MAPBOX_ACCESS_TOKEN is not configured",
                }
        except RuntimeError as error:
            if strict:
                raise

            coordinates = _add_interpolated_z(
                [[point["longitude"], point["latitude"]] for point in source_points],
                source_points,
            )
            metadata = {
                "snapped": False,
                "mode": mode,
                "profile": _normalize_profile(profile),
                "sourceCoordinateCount": len(source_points),
                "snappedCoordinateCount": len(coordinates),
                "error": str(error),
            }

        length_m = _segment_length_m(coordinates)
        cumulative_distance_m += length_m
        enriched["id"] = enriched.get("id") or enriched.get("segment_id")
        enriched["coordinates"] = coordinates
        enriched["geometry"] = {
            "type": "LineString",
            "coordinates": coordinates,
        }
        enriched["accessibilityScore"] = enriched.get("accessibilityScore", enriched.get("accessibility_score", 100.0))
        enriched["runningSlopePct"] = enriched.get("runningSlopePct", enriched.get("slope", 0.0))
        enriched["crossSlopePct"] = enriched.get("crossSlopePct", enriched.get("cross_slope", 0.0))
        enriched["type"] = enriched.get("type") or ("curb_no_ramp" if enriched.get("has_obstruction") else "sidewalk")
        enriched["length_m"] = length_m
        enriched["cumulative_distance_m"] = cumulative_distance_m
        enriched["snapping"] = metadata
        snapped_segments.append(enriched)

    return snapped_segments
