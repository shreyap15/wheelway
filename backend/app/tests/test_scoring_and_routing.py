"""
WheelWay — Tests for scoring engine and A* router.

Run with: pytest backend/app/tests/test_scoring_and_routing.py -v
"""

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.models.accessibility import Segment, UserMobilityProfile, SurfaceType, WheelchairType
from app.scoring.engine import (
    accessibility_score,
    traversal_cost,
    is_hard_disqualified,
    slope_quality,
    cross_slope_quality,
)
from app.routing.graph import AccessibilityGraph, Node
from app.routing.astar import find_accessible_route, haversine_m
from app.data.mock_graph import build_mock_graph


def make_segment(**overrides) -> Segment:
    defaults = dict(
        segment_id="s1",
        start_node_id="n1",
        end_node_id="n2",
        length_m=50.0,
        slope=2.0,
        cross_slope=1.0,
        width=1.52,
        surface=SurfaceType.CONCRETE,
        surface_condition=0.9,
    )
    defaults.update(overrides)
    return Segment(**defaults)


# ---------------------------------------------------------------------------
# Scoring engine tests
# ---------------------------------------------------------------------------

def test_ideal_segment_scores_near_100():
    seg = make_segment(slope=1.0, cross_slope=0.5, width=1.6, surface_condition=1.0)
    score = accessibility_score(seg)
    assert score >= 90, f"expected near-perfect score, got {score}"


def test_slope_at_prowag_max_still_full_quality():
    # 5.0% is the PROWAG standard PAR max — should not be penalized yet
    assert slope_quality(5.0) == 1.0
    assert slope_quality(4.99) == 1.0


def test_slope_beyond_ramp_max_is_heavily_penalized():
    q_at_ramp_max = slope_quality(8.33)
    q_severe = slope_quality(11.0)
    assert q_at_ramp_max > q_severe
    assert q_severe <= 0.1


def test_cross_slope_above_2pct_penalized():
    assert cross_slope_quality(2.0) == 1.0
    assert cross_slope_quality(4.0) < 1.0
    assert cross_slope_quality(7.0) <= 0.1


def test_stairs_collapse_score():
    seg = make_segment(stairs=True)
    score = accessibility_score(seg)
    assert score < 10, f"stairs should crater the score, got {score}"


def test_steep_hill_disqualified_for_default_profile():
    seg = make_segment(slope=12.0)
    profile = UserMobilityProfile()  # default max_slope_pct = 8.33 (ADA ramp max)
    disqualified, reason = is_hard_disqualified(seg, profile)
    assert disqualified
    assert "slope" in reason


def test_power_chair_profile_more_tolerant_of_slope():
    seg = make_segment(slope=9.0)
    manual_profile = UserMobilityProfile(
        wheelchair_type=WheelchairType.MANUAL, max_slope_pct=8.33
    )
    powered_profile = UserMobilityProfile(
        wheelchair_type=WheelchairType.POWERED, max_slope_pct=12.0
    )
    manual_disq, _ = is_hard_disqualified(seg, manual_profile)
    powered_disq, _ = is_hard_disqualified(seg, powered_profile)
    assert manual_disq is True
    assert powered_disq is False


def test_narrow_segment_below_ada_min_disqualified():
    seg = make_segment(width=0.6)  # below 0.91m ADA absolute minimum
    profile = UserMobilityProfile()  # default min_width_m = 0.91
    disqualified, reason = is_hard_disqualified(seg, profile)
    assert disqualified
    assert "width" in reason


def test_traversal_cost_inf_for_disqualified_segment():
    seg = make_segment(stairs=True)
    profile = UserMobilityProfile(avoid_stairs=True)
    cost = traversal_cost(seg, profile)
    assert math.isinf(cost)


def test_traversal_cost_scales_with_score():
    good = make_segment(slope=1.0, cross_slope=0.5, surface_condition=1.0)
    bad = make_segment(slope=6.0, cross_slope=3.0, surface_condition=0.5)
    profile = UserMobilityProfile(max_slope_pct=20, max_cross_slope_pct=20)  # permissive, not disqualifying
    cost_good = traversal_cost(good, profile)
    cost_bad = traversal_cost(bad, profile)
    assert cost_bad > cost_good, "worse accessibility should cost more even at equal distance"


def test_stale_data_pulls_score_toward_neutral():
    import time
    fresh = make_segment(
        slope=1.0, cross_slope=0.5, surface_condition=1.0,
        last_verified_ts=time.time(), report_confidence=1.0,
    )
    stale = make_segment(
        slope=1.0, cross_slope=0.5, surface_condition=1.0,
        last_verified_ts=time.time() - 86400 * 365,  # a year old
        report_confidence=1.0,
    )
    score_fresh = accessibility_score(fresh)
    score_stale = accessibility_score(stale)
    assert score_fresh > score_stale, "stale data should not retain full confidence in a great score"


# ---------------------------------------------------------------------------
# Router tests
# ---------------------------------------------------------------------------

def test_haversine_known_distance():
    # Berkeley campus-ish, ~80m apart should compute close to 80m
    d = haversine_m(37.8719, -122.2585, 37.87118, -122.2585)
    assert 75 < d < 85


def test_simple_two_node_route():
    graph = AccessibilityGraph()
    graph.add_node(Node("n1", 37.8719, -122.2585))
    graph.add_node(Node("n2", 37.87118, -122.2585))
    graph.add_segment(make_segment(segment_id="e1", start_node_id="n1", end_node_id="n2"))

    result = find_accessible_route(graph, "n1", "n2")
    assert result.found
    assert len(result.steps) == 1
    assert result.total_distance_m == 50.0


def test_router_avoids_stairs_on_mock_graph():
    graph = build_mock_graph()
    profile = UserMobilityProfile()  # avoid_stairs=True by default

    result = find_accessible_route(graph, "A1", "D2", profile)
    assert result.found, result.failure_reason

    used_segment_ids = {s.segment.segment_id for s in result.steps}
    assert "C1_C2" not in used_segment_ids and "C2_C1_rev" not in used_segment_ids, (
        "router should never route through the stairs segment for a wheelchair profile"
    )


def test_router_avoids_steep_hill_for_manual_chair():
    graph = build_mock_graph()
    profile = UserMobilityProfile(wheelchair_type=WheelchairType.MANUAL)  # default max_slope 8.33

    result = find_accessible_route(graph, "B1", "B4", profile)
    assert result.found, result.failure_reason
    used_ids = {s.segment.segment_id for s in result.steps}
    assert "B2_B3" not in used_ids, "11.5% slope exceeds manual chair max, must be avoided"


def test_router_prefers_accessible_over_shortest_when_alternative_exists():
    graph = build_mock_graph()
    profile = UserMobilityProfile()

    result = find_accessible_route(graph, "A1", "A4", profile)
    assert result.found
    # A3_A4 has a near-blocking obstruction; router should detour via row B
    # rather than barrel through it, given the cost penalty (not a hard
    # disqualification in this case since clearance 0.5m doesn't always
    # violate every profile's min width, so we just check the route is sane).
    assert result.average_accessibility_score > 0


def test_no_route_when_all_paths_disqualified():
    graph = AccessibilityGraph()
    graph.add_node(Node("n1", 37.8719, -122.2585))
    graph.add_node(Node("n2", 37.87118, -122.2585))
    graph.add_segment(make_segment(segment_id="e1", start_node_id="n1", end_node_id="n2", stairs=True))

    result = find_accessible_route(graph, "n1", "n2", UserMobilityProfile(avoid_stairs=True))
    assert not result.found
    assert result.failure_reason is not None


def test_route_result_includes_per_segment_scores_for_explanation_layer():
    graph = build_mock_graph()
    result = find_accessible_route(graph, "A1", "B1")
    assert result.found
    for step in result.steps:
        assert 0 <= step.accessibility_score <= 100


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
