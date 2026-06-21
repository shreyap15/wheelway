// Pure helpers for the real-route STAIR overlay. Kept free of mapbox-gl/React
// so it is unit-testable with `node --test`. The stair overlay is a distinct
// dashed layer drawn ON TOP of the slope colors -- it never replaces them.

// Honest status -> color for the dashed stair overlay (distinct from slope fills).
export const STAIR_STATUS_COLOR = {
  confirmed: "#b00020", // dark red
  likely: "#e8821f", // orange
  possible: "#caa83a", // amber
  unknown: "#7a7a7a", // grey
  not_detected: "#2f9b5f", // green (informational only; no overlay drawn)
};

// Honest, source-aware messages.
export const STAIR_STATUS_MESSAGE = {
  confirmed: "Confirmed stairs detected",
  likely: "Likely stairs based on OpenStreetMap",
  possible: "Possible stairs mentioned in route instructions",
  unknown: "Stair status unknown",
  not_detected: "No stairs detected by available sources",
};

export function stairStatusMessage(status) {
  return STAIR_STATUS_MESSAGE[status] || STAIR_STATUS_MESSAGE.unknown;
}

// Whether an overlay should be drawn (only when there is positive evidence).
export function hasStairOverlay(route) {
  return !!(
    route &&
    Array.isArray(route.stairs_segments) &&
    route.stairs_segments.length &&
    ["confirmed", "likely", "possible"].includes(route.stairs_status)
  );
}

// Dashed stair features for the selected route. Empty array when there is no
// positive evidence (so the slope coloring shows through untouched).
export function buildStairFeatures(route) {
  if (!hasStairOverlay(route)) return [];
  return route.stairs_segments
    .filter((s) => s && s.geometry && s.geometry.coordinates && s.geometry.coordinates.length)
    .map((s, i) => ({
      type: "Feature",
      properties: {
        kind: "stairs",
        index: i,
        status: s.status,
        confidence: s.confidence,
        sources: Array.isArray(s.sources) ? s.sources.join(", ") : "",
        color: STAIR_STATUS_COLOR[s.status] || STAIR_STATUS_COLOR.unknown,
      },
      geometry: s.geometry,
    }));
}

// Human list of distinct evidence sources, e.g. "openstreetmap, camera_cv".
export function stairSourceSummary(route) {
  if (!route || !Array.isArray(route.stairs_sources)) return "";
  const distinct = [...new Set(route.stairs_sources.map((e) => e.source))];
  return distinct.join(", ");
}
