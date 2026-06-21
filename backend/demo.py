"""
WheelWay — Demo script.

Run from the repo root:
  python backend/demo.py
  python -m backend.demo

Shows the scoring engine and A* router working together on the mock graph,
for two different mobility profiles, to illustrate that the route actually
changes based on user constraints (not just distance).
"""

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.data.mock_graph import build_mock_graph
from app.models.accessibility import UserMobilityProfile, WheelchairType
from app.routing.astar import find_accessible_route
from app.scoring.engine import explain_segment


def print_route(label: str, result):
    print(f"\n=== {label} ===")
    if not result.found:
        print(f"  NO ROUTE FOUND: {result.failure_reason}")
        return
    print(f"  distance: {result.total_distance_m}m | cost: {result.total_cost} | "
          f"avg accessibility score: {result.average_accessibility_score}/100 | "
          f"nodes expanded: {result.nodes_expanded}")
    for step in result.steps:
        seg = step.segment
        flags = []
        if seg.stairs:
            flags.append("STAIRS")
        if seg.has_obstruction:
            flags.append("OBSTRUCTION")
        if abs(seg.slope) > 8.33:
            flags.append("STEEP")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        print(f"    {seg.start_node_id} -> {seg.end_node_id} "
              f"(score={step.accessibility_score}, slope={seg.slope}%, "
              f"cross_slope={seg.cross_slope}%, surface={seg.surface.value}){flag_str}")


def main():
    graph = build_mock_graph()
    print(f"Mock graph built: {len(graph.nodes)} nodes, {len(graph)} directed segments")

    manual_profile = UserMobilityProfile(wheelchair_type=WheelchairType.MANUAL)
    powered_profile = UserMobilityProfile(
        wheelchair_type=WheelchairType.POWERED, max_slope_pct=12.0, max_cross_slope_pct=4.0
    )

    print_route("Manual wheelchair: A1 -> D2", find_accessible_route(graph, "A1", "D2", manual_profile))
    print_route("Powered wheelchair: A1 -> D2", find_accessible_route(graph, "A1", "D2", powered_profile))
    print_route("Manual wheelchair: B1 -> B4 (steep hill in the way)",
                find_accessible_route(graph, "B1", "B4", manual_profile))

    print("\n=== Segment explanation example (for Claude reasoning layer) ===")
    seg = graph.get_segment("B2_B3")
    print(explain_segment(seg, manual_profile))


if __name__ == "__main__":
    main()
