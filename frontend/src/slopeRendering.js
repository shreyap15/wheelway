// Pure helpers for rendering the real-route by LOCAL slope.
//
// Kept free of mapbox-gl / React so the grouping + fallback logic is unit
// testable with `node --test`. The map component (RealRoutePlanner.jsx) feeds
// the returned GeoJSON features straight into mapbox sources.

// Classification -> color. green / yellow / orange / red per the slope bands.
export const SLOPE_COLORS = {
  low: "#2f9b5f", // green   (< 3%)
  moderate: "#e8c44a", // yellow  (3% – <5%)
  challenging: "#e8821f", // orange  (5% – user max)
  exceeds_limit: "#d94444", // red     (> user max)
  unavailable: "#6d9eca", // neutral (no elevation data)
};

export const SLOPE_LABELS = {
  low: "Low (<3%)",
  moderate: "Moderate (3–5%)",
  challenging: "Challenging (5%–limit)",
  exceeds_limit: "Exceeds your limit",
};

// Whether a route carries usable per-segment slope data.
export function hasSlopeData(route) {
  return !!(route && Array.isArray(route.slope_segments) && route.slope_segments.length);
}

// One colored Feature per slope_segment of a route. Empty array when slope data
// is unavailable (the caller renders a fallback line instead).
export function buildSlopeFeatures(route) {
  if (!hasSlopeData(route)) return [];
  return route.slope_segments.map((s, i) => ({
    type: "Feature",
    properties: {
      kind: "slope",
      index: i,
      classification: s.classification,
      color: SLOPE_COLORS[s.classification] || SLOPE_COLORS.low,
      grade_pct: s.grade_pct,
      absolute_grade_pct: s.absolute_grade_pct,
      elevation_start_m: s.elevation_start_m,
      elevation_end_m: s.elevation_end_m,
      exceeds_user_limit: !!s.exceeds_user_limit,
    },
    geometry: s.geometry,
  }));
}

// Full-route casing/outline features for every route. The selected route gets a
// thick dark casing (drawn beneath the colored slope sections); alternatives
// stay thin and grey so they remain distinguishable. Sorted so the selected
// casing is appended last (rendered on top of the alternatives).
export function buildCasingFeatures(routes, selectedId) {
  if (!Array.isArray(routes) || !routes.length) return [];
  return routes
    .filter((r) => r && r.geometry)
    .map((r) => {
      const isSel = r.route_id === selectedId;
      return {
        type: "Feature",
        properties: {
          kind: "casing",
          route_id: r.route_id,
          selected: isSel,
          color: isSel ? "#10243a" : "#9aa6a0",
          width: isSel ? 9 : 3,
          opacity: isSel ? 1 : 0.5,
        },
        geometry: r.geometry,
      };
    })
    .sort((a, b) => Number(a.properties.selected) - Number(b.properties.selected));
}

// Overlay drawn ON TOP of the selected route's casing: the colored slope
// sections when present, otherwise a single fallback line colored by the
// route's accessibility score and tagged "unavailable".
export function buildSelectedOverlayFeatures(route, scoreColorFn) {
  const slopes = buildSlopeFeatures(route);
  if (slopes.length) return slopes;
  if (!route || !route.geometry) return [];
  return [
    {
      type: "Feature",
      properties: {
        kind: "fallback",
        classification: "unavailable",
        color: scoreColorFn ? scoreColorFn(route.accessibility_score) : SLOPE_COLORS.unavailable,
      },
      geometry: route.geometry,
    },
  ];
}
