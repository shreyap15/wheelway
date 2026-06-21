// Sponsor/demo diagnostics helpers (pure; unit-testable).
// The panel is OPT-IN: shown only when VITE_SHOW_DIAGNOSTICS is set, so it stays
// hidden in the normal presentation UI (even under `npm run dev`). Never displays
// secrets or connection URLs -- only safe booleans/ids.

const API_URL = "http://127.0.0.1:5000";

export function diagnosticsVisible(env = {}) {
  return Boolean(env.VITE_SHOW_DIAGNOSTICS);
}

// Keep only safe, non-secret fields from /health.
export function sanitizeHealth(health = {}) {
  const allow = [
    "storage_mode",
    "redis_configured",
    "redis_connected",
    "deepgram_configured",
    "mapbox_configured",
    "google_enrichment_configured",
    "fetchai_gateway_configured",
  ];
  const out = {};
  for (const k of allow) if (k in health) out[k] = health[k];
  return out;
}

export async function fetchHealth({ apiUrl = API_URL, fetchImpl } = {}) {
  const doFetch = fetchImpl || fetch;
  const resp = await doFetch(`${apiUrl}/health`);
  if (!resp.ok) throw new Error("health_unavailable");
  return sanitizeHealth(await resp.json());
}

// Lightweight pub/sub so the real-route view + voice client can publish runtime
// state (session id, latest alert, speech status) to the dev diagnostics panel.
const _diag = {};
const _subs = new Set();

export function setDiag(patch) {
  Object.assign(_diag, patch);
  for (const fn of _subs) fn({ ..._diag });
}

export function subscribeDiag(fn) {
  _subs.add(fn);
  fn({ ..._diag });
  return () => _subs.delete(fn);
}
