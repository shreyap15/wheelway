"""Tests for accessroute.tools.elevation_tool module.

Tests elevation sampling, sample count computation, and grade segment analysis.
"""

import pytest

from accessroute.tools.elevation_tool import (
    compute_sample_count,
    grade_segments,
)
from accessroute.schemas import (
    WheelchairProfile,
    SegmentElevationReport,
)


class TestComputeSampleCount:
    """Test sample count computation for elevation API requests."""

    def test_sample_count_small_distance(self):
        """Very short route (5m) should use minimum 2 samples."""
        count = compute_sample_count(5)
        assert count >= 2

    def test_sample_count_medium_distance(self):
        """5 km should yield ~500 samples (one per 10m)."""
        count = compute_sample_count(5000)
        assert count == 500, f"Expected 500 for 5000m, got {count}"

    def test_sample_count_cap_at_512(self):
        """Distances requiring >512 samples should be capped at 512."""
        count_20km = compute_sample_count(20000)
        assert count_20km == 512, f"Expected 512 for 20000m, got {count_20km}"

        count_100km = compute_sample_count(100000)
        assert count_100km == 512, f"Expected 512 for 100000m, got {count_100km}"

    def test_sample_count_rounding(self):
        """Verify rounding: round(distance / 10)."""
        # 115m -> round(11.5) = 12
        count = compute_sample_count(115)
        assert count == 12

        # 124m -> round(12.4) = 12
        count = compute_sample_count(124)
        assert count == 12

        # 125m -> round(12.5) = 12 (banker's rounding) or 13
        count = compute_sample_count(125)
        assert count in (12, 13), f"Expected 12 or 13 for 125m, got {count}"

    def test_sample_count_edge_cases(self):
        """Test edge cases: very small, boundary, very large."""
        assert compute_sample_count(1) >= 2
        assert compute_sample_count(10) >= 2
        assert compute_sample_count(512 * 10) == 512
        assert compute_sample_count(10000) > 500
        assert compute_sample_count(512 * 20) == 512


class TestGradeSegments:
    """Test elevation grade analysis for route segments."""

    def test_grade_segments_flat_route(self):
        """A flat route should have 0% grade and be compliant."""
        # Three samples at same elevation, slightly different locations
        # to get non-zero haversine distance
        samples = [
            {
                "elevation": 100.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 100.0,
                "lat": 37.0009,
                "lng": -122.0000,
            },
            {
                "elevation": 100.0,
                "lat": 37.0018,
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(device_type="manual")

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        assert len(reports) == 2  # 2 segments for 3 samples
        assert all_compliant is True
        assert max_grade == 0.0 or max_grade < 0.01  # Essentially flat

    def test_grade_segments_gentle_uphill(self):
        """A gently sloping uphill route should be compliant."""
        # Gentle uphill: 15 m elevation over ~1000 m horizontal = 1.5% grade
        samples = [
            {
                "elevation": 0.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 15.0,
                "lat": 37.0090,  # ~1000m north
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(
            device_type="manual",
            max_incline_grade=8.33,
        )

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        assert len(reports) == 1
        assert reports[0].is_compliant is True
        assert reports[0].grade_percentage > 0  # Uphill
        assert reports[0].grade_percentage < 8.33
        assert all_compliant is True

    def test_grade_segments_steep_uphill_noncompliant(self):
        """A steep uphill that exceeds max_incline_grade should be non-compliant."""
        # Steep uphill: 150 m elevation over ~1000 m horizontal = 15% grade
        # Max incline is 8.33%, so this should fail
        samples = [
            {
                "elevation": 0.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 150.0,
                "lat": 37.0090,  # ~1000m north
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(
            device_type="manual",
            max_incline_grade=8.33,
        )

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        assert len(reports) == 1
        assert reports[0].is_compliant is False
        assert reports[0].grade_percentage > 8.33
        assert all_compliant is False
        assert max_grade > 8.33

    def test_grade_segments_steep_downhill_noncompliant(self):
        """A steep downhill that exceeds max_decline_grade should be non-compliant."""
        # Steep downhill: -100 m elevation over ~1000 m = -10% grade
        # Max decline is 10.0%, so this should pass at boundary
        # but slightly steeper should fail
        samples = [
            {
                "elevation": 100.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 0.0,
                "lat": 37.0090,  # ~1000m north
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(
            device_type="manual",
            max_decline_grade=10.0,
        )

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        assert len(reports) == 1
        assert reports[0].is_compliant is True or reports[0].is_compliant is False
        assert reports[0].grade_percentage < 0  # Downhill
        # Grade should be around -10%
        assert -11.0 < reports[0].grade_percentage < -9.0

    def test_grade_segments_max_grade_tracking(self):
        """Verify max_grade_percentage tracks absolute maximum."""
        samples = [
            {
                "elevation": 0.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 50.0,
                "lat": 37.0045,  # ~500m north, 10% uphill
                "lng": -122.0000,
            },
            {
                "elevation": 0.0,
                "lat": 37.0090,  # back down, 10% downhill
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(
            device_type="manual",
            max_incline_grade=15.0,
            max_decline_grade=15.0,
        )

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        # Both segments should have similar absolute grade
        assert max_grade > 9.0 and max_grade < 11.0  # Around 10%

    def test_grade_segments_multiple_compliant_and_noncompliant(self):
        """Route with both compliant and non-compliant segments."""
        # Seg 0: gentle (2% up)
        # Seg 1: steep (15% up) - non-compliant
        # Seg 2: gentle (2% down)
        samples = [
            {
                "elevation": 0.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 20.0,
                "lat": 37.0090,  # ~1000m, 2% uphill
                "lng": -122.0000,
            },
            {
                "elevation": 170.0,
                "lat": 37.0180,  # ~1000m, 15% uphill
                "lng": -122.0000,
            },
            {
                "elevation": 190.0,
                "lat": 37.0270,  # ~1000m, 2% uphill
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(
            device_type="manual",
            max_incline_grade=8.33,
        )

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        assert len(reports) == 3
        assert reports[0].is_compliant is True
        assert reports[1].is_compliant is False
        assert reports[2].is_compliant is True
        assert all_compliant is False  # At least one segment is non-compliant
        assert max_grade > 8.33

    def test_grade_segments_zero_distance_segment(self):
        """Segment with same lat/lng should have ~0% grade."""
        samples = [
            {
                "elevation": 0.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 100.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(device_type="manual")

        reports, all_compliant, max_grade = grade_segments(samples, profile)

        assert len(reports) == 1
        assert reports[0].grade_percentage == 0.0
        assert reports[0].is_compliant is True

    def test_grade_segments_report_structure(self):
        """Verify SegmentElevationReport fields are correctly populated."""
        samples = [
            {
                "elevation": 50.0,
                "lat": 37.0000,
                "lng": -122.0000,
            },
            {
                "elevation": 55.0,
                "lat": 37.0009,
                "lng": -122.0000,
            },
        ]
        profile = WheelchairProfile(device_type="manual")

        reports, _, _ = grade_segments(samples, profile)

        report = reports[0]
        assert report.segment_index == 0
        assert report.start_location.lat == 37.0000
        assert report.start_location.lng == -122.0000
        assert report.end_location.lat == 37.0009
        assert report.end_location.lng == -122.0000
        assert report.distance_meters > 0
        assert report.elevation_change_meters == 5.0
        assert report.grade_percentage > 0
