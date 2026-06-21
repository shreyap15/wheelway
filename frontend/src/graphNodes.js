/**
 * Demo graph nodes — mirrors backend/app/data/mock_graph.py (Lower Sproul area).
 *
 * Used only for the start/destination dropdown labels, the initial map fit, and
 * a straight-line fallback if a segment ever lacks geometry. The drawn route
 * shape itself comes from each segment's backend `geometry` LineString.
 *
 * Coordinates are hand-traced (approximate). Keep in sync with NODES in the
 * backend until a real /nodes endpoint exists.
 */

// id -> { lat, lon, name }
export const GRAPH_NODES = {
  sather_gate: { lat: 37.86998, lon: -122.25919, name: "Sather Gate" },
  sproul_plaza: { lat: 37.86945, lon: -122.25898, name: "Upper Sproul Plaza" },
  student_union: { lat: 37.86888, lon: -122.25948, name: "MLK Jr. Student Union" },
  lower_sproul: { lat: 37.86876, lon: -122.25902, name: "Lower Sproul Plaza" },
  eshleman: { lat: 37.86848, lon: -122.25968, name: "Eshleman Hall" },
  zellerbach: { lat: 37.86902, lon: -122.26030, name: "Zellerbach Hall" },
  bancroft_dana: { lat: 37.86828, lon: -122.25995, name: "Bancroft Way & Dana St" },
  bancroft_tele: { lat: 37.86842, lon: -122.25858, name: "Bancroft Way & Telegraph Ave" },
};

// Ordered list for the dropdowns: { id, name }.
export const NODES = Object.entries(GRAPH_NODES).map(([id, n]) => ({
  id,
  name: n.name,
}));

export const NODE_IDS = NODES.map((n) => n.id);

// Mapbox expects [lon, lat]. Returns null for unknown ids.
export function nodeLngLat(nodeId) {
  const n = GRAPH_NODES[nodeId];
  return n ? [n.lon, n.lat] : null;
}

// Bounding box of the whole network, for the initial viewport fit:
// [[minLon, minLat], [maxLon, maxLat]].
const lons = Object.values(GRAPH_NODES).map((n) => n.lon);
const lats = Object.values(GRAPH_NODES).map((n) => n.lat);
export const NETWORK_BOUNDS = [
  [Math.min(...lons), Math.min(...lats)],
  [Math.max(...lons), Math.max(...lats)],
];

export const GRAPH_CENTER = [
  (Math.min(...lons) + Math.max(...lons)) / 2,
  (Math.min(...lats) + Math.max(...lats)) / 2,
];
