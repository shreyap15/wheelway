"""Google Elevation API tool for sampling elevations along a route polyline.

Calls the legacy Elevation API and grades each segment against the user's
wheelchair profile.
"""

import polyline

from accessroute.schemas import LatLng, SegmentElevationReport, WheelchairProfile
from accessroute.common.http import request_with_retry
from accessroute.common.geo import decode_polyline, haversine_meters


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
    return max(2, min(512, round(total_distance_meters / 10)))


def _parse_elevation_response(data: dict) -> list[dict]:
    """Parse a Google Elevation API response into normalized dicts.

    Helper for offline testing. Extracts elevation, lat, lng from results.

    Args:
        data: JSON response dict from the Elevation API.

    Returns:
        List of dicts with keys: ``elevation``, ``lat``, ``lng``.
    """
    results = []
    for result in data.get("results", []):
        location = result.get("location", {})
        results.append({
            "elevation": result.get("elevation"),
            "lat": location.get("lat"),
            "lng": location.get("lng"),
        })
    return results


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

    Chunking strategy: For polylines requiring >512 samples, decode the
    polyline into coordinate tuples, split into consecutive sub-paths,
    re-encode each chunk, and request ≤512 samples per chunk. Concatenate
    results in order.

    Args:
        encoded_polyline: Google-encoded polyline string.
        total_distance_meters: Total route distance for sample count calc.
        api_key: Google Maps API key.

    Returns:
        List of dicts with keys: ``elevation`` (float), ``lat`` (float),
        ``lng`` (float).
    """
    total_samples = compute_sample_count(total_distance_meters)

    from accessroute.common.http import ServiceDegraded

    # If total_samples <= 512, single request
    if total_samples <= 512:
        url = "https://maps.googleapis.com/maps/api/elevation/json"
        params = {
            "path": f"enc:{encoded_polyline}",
            "samples": total_samples,
            "key": api_key,
        }
        resp = request_with_retry("GET", url, params=params)
        if not resp.ok:
            raise ServiceDegraded(
                f"Elevation API HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        return _parse_elevation_response(data)

    # Chunking: decode polyline, split into sub-paths
    coords = decode_polyline(encoded_polyline)
    num_chunks = (total_samples + 511) // 512  # ceiling division
    coords_per_chunk = (len(coords) + num_chunks - 1) // num_chunks

    all_results = []

    for i in range(num_chunks):
        start_idx = i * coords_per_chunk
        end_idx = min(start_idx + coords_per_chunk, len(coords))

        if start_idx >= len(coords):
            break

        chunk_coords = coords[start_idx:end_idx]

        # Re-encode chunk
        chunk_encoded = polyline.encode(chunk_coords)

        # Compute samples for this chunk
        chunk_samples = min(512, max(2, len(chunk_coords)))

        url = "https://maps.googleapis.com/maps/api/elevation/json"
        params = {
            "path": f"enc:{chunk_encoded}",
            "samples": chunk_samples,
            "key": api_key,
        }
        resp = request_with_retry("GET", url, params=params)
        if not resp.ok:
            raise ServiceDegraded(
                f"Elevation API HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        chunk_results = _parse_elevation_response(data)
        all_results.extend(chunk_results)

    return all_results


def smooth_elevation_samples(samples: list[dict], window: int = 5) -> list[dict]:
    """Apply a moving average to elevations to reduce API/GPS noise spikes."""
    if len(samples) <= 2 or window <= 1:
        return samples

    smoothed: list[dict] = []
    half = window // 2
    for i, sample in enumerate(samples):
        chunk = samples[max(0, i - half) : min(len(samples), i + half + 1)]
        avg_elev = sum(point["elevation"] for point in chunk) / len(chunk)
        smoothed.append({**sample, "elevation": avg_elev})
    return smoothed


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
    reports = []
    max_grade = 0.0

    for i in range(len(samples) - 1):
        a = samples[i]
        b = samples[i + 1]

        # Compute horizontal distance
        dist = haversine_meters((a["lat"], a["lng"]), (b["lat"], b["lng"]))

        # Compute elevation change
        elev_change = b["elevation"] - a["elevation"]

        # Compute grade percentage
        if dist > 0:
            grade = (elev_change / dist) * 100
        else:
            grade = 0.0

        # Determine compliance
        if grade > 0:  # Uphill
            is_compliant = grade <= profile.max_incline_grade
        elif grade < 0:  # Downhill
            is_compliant = abs(grade) <= profile.max_decline_grade
        else:  # Flat
            is_compliant = True

        max_grade = max(max_grade, abs(grade))

        # Build report
        report = SegmentElevationReport(
            segment_index=i,
            start_location=LatLng(lat=a["lat"], lng=a["lng"]),
            end_location=LatLng(lat=b["lat"], lng=b["lng"]),
            distance_meters=dist,
            elevation_change_meters=elev_change,
            grade_percentage=grade,
            is_compliant=is_compliant,
        )
        reports.append(report)

    uphill_max = max((report.grade_percentage for report in reports if report.grade_percentage > 0), default=0.0)
    downhill_max = max(
        (abs(report.grade_percentage) for report in reports if report.grade_percentage < 0),
        default=0.0,
    )
    all_compliant = (
        uphill_max <= profile.max_incline_grade
        and downhill_max <= profile.max_decline_grade
    )

    return reports, all_compliant, max_grade
