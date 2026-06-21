"""Tests for accessroute.schemas module.

Tests that all frozen schema Models can be constructed, have correct defaults,
and support round-trip serialization via .dict() / .parse_obj().
"""

import pytest

from accessroute.schemas import (
    LatLng,
    WheelchairProfile,
    RouteEvaluationRequest,
    SegmentElevationReport,
    RouteCandidate,
    RouteCandidates,
    ElevationCheckRequest,
    ElevationVerdict,
    AccessibilityCheckRequest,
    AccessibilityVerdict,
    FinalRoute,
)


class TestLatLng:
    """Test LatLng model construction and serialization."""

    def test_construct_basic(self):
        """Construct a LatLng with required fields."""
        loc = LatLng(lat=37.7749, lng=-122.4194)
        assert loc.lat == 37.7749
        assert loc.lng == -122.4194

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization via .dict() and .parse_obj()."""
        original = LatLng(lat=40.7128, lng=-74.0060)
        d = original.dict()
        restored = LatLng.parse_obj(d)

        assert restored.lat == original.lat
        assert restored.lng == original.lng


class TestWheelchairProfile:
    """Test WheelchairProfile model with defaults."""

    def test_construct_minimal(self):
        """Construct with only required device_type field."""
        profile = WheelchairProfile(device_type="manual")
        assert profile.device_type == "manual"
        assert profile.max_width_cm == 75
        assert profile.max_incline_grade == 8.33
        assert profile.max_decline_grade == 10.0
        assert profile.requires_curb_ramps is True
        assert profile.battery_range_km == 15.0

    def test_construct_with_overrides(self):
        """Construct with custom values."""
        profile = WheelchairProfile(
            device_type="power",
            max_width_cm=90,
            max_incline_grade=5.0,
            max_decline_grade=8.0,
            requires_curb_ramps=False,
            battery_range_km=25.0,
        )
        assert profile.device_type == "power"
        assert profile.max_width_cm == 90
        assert profile.max_incline_grade == 5.0
        assert profile.max_decline_grade == 8.0
        assert profile.requires_curb_ramps is False
        assert profile.battery_range_km == 25.0

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization."""
        original = WheelchairProfile(
            device_type="scooter",
            max_width_cm=85,
        )
        d = original.dict()
        restored = WheelchairProfile.parse_obj(d)

        assert restored.device_type == original.device_type
        assert restored.max_width_cm == original.max_width_cm
        assert restored.max_incline_grade == original.max_incline_grade


class TestSegmentElevationReport:
    """Test SegmentElevationReport model."""

    def test_construct_basic(self):
        """Construct a segment report."""
        report = SegmentElevationReport(
            segment_index=0,
            start_location=LatLng(lat=37.0, lng=-122.0),
            end_location=LatLng(lat=37.1, lng=-122.0),
            distance_meters=100.0,
            elevation_change_meters=5.0,
            grade_percentage=5.0,
            is_compliant=True,
        )
        assert report.segment_index == 0
        assert report.distance_meters == 100.0
        assert report.grade_percentage == 5.0
        assert report.is_compliant is True

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization."""
        original = SegmentElevationReport(
            segment_index=2,
            start_location=LatLng(lat=40.0, lng=-74.0),
            end_location=LatLng(lat=40.01, lng=-74.01),
            distance_meters=500.0,
            elevation_change_meters=-10.0,
            grade_percentage=-2.0,
            is_compliant=True,
        )
        d = original.dict()
        restored = SegmentElevationReport.parse_obj(d)

        assert restored.segment_index == original.segment_index
        assert restored.distance_meters == original.distance_meters
        assert restored.grade_percentage == original.grade_percentage


class TestRouteCandidate:
    """Test RouteCandidate model."""

    def test_construct_basic(self):
        """Construct a route candidate."""
        candidate = RouteCandidate(
            route_index=0,
            encoded_polyline="_p~iF~ps|U_ulLnnqC_mqNvxq`@",
            distance_meters=1500.0,
            duration_seconds=450.0,
            num_steps=5,
            travel_mode="WALK",
        )
        assert candidate.route_index == 0
        assert candidate.distance_meters == 1500.0
        assert candidate.num_steps == 5
        assert candidate.travel_mode == "WALK"

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization."""
        original = RouteCandidate(
            route_index=1,
            encoded_polyline="test_encoded",
            distance_meters=2000.0,
            duration_seconds=600.0,
            num_steps=8,
            travel_mode="TRANSIT",
        )
        d = original.dict()
        restored = RouteCandidate.parse_obj(d)

        assert restored.route_index == original.route_index
        assert restored.distance_meters == original.distance_meters
        assert restored.num_steps == original.num_steps


class TestElevationVerdict:
    """Test ElevationVerdict model."""

    def test_construct_basic(self):
        """Construct an elevation verdict."""
        segments = [
            SegmentElevationReport(
                segment_index=0,
                start_location=LatLng(lat=37.0, lng=-122.0),
                end_location=LatLng(lat=37.01, lng=-122.0),
                distance_meters=100.0,
                elevation_change_meters=2.0,
                grade_percentage=2.0,
                is_compliant=True,
            )
        ]
        verdict = ElevationVerdict(
            session_id="sess-123",
            route_index=0,
            segments=segments,
            is_route_compliant=True,
            max_grade_percentage=2.0,
        )
        assert verdict.session_id == "sess-123"
        assert verdict.route_index == 0
        assert verdict.is_route_compliant is True
        assert verdict.max_grade_percentage == 2.0
        assert verdict.service_degraded is False  # default

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization with nested segments."""
        segments = [
            SegmentElevationReport(
                segment_index=0,
                start_location=LatLng(lat=40.0, lng=-74.0),
                end_location=LatLng(lat=40.01, lng=-74.0),
                distance_meters=100.0,
                elevation_change_meters=0.0,
                grade_percentage=0.0,
                is_compliant=True,
            ),
        ]
        original = ElevationVerdict(
            session_id="sess-456",
            route_index=2,
            segments=segments,
            is_route_compliant=True,
            max_grade_percentage=0.0,
            service_degraded=False,
        )
        d = original.dict()
        restored = ElevationVerdict.parse_obj(d)

        assert restored.session_id == original.session_id
        assert restored.route_index == original.route_index
        assert restored.is_route_compliant == original.is_route_compliant
        assert len(restored.segments) == len(original.segments)


class TestFinalRoute:
    """Test FinalRoute model."""

    def test_construct_success(self):
        """Construct a successful final route."""
        route = FinalRoute(
            session_id="sess-789",
            success=True,
            chosen_route_index=0,
            directions_prose="Turn left at main street...",
            warnings=[],
            total_distance_meters=1500.0,
            travel_mode="WALK",
        )
        assert route.session_id == "sess-789"
        assert route.success is True
        assert route.chosen_route_index == 0
        assert route.travel_mode == "WALK"

    def test_construct_failure(self):
        """Construct a failed final route (no suitable route)."""
        route = FinalRoute(
            session_id="sess-999",
            success=False,
            chosen_route_index=None,
            directions_prose="",
            warnings=["All routes have excessive grades"],
        )
        assert route.success is False
        assert route.chosen_route_index is None

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization."""
        original = FinalRoute(
            session_id="sess-abc",
            success=True,
            chosen_route_index=1,
            directions_prose="Walk north on 5th Ave...",
            warnings=["One segment exceeds max grade by 0.5%"],
            total_distance_meters=2000.0,
            travel_mode="WALK",
            service_degraded=False,
        )
        d = original.dict()
        restored = FinalRoute.parse_obj(d)

        assert restored.session_id == original.session_id
        assert restored.success == original.success
        assert restored.chosen_route_index == original.chosen_route_index


class TestRouteEvaluationRequest:
    """Test RouteEvaluationRequest model with nested models."""

    def test_construct_with_nested_models(self):
        """Construct a request with nested LatLng and WheelchairProfile."""
        req = RouteEvaluationRequest(
            session_id="sess-req-1",
            origin=LatLng(lat=37.7749, lng=-122.4194),
            destination=LatLng(lat=37.3382, lng=-121.8863),
            profile=WheelchairProfile(device_type="manual"),
            travel_mode="WALK",
        )
        assert req.session_id == "sess-req-1"
        assert req.origin.lat == 37.7749
        assert req.destination.lat == 37.3382
        assert req.profile.device_type == "manual"

    def test_roundtrip_via_dict(self):
        """Test round-trip serialization with all nested models."""
        original = RouteEvaluationRequest(
            session_id="sess-req-2",
            origin=LatLng(lat=40.7128, lng=-74.0060),
            destination=LatLng(lat=34.0522, lng=-118.2437),
            profile=WheelchairProfile(
                device_type="power",
                max_incline_grade=6.0,
            ),
            travel_mode="WALK",
        )
        d = original.dict()
        restored = RouteEvaluationRequest.parse_obj(d)

        assert restored.session_id == original.session_id
        assert restored.origin.lat == original.origin.lat
        assert restored.destination.lng == original.destination.lng
        assert restored.profile.device_type == original.profile.device_type
        assert restored.profile.max_incline_grade == original.profile.max_incline_grade


class TestRouteCandidates:
    """Test RouteCandidates collection model."""

    def test_construct_multiple_candidates(self):
        """Construct a RouteCandidates with multiple candidates."""
        candidates = RouteCandidates(
            session_id="sess-coll-1",
            candidates=[
                RouteCandidate(
                    route_index=0,
                    encoded_polyline="encoded_0",
                    distance_meters=1000.0,
                    duration_seconds=300.0,
                    num_steps=3,
                    travel_mode="WALK",
                ),
                RouteCandidate(
                    route_index=1,
                    encoded_polyline="encoded_1",
                    distance_meters=1200.0,
                    duration_seconds=350.0,
                    num_steps=4,
                    travel_mode="WALK",
                ),
            ],
            travel_mode="WALK",
        )
        assert candidates.session_id == "sess-coll-1"
        assert len(candidates.candidates) == 2
        assert candidates.candidates[0].route_index == 0
        assert candidates.service_degraded is False


class TestAccessibilityVerdict:
    """Test AccessibilityVerdict model."""

    def test_construct_with_wheelchair_access(self):
        """Construct a verdict with wheelchair access info."""
        verdict = AccessibilityVerdict(
            session_id="sess-acc-1",
            place_id="place_12345",
            display_name="Library",
            wheelchair_entrance=True,
        )
        assert verdict.session_id == "sess-acc-1"
        assert verdict.wheelchair_entrance is True

    def test_construct_with_warning(self):
        """Construct a verdict with warning and no accessibility info."""
        verdict = AccessibilityVerdict(
            session_id="sess-acc-2",
            warning="Wheelchair accessibility information unavailable",
            service_degraded=True,
        )
        assert verdict.warning is not None
        assert verdict.service_degraded is True
        assert verdict.wheelchair_entrance is None
