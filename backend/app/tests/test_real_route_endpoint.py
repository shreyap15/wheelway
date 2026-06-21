"""
WheelWay — /real-route endpoint tests.

These verify the thin Flask adapter over the shared pipeline:
  - request validation (400 validation_error),
  - the honest-failure path with no Mapbox token (503 configuration_error,
    never fabricated geometry),
  - a mocked success path (200) proving the endpoint returns exact Mapbox
    geometry as GeoJSON [lng, lat] and reuses accessroute.pipeline.

All paid API calls are mocked; no network access is required.
"""

import polyline as _polyline
import pytest

from main import app
from accessroute import pipeline
from accessroute.schemas import AccessibilityVerdict, RouteCandidate

ENCODED = _polyline.encode([(37.869, -122.259), (37.868, -122.258)])


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _no_live_calls(monkeypatch):
    """Default: never hit live Overpass/Places. Tests override as needed."""
    monkeypatch.setattr(
        pipeline.stairs_tool,
        "query_overpass_stairs",
        lambda *a, **k: ([], False, "connection_error"),
    )
    # Default: discovery makes no live Mapbox via-calls (tests override).
    monkeypatch.setattr(pipeline, "compute_mapbox_route_via", lambda *a, **k: [])
    monkeypatch.setattr(
        pipeline,
        "check_destination_accessibility",
        lambda *a, **k: AccessibilityVerdict(
            session_id="", display_name="Test Place", wheelchair_entrance=True
        ),
    )


VALID_BODY = {
    "origin": {"latitude": 37.869, "longitude": -122.259},
    "destination": {"latitude": 37.868, "longitude": -122.258},
    "profile": {
        "wheelchair_type": "manual",
        "avoid_stairs": True,
        "max_slope_pct": 8.33,
        "min_width_m": 0.91,
    },
}


def _patch_mapbox(monkeypatch, candidates=None, exc=None):
    def fake(*args, **kwargs):
        if exc is not None:
            raise exc
        return candidates if candidates is not None else [
            RouteCandidate(
                route_index=0,
                encoded_polyline=ENCODED,
                distance_meters=300.0,
                duration_seconds=240.0,
                num_steps=2,
                travel_mode="WALK",
            )
        ]

    monkeypatch.setattr(pipeline, "compute_mapbox_routes", fake)


def test_real_route_missing_mapbox_token_returns_config_error(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "", raising=False)
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["error"] == "configuration_error"
    assert "MAPBOX_ACCESS_TOKEN" in body["missing_env"]
    # Must not fabricate any geometry on the failure path.
    assert "routes" not in body


def test_real_route_invalid_body_is_400(client):
    resp = client.post("/real-route", json={"origin": {"latitude": 37.0}})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "validation_error"


def test_real_route_no_json_is_400(client):
    resp = client.post("/real-route", data="nope", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "validation_error"


def test_real_route_success_returns_mapbox_geojson(client, monkeypatch):
    """Mapbox token present, Google enrichment absent -> exact geometry, 200."""
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_mapbox(monkeypatch)

    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "real_route"
    route = data["routes"][0]
    # Geometry is the exact decoded Mapbox polyline in [lng, lat] order.
    assert route["geometry"]["type"] == "LineString"
    assert route["geometry"]["coordinates"] == [[-122.259, 37.869], [-122.258, 37.868]]
    assert route["sources"]["geometry"] == "mapbox"
    assert route["stairs_detected"] is None
    # No Google key -> slope unavailable, but geometry is real (not fabricated).
    assert route["max_slope_pct"] is None
    # Elevation unavailable -> empty slope_segments (no placeholder sections),
    # and the provenance marks slope data unavailable.
    assert route["slope_segments"] == []
    assert data["data_sources"]["slope_segments"] == "unavailable"


def test_real_route_slope_segments_present_with_elevation(client, monkeypatch):
    """Google key present + mocked elevation -> classified slope_segments."""
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "g-key", raising=False)
    _patch_mapbox(monkeypatch)

    # Mocked smoothed elevation samples: a flat run then a steep climb. Patch the
    # name as bound inside the pipeline module (no live Elevation API call).
    def fake_sample_elevations(encoded, distance, *, api_key):
        return [
            {"lat": 37.8690, "lng": -122.2590, "elevation": 100.0},
            {"lat": 37.8699, "lng": -122.2590, "elevation": 100.5},  # ~0.5% flat
            {"lat": 37.8708, "lng": -122.2590, "elevation": 101.0},  # ~0.5% flat
            {"lat": 37.8717, "lng": -122.2590, "elevation": 113.0},  # ~12% steep
        ]

    monkeypatch.setattr(pipeline, "sample_elevations", fake_sample_elevations)
    monkeypatch.setattr(pipeline, "smooth_elevation_samples", lambda s, *a, **k: s)

    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 200
    route = resp.get_json()["routes"][0]
    segs = route["slope_segments"]
    assert len(segs) >= 2  # a low run and a steep section, grouped
    first = segs[0]
    # GeoJSON [lng, lat] order is preserved end-to-end.
    assert first["geometry"]["type"] == "LineString"
    assert first["geometry"]["coordinates"][0] == [-122.2590, 37.8690]
    classifications = {s["classification"] for s in segs}
    assert "low" in classifications
    # The 12% climb exceeds the 8.33% profile limit.
    assert any(s["exceeds_user_limit"] for s in segs)


def _candidate(idx, coords, steps=None, distance=300.0, duration=240.0):
    """Build a Mapbox RouteCandidate from (lat, lng) coords (encoded polyline)."""
    return RouteCandidate(
        route_index=idx,
        encoded_polyline=_polyline.encode(coords),
        distance_meters=distance,
        duration_seconds=duration,
        num_steps=len(steps or []),
        travel_mode="WALK",
        steps=steps or [],
    )


def _patch_overpass(monkeypatch, features=None, available=True, error=None):
    monkeypatch.setattr(
        pipeline.stairs_tool,
        "query_overpass_stairs",
        lambda *a, **k: (features or [], available, error if not available else None),
    )


def test_stairs_possible_from_mapbox_instruction(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    coords = [(37.869, -122.259), (37.868, -122.258)]
    steps = [{"name": "", "instruction": "Take the stairs down", "location": [-122.2585, 37.8685]}]
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, coords, steps)])
    _patch_overpass(monkeypatch, features=[], available=True)  # OSM ran, found nothing

    route = client.post("/real-route", json=VALID_BODY).get_json()["routes"][0]
    assert route["stairs_status"] == "possible"
    assert route["stairs_detected"] is None  # never claims confirmed from text alone
    # Geometry is unchanged Mapbox geometry.
    assert route["geometry"]["coordinates"] == [[-122.259, 37.869], [-122.258, 37.868]]


def test_stairs_failed_sources_are_unknown_not_false(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, [(37.869, -122.259), (37.868, -122.258)])])
    _patch_overpass(monkeypatch, features=[], available=False)  # Overpass unavailable

    data = client.post("/real-route", json=VALID_BODY).get_json()
    route = data["routes"][0]
    assert route["stairs_status"] == "unknown"
    assert route["stairs_detected"] is None  # never False when a source failed


def test_confirmed_cv_stairs_route_ranked_below_stairfree(client, monkeypatch):
    """avoid_stairs=true: confirmed-stair candidate ranked LAST (preserved), stair-free recommended."""
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    route_a = [(37.8690, -122.2590), (37.8700, -122.2580)]  # CV stairs here
    route_b = [(37.8690, -122.2590), (37.8600, -122.2700)]  # diverges far, stair-free
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, route_a), _candidate(1, route_b)])
    _patch_overpass(monkeypatch, features=[], available=True)

    body = {
        **VALID_BODY,
        "cv_observations": [
            {
                "feature_type": "stairs",
                "latitude": 37.8700,
                "longitude": -122.2580,  # on route A vertex
                "confidence": 0.95,
                "source": "camera_cv",
            }
        ],
    }
    data = client.post("/real-route", json=body).get_json()
    routes = data["routes"]
    # Both routes preserved (no dropping); stair-free B recommended, A ranked last.
    assert len(routes) == 2
    assert routes[0]["route_id"] == "route-2"
    assert routes[0]["recommended"] is True
    a = next(r for r in routes if r["route_id"] == "route-1")
    assert a["stairs_status"] == "confirmed"
    assert a["accessibility_rank"] == 2
    assert a["recommended"] is False
    # Geometry preserved exactly for BOTH routes.
    assert routes[0]["geometry"]["coordinates"][0] == [-122.2590, 37.8690]
    assert a["geometry"]["coordinates"][-1] == [-122.2580, 37.8700]
    assert data["data_sources"]["stairs_detection"].startswith("mapbox_steps")


_ROUTE_A = [(37.8690, -122.2590), (37.8700, -122.2580)]  # CV stairs here
_ROUTE_B = [(37.8690, -122.2590), (37.8600, -122.2700)]  # diverges far, stair-free
_CV_STAIRS_ON_A = [
    {
        "feature_type": "stairs",
        "latitude": 37.8700,
        "longitude": -122.2580,
        "confidence": 0.95,
        "source": "camera_cv",
    }
]


def _two_route_setup(monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, _ROUTE_A), _candidate(1, _ROUTE_B)])
    _patch_overpass(monkeypatch, features=[], available=True)


def test_avoid_stairs_true_reranks_confirmed_route(client, monkeypatch):
    _two_route_setup(monkeypatch)
    body = {**VALID_BODY, "profile": {**VALID_BODY["profile"], "avoid_stairs": True},
            "cv_observations": _CV_STAIRS_ON_A}
    routes = client.post("/real-route", json=body).get_json()["routes"]
    # Confirmed-stair route A ranked last (preserved); stair-free B recommended.
    assert routes[0]["route_id"] == "route-2"
    assert {r["route_id"] for r in routes} == {"route-1", "route-2"}
    assert routes[-1]["route_id"] == "route-1"


def test_avoid_stairs_false_keeps_original_order(client, monkeypatch):
    _two_route_setup(monkeypatch)
    body = {**VALID_BODY, "profile": {**VALID_BODY["profile"], "avoid_stairs": False},
            "cv_observations": _CV_STAIRS_ON_A}
    data = client.post("/real-route", json=body).get_json()
    routes = data["routes"]
    # No rejection / rerank: original Mapbox order preserved (route-1 first).
    assert [r["route_id"] for r in routes] == ["route-1", "route-2"]
    # Stairs still honestly reported on A even though not avoided.
    assert routes[0]["stairs_status"] == "confirmed"
    assert data["profile"]["avoid_stairs"] is False


def test_requires_curb_ramps_does_not_toggle_avoid_stairs(client, monkeypatch):
    _two_route_setup(monkeypatch)
    # requires_curb_ramps False must NOT disable stair avoidance.
    body = {**VALID_BODY,
            "profile": {**VALID_BODY["profile"], "avoid_stairs": True, "requires_curb_ramps": False},
            "cv_observations": _CV_STAIRS_ON_A}
    data = client.post("/real-route", json=body).get_json()
    assert data["routes"][0]["route_id"] == "route-2"  # still avoided
    assert data["profile"]["avoid_stairs"] is True
    assert data["profile"]["requires_curb_ramps"] is False  # independent


def test_avoid_stairs_does_not_toggle_requires_curb_ramps(client, monkeypatch):
    _two_route_setup(monkeypatch)
    # avoid_stairs False; requires_curb_ramps omitted -> keeps its own default (True).
    body = {**VALID_BODY, "profile": {**VALID_BODY["profile"], "avoid_stairs": False}}
    data = client.post("/real-route", json=body).get_json()
    assert data["profile"]["avoid_stairs"] is False
    assert data["profile"]["requires_curb_ramps"] is True  # not toggled


def test_legacy_payload_without_avoid_stairs_defaults_safe(client, monkeypatch):
    _two_route_setup(monkeypatch)
    # Older payload omits avoid_stairs entirely -> safe default True -> avoided.
    legacy_profile = {"wheelchair_type": "manual", "max_slope_pct": 8.33, "min_width_m": 0.91}
    body = {**VALID_BODY, "profile": legacy_profile, "cv_observations": _CV_STAIRS_ON_A}
    data = client.post("/real-route", json=body).get_json()
    assert data["profile"]["avoid_stairs"] is True
    assert data["routes"][0]["route_id"] == "route-2"


def test_stairs_debug_pinpoints_osm_as_unknown_cause(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, [(37.869, -122.259), (37.868, -122.258)])])
    _patch_overpass(monkeypatch, features=[], available=False, error="timeout")

    route = client.post("/real-route", json=VALID_BODY).get_json()["routes"][0]
    dbg = route["stairs_debug"]
    # Mapbox + CV completed (empty is not failure); OSM is the lone failed source.
    assert dbg["mapbox_steps"]["completed"] is True
    assert dbg["mapbox_steps"]["error"] is None
    assert dbg["camera_cv"]["completed"] is True
    assert dbg["camera_cv"]["observation_count"] == 0
    assert dbg["openstreetmap"]["completed"] is False
    assert dbg["openstreetmap"]["error"] == "timeout"
    # Hence the (correct) unknown verdict.
    assert route["stairs_status"] == "unknown"


def test_osm_valid_empty_response_yields_not_detected(client, monkeypatch):
    """The fix: a valid empty Overpass response completes -> not_detected, not unknown."""
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, [(37.869, -122.259), (37.868, -122.258)])])
    _patch_overpass(monkeypatch, features=[], available=True)  # valid, zero features

    route = client.post("/real-route", json=VALID_BODY).get_json()["routes"][0]
    dbg = route["stairs_debug"]
    assert dbg["openstreetmap"]["completed"] is True
    assert dbg["openstreetmap"]["error"] is None
    assert all(dbg[s]["completed"] for s in ("mapbox_steps", "openstreetmap", "camera_cv"))
    assert route["stairs_status"] == "not_detected"
    assert route["stairs_detected"] is False


# --- Accessibility-first ranking (Task 2) ---------------------------------- #
# Short steep route (exceeds limit) vs longer gentle route (compliant).
_SHORT_STEEP = [(37.8690, -122.2590), (37.8693, -122.2590)]   # ~33 m, climbs hard
_LONG_GENTLE = [(37.8690, -122.2590), (37.8690, -122.2700), (37.8690, -122.2800)]  # long, flat


def _patch_elevation_by_distance(monkeypatch):
    """Mock elevation: short route climbs steeply, long route stays flat."""
    def fake_sample(encoded, distance, *, api_key):
        coords = _polyline.decode(encoded)  # [(lat, lng), ...]
        if distance < 200:  # short steep route -> ~30% grade
            elevs = [100.0 + i * 10.0 for i in range(len(coords))]
        else:  # long gentle route -> negligible grade
            elevs = [100.0 + i * 0.2 for i in range(len(coords))]
        return [{"lat": c[0], "lng": c[1], "elevation": e} for c, e in zip(coords, elevs)]

    monkeypatch.setattr(pipeline, "sample_elevations", fake_sample)
    monkeypatch.setattr(pipeline, "smooth_elevation_samples", lambda s, *a, **k: s)


def test_longer_compliant_route_outranks_shorter_red_route(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "g-key", raising=False)
    _patch_overpass(monkeypatch, features=[], available=True)
    _patch_elevation_by_distance(monkeypatch)
    _patch_mapbox(monkeypatch, candidates=[
        _candidate(0, _SHORT_STEEP, distance=33.0, duration=40.0),     # route-1 red
        _candidate(1, _LONG_GENTLE, distance=1800.0, duration=1300.0),  # route-2 compliant
    ])

    data = client.post("/real-route", json=VALID_BODY).get_json()
    routes = data["routes"]
    # The longer compliant route wins despite being much longer.
    assert routes[0]["route_id"] == "route-2"
    assert routes[0]["recommended"] is True
    assert routes[0]["exceeds_limit_distance_m"] == 0
    red = next(r for r in routes if r["route_id"] == "route-1")
    assert red["exceeds_limit_distance_m"] > 0  # Task 6.3: distance above limit computed
    assert red["accessibility_rank"] == 2
    assert any("avoids slopes above" in s for s in routes[0]["selection_reasons"])


def test_all_unsafe_returns_least_bad_with_warning(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "g-key", raising=False)
    _patch_overpass(monkeypatch, features=[], available=True)

    # Both routes steep; route-2 has a shorter exceed distance -> least bad.
    def fake_sample(encoded, distance, *, api_key):
        coords = _polyline.decode(encoded)
        step = 10.0 if distance < 200 else 9.0  # both exceed; long one slightly less steep per-seg
        elevs = [100.0 + i * step for i in range(len(coords))]
        return [{"lat": c[0], "lng": c[1], "elevation": e} for c, e in zip(coords, elevs)]

    monkeypatch.setattr(pipeline, "sample_elevations", fake_sample)
    monkeypatch.setattr(pipeline, "smooth_elevation_samples", lambda s, *a, **k: s)
    _patch_mapbox(monkeypatch, candidates=[
        _candidate(0, _SHORT_STEEP, distance=33.0),
        _candidate(1, [(37.8690, -122.2590), (37.8694, -122.2590)], distance=44.0),
    ])

    data = client.post("/real-route", json=VALID_BODY).get_json()
    assert all(r["exceeds_limit_distance_m"] > 0 for r in data["routes"])
    assert any("No route under your selected" in w for w in data["warnings"])
    assert data["routes"][0]["recommended"] is True


def test_single_route_no_fake_geometry(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    coords = [(37.869, -122.259), (37.868, -122.258)]
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, coords)])
    _patch_overpass(monkeypatch, features=[], available=True)

    data = client.post("/real-route", json=VALID_BODY).get_json()
    routes = data["routes"]
    assert len(routes) == 1  # not fabricated into more
    assert routes[0]["geometry"]["coordinates"] == [[-122.259, 37.869], [-122.258, 37.868]]
    assert any("Only one distinct pedestrian route" in s for s in routes[0]["selection_reasons"])


def test_discovery_finds_gentler_route_that_outranks_red_original(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "g-key", raising=False)
    _patch_overpass(monkeypatch, features=[], available=True)

    # Steep if distance <= 400 m, gentle otherwise.
    def fake_sample(encoded, distance, *, api_key):
        coords = _polyline.decode(encoded)
        step = 10.0 if distance <= 400 else 0.2
        elevs = [100.0 + i * step for i in range(len(coords))]
        return [{"lat": c[0], "lng": c[1], "elevation": e} for c, e in zip(coords, elevs)]

    monkeypatch.setattr(pipeline, "sample_elevations", fake_sample)
    monkeypatch.setattr(pipeline, "smooth_elevation_samples", lambda s, *a, **k: s)

    # Mapbox returns ONE steep route.
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, _SHORT_STEEP, distance=300.0)])

    # Discovery returns a longer, gentle real route.
    gentle = _candidate(1, _LONG_GENTLE, distance=600.0, duration=520.0)
    monkeypatch.setattr(pipeline, "compute_mapbox_route_via", lambda *a, **k: [gentle])

    data = client.post("/real-route", json=VALID_BODY).get_json()
    routes = data["routes"]
    assert data["raw_mapbox_candidate_count"] == 1
    assert data["distinct_candidate_count"] == 2
    assert 1 <= data["additional_requests_made"] <= 3  # capped
    assert "waypoint_discovery" in data["candidate_generation_method"]
    assert data["only_one_route_available"] is False
    # The discovered gentle route is recommended over the steep original.
    assert routes[0]["recommended"] is True
    assert routes[0]["exceeds_limit_distance_m"] == 0
    assert any("detour" in s.lower() for s in routes[0]["selection_reasons"])


def test_discovery_request_count_is_capped(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    _patch_overpass(monkeypatch, features=[], available=True)
    _patch_mapbox(monkeypatch, candidates=[_candidate(0, _SHORT_STEEP, distance=300.0)])

    calls = {"n": 0}

    def counting_via(*a, **k):
        calls["n"] += 1
        return []  # never yields a distinct route

    monkeypatch.setattr(pipeline, "compute_mapbox_route_via", counting_via)

    data = client.post("/real-route", json=VALID_BODY).get_json()
    assert calls["n"] <= 3  # no retry storm / uncontrolled grid
    assert data["additional_requests_made"] <= 3
    assert data["only_one_route_available"] is True  # nothing distinct discovered


def test_near_duplicate_routes_deduped_distinct_preserved(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(pipeline, "GOOGLE_MAPS_API_KEY", "", raising=False)
    base = [(37.8690, -122.2590), (37.8700, -122.2580)]
    near_dup = [(37.8690, -122.2590), (37.8700, -122.2580)]  # identical -> deduped
    distinct = [(37.8690, -122.2590), (37.8600, -122.2700)]  # meaningfully different -> kept
    _patch_mapbox(monkeypatch, candidates=[
        _candidate(0, base), _candidate(1, near_dup), _candidate(2, distinct),
    ])
    _patch_overpass(monkeypatch, features=[], available=True)

    routes = client.post("/real-route", json=VALID_BODY).get_json()["routes"]
    assert len(routes) == 2  # one duplicate removed, distinct alternative kept


def test_real_route_no_route_is_404(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    _patch_mapbox(
        monkeypatch,
        exc=pipeline.ServiceDegraded("Mapbox Directions returned no usable route geometry"),
    )
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "no_route"


def test_real_route_routing_unavailable_is_502(client, monkeypatch):
    monkeypatch.setattr(pipeline, "MAPBOX_ACCESS_TOKEN", "test-token", raising=False)
    _patch_mapbox(monkeypatch, exc=pipeline.ServiceDegraded("Mapbox Directions HTTP 500"))
    resp = client.post("/real-route", json=VALID_BODY)
    assert resp.status_code == 502
    assert resp.get_json()["error"] == "routing_unavailable"
