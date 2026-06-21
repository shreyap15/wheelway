"""Tests for multi-source stair detection (accessroute.tools.stairs_tool).

All external calls are mocked/injected -- no live Overpass requests.
"""

from accessroute.tools import stairs_tool as st

# A short straight route (lat, lng) near Berkeley.
ROUTE = [
    (37.8690, -122.2590),
    (37.8695, -122.2588),
    (37.8700, -122.2586),
    (37.8705, -122.2584),
]


def _classify(evidence, ran):
    return st.classify_stairs(evidence, sources_ran=ran)


class TestMapboxHeuristic:
    def test_instruction_text_is_possible(self):
        steps = [
            {"name": "", "instruction": "Take the stairs to the plaza", "location": [-122.2588, 37.8695]},
        ]
        ev = st.detect_mapbox_step_stairs(steps)
        assert len(ev) == 1
        assert ev[0]["source"] == st.SRC_MAPBOX_STEPS
        assert ev[0]["matched_term"] == "stairs"
        status, conf = _classify(ev, {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: True})
        assert status == st.STATUS_POSSIBLE
        assert 0 < conf < 0.7

    def test_case_insensitive_and_no_match(self):
        assert st.detect_mapbox_step_stairs([{"instruction": "ESCALATOR ahead"}])
        assert st.detect_mapbox_step_stairs([{"instruction": "Turn left on Bancroft"}]) == []


class TestOsmEvidence:
    def test_nearby_highway_steps_is_likely(self):
        features = [
            {"lat": 37.8700, "lng": -122.2586, "key": "highway", "value": "steps",
             "tag": "highway=steps", "is_steps": True},
        ]
        ev = st.match_osm_to_route(features, ROUTE)
        assert len(ev) == 1
        assert ev[0]["osm_tag"] == "highway=steps"
        status, conf = _classify(ev, {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: True})
        assert status == st.STATUS_LIKELY
        assert conf == 0.7

    def test_far_feature_is_dropped(self):
        features = [
            {"lat": 37.9000, "lng": -122.3000, "key": "highway", "value": "steps",
             "tag": "highway=steps", "is_steps": True},
        ]
        assert st.match_osm_to_route(features, ROUTE) == []


class TestCvEvidence:
    def test_high_confidence_cv_is_confirmed(self):
        obs = [{
            "feature_type": "stairs", "latitude": 37.8695, "longitude": -122.2588,
            "confidence": 0.94, "source": "camera_cv",
        }]
        ev = st.detect_cv_stairs(obs, ROUTE)
        assert len(ev) == 1
        status, conf = _classify(ev, {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: True})
        assert status == st.STATUS_CONFIRMED
        assert conf >= 0.9

    def test_low_confidence_cv_alone_is_possible(self):
        obs = [{"feature_type": "stairs", "latitude": 37.8695, "longitude": -122.2588, "confidence": 0.3}]
        ev = st.detect_cv_stairs(obs, ROUTE)
        status, _ = _classify(ev, {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: True})
        assert status == st.STATUS_POSSIBLE  # single weak source

    def test_far_cv_ignored(self):
        obs = [{"feature_type": "stairs", "latitude": 37.95, "longitude": -122.40, "confidence": 0.99}]
        assert st.detect_cv_stairs(obs, ROUTE) == []


class TestFusion:
    def test_multiple_independent_sources_confirm(self):
        # Mapbox text + OSM barrier (non-steps) = two sources -> confirmed.
        ev = [
            {"source": st.SRC_MAPBOX_STEPS, "confidence": 0.4, "matched_term": "steps"},
            {"source": st.SRC_OSM, "confidence": 0.5, "osm_tag": "wheelchair=no", "_is_steps": False},
        ]
        status, conf = _classify(ev, {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: True})
        assert status == st.STATUS_CONFIRMED

    def test_no_evidence_all_sources_ran_is_not_detected(self):
        status, conf = _classify([], {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: True})
        assert status == st.STATUS_NOT_DETECTED
        assert conf == 0.0

    def test_failed_source_no_match_is_unknown_not_false(self):
        # OSM did not complete -> cannot claim absence.
        status, conf = _classify([], {st.SRC_MAPBOX_STEPS: True, st.SRC_CV: True, st.SRC_OSM: False})
        assert status == st.STATUS_UNKNOWN
        assert status != st.STATUS_NOT_DETECTED


class TestOverpassDegradation:
    def test_unavailable_overpass_degrades(self):
        def boom(query, timeout):
            raise TimeoutError("overpass down")

        features, completed, error = st.query_overpass_stairs(ROUTE, fetch=boom, use_cache=False)
        assert features == []
        assert completed is False
        assert error == "timeout"  # sanitized, no body/secret

    def test_valid_empty_response_completes(self):
        # A valid response with zero matching features completes successfully.
        features, completed, error = st.query_overpass_stairs(
            ROUTE, fetch=lambda q, t: {"elements": []}, use_cache=False
        )
        assert features == []
        assert completed is True
        assert error is None

    def test_parses_and_matches_with_injected_fetch(self):
        payload = {
            "elements": [
                {"type": "node", "lat": 37.8700, "lon": -122.2586, "tags": {"highway": "steps"}},
                {"type": "way", "center": {"lat": 37.8695, "lon": -122.2588},
                 "tags": {"barrier": "step"}},
                {"type": "node", "lat": 37.8702, "lon": -122.2585, "tags": {"amenity": "cafe"}},
            ]
        }
        features, completed, error = st.query_overpass_stairs(
            ROUTE, fetch=lambda q, t: payload, use_cache=False
        )
        assert completed is True
        assert error is None
        # cafe (no stair tag) filtered out.
        assert len(features) == 2
        ev = st.match_osm_to_route(features, ROUTE)
        assert any(e["osm_tag"] == "highway=steps" for e in ev)

    def test_build_stair_segments_have_linestring(self):
        ev = [{
            "source": st.SRC_OSM, "confidence": 0.7, "osm_tag": "highway=steps",
            "geometry": {"type": "LineString", "coordinates": [[-122.2586, 37.8700], [-122.2584, 37.8705]]},
        }]
        segs = st.build_stair_segments(ev, st.STATUS_LIKELY, 0.7)
        assert len(segs) == 1
        assert segs[0]["geometry"]["type"] == "LineString"
        assert segs[0]["status"] == st.STATUS_LIKELY
        assert segs[0]["sources"] == [st.SRC_OSM]
