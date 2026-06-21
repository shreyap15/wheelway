"""Tests for accessroute.common.geo module.

Tests polyline encoding/decoding and haversine distance calculations.
"""

import math

import polyline as _polyline
import pytest

from accessroute.common.geo import decode_polyline, haversine_meters


class TestDecodePolyline:
    """Test polyline decoding against known encoded strings."""

    def test_decode_known_polyline(self):
        """Decode a known encoded polyline and verify coordinates."""
        # Encode a known set of points
        points = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
        encoded = _polyline.encode(points)

        # Decode and verify
        decoded = decode_polyline(encoded)
        assert len(decoded) == len(points)

        # Check that decoded points are approximately equal
        # (polyline encoding uses precision 5, so ~0.00001 degree precision)
        for i, (lat, lng) in enumerate(decoded):
            assert abs(lat - points[i][0]) < 1e-4
            assert abs(lng - points[i][1]) < 1e-4

    def test_decode_empty_string(self):
        """Decoding an empty string should return an empty list."""
        decoded = decode_polyline("")
        assert decoded == []

    def test_decode_simple_two_points(self):
        """Decode a polyline with just two points."""
        points = [(37.0, -122.0), (37.1, -122.1)]
        encoded = _polyline.encode(points)
        decoded = decode_polyline(encoded)

        assert len(decoded) == 2
        assert abs(decoded[0][0] - 37.0) < 1e-4
        assert abs(decoded[0][1] - (-122.0)) < 1e-4
        assert abs(decoded[1][0] - 37.1) < 1e-4
        assert abs(decoded[1][1] - (-122.1)) < 1e-4

    def test_decode_roundtrip(self):
        """Test encoding and then decoding returns approximately original points."""
        original = [(40.0, -74.0), (40.1, -74.1), (40.2, -74.2)]
        encoded = _polyline.encode(original)
        decoded = decode_polyline(encoded)

        assert len(decoded) == len(original)
        for orig, dec in zip(original, decoded):
            assert abs(orig[0] - dec[0]) < 1e-4, f"Lat mismatch: {orig[0]} vs {dec[0]}"
            assert abs(orig[1] - dec[1]) < 1e-4, f"Lng mismatch: {orig[1]} vs {dec[1]}"


class TestHaversineMeter:
    """Test great-circle distance calculations."""

    def test_haversine_same_point(self):
        """Distance from a point to itself should be ~0."""
        point = (37.7749, -122.4194)  # San Francisco
        dist = haversine_meters(point, point)
        assert abs(dist) < 1.0  # Within 1 meter

    def test_haversine_one_degree_latitude(self):
        """One degree of latitude is approximately 111 km."""
        point_a = (0.0, 0.0)
        point_b = (1.0, 0.0)

        dist = haversine_meters(point_a, point_b)

        # One degree of latitude ≈ 111 km at the equator
        expected = 111_000  # meters
        assert 110_000 < dist < 112_000, f"Got {dist} meters, expected ~111000"

    def test_haversine_known_distance(self):
        """Test distance between two known cities."""
        # San Francisco: (37.7749, -122.4194)
        # Los Angeles: (34.0522, -118.2437)
        # Expected distance: ~559 km
        sf = (37.7749, -122.4194)
        la = (34.0522, -118.2437)

        dist = haversine_meters(sf, la)

        # Approximate distance is 559 km
        expected = 559_000  # meters
        tolerance = 10_000  # ±10 km tolerance
        assert expected - tolerance < dist < expected + tolerance, \
            f"SF to LA distance {dist}m, expected ~{expected}m"

    def test_haversine_symetric(self):
        """Distance from A to B should equal distance from B to A."""
        point_a = (40.7128, -74.0060)  # New York
        point_b = (51.5074, -0.1278)   # London

        dist_ab = haversine_meters(point_a, point_b)
        dist_ba = haversine_meters(point_b, point_a)

        assert abs(dist_ab - dist_ba) < 1.0, "Distance should be symmetric"

    def test_haversine_antipodal_points(self):
        """Distance between antipodal points should be ~half Earth's circumference."""
        # North Pole and South Pole
        north = (90.0, 0.0)
        south = (-90.0, 0.0)

        dist = haversine_meters(north, south)

        # Half Earth's circumference ≈ 20,037 km
        R = 6_371_000.0
        expected = math.pi * R
        tolerance = 1_000  # ±1 km tolerance
        assert expected - tolerance < dist < expected + tolerance, \
            f"Pole-to-pole distance {dist}m, expected ~{expected}m"
