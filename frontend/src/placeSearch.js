// Pure helpers for Mapbox Geocoding place search. Kept free of React/DOM so the
// URL building, response parsing, stale-guard, and swap logic are unit-testable
// with `node --test`. Provider: Mapbox Geocoding (reuses the public
// VITE_MAPBOX_TOKEN already used for the map -- no private backend key).

const GEOCODE_BASE = "https://api.mapbox.com/geocoding/v5/mapbox.places";

// Build a forward-geocoding (autocomplete) request URL. `proximity` is an
// optional [lng, lat] to bias results near the map view.
export function buildGeocodeUrl(query, token, { proximity, limit = 5 } = {}) {
  const q = encodeURIComponent((query || "").trim());
  const params = new URLSearchParams({
    access_token: token || "",
    autocomplete: "true",
    limit: String(limit),
    types: "address,poi,place,neighborhood",
  });
  if (proximity && proximity.length === 2) {
    params.set("proximity", `${proximity[0]},${proximity[1]}`);
  }
  return `${GEOCODE_BASE}/${q}.json?${params.toString()}`;
}

// Normalize a Mapbox geocoding response into compact, UI-ready results.
export function parseGeocodeResults(json) {
  const features = (json && json.features) || [];
  return features
    .filter((f) => Array.isArray(f.center) && f.center.length === 2)
    .map((f) => ({
      id: f.id,
      name: f.text || f.place_name,
      address: f.place_name,
      lng: f.center[0],
      lat: f.center[1],
    }));
}

// Stale-response guard: only the newest issued request may apply its results.
// Returns true when `responseSeq` is the latest issued sequence number.
export function isLatestResponse(responseSeq, latestSeq) {
  return responseSeq >= latestSeq;
}

// Swap origin/destination selections.
export function swapPlaces(origin, destination) {
  return [destination, origin];
}

// A route may be requested only when BOTH ends have valid coordinates.
export function canRequestRoute(origin, destination) {
  return Boolean(
    origin &&
      destination &&
      Number.isFinite(origin.lat) &&
      Number.isFinite(origin.lng) &&
      Number.isFinite(destination.lat) &&
      Number.isFinite(destination.lng)
  );
}
