// Tests for place-search pure helpers + mode separation. Run:
//   node --test src/placeSearch.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import {
  buildGeocodeUrl,
  parseGeocodeResults,
  isLatestResponse,
  swapPlaces,
  canRequestRoute,
} from "./placeSearch.js";
import { REAL_MODE_LABEL, SYNTHETIC_MODE_LABEL } from "./syntheticMode.js";

const HERE = dirname(fileURLToPath(import.meta.url));

test("buildGeocodeUrl encodes query and includes token + autocomplete", () => {
  const url = buildGeocodeUrl("Sproul Hall", "pk.test", { proximity: [-122.25, 37.87] });
  assert.ok(url.includes("Sproul%20Hall"));
  assert.ok(url.includes("access_token=pk.test"));
  assert.ok(url.includes("autocomplete=true"));
  assert.ok(url.includes("proximity=-122.25%2C37.87") || url.includes("proximity=-122.25,37.87"));
});

test("parseGeocodeResults yields valid coordinates from features (Task 6.8)", () => {
  const json = {
    features: [
      { id: "a", text: "Sproul", place_name: "Sproul Hall, Berkeley", center: [-122.2590, 37.8695] },
      { id: "b", text: "NoCoord", place_name: "bad" }, // dropped (no center)
    ],
  };
  const results = parseGeocodeResults(json);
  assert.equal(results.length, 1);
  assert.equal(results[0].lat, 37.8695);
  assert.equal(results[0].lng, -122.2590);
  assert.equal(results[0].name, "Sproul");
  assert.equal(results[0].address, "Sproul Hall, Berkeley");
});

test("stale autocomplete responses are ignored (Task 6.9)", () => {
  // request seq 1 issued, then seq 2; seq 2 applied -> seq 1 is stale.
  let latestApplied = 2;
  assert.equal(isLatestResponse(1, latestApplied), false); // stale, ignore
  assert.equal(isLatestResponse(2, latestApplied), true); // newest, apply
  assert.equal(isLatestResponse(3, latestApplied), true);
});

test("swap origin/destination (Task 6.11)", () => {
  const o = { name: "A", lat: 1, lng: 2 };
  const d = { name: "B", lat: 3, lng: 4 };
  const [no, nd] = swapPlaces(o, d);
  assert.equal(no.name, "B");
  assert.equal(nd.name, "A");
});

test("route requires two valid selected coordinates", () => {
  assert.equal(canRequestRoute(null, { lat: 1, lng: 2 }), false);
  assert.equal(canRequestRoute({ lat: 1, lng: 2 }, { lat: 3, lng: 4 }), true);
  assert.equal(canRequestRoute({ lat: NaN, lng: 2 }, { lat: 3, lng: 4 }), false);
});

test("real mode does NOT import graphNodes; synthetic mode does (Task 6.15)", () => {
  const real = readFileSync(join(HERE, "RealRoutePlanner.jsx"), "utf8");
  const synth = readFileSync(join(HERE, "RoutePlanner.jsx"), "utf8");
  // Match the module-resolution `from "./graphNodes"` (handles multi-line
  // imports; ignores prose comments).
  assert.equal(/from\s+["']\.\/graphNodes/.test(real), false);
  assert.ok(/from\s+["']\.\/graphNodes/.test(synth)); // synthetic depends on it
});

test("real and synthetic are separate components rendered conditionally (Task 6.14)", () => {
  const app = readFileSync(join(HERE, "App.jsx"), "utf8");
  // Conditional render -> the inactive mode unmounts, so no state leak. Real is
  // the default; synthetic mounts only when its dev flag is on (and lazy-loaded).
  assert.ok(app.includes("showSynthetic ?"));
  assert.ok(app.includes("<RealRoutePlanner />"));
  assert.ok(/SYNTHETIC_ENABLED\s*&&\s*routeMode === "demo"/.test(app));
  assert.notEqual(REAL_MODE_LABEL, SYNTHETIC_MODE_LABEL);
});
