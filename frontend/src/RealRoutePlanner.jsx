import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

// REAL-ROUTE MODE — geometry comes entirely from the backend /real-route
// endpoint (Google Routes pedestrian polyline). This component deliberately
// does NOT import graphNodes.js; nothing here is synthetic.

const API_URL = "http://127.0.0.1:5000";
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;

const STYLES = {
  streets: "mapbox://styles/mapbox/streets-v12",
  satellite: "mapbox://styles/mapbox/satellite-streets-v12",
};

// Editable starting coordinates (real Berkeley points). These are INPUT
// DEFAULTS the user can change — not drawn geometry.
const DEFAULTS = {
  originLat: 37.8694,
  originLng: -122.2592,
  destLat: 37.8683,
  destLng: -122.2585,
};

const WHEELCHAIR_TYPES = ["manual", "powered", "scooter", "walker"];

function scoreColor(score) {
  if (score == null) return "#6d9eca";
  if (score >= 80) return "#2f9b5f";
  if (score >= 60) return "#9bc53d";
  if (score >= 40) return "#e8af45";
  return "#d94444";
}

const CV_COLORS = {
  obstruction: "#d94444",
  curb: "#e8af45",
  ramp: "#2f9b5f",
  default: "#6d9eca",
};

// One badge per provenance source so judges can see what is real vs unavailable.
const SOURCE_LABELS = {
  google_routes: "Google Routes",
  google_elevation: "Google Elevation",
  google_places: "Google Places",
  wheelway_scoring: "Wheelway scoring",
  camera_cv: "Camera CV",
  mocked: "Mocked",
  unavailable: "Unavailable",
};

export default function RealRoutePlanner() {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const cvMarkersRef = useRef([]);
  const endMarkersRef = useRef([]);
  // Keep latest draw data available to the style.load re-add handler.
  const drawRef = useRef({ resp: null, selectedId: null });
  const [mapReady, setMapReady] = useState(false);

  const [coords, setCoords] = useState(DEFAULTS);
  const [profile, setProfile] = useState({
    wheelchair_type: "manual",
    avoid_stairs: true,
    max_slope_pct: 8.33,
    min_width_m: 0.91,
  });
  const [mapStyle, setMapStyle] = useState("streets");

  // idle | loading | success | error | config | offline | no-route
  const [status, setStatus] = useState("idle");
  const [resp, setResp] = useState(null);
  const [errorInfo, setErrorInfo] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  // --- Map init ---
  useEffect(() => {
    if (!MAPBOX_TOKEN || mapRef.current) return;
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: STYLES[mapStyle],
      center: [DEFAULTS.originLng, DEFAULTS.originLat],
      zoom: 15,
    });
    map.on("load", () => {
      addRouteLayers(map);
      setMapReady(true);
    });
    // Re-add the source/layers whenever the base style changes (setStyle wipes them).
    map.on("style.load", () => {
      addRouteLayers(map);
      redraw(map, drawRef.current.resp, drawRef.current.selectedId);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  function addRouteLayers(map) {
    if (!map.getSource("real-route")) {
      map.addSource("real-route", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    if (!map.getLayer("real-route-line")) {
      map.addLayer({
        id: "real-route-line",
        type: "line",
        source: "real-route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["get", "width"],
          "line-opacity": ["get", "opacity"],
        },
      });
    }
  }

  // --- Style toggle ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    map.setStyle(STYLES[mapStyle]);
  }, [mapStyle, mapReady]);

  // --- Redraw on response / selection change ---
  useEffect(() => {
    drawRef.current = { resp, selectedId };
    const map = mapRef.current;
    if (!map || !mapReady) return;
    redraw(map, resp, selectedId);
  }, [resp, selectedId, mapReady]);

  function redraw(map, response, selId) {
    const src = map.getSource && map.getSource("real-route");
    if (!src) return;

    // clear markers
    cvMarkersRef.current.forEach((m) => m.remove());
    cvMarkersRef.current = [];
    endMarkersRef.current.forEach((m) => m.remove());
    endMarkersRef.current = [];

    if (!response || !response.routes?.length) {
      src.setData({ type: "FeatureCollection", features: [] });
      return;
    }

    const features = [];
    let selectedCoords = null;
    for (const r of response.routes) {
      const isSel = r.route_id === selId;
      features.push({
        type: "Feature",
        properties: {
          color: isSel ? scoreColor(r.accessibility_score) : "#9aa6a0",
          width: isSel ? 6 : 3,
          opacity: isSel ? 1 : 0.5,
        },
        geometry: r.geometry,
      });
      if (isSel) selectedCoords = r.geometry?.coordinates ?? null;
    }
    // Draw selected last so it sits on top.
    features.sort((a, b) => a.properties.width - b.properties.width);
    src.setData({ type: "FeatureCollection", features });

    // origin/destination markers (from request echo — real coords)
    if (response.origin) {
      endMarkersRef.current.push(
        new mapboxgl.Marker({ color: "#183e2c" })
          .setLngLat([response.origin.longitude, response.origin.latitude])
          .setPopup(new mapboxgl.Popup().setText("Origin"))
          .addTo(map)
      );
    }
    if (response.destination) {
      endMarkersRef.current.push(
        new mapboxgl.Marker({ color: "#d94444" })
          .setLngLat([response.destination.longitude, response.destination.latitude])
          .setPopup(
            new mapboxgl.Popup().setText(
              response.destination_place?.place_name || "Destination"
            )
          )
          .addTo(map)
      );
    }

    // CV detections (requirement 8) — backend echoes any posted observations.
    for (const obs of response.cv_observations || []) {
      if (obs.latitude == null || obs.longitude == null) continue;
      const el = document.createElement("div");
      el.className = "cv-marker";
      el.style.background = CV_COLORS[obs.feature_type] || CV_COLORS.default;
      cvMarkersRef.current.push(
        new mapboxgl.Marker({ element: el })
          .setLngLat([obs.longitude, obs.latitude])
          .setPopup(
            new mapboxgl.Popup().setText(
              `${obs.feature_type} (${Math.round((obs.confidence || 0) * 100)}%) — ${obs.source}`
            )
          )
          .addTo(map)
      );
    }

    // Fit to the selected route geometry exactly.
    if (selectedCoords && selectedCoords.length) {
      const bounds = selectedCoords.reduce(
        (b, c) => b.extend(c),
        new mapboxgl.LngLatBounds(selectedCoords[0], selectedCoords[0])
      );
      map.fitBounds(bounds, { padding: 70, maxZoom: 17, duration: 600 });
    }
  }

  async function planRoute() {
    setStatus("loading");
    setResp(null);
    setErrorInfo(null);
    setSelectedId(null);

    const body = {
      origin: { latitude: Number(coords.originLat), longitude: Number(coords.originLng) },
      destination: { latitude: Number(coords.destLat), longitude: Number(coords.destLng) },
      profile: {
        wheelchair_type: profile.wheelchair_type,
        avoid_stairs: profile.avoid_stairs,
        max_slope_pct: Number(profile.max_slope_pct),
        min_width_m: Number(profile.min_width_m),
      },
    };

    let r;
    try {
      r = await fetch(`${API_URL}/real-route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      setStatus("offline");
      setErrorInfo({ message: "Backend offline. Start the Flask API on 127.0.0.1:5000." });
      return;
    }

    let data = null;
    try {
      data = await r.json();
    } catch {
      data = null;
    }

    if (r.status === 503) {
      setStatus("config");
      setErrorInfo(data || { message: "Google Maps API key not configured." });
      return;
    }
    if (r.status === 400) {
      setStatus("error");
      setErrorInfo({ message: data?.error || "Invalid request.", details: data?.details });
      return;
    }
    if (r.status === 404) {
      setStatus("no-route");
      setErrorInfo({ message: data?.message || "No walking route found." });
      return;
    }
    if (!r.ok || !data?.routes) {
      setStatus("error");
      setErrorInfo({ message: data?.message || `Request failed (HTTP ${r.status}).` });
      return;
    }

    setResp(data);
    setSelectedId(data.routes[0]?.route_id ?? null);
    setStatus("success");
  }

  const selectedRoute = resp?.routes?.find((r) => r.route_id === selectedId) || null;
  const tokenMissing = !MAPBOX_TOKEN;

  return (
    <section className="route-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Real route mode · API-derived geometry</p>
          <h2>Real pedestrian route</h2>
        </div>
        <div className="style-toggle">
          <button
            className={mapStyle === "streets" ? "active" : ""}
            onClick={() => setMapStyle("streets")}
          >
            Streets
          </button>
          <button
            className={mapStyle === "satellite" ? "active" : ""}
            onClick={() => setMapStyle("satellite")}
          >
            Satellite
          </button>
        </div>
      </div>

      <div className="route-layout">
        <div className="route-controls">
          <p className="control-subhead">Origin (lat, lng)</p>
          <div className="control-group">
            <label>
              Latitude
              <input
                type="number" step="0.0001" value={coords.originLat}
                onChange={(e) => setCoords({ ...coords, originLat: e.target.value })}
              />
            </label>
            <label>
              Longitude
              <input
                type="number" step="0.0001" value={coords.originLng}
                onChange={(e) => setCoords({ ...coords, originLng: e.target.value })}
              />
            </label>
          </div>

          <p className="control-subhead">Destination (lat, lng)</p>
          <div className="control-group">
            <label>
              Latitude
              <input
                type="number" step="0.0001" value={coords.destLat}
                onChange={(e) => setCoords({ ...coords, destLat: e.target.value })}
              />
            </label>
            <label>
              Longitude
              <input
                type="number" step="0.0001" value={coords.destLng}
                onChange={(e) => setCoords({ ...coords, destLng: e.target.value })}
              />
            </label>
          </div>

          <p className="control-subhead">Mobility settings</p>
          <div className="control-group">
            <label>
              Wheelchair type
              <select
                value={profile.wheelchair_type}
                onChange={(e) => setProfile({ ...profile, wheelchair_type: e.target.value })}
              >
                {WHEELCHAIR_TYPES.map((w) => (
                  <option key={w} value={w}>{w}</option>
                ))}
              </select>
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox" checked={profile.avoid_stairs}
                onChange={(e) => setProfile({ ...profile, avoid_stairs: e.target.checked })}
              />
              Avoid stairs
            </label>
          </div>
          <div className="control-group">
            <label>
              Max slope (%)
              <input
                type="number" step="0.1" value={profile.max_slope_pct}
                onChange={(e) => setProfile({ ...profile, max_slope_pct: e.target.value })}
              />
            </label>
            <label>
              Min width (m)
              <input
                type="number" step="0.01" value={profile.min_width_m}
                onChange={(e) => setProfile({ ...profile, min_width_m: e.target.value })}
              />
            </label>
          </div>

          <button className="route-button" onClick={planRoute} disabled={status === "loading"}>
            {status === "loading" ? "Requesting real route…" : "Get real route"}
          </button>

          {status === "loading" && (
            <div className="route-state state-loading">Calling Google Routes + Elevation + Places…</div>
          )}
          {status === "offline" && (
            <div className="route-state state-error">{errorInfo?.message}</div>
          )}
          {status === "no-route" && (
            <div className="route-state state-warn">{errorInfo?.message}</div>
          )}
          {status === "error" && (
            <div className="route-state state-error">{errorInfo?.message}</div>
          )}
          {status === "config" && (
            <div className="route-state state-error">
              <strong>Google API not configured.</strong>
              <p>{errorInfo?.message}</p>
              {errorInfo?.missing_env && (
                <p>Missing: <code>{errorInfo.missing_env.join(", ")}</code></p>
              )}
              {errorInfo?.how_to_fix && <p>{errorInfo.how_to_fix}</p>}
            </div>
          )}

          {status === "success" && resp && (
            <div className="route-summary">
              {resp.routes.length > 1 && (
                <div className="alt-list">
                  <p className="control-subhead">Alternatives ({resp.routes.length})</p>
                  {resp.routes.map((r) => (
                    <button
                      key={r.route_id}
                      className={`alt-chip ${r.route_id === selectedId ? "active" : ""}`}
                      onClick={() => setSelectedId(r.route_id)}
                    >
                      <span className="alt-dot" style={{ background: scoreColor(r.accessibility_score) }} />
                      {r.route_id} · {r.distance_m} m
                    </button>
                  ))}
                </div>
              )}

              {selectedRoute && (
                <>
                  <div className="summary-stats">
                    <div className="stat">
                      <span className="stat-label">Distance</span>
                      <strong>{selectedRoute.distance_m} m</strong>
                    </div>
                    <div className="stat">
                      <span className="stat-label">Duration</span>
                      <strong>{Math.round(selectedRoute.duration_s / 60)} min</strong>
                    </div>
                    <div className="stat">
                      <span className="stat-label">Max slope</span>
                      <strong>{selectedRoute.max_slope_pct ?? "—"}%</strong>
                    </div>
                    <div className="stat">
                      <span className="stat-label">Score</span>
                      <strong>{selectedRoute.accessibility_score ?? "—"}</strong>
                    </div>
                  </div>

                  <p className="explanation">{selectedRoute.explanation}</p>

                  <div className="warnings-block">
                    <p className="control-subhead">
                      Warnings ({selectedRoute.accessibility_warnings.length})
                    </p>
                    <ul className="warning-list">
                      {selectedRoute.accessibility_warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                </>
              )}

              <div className="destination-block">
                <p className="control-subhead">Destination (Google Places)</p>
                <p>
                  {resp.destination_place?.place_name || "Unknown place"} —{" "}
                  {resp.destination_place?.wheelchair_accessible_entrance === true
                    ? "Accessible entrance ✓"
                    : resp.destination_place?.wheelchair_accessible_entrance === false
                    ? "Entrance NOT accessible ✗"
                    : "Entrance accessibility unknown"}
                </p>
                {resp.destination_place?.warning && (
                  <p className="muted">{resp.destination_place.warning}</p>
                )}
              </div>

              <div className="provenance">
                <p className="control-subhead">Data sources</p>
                <div className="badges">
                  {Object.entries(resp.data_sources || {}).map(([field, src]) => (
                    <span
                      key={field}
                      className={`badge ${src === "unavailable" ? "badge-off" : "badge-on"}`}
                    >
                      {field}: {SOURCE_LABELS[src] || src}
                    </span>
                  ))}
                </div>
              </div>

              {resp.service_degraded && (
                <div className="route-state state-warn">
                  Some data sources were degraded; see warnings.
                </div>
              )}
            </div>
          )}
        </div>

        <div className="map-wrap">
          {tokenMissing ? (
            <div className="map-placeholder">
              Set VITE_MAPBOX_TOKEN in frontend/.env to display the map.
            </div>
          ) : (
            <div ref={mapContainer} className="map-canvas" />
          )}
        </div>
      </div>
    </section>
  );
}
