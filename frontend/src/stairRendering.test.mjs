// Focused tests for the stair overlay helpers. Run:
//   node --test src/stairRendering.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  STAIR_STATUS_COLOR,
  buildStairFeatures,
  hasStairOverlay,
  stairSourceSummary,
  stairStatusMessage,
} from "./stairRendering.js";
import { buildSlopeFeatures } from "./slopeRendering.js";

const STAIR_SEG = {
  geometry: { type: "LineString", coordinates: [[-122.259, 37.869], [-122.258, 37.868]] },
  status: "confirmed",
  confidence: 0.94,
  sources: ["camera_cv"],
};

const SLOPE_SEG = {
  geometry: { type: "LineString", coordinates: [[-122.259, 37.869], [-122.258, 37.868]] },
  classification: "challenging",
  grade_pct: 6.1,
  absolute_grade_pct: 6.1,
  elevation_start_m: 10,
  elevation_end_m: 16,
  exceeds_user_limit: false,
};

test("buildStairFeatures emits dashed-overlay features when evidence exists", () => {
  const route = { stairs_status: "confirmed", stairs_segments: [STAIR_SEG] };
  const feats = buildStairFeatures(route);
  assert.equal(feats.length, 1);
  assert.equal(feats[0].properties.kind, "stairs");
  assert.equal(feats[0].properties.color, STAIR_STATUS_COLOR.confirmed);
  assert.equal(feats[0].properties.sources, "camera_cv");
  assert.deepEqual(feats[0].geometry, STAIR_SEG.geometry);
});

test("no overlay for not_detected / unknown", () => {
  assert.equal(hasStairOverlay({ stairs_status: "not_detected", stairs_segments: [] }), false);
  assert.equal(hasStairOverlay({ stairs_status: "unknown", stairs_segments: [] }), false);
  assert.deepEqual(buildStairFeatures({ stairs_status: "not_detected", stairs_segments: [STAIR_SEG] }), []);
});

test("stair overlay coexists with slope rendering (both produced)", () => {
  const route = {
    stairs_status: "likely",
    stairs_segments: [{ ...STAIR_SEG, status: "likely" }],
    slope_segments: [SLOPE_SEG],
  };
  const slope = buildSlopeFeatures(route);
  const stairs = buildStairFeatures(route);
  assert.equal(slope.length, 1); // slope colors still present
  assert.equal(stairs.length, 1); // stair overlay present
  assert.equal(slope[0].properties.kind, "slope");
  assert.equal(stairs[0].properties.kind, "stairs");
});

test("honest status messages", () => {
  assert.equal(stairStatusMessage("confirmed"), "Confirmed stairs detected");
  assert.equal(stairStatusMessage("likely"), "Likely stairs based on OpenStreetMap");
  assert.equal(stairStatusMessage("possible"), "Possible stairs mentioned in route instructions");
  assert.equal(stairStatusMessage("unknown"), "Stair status unknown");
  assert.equal(stairStatusMessage("not_detected"), "No stairs detected by available sources");
});

test("stairSourceSummary lists distinct sources", () => {
  const route = {
    stairs_sources: [
      { source: "openstreetmap" },
      { source: "camera_cv" },
      { source: "camera_cv" },
    ],
  };
  assert.equal(stairSourceSummary(route), "openstreetmap, camera_cv");
});
