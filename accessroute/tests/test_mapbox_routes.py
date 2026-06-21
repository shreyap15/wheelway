"""Tests for Mapbox walking route candidate generation."""

import json

import polyline as _polyline
import pytest

from accessroute.common.geo import decode_polyline
from accessroute.schemas import LatLng
from accessroute.tools.mapbox_routes_tool import compute_mapbox_routes


MAPBOX_FIXTURE = {
    "code": "Ok",
    "routes": [
        {
            "geometry": {
                "coordinates": [
                    [-122.2595, 37.8715],
                    [-122.2588, 37.8756],
                ],
                "type": "LineString",
            },
            "distance": 612.4,
            "duration": 480.2,
            "legs": [{"steps": [{"maneuver": {"type": "depart"}}, {"maneuver": {"type": "arrive"}}]}],
        },
        {
            "geometry": {
                "coordinates": [
                    [-122.2595, 37.8715],
                    [-122.2590, 37.8730],
                    [-122.2588, 37.8756],
                ],
                "type": "LineString",
            },
            "distance": 701.0,
            "duration": 520.0,
            "legs": [{"steps": [{"maneuver": {"type": "depart"}}]}],
        },
    ],
}


class TestComputeMapboxRoutes:
    def test_parses_routes_and_encodes_google_polyline(self, monkeypatch):
        class FakeResponse:
            ok = True
            status_code = 200

            @staticmethod
            def json():
                return MAPBOX_FIXTURE

        monkeypatch.setattr(
            "accessroute.tools.mapbox_routes_tool.request_with_retry",
            lambda *args, **kwargs: FakeResponse(),
        )

        origin = LatLng(lat=37.8715, lng=-122.2595)
        destination = LatLng(lat=37.8756, lng=-122.2588)
        candidates = compute_mapbox_routes(
            origin,
            destination,
            access_token="test-token",
            travel_mode="WALK",
        )

        assert len(candidates) == 2
        assert candidates[0].route_index == 0
        assert candidates[0].distance_meters == pytest.approx(612.4)
        assert candidates[0].duration_seconds == pytest.approx(480.2)
        assert candidates[0].travel_mode == "WALK"
        assert candidates[0].num_steps == 2

        decoded = decode_polyline(candidates[0].encoded_polyline)
        expected = _polyline.encode([(37.8715, -122.2595), (37.8756, -122.2588)])
        assert decoded == _polyline.decode(expected)

    def test_requires_access_token(self):
        origin = LatLng(lat=37.8715, lng=-122.2595)
        destination = LatLng(lat=37.8756, lng=-122.2588)
        with pytest.raises(Exception, match="MAPBOX_ACCESS_TOKEN"):
            compute_mapbox_routes(origin, destination, access_token="")
