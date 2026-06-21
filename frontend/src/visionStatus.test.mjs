// Vision status helper tests. Run: node --test src/visionStatus.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  deriveBanner,
  isCameraOnline,
  latestVisionObservation,
  ttcDisplay,
  visionStreamUrl,
  voiceKey,
} from "./visionStatus.js";

const NOW = Date.parse("2026-06-21T18:30:10Z");

function obs(over = {}) {
  return {
    source: "vision_modal",
    feature_type: "dynamic_obstacle",
    device_id: "wheelway-pi-01",
    track_id: 7,
    timestamp: "2026-06-21T18:30:08Z",
    avoidance_action: "STOP",
    collision_risk: 0.9,
    time_to_collision_s: 1.4,
    ...over,
  };
}

test("latestVisionObservation ignores non-vision sources", () => {
  const list = [{ source: "simulated-pi" }, obs({ track_id: 1 }), { source: "other" }];
  assert.equal(latestVisionObservation(list).track_id, 1);
  assert.equal(latestVisionObservation([{ source: "x" }]), null);
});

test("STOP banner is critical", () => {
  const b = deriveBanner(obs({ avoidance_action: "STOP" }));
  assert.equal(b.level, "critical");
  assert.equal(b.text, "Stop. Collision risk ahead.");
});

test("LEFT/RIGHT banners carry direction + severity", () => {
  const left = deriveBanner(obs({ avoidance_action: "LEFT", time_to_collision_s: 1.0 }));
  assert.equal(left.arrow, "←");
  assert.equal(left.level, "critical"); // low TTC
  const right = deriveBanner(obs({ avoidance_action: "RIGHT", time_to_collision_s: 5.0, collision_risk: 0.55 }));
  assert.equal(right.arrow, "→");
  assert.equal(right.level, "warning");
  assert.equal(right.text, "Obstacle approaching. Move right.");
});

test("CLEAR and heartbeat produce no banner", () => {
  assert.equal(deriveBanner(obs({ avoidance_action: "CLEAR" })), null);
  assert.equal(deriveBanner(obs({ feature_type: "camera_status" })), null);
});

test("ttcDisplay only when finite + confident; never fake distance", () => {
  assert.equal(ttcDisplay(obs({ time_to_collision_s: 1.4, collision_risk: 0.9 })),
    "Collision predicted in approximately 1.4 seconds");
  assert.equal(ttcDisplay(obs({ time_to_collision_s: null })), null);
  assert.equal(ttcDisplay(obs({ time_to_collision_s: 2.0, collision_risk: 0.2 })), null);
});

test("camera offline by staleness and by explicit offline heartbeat", () => {
  assert.equal(isCameraOnline(obs({ timestamp: "2026-06-21T18:30:08Z" }), NOW, 6000), true);
  assert.equal(isCameraOnline(obs({ timestamp: "2026-06-21T18:29:00Z" }), NOW, 6000), false);
  assert.equal(
    isCameraOnline(obs({ feature_type: "camera_status", camera_online: false }), NOW, 6000),
    false,
  );
});

test("voiceKey mirrors the backend dedupe keys", () => {
  assert.equal(voiceKey(obs({ avoidance_action: "STOP" })), "vision-stop:wheelway-pi-01:7");
  assert.equal(voiceKey(obs({ avoidance_action: "LEFT" })), "vision-left:wheelway-pi-01:7");
  assert.equal(voiceKey(obs({ avoidance_action: "CLEAR" })), null);
});

test("visionStreamUrl reads env, empty by default", () => {
  assert.equal(visionStreamUrl({}), "");
  assert.equal(visionStreamUrl({ VITE_VISION_STREAM_URL: "http://pi:8000" }), "http://pi:8000");
});
