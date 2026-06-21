// Voice-alert client/helper tests. Run:
//   node --test src/services/speechClient.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ClientDedupe,
  classifyPlayError,
  deriveVoiceAlerts,
  fetchSpeech,
  insertByPriority,
  makeRerouteAlert,
  nextToSpeak,
} from "./speechClient.js";

test("priority queue: critical jumps ahead, FIFO within priority", () => {
  let q = [];
  q = insertByPriority(q, { id: 1, priority: "info" });
  q = insertByPriority(q, { id: 2, priority: "info" });
  q = insertByPriority(q, { id: 3, priority: "critical" });
  q = insertByPriority(q, { id: 4, priority: "warning" });
  assert.deepEqual(q.map((x) => x.id), [3, 4, 1, 2]);
});

test("nextToSpeak respects disabled / playing (voice disabled handled)", () => {
  const q = [{ priority: "info", text: "hi" }];
  assert.equal(nextToSpeak(q, { enabled: false, playing: false }), null); // disabled
  assert.equal(nextToSpeak(q, { enabled: true, playing: true }), null); // busy
  assert.equal(nextToSpeak([], { enabled: true, playing: false }), null); // empty
  assert.equal(nextToSpeak(q, { enabled: true, playing: false }), q[0]);
});

test("client dedupe suppresses within TTL, allows after expiry", () => {
  const clock = { t: 0 };
  const d = new ClientDedupe(1000, () => clock.t);
  assert.equal(d.claim("steep:r1"), true);
  assert.equal(d.claim("steep:r1"), false); // within TTL
  assert.equal(d.claim(undefined), true); // no key -> never suppressed
  clock.t = 1001;
  assert.equal(d.claim("steep:r1"), true); // expired
});

test("deriveVoiceAlerts triggers on slope-over-limit and stairs only", () => {
  const none = deriveVoiceAlerts({ route_id: "r0", exceeds_limit_distance_m: 0, stairs_status: "not_detected" });
  assert.equal(none.length, 0); // no blanket narration

  const steep = deriveVoiceAlerts({ route_id: "r1", exceeds_limit_distance_m: 80, stairs_status: "not_detected" });
  assert.equal(steep.length, 1);
  assert.equal(steep[0].type, "steep_slope");
  assert.equal(steep[0].priority, "warning");
  assert.ok(steep[0].dedupe_key.includes("r1"));

  const stairs = deriveVoiceAlerts({ route_id: "r2", exceeds_limit_distance_m: 0, stairs_status: "confirmed" });
  assert.equal(stairs[0].type, "stairs");
  assert.equal(stairs[0].priority, "critical");
});

test("reroute alert is explicit", () => {
  const a = makeRerouteAlert("sess-9");
  assert.equal(a.type, "reroute");
  assert.ok(a.dedupe_key.includes("sess-9"));
});

test("classifyPlayError detects autoplay block", () => {
  assert.equal(classifyPlayError({ name: "NotAllowedError" }), "autoplay-blocked");
  assert.equal(classifyPlayError({ name: "AbortError" }), "error");
});

test("fetchSpeech: 409 suppressed, 200 blob, 503 throws", async () => {
  const mk = (status, ok) => async () => ({
    status,
    ok,
    blob: async () => "BLOB",
  });

  assert.deepEqual(
    await fetchSpeech({ text: "x", priority: "info" }, { fetchImpl: mk(409, false) }),
    { suppressed: true }
  );
  assert.deepEqual(
    await fetchSpeech({ text: "x", priority: "info" }, { fetchImpl: mk(200, true) }),
    { blob: "BLOB" }
  );
  await assert.rejects(
    fetchSpeech({ text: "x", priority: "info" }, { fetchImpl: mk(503, false) }),
    (e) => e.status === 503
  );
});
