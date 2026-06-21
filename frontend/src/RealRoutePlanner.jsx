import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import {
  SLOPE_COLORS,
  SLOPE_LABELS,
  buildCasingFeatures,
  buildSelectedOverlayFeatures,
  hasSlopeData,
} from "./slopeRendering";
import {
  STAIR_STATUS_COLOR,
  buildStairFeatures,
  hasStairOverlay,
  stairSourceSummary,
  stairStatusMessage,
} from "./stairRendering";
import PlaceSearch from "./PlaceSearchBox";
import { canRequestRoute, swapPlaces } from "./placeSearch";
import { backendAlertToVoice, voiceBus } from "./services/speechClient";
import { setDiag } from "./services/diagnostics";

const SELECT_API = "http://127.0.0.1:5000";

// REAL-ROUTE MODE — geometry comes entirely from the backend /real-route
// endpoint (exact Mapbox walking-directions polyline). This component
// deliberately does NOT import graphNodes.js; nothing here is synthetic.

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
  mapbox: "Mapbox Directions",
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
  const hoverPopupRef = useRef(null);
  // Keep latest draw data available to the style.load re-add handler.
  const drawRef = useRef({ resp: null, selectedId: null });
  const [mapReady, setMapReady] = useState(false);

  const [coords, setCoords] = useState(DEFAULTS);
  // Selected places from autocomplete ({name, address, lat, lng}) — primary input.
  const [originPlace, setOriginPlace] = useState(null);
  const [destPlace, setDestPlace] = useState(null);
  const [profile, setProfile] = useState({
    wheelchair_type: "manual",
    avoid_stairs: true,
    max_slope_pct: 8.33,
    max_cross_slope_pct: 2.0,
    min_width_m: 0.91,
    requires_curb_ramps: true,
    surface_sensitivity: 0.5,
  });
  const [mapStyle, setMapStyle] = useState("streets");

  // idle | loading | success | error | config | offline | no-route
  const [status, setStatus] = useState("idle");
  const [resp, setResp] = useState(null);
  const [errorInfo, setErrorInfo] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [routeSessionId, setRouteSessionId] = useState(null);
  // Guards so re-renders never replay alerts or re-POST the same selection.
  const sessionRef = useRef(null);
  const lastSelectSentRef = useRef(null);

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
      registerSlopeInteractions(map);
      setMapReady(true);
    });
    // Re-add the source/layers whenever the base style changes (setStyle wipes
    // them). Interaction handlers are bound to the map (not the layer) so they
    // survive setStyle and keep working once the layer id reappears.
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
    // Casing/outline source: full geometry of every route (req. 1, 7).
    if (!map.getSource("real-route-casing")) {
      map.addSource("real-route-casing", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    // Colored local-slope sections for the selected route (req. 2-4).
    if (!map.getSource("real-route-slopes")) {
      map.addSource("real-route-slopes", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    // Casing first so the colored slope sections render on top of it.
    if (!map.getLayer("real-route-casing-line")) {
      map.addLayer({
        id: "real-route-casing-line",
        type: "line",
        source: "real-route-casing",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["get", "width"],
          "line-opacity": ["get", "opacity"],
        },
      });
    }
    if (!map.getLayer("real-route-slopes-line")) {
      map.addLayer({
        id: "real-route-slopes-line",
        type: "line",
        source: "real-route-slopes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": 6,
          "line-opacity": 1,
        },
      });
    }
    // Distinct DASHED stair overlay drawn on top of the slope colors (does not
    // hide them -- slope shows through the gaps).
    if (!map.getSource("real-route-stairs")) {
      map.addSource("real-route-stairs", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
    }
    if (!map.getLayer("real-route-stairs-line")) {
      map.addLayer({
        id: "real-route-stairs-line",
        type: "line",
        source: "real-route-stairs",
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": 4,
          "line-opacity": 0.95,
          "line-dasharray": [1, 1.2],
        },
      });
    }
  }

  // Hover/click details for a slope section (req. 6). Bound once to the map.
  function registerSlopeInteractions(map) {
    if (!hoverPopupRef.current) {
      hoverPopupRef.current = new mapboxgl.Popup({
        closeButton: false,
        closeOnClick: false,
      });
    }
    const showDetails = (e) => {
      const f = e.features && e.features[0];
      if (!f || f.properties.kind !== "slope") return;
      map.getCanvas().style.cursor = "pointer";
      const p = f.properties;
      const dir = p.grade_pct > 0 ? "uphill" : p.grade_pct < 0 ? "downhill" : "flat";
      const exceeds =
        String(p.exceeds_user_limit) === "true"
          ? '<span style="color:#d94444">exceeds your limit</span>'
          : "within your limit";
      hoverPopupRef.current
        .setLngLat(e.lngLat)
        .setHTML(
          `<div class="slope-popup">` +
            `<strong>${SLOPE_LABELS[p.classification] || p.classification}</strong><br/>` +
            `Local grade: ${p.grade_pct}% (${dir})<br/>` +
            `Elevation: ${p.elevation_start_m} m → ${p.elevation_end_m} m<br/>` +
            `${exceeds}` +
            `</div>`
        )
        .addTo(map);
    };
    map.on("mousemove", "real-route-slopes-line", showDetails);
    map.on("click", "real-route-slopes-line", showDetails);
    map.on("mouseleave", "real-route-slopes-line", () => {
      map.getCanvas().style.cursor = "";
      hoverPopupRef.current && hoverPopupRef.current.remove();
    });

    const showStairs = (e) => {
      const f = e.features && e.features[0];
      if (!f || f.properties.kind !== "stairs") return;
      map.getCanvas().style.cursor = "pointer";
      const p = f.properties;
      hoverPopupRef.current
        .setLngLat(e.lngLat)
        .setHTML(
          `<div class="slope-popup">` +
            `<strong>${stairStatusMessage(p.status)}</strong><br/>` +
            `Confidence: ${Math.round((p.confidence || 0) * 100)}%<br/>` +
            `Sources: ${p.sources || "—"}` +
            `</div>`
        )
        .addTo(map);
    };
    map.on("mousemove", "real-route-stairs-line", showStairs);
    map.on("click", "real-route-stairs-line", showStairs);
    map.on("mouseleave", "real-route-stairs-line", () => {
      map.getCanvas().style.cursor = "";
      hoverPopupRef.current && hoverPopupRef.current.remove();
    });

    // Click a faded alternative casing to select it (Google-Maps style).
    map.on("click", "real-route-casing-line", (e) => {
      const f = e.features && e.features[0];
      if (f && f.properties && f.properties.route_id) {
        setSelectedId(f.properties.route_id);
      }
    });
    map.on("mouseenter", "real-route-casing-line", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "real-route-casing-line", () => {
      map.getCanvas().style.cursor = "";
    });
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
    const casingSrc = map.getSource && map.getSource("real-route-casing");
    const slopeSrc = map.getSource && map.getSource("real-route-slopes");
    const stairSrc = map.getSource && map.getSource("real-route-stairs");
    if (!casingSrc || !slopeSrc || !stairSrc) return;

    // clear markers
    cvMarkersRef.current.forEach((m) => m.remove());
    cvMarkersRef.current = [];
    endMarkersRef.current.forEach((m) => m.remove());
    endMarkersRef.current = [];
    hoverPopupRef.current && hoverPopupRef.current.remove();

    const empty = { type: "FeatureCollection", features: [] };
    if (!response || !response.routes?.length) {
      casingSrc.setData(empty);
      slopeSrc.setData(empty);
      stairSrc.setData(empty);
      return;
    }

    // Casing for ALL routes (selected emphasized, alternatives grey). The
    // selected route is then colored by its LOCAL slope sections on top -- the
    // whole route is never colored by a single max-slope value (req. 4).
    const selected = response.routes.find((r) => r.route_id === selId) || null;
    casingSrc.setData({
      type: "FeatureCollection",
      features: buildCasingFeatures(response.routes, selId),
    });
    slopeSrc.setData({
      type: "FeatureCollection",
      features: buildSelectedOverlayFeatures(selected, scoreColor),
    });
    stairSrc.setData({
      type: "FeatureCollection",
      features: buildStairFeatures(selected),
    });
    const selectedCoords = selected?.geometry?.coordinates ?? null;

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

  // A place change invalidates any shown route.
  function selectOrigin(place) {
    setOriginPlace(place);
    setResp(null);
    setStatus("idle");
    setSelectedId(null);
  }
  function selectDest(place) {
    setDestPlace(place);
    setResp(null);
    setStatus("idle");
    setSelectedId(null);
  }
  function swap() {
    const [o, d] = swapPlaces(originPlace, destPlace);
    setOriginPlace(o);
    setDestPlace(d);
    setResp(null);
    setStatus("idle");
    setSelectedId(null);
  }

  async function planRoute() {
    // Prefer selected places; fall back to raw dev coordinates.
    const origin = originPlace
      ? { latitude: originPlace.lat, longitude: originPlace.lng }
      : { latitude: Number(coords.originLat), longitude: Number(coords.originLng) };
    const destination = destPlace
      ? { latitude: destPlace.lat, longitude: destPlace.lng }
      : { latitude: Number(coords.destLat), longitude: Number(coords.destLng) };

    setStatus("loading");
    setResp(null);
    setErrorInfo(null);
    setSelectedId(null);

    const body = {
      origin,
      destination,
      profile: {
        wheelchair_type: profile.wheelchair_type,
        avoid_stairs: profile.avoid_stairs,
        max_slope_pct: Number(profile.max_slope_pct),
        max_cross_slope_pct: Number(profile.max_cross_slope_pct),
        min_width_m: Number(profile.min_width_m),
        requires_curb_ramps: profile.requires_curb_ramps,
        surface_sensitivity: Number(profile.surface_sensitivity),
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

    const firstId = data.routes[0]?.route_id ?? null;
    setResp(data);
    setSelectedId(firstId);
    setRouteSessionId(data.route_session_id ?? null);
    sessionRef.current = data.route_session_id ?? null;
    lastSelectSentRef.current = firstId; // initial selection came from the server
    setStatus("success");

    // Auto-speak only the defined triggers (server already chose them); the
    // VoiceAlerts component respects the toggle + dedupes. Text warnings remain
    // visible regardless of voice settings.
    (data.auto_speak_alerts || []).forEach((a) => voiceBus.emit(backendAlertToVoice(a)));
    setDiag({
      routeSessionId: data.route_session_id || "—",
      selectedRouteId: firstId || "—",
      eventCount: (data.alerts || []).length,
      latestAlert: (data.alerts || [])[0]?.text || "—",
    });
  }

  // When the user picks a different alternative, update the SAME session on the
  // backend and speak the reroute notice. Guarded against re-render replays.
  useEffect(() => {
    const sid = sessionRef.current;
    if (!sid || !selectedId) return;
    if (selectedId === lastSelectSentRef.current) return;
    lastSelectSentRef.current = selectedId;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${SELECT_API}/route-sessions/${sid}/select`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ route_id: selectedId }),
        });
        if (cancelled || !r.ok) return;
        const body = await r.json();
        (body.auto_speak_alerts || []).forEach((a) => voiceBus.emit(backendAlertToVoice(a)));
        setDiag({ selectedRouteId: selectedId, latestAlert: (body.alerts || [])[0]?.text || "—" });
      } catch {
        /* selection persistence is best-effort; route stays usable */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selectedRoute = resp?.routes?.find((r) => r.route_id === selectedId) || null;
  const slopeAvailable = hasSlopeData(selectedRoute);
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
          <PlaceSearch
            label="Origin"
            placeholder="Search a starting place…"
            selected={originPlace}
            onSelect={selectOrigin}
            token={MAPBOX_TOKEN}
            proximity={[DEFAULTS.originLng, DEFAULTS.originLat]}
          />
          <div className="swap-row">
            <button type="button" className="swap-btn" onClick={swap} title="Swap origin and destination">
              ⇅ Swap
            </button>
          </div>
          <PlaceSearch
            label="Destination"
            placeholder="Search a destination…"
            selected={destPlace}
            onSelect={selectDest}
            token={MAPBOX_TOKEN}
            proximity={[DEFAULTS.destLng, DEFAULTS.destLat]}
          />

          <details className="dev-fallback">
            <summary>Developer: raw coordinates</summary>
            <div className="control-group">
              <label>
                Origin lat
                <input type="number" step="0.0001" value={coords.originLat}
                  onChange={(e) => setCoords({ ...coords, originLat: e.target.value })} />
              </label>
              <label>
                Origin lng
                <input type="number" step="0.0001" value={coords.originLng}
                  onChange={(e) => setCoords({ ...coords, originLng: e.target.value })} />
              </label>
            </div>
            <div className="control-group">
              <label>
                Dest lat
                <input type="number" step="0.0001" value={coords.destLat}
                  onChange={(e) => setCoords({ ...coords, destLat: e.target.value })} />
              </label>
              <label>
                Dest lng
                <input type="number" step="0.0001" value={coords.destLng}
                  onChange={(e) => setCoords({ ...coords, destLng: e.target.value })} />
              </label>
            </div>
          </details>

          <p className="control-subhead">Mobility settings</p>
          <p className="affects-note">Affects routing</p>
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
          </div>

          <p className="affects-note affects-note-muted">
            Recorded but not yet verified by real-route data:
          </p>
          <div className="control-group">
            <label>
              Min width (m)
              <input
                type="number" step="0.01" value={profile.min_width_m}
                onChange={(e) => setProfile({ ...profile, min_width_m: e.target.value })}
              />
            </label>
            <label>
              Max cross slope (%)
              <input
                type="number" step="0.1" value={profile.max_cross_slope_pct}
                onChange={(e) => setProfile({ ...profile, max_cross_slope_pct: e.target.value })}
              />
            </label>
          </div>
          <div className="control-group">
            <label className="checkbox-label">
              <input
                type="checkbox" checked={profile.requires_curb_ramps}
                onChange={(e) => setProfile({ ...profile, requires_curb_ramps: e.target.checked })}
              />
              Requires curb ramps
            </label>
            <label>
              Surface sensitivity (0–1)
              <input
                type="number" step="0.1" min="0" max="1" value={profile.surface_sensitivity}
                onChange={(e) => setProfile({ ...profile, surface_sensitivity: e.target.value })}
              />
            </label>
          </div>

          <button
            className="route-button"
            onClick={planRoute}
            disabled={
              status === "loading" ||
              !(canRequestRoute(originPlace, destPlace) || (coords.originLat && coords.destLat))
            }
          >
            {status === "loading" ? "Requesting real route…" : "Get real route"}
          </button>

          {status === "loading" && (
            <div className="route-state state-loading">Calling Mapbox Directions + Google Elevation + Places…</div>
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
              <strong>Routing API not configured.</strong>
              <p>{errorInfo?.message}</p>
              {errorInfo?.missing_env && (
                <p>Missing: <code>{errorInfo.missing_env.join(", ")}</code></p>
              )}
              {errorInfo?.how_to_fix && <p>{errorInfo.how_to_fix}</p>}
            </div>
          )}

          {status === "success" && resp && (
            <div className="route-summary">
              {(originPlace || destPlace) && (
                <p className="trip-line">
                  <strong>{originPlace?.name || "Origin"}</strong> →{" "}
                  <strong>{destPlace?.name || "Destination"}</strong>
                </p>
              )}
              <div className="route-cards">
                <p className="control-subhead">Routes ({resp.routes.length})</p>
                {resp.routes.map((r) => (
                  <button
                    key={r.route_id}
                    className={`route-card ${r.route_id === selectedId ? "active" : ""}`}
                    onClick={() => setSelectedId(r.route_id)}
                  >
                    <div className="route-card-head">
                      <span className="alt-dot" style={{ background: scoreColor(r.accessibility_score) }} />
                      <strong>{r.route_id}</strong>
                      {r.recommended && <span className="rec-badge">Recommended</span>}
                    </div>
                    <div className="route-card-stats">
                      <span>{r.distance_m} m</span>
                      <span>{Math.round(r.duration_s / 60)} min</span>
                      <span>Max {r.max_slope_pct ?? "—"}%</span>
                      <span>
                        Over limit:{" "}
                        {r.exceeds_limit_distance_m != null
                          ? `${Math.round(r.exceeds_limit_distance_m)} m`
                          : "—"}
                      </span>
                      <span>Score {r.accessibility_score ?? "—"}</span>
                      <span>Stairs: {r.stairs_status}</span>
                    </div>
                    {r.selection_reasons?.length > 0 && (
                      <p className="route-card-reason">{r.selection_reasons[0]}</p>
                    )}
                  </button>
                ))}
              </div>

              {selectedRoute && (
                <>
                  {selectedRoute.selection_reasons?.length > 0 && (
                    <div className="selection-reasons">
                      {selectedRoute.selection_reasons.map((reason, i) => (
                        <p key={i}>{reason}</p>
                      ))}
                    </div>
                  )}
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

                  <div className={`stair-status stair-${selectedRoute.stairs_status}`}>
                    <span
                      className="stair-dot"
                      style={{ background: STAIR_STATUS_COLOR[selectedRoute.stairs_status] }}
                    />
                    <div>
                      <strong>{stairStatusMessage(selectedRoute.stairs_status)}</strong>
                      {!["not_detected", "unknown"].includes(selectedRoute.stairs_status) && (
                        <span className="stair-meta">
                          {" "}
                          · {Math.round((selectedRoute.stairs_confidence || 0) * 100)}% confidence
                        </span>
                      )}
                      {stairSourceSummary(selectedRoute) && (
                        <p className="stair-sources">
                          Evidence: {stairSourceSummary(selectedRoute)}
                        </p>
                      )}
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
            <>
              <div ref={mapContainer} className="map-canvas" />
              {status === "success" && selectedRoute && (
                <div className="slope-legend">
                  <p className="slope-legend-title">Local slope</p>
                  {slopeAvailable ? (
                    <ul>
                      {["low", "moderate", "challenging", "exceeds_limit"].map((c) => (
                        <li key={c}>
                          <span
                            className="slope-swatch"
                            style={{ background: SLOPE_COLORS[c] }}
                          />
                          {SLOPE_LABELS[c]}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="slope-legend-note">
                      Detailed slope coloring unavailable (no elevation data). Showing
                      the route line only.
                    </p>
                  )}
                  {hasStairOverlay(selectedRoute) && (
                    <div className="legend-stairs">
                      <span
                        className="slope-swatch stair-swatch"
                        style={{ background: STAIR_STATUS_COLOR[selectedRoute.stairs_status] }}
                      />
                      {stairStatusMessage(selectedRoute.stairs_status)}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
