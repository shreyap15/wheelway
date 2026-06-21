// Focused logic tests for the real-route slope rendering helpers and the
// synthetic-mode labels. Runs with Node's built-in runner (no framework):
//   node --test src/slopeRendering.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  SLOPE_COLORS,
  buildCasingFeatures,
  buildSelectedOverlayFeatures,
  buildSlopeFeatures,
  hasSlopeData,
} from "./slopeRendering.js";
import {
  SYNTHETIC_MODE_LABEL,
  SYNTHETIC_MODE_NOTE,
} from "./syntheticMode.js";

const SEG = {
  geometry: { type: "LineString", coordinates: [[-122.25, 37.5], [-122.24, 37.51]] },
  start_index: 0,
  end_index: 1,
  grade_pct: 6.2,
  absolute_grade_pct: 6.2,
  elevation_start_m: 100,
  elevation_end_m: 106,
  classification: "challenging",
  exceeds_user_limit: false,
};

test("buildSlopeFeatures preserves geometry and maps classification to color", () => {
  const features = buildSlopeFeatures({ slope_segments: [SEG] });
  assert.equal(features.length, 1);
  // Geometry passed through exactly ([lng, lat] as returned by the backend).
  assert.deepEqual(features[0].geometry, SEG.geometry);
  assert.equal(features[0].geometry.coordinates[0][0], -122.25); // lng first
  assert.equal(features[0].properties.color, SLOPE_COLORS.challenging);
  assert.equal(features[0].properties.grade_pct, 6.2);
});

test("fallback overlay used when slope_segments is empty", () => {
  const route = {
    geometry: { type: "LineString", coordinates: [[-122.2, 37.8], [-122.1, 37.9]] },
    accessibility_score: 72,
    slope_segments: [],
  };
  assert.equal(hasSlopeData(route), false);
  const overlay = buildSelectedOverlayFeatures(route, () => "#abc123");
  assert.equal(overlay.length, 1);
  assert.equal(overlay[0].properties.classification, "unavailable");
  assert.equal(overlay[0].properties.color, "#abc123");
  // Falls back to the full route geometry (geometry preserved, not fabricated).
  assert.deepEqual(overlay[0].geometry, route.geometry);
});

test("colored sections used when slope_segments present", () => {
  const overlay = buildSelectedOverlayFeatures({ slope_segments: [SEG] }, () => "#000");
  assert.equal(overlay.length, 1);
  assert.equal(overlay[0].properties.kind, "slope");
});

test("casing keeps alternatives distinguishable and selected on top", () => {
  const routes = [
    { route_id: "route-1", geometry: { type: "LineString", coordinates: [] } },
    { route_id: "route-2", geometry: { type: "LineString", coordinates: [] } },
  ];
  const casing = buildCasingFeatures(routes, "route-2");
  const sel = casing.find((f) => f.properties.route_id === "route-2");
  const alt = casing.find((f) => f.properties.route_id === "route-1");
  assert.equal(sel.properties.selected, true);
  assert.equal(alt.properties.selected, false);
  assert.notEqual(sel.properties.color, alt.properties.color); // distinguishable
  assert.ok(sel.properties.width > alt.properties.width);
  // Selected appended last so it renders above the alternatives.
  assert.equal(casing[casing.length - 1].properties.route_id, "route-2");
});

test("renders one selected (thick) and faded alternatives", () => {
  const routes = [
    { route_id: "route-1", geometry: { type: "LineString", coordinates: [] } },
    { route_id: "route-2", geometry: { type: "LineString", coordinates: [] } },
    { route_id: "route-3", geometry: { type: "LineString", coordinates: [] } },
  ];
  const casing = buildCasingFeatures(routes, "route-2");
  const selected = casing.filter((f) => f.properties.selected);
  const faded = casing.filter((f) => !f.properties.selected);
  assert.equal(selected.length, 1); // exactly one selected
  assert.equal(faded.length, 2); // others faded
  assert.ok(selected[0].properties.width > faded[0].properties.width);
  assert.ok(selected[0].properties.opacity > faded[0].properties.opacity);
});

test("selecting a different alternative flips which is thick (simulated click)", () => {
  const routes = [
    { route_id: "route-1", geometry: { type: "LineString", coordinates: [] } },
    { route_id: "route-2", geometry: { type: "LineString", coordinates: [] } },
  ];
  const before = buildCasingFeatures(routes, "route-1");
  const after = buildCasingFeatures(routes, "route-2"); // user clicked route-2
  const selBefore = before.find((f) => f.properties.selected).properties.route_id;
  const selAfter = after.find((f) => f.properties.selected).properties.route_id;
  assert.equal(selBefore, "route-1");
  assert.equal(selAfter, "route-2");
  // Only the selected route gets detailed slope coloring at a time.
  const overlay = buildSlopeFeatures(routes.find((r) => r.route_id === "route-2"));
  assert.equal(overlay.length, 0); // no slope_segments on this stub -> fallback handled elsewhere
});

test("synthetic mode label and disclosure are present", () => {
  assert.equal(
    SYNTHETIC_MODE_LABEL,
    "Accessibility Algorithm Demo — simulated path conditions",
  );
  const joined = SYNTHETIC_MODE_NOTE.join(" ").toLowerCase();
  assert.ok(joined.includes("a* algorithm"));
  assert.ok(joined.includes("mocked"));
  assert.ok(joined.includes("not a verified accessibility audit"));
  assert.ok(joined.includes("mapbox") && joined.includes("google elevation"));
});
