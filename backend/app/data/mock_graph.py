"""
WheelWay — Curated demo accessibility graph (Lower Sproul Plaza, UC Berkeley).

A small, hand-curated pedestrian network around Lower/Upper Sproul Plaza. It
replaces the old synthetic A1-D4 grid so routes drawn on the Mapbox basemap sit
on visible walkways instead of cutting across buildings.

================================ DATA PROVENANCE ===============================
TRACED (approximate, NOT survey-grade):
  - Node lat/lon and every segment `geometry` LineString were hand-traced from
    the public basemap/satellite imagery of the Sproul Plaza area. They are
    eyeballed to follow visible paths; they are not GPS-surveyed and may be off
    by several meters.

MOCKED (illustrative only — NO verified/audited source):
  - EVERY accessibility attribute below is fabricated for demo purposes:
    slope, cross_slope, width, surface, surface_condition, curb_ramp, stairs,
    has_obstruction, obstruction_clearance_m, construction_risk.
  - These do NOT come from any accessibility audit, PROWAG survey, or sensor
    pass. Do not treat them as real conditions on the ground.
  - `length_m` is derived from the traced geometry (sum of haversine hops), so
    it is as approximate as the tracing.

When real data lands (OSM ways + a CV/audit pass), replace this whole module;
the Segment model and the /route serialization contract stay the same.
===============================================================================

Layout (node id -> place):

  sather_gate ── sproul_plaza
                   │   ╲
        (stairs)   │    ╲ (ramp, accessible)
                   │     ╲
              student_union ── lower_sproul
                   │  (steep)  │   ╲(narrow)
                   │           │    ╲
                 eshleman ─────┘     │
                   │  (obstruction)  │
               zellerbach            │ (rough)
                   │                 │
              bancroft_dana ─────────┘
                   │ (accessible sidewalk)
              bancroft_tele
"""

from __future__ import annotations

import math

from app.models.accessibility import LineStringGeometry, Segment, SurfaceType
from app.routing.graph import AccessibilityGraph, Node

# --- TRACED node positions (lat, lon, human-readable name) --------------------
# Approximate, hand-traced from the basemap. Not survey-grade.
NODES: dict[str, tuple[float, float, str]] = {
    "sather_gate": (37.86998, -122.25919, "Sather Gate"),
    "sproul_plaza": (37.86945, -122.25898, "Upper Sproul Plaza"),
    "student_union": (37.86888, -122.25948, "MLK Jr. Student Union"),
    "lower_sproul": (37.86876, -122.25902, "Lower Sproul Plaza"),
    "eshleman": (37.86848, -122.25968, "Eshleman Hall"),
    "zellerbach": (37.86902, -122.26030, "Zellerbach Hall"),
    "bancroft_dana": (37.86828, -122.25995, "Bancroft Way & Dana St"),
    "bancroft_tele": (37.86842, -122.25858, "Bancroft Way & Telegraph Ave"),
}

# --- TRACED walkway geometries (GeoJSON [lon, lat], start -> end) -------------
# Each follows a visible path. The first/last vertex match the node positions.
_GEOMETRY: dict[tuple[str, str], list[list[float]]] = {
    ("sather_gate", "sproul_plaza"): [
        [-122.25919, 37.86998], [-122.25908, 37.86970], [-122.25898, 37.86945],
    ],
    ("sproul_plaza", "student_union"): [
        [-122.25898, 37.86945], [-122.25918, 37.86918], [-122.25948, 37.86888],
    ],
    ("sproul_plaza", "lower_sproul"): [
        [-122.25898, 37.86945], [-122.25884, 37.86911], [-122.25902, 37.86876],
    ],
    ("lower_sproul", "student_union"): [
        [-122.25902, 37.86876], [-122.25926, 37.86882], [-122.25948, 37.86888],
    ],
    ("lower_sproul", "eshleman"): [
        [-122.25902, 37.86876], [-122.25935, 37.86862], [-122.25968, 37.86848],
    ],
    ("student_union", "eshleman"): [
        [-122.25948, 37.86888], [-122.25959, 37.86868], [-122.25968, 37.86848],
    ],
    ("eshleman", "zellerbach"): [
        [-122.25968, 37.86848], [-122.26001, 37.86876], [-122.26030, 37.86902],
    ],
    ("lower_sproul", "bancroft_dana"): [
        [-122.25902, 37.86876], [-122.25949, 37.86852], [-122.25995, 37.86828],
    ],
    ("eshleman", "bancroft_dana"): [
        [-122.25968, 37.86848], [-122.25982, 37.86838], [-122.25995, 37.86828],
    ],
    ("bancroft_dana", "bancroft_tele"): [
        [-122.25995, 37.86828], [-122.25925, 37.86835], [-122.25858, 37.86842],
    ],
    ("zellerbach", "bancroft_dana"): [
        [-122.26030, 37.86902], [-122.26013, 37.86865], [-122.25995, 37.86828],
    ],
}

# --- Per-segment MOCKED accessibility attributes -----------------------------
# value = (start, end, label, attribute overrides). ALL attributes are fabricated.
_SEGMENTS: list[tuple[str, str, str, dict]] = [
    # Wide, gentle promenade — the accessible spine. (MOCKED)
    ("sather_gate", "sproul_plaza", "Sproul Plaza Promenade",
     dict(slope=1.5, width=3.0, surface=SurfaceType.CONCRETE, surface_condition=0.95)),

    # STAIRS between upper and lower plaza levels. (MOCKED)
    ("sproul_plaza", "student_union", "Lower Sproul Steps",
     dict(stairs=True, curb_ramp=False, slope=0.0, width=2.0,
          surface=SurfaceType.CONCRETE, surface_condition=0.9)),

    # Accessible RAMP alternative to the stairs. (MOCKED)
    ("sproul_plaza", "lower_sproul", "Sproul Accessible Ramp",
     dict(slope=4.5, width=1.8, surface=SurfaceType.CONCRETE, surface_condition=0.9)),

    # Flat plaza walk. (MOCKED)
    ("lower_sproul", "student_union", "Lower Sproul Plaza Walk",
     dict(slope=1.0, width=2.5, surface=SurfaceType.CONCRETE, surface_condition=0.95)),

    # NARROW pinch passage below ADA minimum. (MOCKED)
    ("lower_sproul", "eshleman", "Eshleman Passage",
     dict(slope=2.0, width=0.75, surface=SurfaceType.CONCRETE, surface_condition=0.85)),

    # STEEP incline above the manual-chair ceiling. (MOCKED)
    ("student_union", "eshleman", "Union West Incline",
     dict(slope=10.5, cross_slope=2.5, width=1.5,
          surface=SurfaceType.CONCRETE, surface_condition=0.9)),

    # OBSTRUCTED / construction zone. (MOCKED)
    ("eshleman", "zellerbach", "Zellerbach Construction Walk",
     dict(slope=2.0, width=1.5, has_obstruction=True, obstruction_clearance_m=0.6,
          construction_risk=0.8, surface=SurfaceType.CONCRETE, surface_condition=0.7)),

    # ROUGH surface (gravel, cracked) — passable but low-scoring; this is the
    # accessible alternative the router falls back to. cross_slope kept within
    # the default 2.0% ceiling so it is NOT hard-disqualified. (MOCKED)
    ("lower_sproul", "bancroft_dana", "Lower Sproul to Bancroft Path",
     dict(slope=2.0, cross_slope=1.5, width=1.4,
          surface=SurfaceType.GRAVEL, surface_condition=0.4)),

    # Accessible connector. (MOCKED)
    ("eshleman", "bancroft_dana", "Eshleman South Path",
     dict(slope=2.0, width=1.6, surface=SurfaceType.CONCRETE, surface_condition=0.9)),

    # Accessible street sidewalk. (MOCKED)
    ("bancroft_dana", "bancroft_tele", "Bancroft Way Sidewalk",
     dict(slope=1.0, width=2.5, surface=SurfaceType.CONCRETE, surface_condition=0.95)),

    # Accessible connector. (MOCKED)
    ("zellerbach", "bancroft_dana", "Zellerbach South Walk",
     dict(slope=3.0, width=1.8, surface=SurfaceType.CONCRETE, surface_condition=0.9)),
]

EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _polyline_length_m(coords: list[list[float]]) -> float:
    total = 0.0
    for (lon_a, lat_a), (lon_b, lat_b) in zip(coords, coords[1:]):
        total += _haversine_m(lat_a, lon_a, lat_b, lon_b)
    return round(total, 1)


def build_mock_graph() -> AccessibilityGraph:
    graph = AccessibilityGraph()

    for node_id, (lat, lon, name) in NODES.items():
        graph.add_node(Node(node_id=node_id, lat=lat, lon=lon, name=name))

    for n1, n2, _label, attrs in _SEGMENTS:
        coords = _GEOMETRY[(n1, n2)]
        # length derived from the traced geometry; keeps A* heuristic admissible
        # (polyline length >= straight-line endpoint distance).
        length_m = _polyline_length_m(coords)
        seg_attrs = dict(
            length_m=length_m,
            slope=2.0,
            cross_slope=1.0,
            width=1.52,
            surface=SurfaceType.CONCRETE,
            surface_condition=0.9,
            curb_ramp=True,
        )
        seg_attrs.update(attrs)
        graph.add_segment(
            Segment(
                segment_id=f"{n1}__{n2}",
                start_node_id=n1,
                end_node_id=n2,
                geometry=LineStringGeometry(coordinates=coords),
                **seg_attrs,
            )
        )

    return graph


if __name__ == "__main__":
    g = build_mock_graph()
    print(f"Built demo graph: {len(g.nodes)} nodes, {len(g)} directed segments")
