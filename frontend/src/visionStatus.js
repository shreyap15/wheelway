// Pure helpers for the live physical-AI (camera obstacle detection) UI.
// Presentation-safe: derives only user-facing hazard state from vision_modal
// observations. No raw Kalman/RK4/track-id/Redis fields leak to the UI.

export const VISION_SOURCE = "vision_modal";

const CRITICAL_TTC = 1.5;
const CRITICAL_RISK = 0.8;
// Only surface TTC text when the prediction is confident enough.
const TTC_MIN_RISK = 0.5;

export function latestVisionObservation(observations = []) {
  for (let i = observations.length - 1; i >= 0; i -= 1) {
    if (observations[i] && observations[i].source === VISION_SOURCE) return observations[i];
  }
  return null;
}

function obsTimeMs(obs) {
  if (!obs || !obs.timestamp) return null;
  const t = Date.parse(obs.timestamp);
  return Number.isFinite(t) ? t : null;
}

// Camera considered online when we have a fresh observation and the device did
// not explicitly report the camera/detector offline.
export function isCameraOnline(obs, nowMs, staleMs = 6000) {
  if (!obs) return false;
  if (obs.feature_type === "camera_status") {
    if (obs.camera_online === false || obs.detector_online === false) return false;
  }
  const t = obsTimeMs(obs);
  if (t == null) return false;
  return nowMs - t <= staleMs;
}

export function freshnessSeconds(obs, nowMs) {
  const t = obsTimeMs(obs);
  if (t == null) return null;
  return Math.max(0, Math.round((nowMs - t) / 100) / 10);
}

function isCritical(obs) {
  const ttc = obs.time_to_collision_s;
  const risk = obs.collision_risk;
  if (typeof ttc === "number" && ttc <= CRITICAL_TTC) return true;
  if (typeof risk === "number" && risk >= CRITICAL_RISK) return true;
  return false;
}

// Map an observation to a user-facing banner, or null (CLEAR / heartbeat).
export function deriveBanner(obs) {
  if (!obs || obs.feature_type === "camera_status") return null;
  switch (obs.avoidance_action) {
    case "STOP":
      return { level: "critical", text: "Stop. Collision risk ahead.", arrow: null, action: "STOP" };
    case "LEFT":
      return {
        level: isCritical(obs) ? "critical" : "warning",
        text: "Obstacle approaching. Move left.", arrow: "←", action: "LEFT",
      };
    case "RIGHT":
      return {
        level: isCritical(obs) ? "critical" : "warning",
        text: "Obstacle approaching. Move right.", arrow: "→", action: "RIGHT",
      };
    default:
      return null; // CLEAR -> no hazard banner
  }
}

// Optional, honest technical detail: only when TTC is finite AND risk is high
// enough to trust the estimate. Never shows fake distance.
export function ttcDisplay(obs, { minRisk = TTC_MIN_RISK } = {}) {
  if (!obs) return null;
  const ttc = obs.time_to_collision_s;
  const risk = obs.collision_risk;
  if (typeof ttc !== "number" || !Number.isFinite(ttc)) return null;
  if (typeof risk === "number" && risk < minRisk) return null;
  return `Collision predicted in approximately ${ttc.toFixed(1)} seconds`;
}

// A stable voice key so the same hazard/track is spoken once (mirrors backend).
export function voiceKey(obs) {
  const dev = obs.device_id || "pi";
  const id = obs.track_id ?? "x";
  switch (obs.avoidance_action) {
    case "STOP": return `vision-stop:${dev}:${id}`;
    case "LEFT": return `vision-left:${dev}:${id}`;
    case "RIGHT": return `vision-right:${dev}:${id}`;
    default: return null;
  }
}

export function visionStreamUrl(env = {}) {
  return (env.VITE_VISION_STREAM_URL || "").trim();
}
