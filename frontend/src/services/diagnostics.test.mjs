// Diagnostics + integration source checks. Run:
//   node --test src/services/diagnostics.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { diagnosticsVisible, sanitizeHealth, setDiag, subscribeDiag } from "./diagnostics.js";
import { backendAlertToVoice } from "./speechClient.js";

const SRC = dirname(dirname(fileURLToPath(import.meta.url))); // .../src

test("diagnostics panel hidden by default; only VITE_SHOW_DIAGNOSTICS shows it", () => {
  assert.equal(diagnosticsVisible({}), false);
  assert.equal(diagnosticsVisible({ DEV: false }), false);
  // Plain dev mode must NOT reveal diagnostics in the presentation UI.
  assert.equal(diagnosticsVisible({ DEV: true }), false);
  assert.equal(diagnosticsVisible({ VITE_SHOW_DIAGNOSTICS: "1" }), true);
  assert.equal(diagnosticsVisible({ VITE_SHOW_DIAGNOSTICS: "true" }), true);
});

test("sanitizeHealth keeps only safe booleans (never URLs/keys)", () => {
  const out = sanitizeHealth({
    storage_mode: "memory",
    redis_connected: false,
    REDIS_URL: "redis://secret@host",
    DEEPGRAM_API_KEY: "sk-xxx",
  });
  assert.deepEqual(out, { storage_mode: "memory", redis_connected: false });
  assert.ok(!("REDIS_URL" in out) && !("DEEPGRAM_API_KEY" in out));
});

test("diag pub/sub delivers merged state", () => {
  let seen = null;
  const unsub = subscribeDiag((s) => (seen = s));
  setDiag({ routeSessionId: "rs-1" });
  setDiag({ speechStatus: "speaking" });
  assert.equal(seen.routeSessionId, "rs-1");
  assert.equal(seen.speechStatus, "speaking");
  unsub();
});

test("backendAlertToVoice maps the shared contract", () => {
  const v = backendAlertToVoice({ type: "stairs", priority: "critical", text: "Stairs", dedupe_key: "k" });
  assert.deepEqual(v, { type: "stairs", priority: "critical", text: "Stairs", dedupe_key: "k" });
});

test("synthetic mode has no route-session / voice wiring (no leak)", () => {
  const synth = readFileSync(join(SRC, "RoutePlanner.jsx"), "utf8");
  assert.equal(/route_session|route-sessions|voiceBus|speechClient/.test(synth), false);
  // Real mode DOES wire them.
  const real = readFileSync(join(SRC, "RealRoutePlanner.jsx"), "utf8");
  assert.ok(/voiceBus/.test(real) && /route-sessions/.test(real));
});
