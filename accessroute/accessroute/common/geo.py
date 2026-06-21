"""Geographic utility functions for the accessroute system.

Provides polyline decoding and great-circle distance calculations.
"""

import math

import polyline as _polyline


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google-encoded polyline string into coordinate pairs.

    Uses the ``polyline`` package (precision 5, the Google standard).

    Args:
        encoded: An encoded polyline string (e.g. from Google Routes API
                 ``routes[i].polyline.encodedPolyline``).

    Returns:
        A list of (lat, lng) tuples.
    """
    return _polyline.decode(encoded)


def encode_polyline(coordinates: list[tuple[float, float]]) -> str:
    """Encode (lat, lng) coordinate pairs into a Google-standard polyline string."""
    return _polyline.encode(coordinates)


def geojson_linestring_to_latlng(
    coordinates: list[list[float] | tuple[float, ...]],
) -> list[tuple[float, float]]:
    """Convert GeoJSON [lng, lat] coordinates to (lat, lng) tuples."""
    return [(float(point[1]), float(point[0])) for point in coordinates]


def haversine_meters(
    a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Compute the great-circle distance in meters between two points.

    Args:
        a: (lat, lng) of the first point in decimal degrees.
        b: (lat, lng) of the second point in decimal degrees.

    Returns:
        Distance in meters.
    """
    R = 6_371_000.0  # Earth's mean radius in meters

    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])

    dlat = lat2 - lat1
    dlng = lng2 - lng1

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(h))
