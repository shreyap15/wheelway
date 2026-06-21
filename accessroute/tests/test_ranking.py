"""Unit tests for accessibility-first ranking helpers (pure, no network)."""

from accessroute.pipeline import (
    AccessibleRoute,
    SlopeSegment,
    _dedup_routes,
    _rank_routes,
    slope_distance_metrics,
)
from accessroute.tools import stairs_tool as st


def _seg(classification, coords):
    return SlopeSegment(
        geometry={"type": "LineString", "coordinates": coords},
        start_index=0,
        end_index=1,
        grade_pct=10.0,
        absolute_grade_pct=10.0,
        elevation_start_m=0.0,
        elevation_end_m=1.0,
        classification=classification,
        exceeds_user_limit=(classification == "exceeds_limit"),
    )


def test_slope_distance_metrics_sums_by_classification():
    # ~111 m per 0.001 deg latitude.
    exceed = _seg("exceeds_limit", [[-122.0, 37.000], [-122.0, 37.001]])
    chall = _seg("challenging", [[-122.0, 37.001], [-122.0, 37.002]])
    low = _seg("low", [[-122.0, 37.002], [-122.0, 37.004]])
    ex_d, ch_d, pct = slope_distance_metrics([exceed, chall, low], total_distance_m=1000.0)
    assert 100 < ex_d < 120  # ~111 m
    assert 100 < ch_d < 120
    assert 9 < pct < 13  # ~11% of 1000 m

    assert slope_distance_metrics([], 1000.0) == (None, None, None)


def _route(rid, *, exceed=0.0, max_slope=2.0, score=90.0, dist=100.0, dur=80.0):
    return AccessibleRoute(
        route_id=rid,
        geometry={"type": "LineString", "coordinates": []},
        distance_m=dist,
        duration_s=dur,
        max_slope_pct=max_slope,
        exceeds_limit_distance_m=exceed,
        accessibility_score=score,
    )


def test_compliant_longer_outranks_shorter_red():
    red_short = (_route("short", exceed=50.0, max_slope=20.0, score=40.0, dist=100.0),
                 st.STATUS_NOT_DETECTED)
    ok_long = (_route("long", exceed=0.0, max_slope=3.0, score=85.0, dist=400.0),
               st.STATUS_NOT_DETECTED)
    ranked = _rank_routes([red_short, ok_long], avoid_stairs=True)
    assert ranked[0].route_id == "long"
    assert ranked[0].recommended is True
    assert ranked[0].accessibility_rank == 1
    assert ranked[1].route_id == "short"


def test_stair_route_ranked_below_when_avoiding():
    stair = (_route("stair", exceed=0.0, score=90.0, dist=100.0), st.STATUS_CONFIRMED)
    free = (_route("free", exceed=0.0, score=70.0, dist=120.0), st.STATUS_NOT_DETECTED)
    ranked = _rank_routes([stair, free], avoid_stairs=True)
    assert ranked[0].route_id == "free"
    # Stair route preserved, not dropped.
    assert {r.route_id for r in ranked} == {"free", "stair"}


def test_dedup_keeps_distinct_drops_identical():
    geom_a = {"type": "LineString", "coordinates": [[-122.0, 37.0], [-122.0, 37.001]]}
    geom_b = {"type": "LineString", "coordinates": [[-122.0, 37.0], [-122.1, 37.05]]}
    r1 = AccessibleRoute(route_id="a", geometry=geom_a, distance_m=100.0, duration_s=80.0)
    r2 = AccessibleRoute(route_id="b", geometry=dict(geom_a), distance_m=100.0, duration_s=80.0)
    r3 = AccessibleRoute(route_id="c", geometry=geom_b, distance_m=200.0, duration_s=160.0)
    kept = _dedup_routes([(r1, st.STATUS_NOT_DETECTED), (r2, st.STATUS_NOT_DETECTED), (r3, st.STATUS_NOT_DETECTED)])
    ids = {item[0].route_id for item in kept}
    assert len(kept) == 2  # identical r2 dropped
    assert "c" in ids  # distinct route preserved
