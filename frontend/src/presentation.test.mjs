// Presentation-UI guarantees. Pure-function + source-scan style (no DOM), run:
//   node --test src/presentation.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { syntheticDemoEnabled } from "./syntheticMode.js";
import { diagnosticsVisible } from "./services/diagnostics.js";

const SRC = dirname(fileURLToPath(import.meta.url)); // .../src
const read = (rel) => readFileSync(join(SRC, rel), "utf8");

test("synthetic demo is hidden by default, enabled only by its flag", () => {
  assert.equal(syntheticDemoEnabled({}), false);
  assert.equal(syntheticDemoEnabled({ VITE_ENABLE_SYNTHETIC_DEMO: "" }), false);
  assert.equal(syntheticDemoEnabled({ VITE_ENABLE_SYNTHETIC_DEMO: "true" }), true);
});

test("diagnostics are hidden by default, enabled only by its flag", () => {
  assert.equal(diagnosticsVisible({}), false);
  assert.equal(diagnosticsVisible({ VITE_SHOW_DIAGNOSTICS: "true" }), true);
});

test("App mounts the live camera obstacle-detection status in the presentation UI", () => {
  const app = read("App.jsx");
  assert.match(app, /<VisionStatus observations=\{observations\} \/>/);
  assert.match(app, /import VisionStatus from "\.\/components\/VisionStatus"/);
});

test("App defaults to real mode and gates synthetic behind the flag + lazy load", () => {
  const app = read("App.jsx");
  // Real route is the default mode.
  assert.match(app, /useState\("real"\)/);
  // Synthetic component is lazy-loaded (its chunk isn't fetched in presentation).
  assert.match(app, /lazy\(\(\)\s*=>\s*import\(["']\.\/RoutePlanner["']\)\)/);
  // Mode switch + synthetic mount are both gated on the dev flag.
  assert.match(app, /SYNTHETIC_ENABLED\s*&&/);
  assert.match(app, /syntheticDemoEnabled\(import\.meta\.env\)/);
  // No unconditional synthetic mount remains.
  assert.equal(/routeMode === "real" \? <RealRoutePlanner \/> : <RoutePlanner \/>/.test(app), false);
});

test("presentation UI carries no technical diagnostics text in VoiceAlerts", () => {
  const voice = read("components/VoiceAlerts.jsx");
  // The compact toggle + test action remain.
  assert.match(voice, /Voice alerts/);
  assert.match(voice, /Test voice/);
  // Technical fields must NOT be rendered.
  for (const banned of ["queued", "Last spoken", "Speaking…", "queueLen}"]) {
    assert.equal(
      voice.includes(`>${banned}`) || voice.includes(`{${banned}`) || voice.includes(banned + "<"),
      false,
      `VoiceAlerts should not render technical field: ${banned}`,
    );
  }
});

test("synthetic disclosures are not rendered in the default App tree", () => {
  const app = read("App.jsx");
  // The simulated-data sublabel is only *rendered* (JSX interpolation) inside
  // the flag-gated block — the import at the top doesn't count.
  const renderIdx = app.indexOf("{SYNTHETIC_MODE_SUBLABEL}");
  if (renderIdx !== -1) {
    const gateIdx = app.indexOf("SYNTHETIC_ENABLED &&");
    assert.ok(
      gateIdx !== -1 && gateIdx < renderIdx,
      "synthetic labels must be rendered only inside the dev-flag gate",
    );
  }
});
