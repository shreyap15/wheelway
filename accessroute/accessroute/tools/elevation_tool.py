"""Google Elevation API tool for sampling elevations along a route polyline.

Calls the legacy Elevation API and grades each segment against the user's
wheelchair profile.
"""

from accessroute.schemas import SegmentElevationReport, WheelchairProfile


def compute_sample_count(total_distance_meters: float) -> int:
    """Compute the number of elevation samples to request.

    Rule: one sample every ~10 meters, rounded, capped at 512
    (the Elevation API's per-request maximum).

    For routes longer than 5120m the caller must chunk into multiple
    requests of at most 512 samples each.

    Args:
        total_distance_meters: Total route distance in meters.

    Returns:
        Number of samples (1..512).
    """
    raise NotImplementedError("compute_sample_count: to be implemented by elevation-agent builder")


def sample_elevations(
    encoded_polyline: str,
    total_distance_meters: float,
    *,
    api_key: str,
) -> list[dict]:
    """Fetch elevation samples along an encoded polyline.

    Endpoint: GET https://maps.googleapis.com/maps/api/elevation/json
    Query params:
        - key=<api_key>  (legacy key= query parameter)
        - path=enc:<encoded_polyline>
        - samples=<int>  (from compute_sample_count, MAX 512 per request)

    For routes requiring more than 512 samples, the implementation MUST
    chunk the polyline into sub-segments and issue multiple requests,
    each with at most 512 samples.

    Response: ``results[].elevation`` (float, meters above sea level)
              ``results[].location.lat``, ``results[].location.lng``

    Uses ``accessroute.common.http.request_with_retry`` for resilient calls.

    Args:
        encoded_polyline: Google-encoded polyline string.
        total_distance_meters: Total route distance for sample count calc.
        api_key: Google Maps API key.

    Returns:
        List of dicts with keys: ``elevation`` (float), ``lat`` (float),
        ``lng`` (float).
    """
    raise NotImplementedError("sample_elevations: to be implemented by elevation-agent builder")


def grade_segments(
    samples: list[dict],
    profile: WheelchairProfile,
) -> tuple[list[SegmentElevationReport], bool, float]:
    """Compute grade for each consecutive pair of elevation samples.

    Grade formula:
        grade_pct = (elevation_change / horizontal_distance) * 100

    Horizontal distance between consecutive samples is computed via
    ``accessroute.common.geo.haversine_meters``.

    A segment is compliant if:
        - Uphill grade <= profile.max_incline_grade
        - Downhill grade <= profile.max_decline_grade

    The route is compliant if ALL segments are compliant.

    Args:
        samples: List of dicts with ``elevation``, ``lat``, ``lng``.
        profile: The user's wheelchair profile with grade limits.

    Returns:
        Tuple of:
            - List of SegmentElevationReport objects.
            - bool: True if the entire route is compliant.
            - float: Maximum absolute grade percentage found.
    """
    raise NotImplementedError("grade_segments: to be implemented by elevation-agent builder")
