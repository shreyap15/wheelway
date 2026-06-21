// Isolated voice-alert client + pure helpers for WheelWay.
//
// The Deepgram key never reaches the browser: this calls the backend POST /speak
// which returns mp3 audio. Pure helpers (queue ordering, client-side dedupe,
// trigger derivation, autoplay classification) are exported for unit testing
// with `node --test`.

const API_URL = "http://127.0.0.1:5000";

// Lower number = spoken sooner. Critical narration jumps ahead of info.
export const PRIORITY_ORDER = { critical: 0, warning: 1, info: 2 };

export function priorityRank(p) {
  return PRIORITY_ORDER[p] ?? PRIORITY_ORDER.info;
}

// Insert keeping higher priority first, FIFO within the same priority.
export function insertByPriority(queue, item) {
  const rank = priorityRank(item.priority);
  const out = queue.slice();
  let idx = out.findIndex((q) => priorityRank(q.priority) > rank);
  if (idx === -1) idx = out.length;
  out.splice(idx, 0, item);
  return out;
}

// Next item to speak, or null when voice is disabled or already playing.
export function nextToSpeak(queue, { enabled, playing }) {
  if (!enabled || playing || !queue.length) return null;
  return queue[0];
}

// Client-side dedupe with TTL (mirrors the server's claim_dedupe_key intent).
export class ClientDedupe {
  constructor(ttlMs = 30000, timeFn = () => Date.now()) {
    this.ttlMs = ttlMs;
    this.time = timeFn;
    this.keys = new Map();
  }

  claim(key) {
    if (!key) return true; // no key -> never suppressed
    const now = this.time();
    const exp = this.keys.get(key);
    if (exp !== undefined && now < exp) return false;
    this.keys.set(key, now + this.ttlMs);
    return true;
  }
}

// Map a selected real route to explicit voice triggers. NEVER narrates a full
// route summary -- only the defined triggers.
export function deriveVoiceAlerts(route) {
  if (!route) return [];
  const alerts = [];
  const exceed = route.exceeds_limit_distance_m;
  if ((exceed != null && exceed > 0) || route.exceeds_max_slope === true) {
    const meters = exceed != null ? Math.round(exceed) : null;
    alerts.push({
      type: "steep_slope",
      priority: "warning",
      text: meters
        ? `Steep slope ahead: about ${meters} meters above your slope limit.`
        : "Steep slope ahead, above your slope limit.",
      dedupe_key: `steep_slope:${route.route_id}`,
    });
  }
  if (route.stairs_status === "confirmed" || route.stairs_status === "likely") {
    alerts.push({
      type: "stairs",
      priority: "critical",
      text:
        route.stairs_status === "confirmed"
          ? "Confirmed stairs detected on this route."
          : "Likely stairs on this route.",
      dedupe_key: `stairs:${route.route_id}`,
    });
  }
  return alerts;
}

// Map a backend alert dict (shared contract) to a voice queue item.
export function backendAlertToVoice(alert) {
  return {
    type: alert.type,
    priority: alert.priority || "info",
    text: alert.text,
    dedupe_key: alert.dedupe_key,
  };
}

// Reroute notice trigger (explicit).
export function makeRerouteAlert(sessionId) {
  return {
    type: "reroute",
    priority: "warning",
    text: "Route recalculated. A new path has been selected.",
    dedupe_key: sessionId ? `reroute:${sessionId}` : undefined,
  };
}

// Classify an HTMLAudioElement.play() rejection.
export function classifyPlayError(err) {
  if (err && err.name === "NotAllowedError") return "autoplay-blocked";
  return "error";
}

// Fetch synthesized audio for an alert. Returns {suppressed} on 409,
// {blob} on success; throws {status} on other errors.
export async function fetchSpeech(alert, { apiUrl = API_URL, fetchImpl } = {}) {
  const doFetch = fetchImpl || fetch;
  const resp = await doFetch(`${apiUrl}/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: alert.text,
      priority: alert.priority || "info",
      dedupe_key: alert.dedupe_key,
    }),
  });
  if (resp.status === 409) return { suppressed: true };
  if (!resp.ok) throw { status: resp.status, error: "speak_failed" };
  const blob = await resp.blob();
  return { blob };
}

// Minimal pub/sub so other code can request voice without prop-drilling.
function createVoiceBus() {
  const listeners = new Set();
  return {
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    emit(alert) {
      for (const fn of listeners) fn(alert);
    },
  };
}

export const voiceBus = createVoiceBus();
