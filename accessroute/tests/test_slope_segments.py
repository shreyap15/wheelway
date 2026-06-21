"""Tests for the canonical ``slope_segments`` builder (elevation_tool).

Covers grouping of adjacent grade samples, GeoJSON coordinate order, signed
uphill/downhill preservation, user-specific ``exceeds_user_limit``, and the
empty result when no elevation data is available. All inputs are synthetic --
no live Google Elevation calls.
"""

from accessroute.schemas import LatLng, SegmentElevationReport
from accessroute.tools.elevation_tool import (
    build_slope_segments,
    classify_grade,
)


def _build(grades, dists=None, base_elev=100.0, base_lat=37.0, base_lng=-122.0):
    """Build matching (samples, reports) for a list of signed grades (%).

    Each segment advances ~``dist`` meters north so haversine distance and the
    elevation deltas are internally consistent with ``grade_percentage``.
    """
    if dists is None:
        dists = [100.0] * len(grades)

    samples = [{"lat": base_lat, "lng": base_lng, "elevation": base_elev}]
    reports = []
    lat, elev = base_lat, base_elev
    for i, (g, d) in enumerate(zip(grades, dists)):
        nlat = lat + d * 0.000009  # ~ d meters north
        nelev = elev + g * d / 100.0
        a = samples[-1]
        b = {"lat": nlat, "lng": base_lng, "elevation": nelev}
        samples.append(b)
        reports.append(
            SegmentElevationReport(
                segment_index=i,
                start_location=LatLng(lat=a["lat"], lng=a["lng"]),
                end_location=LatLng(lat=b["lat"], lng=b["lng"]),
                distance_meters=d,
                elevation_change_meters=nelev - elev,
                grade_percentage=g,
                is_compliant=True,
            )
        )
        lat, elev = nlat, nelev
    return samples, reports


class TestClassifyGrade:
    def test_bands(self):
        assert classify_grade(0.0, 8.33) == "low"
        assert classify_grade(2.9, 8.33) == "low"
        assert classify_grade(3.0, 8.33) == "moderate"
        assert classify_grade(4.9, 8.33) == "moderate"
        assert classify_grade(5.0, 8.33) == "challenging"
        assert classify_grade(8.33, 8.33) == "challenging"  # inclusive of max
        assert classify_grade(8.4, 8.33) == "exceeds_limit"

    def test_exceeds_checked_first_when_limit_below_five(self):
        # User limit 4% -> a 4.5% grade exceeds even though abs<5.
        assert classify_grade(4.5, 4.0) == "exceeds_limit"
        assert classify_grade(3.5, 4.0) == "moderate"


class TestBuildSlopeSegments:
    def test_geojson_coordinate_order_is_lng_lat(self):
        samples, reports = _build([2.0], base_lat=37.5, base_lng=-122.25)
        sections = build_slope_segments(samples, reports, 8.33)
        assert len(sections) == 1
        coords = sections[0]["geometry"]["coordinates"]
        assert sections[0]["geometry"]["type"] == "LineString"
        # Longitude first, latitude second.
        assert coords[0][0] == -122.25
        assert coords[0][1] == 37.5
        for lng, lat in coords:
            assert -180 <= lng <= 180
            assert -90 <= lat <= 90

    def test_groups_adjacent_same_classification(self):
        # low, low, low, moderate, moderate, exceeds  (limit 8.33)
        grades = [1.0, 1.0, 1.0, 4.0, 4.0, 10.0]
        samples, reports = _build(grades)
        sections = build_slope_segments(samples, reports, 8.33)

        assert [s["classification"] for s in sections] == [
            "low",
            "moderate",
            "exceeds_limit",
        ]
        # Indices are into the samples array and are contiguous.
        assert sections[0]["start_index"] == 0 and sections[0]["end_index"] == 3
        assert sections[1]["start_index"] == 3 and sections[1]["end_index"] == 5
        assert sections[2]["start_index"] == 5 and sections[2]["end_index"] == 6
        # The low run merged 3 sample-pairs into a single section.
        assert len(sections[0]["geometry"]["coordinates"]) == 4

    def test_signed_uphill_vs_downhill_preserved(self):
        # uphill moderate, low divider, downhill moderate
        grades = [4.0, 4.0, 1.0, -4.0, -4.0]
        samples, reports = _build(grades)
        sections = build_slope_segments(samples, reports, 8.33)

        assert [s["classification"] for s in sections] == [
            "moderate",
            "low",
            "moderate",
        ]
        assert sections[0]["grade_pct"] > 0  # uphill
        assert sections[2]["grade_pct"] < 0  # downhill
        # Magnitude is reported separately and stays positive.
        assert sections[0]["absolute_grade_pct"] > 0
        assert sections[2]["absolute_grade_pct"] > 0

    def test_exceeds_user_limit_is_user_specific(self):
        grades = [6.0, 6.0]
        samples, reports = _build(grades)

        strict = build_slope_segments(samples, reports, 5.0)
        assert strict[0]["classification"] == "exceeds_limit"
        assert strict[0]["exceeds_user_limit"] is True

        lenient = build_slope_segments(samples, reports, 20.0)
        assert lenient[0]["classification"] == "challenging"
        assert lenient[0]["exceeds_user_limit"] is False

    def test_elevation_endpoints_use_smoothed_samples(self):
        samples, reports = _build([5.0], dists=[100.0], base_elev=200.0)
        sections = build_slope_segments(samples, reports, 8.33)
        assert sections[0]["elevation_start_m"] == 200.0
        assert sections[0]["elevation_end_m"] == 205.0  # +5% over 100m

    def test_empty_when_no_elevation(self):
        assert build_slope_segments([], [], 8.33) == []
        # Fewer than two samples -> no segments, no placeholders.
        assert build_slope_segments([{"lat": 37.0, "lng": -122.0, "elevation": 1.0}], [], 8.33) == []
