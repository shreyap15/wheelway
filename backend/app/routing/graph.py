"""
WheelWay — Accessibility Graph.

A lightweight in-memory graph wrapping the Segment model. This is the
in-process representation the A* router operates on. In production this
would be backed by PostGIS (per docker-compose.yml), but the graph interface
here is storage-agnostic: build it from a DB query, from OSM extraction, or
from the mock fixture data in app/data/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.models.accessibility import Segment


@dataclass
class Node:
    node_id: str
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    is_building_entrance: bool = False
    has_elevator: bool = False
    name: Optional[str] = None


class AccessibilityGraph:
    """
    Undirected-by-default graph (most sidewalks are traversable both ways,
    though slope sign flips — handled by storing direction-aware copies).
    """

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        # adjacency: node_id -> list of (neighbor_node_id, Segment)
        self._adjacency: dict[str, list[tuple[str, Segment]]] = {}
        self._segments_by_id: dict[str, Segment] = {}

    def add_node(self, node: Node) -> None:
        self.nodes[node.node_id] = node
        self._adjacency.setdefault(node.node_id, [])

    def add_segment(self, segment: Segment, bidirectional: bool = True) -> None:
        """
        Adds a segment as a forward edge start->end. If bidirectional, also
        adds a reversed copy end->start with slope negated (since climbing a
        hill one way is descending it the other way).
        """
        self._segments_by_id[segment.segment_id] = segment
        self._adjacency.setdefault(segment.start_node_id, [])
        self._adjacency.setdefault(segment.end_node_id, [])
        self._adjacency[segment.start_node_id].append((segment.end_node_id, segment))

        if bidirectional:
            reversed_segment = segment.model_copy(
                update={
                    "segment_id": segment.segment_id + "_rev",
                    "start_node_id": segment.end_node_id,
                    "end_node_id": segment.start_node_id,
                    "slope": -segment.slope,
                    "geometry": segment.geometry.model_copy(
                        update={
                            "coordinates": list(reversed(segment.geometry.coordinates)),
                        }
                    ),
                    "surface_samples": list(reversed(segment.surface_samples)),
                }
            )
            self._segments_by_id[reversed_segment.segment_id] = reversed_segment
            self._adjacency[segment.end_node_id].append((segment.start_node_id, reversed_segment))

    def neighbors(self, node_id: str) -> list[tuple[str, Segment]]:
        return self._adjacency.get(node_id, [])

    def get_segment(self, segment_id: str) -> Optional[Segment]:
        return self._segments_by_id.get(segment_id)

    def get_node(self, node_id: str) -> Optional[Node]:
        return self.nodes.get(node_id)

    def _replace_segment(self, segment_id: str, updated: Segment) -> None:
        self._segments_by_id[segment_id] = updated
        for node_id in (updated.start_node_id, updated.end_node_id):
            adj = self._adjacency.get(node_id, [])
            for i, (neighbor, seg) in enumerate(adj):
                if seg.segment_id == segment_id:
                    adj[i] = (neighbor, updated)

    def update_segment(self, segment_id: str, **updates) -> None:
        """
        Used by the CV/real-time pipeline to push live updates (e.g. a newly
        detected obstruction or construction zone) into the graph.
        """
        existing = self._segments_by_id.get(segment_id)
        if existing is None:
            return
        updated = existing.model_copy(update=updates)
        self._replace_segment(segment_id, updated)

        reverse_id = (
            segment_id[:-4] if segment_id.endswith("_rev") else segment_id + "_rev"
        )
        reverse = self._segments_by_id.get(reverse_id)
        if reverse is None:
            return

        reverse_updates = dict(updates)
        if "slope" in reverse_updates:
            reverse_updates["slope"] = -reverse_updates["slope"]
        if "geometry" in reverse_updates:
            reverse_updates["geometry"] = reverse_updates["geometry"].model_copy(
                update={
                    "coordinates": list(reversed(reverse_updates["geometry"].coordinates)),
                }
            )
        if "surface_samples" in reverse_updates:
            reverse_updates["surface_samples"] = list(reversed(reverse_updates["surface_samples"]))

        self._replace_segment(reverse_id, reverse.model_copy(update=reverse_updates))

    def __len__(self) -> int:
        return len(self._segments_by_id)
