"""
WheelWay — Mock accessibility graph fixture.

Generates a small synthetic grid of nodes/segments resembling a few campus
blocks, with a deliberate mix of great, mediocre, and bad-accessibility
segments (including one with stairs and one steep hill) so the A* router has
something interesting to route around. Use this for frontend/demo work and
for unit tests while OSM ingestion + CV pipeline aren't wired up yet.

Layout (rough ASCII, 4x4 grid of intersections, ~80m apart):

  A1 --- A2 --- A3 --- A4
  |      |      |      |
  B1 --- B2 --- B3 --- B4
  |      |      |      |
  C1 --- C2 --- C3 --- C4
  |      |      |      |
  D1 --- D2 --- D3 --- D4

Base coordinates are near UC Berkeley (37.8719 N, -122.2585 W) purely for
realistic lat/lon math; not real sidewalk data.
"""

from __future__ import annotations

from app.models.accessibility import Segment, SurfaceType
from app.routing.graph import AccessibilityGraph, Node

BASE_LAT = 37.8719
BASE_LON = -122.2585

# ~0.00072 deg lat ~= 80m; lon spacing adjusted for latitude
LAT_STEP = 0.00072
LON_STEP = 0.00091
SIDEWALK_JOG = 0.00004


def build_mock_graph() -> AccessibilityGraph:
    graph = AccessibilityGraph()

    rows = ["A", "B", "C", "D"]
    cols = [1, 2, 3, 4]

    for r_idx, row in enumerate(rows):
        for c_idx, col in enumerate(cols):
            node_id = f"{row}{col}"
            graph.add_node(
                Node(
                    node_id=node_id,
                    lat=BASE_LAT - r_idx * LAT_STEP,
                    lon=BASE_LON + c_idx * LON_STEP,
                    elevation_m=52.0 + c_idx * 0.35 - r_idx * 0.22,
                    name=f"Intersection {node_id}",
                )
            )

    def segment_geometry(n1, n2):
        start = graph.get_node(n1)
        end = graph.get_node(n2)
        if start is None or end is None:
            raise ValueError(f"Missing node for segment geometry: {n1}->{n2}")

        mid_lat = (start.lat + end.lat) / 2
        mid_lon = (start.lon + end.lon) / 2
        mid_elevation = ((start.elevation_m or 0) + (end.elevation_m or 0)) / 2

        if abs(start.lat - end.lat) > abs(start.lon - end.lon):
            mid_lon += SIDEWALK_JOG
        else:
            mid_lat += SIDEWALK_JOG

        return {
            "type": "LineString",
            "coordinates": [
                (start.lon, start.lat, start.elevation_m or 0),
                (mid_lon, mid_lat, mid_elevation + 0.08),
                (end.lon, end.lat, end.elevation_m or 0),
            ],
        }

    def seg(seg_id, n1, n2, **kwargs):
        defaults = dict(
            length_m=80.0,
            geometry=segment_geometry(n1, n2),
            slope=2.0,
            cross_slope=1.0,
            width=1.52,
            surface=SurfaceType.CONCRETE,
            surface_condition=0.9,
            curb_ramp=True,
        )
        defaults.update(kwargs)
        graph.add_segment(
            Segment(segment_id=seg_id, start_node_id=n1, end_node_id=n2, **defaults)
        )

    # Horizontal segments (within each row)
    for row in rows:
        for c in range(1, 4):
            n1, n2 = f"{row}{c}", f"{row}{c+1}"
            seg(f"{n1}_{n2}", n1, n2)

    # Vertical segments (between rows)
    for r in range(len(rows) - 1):
        for col in cols:
            n1, n2 = f"{rows[r]}{col}", f"{rows[r+1]}{col}"
            seg(f"{n1}_{n2}", n1, n2)

    # --- Deliberate accessibility problem spots for demo/testing ---

    # A steep hill on B2->B3 (exceeds ADA ramp max of 8.33%)
    graph.update_segment("B2_B3", slope=11.5, cross_slope=3.0)

    # Stairs on C1->C2 (should be fully avoided by any wheelchair profile)
    graph.update_segment("C1_C2", stairs=True, curb_ramp=False, slope=0.0)

    # Construction / temporary obstruction on A3->A4
    graph.update_segment(
        "A3_A4", has_obstruction=True, obstruction_clearance_m=0.5, construction_risk=0.8
    )

    # Poor surface (gravel, cracked) on D2->D3
    graph.update_segment(
        "D2_D3", surface=SurfaceType.GRAVEL, surface_condition=0.4, cross_slope=3.5
    )

    # A pristine, ideal "gold standard" path on row A (except the obstruction)
    graph.update_segment("A1_A2", slope=1.0, cross_slope=0.5, surface_condition=0.98)

    # A narrow pinch point below ADA minimum on B1->B2
    graph.update_segment("B1_B2", width=0.7)

    return graph


if __name__ == "__main__":
    g = build_mock_graph()
    print(f"Built mock graph: {len(g.nodes)} nodes, {len(g)} directed segments")
