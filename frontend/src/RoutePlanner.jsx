import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import {
  GRAPH_CENTER,
  GRAPH_NODES,
  NETWORK_BOUNDS,
  NODES,
  nodeLngLat,
} from "./graphNodes";

const API_URL = "http://127.0.0.1:5000";
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;

const WHEELCHAIR_TYPES = [
  { value: "manual", label: "Manual" },
  { value: "powered", label: "Powered" },
  { value: "scooter", label: "Scooter" },
  { value: "walker", label: "Walker" },
];

// Map a 0-100 accessibility score to a color for the route segment.
function scoreColor(score) {
  if (score >= 80) return "#2f9b5f"; // great
  if (score >= 60) return "#9bc53d"; // ok
  if (score >= 40) return "#e8af45"; // poor
  return "#d94444"; // bad
}

// Derive human-readable warnings from the returned route steps.
function deriveWarnings(steps) {
  const warnings = [];
  for (const step of steps) {
    const s = step.segment;
    const where = `${s.start_node_id}→${s.end_node_id}`;
    if (s.stairs) warnings.push(`Stairs on ${where}`);
    if (s.has_obstruction) warnings.push(`Obstruction on ${where}`);
    if (s.slope >= 8.33) warnings.push(`Steep ${s.slope}% slope on ${where}`);
    if (s.width < 0.91) warnings.push(`Narrow ${s.width}m width on ${where}`);
    if (["gravel", "dirt", "grass"].includes(s.surface))
      warnings.push(`Rough ${s.surface} surface on ${where}`);
    if (step.accessibility_score < 40)
      warnings.push(`Low score (${step.accessibility_score}/100) on ${where}`);
  }
  return warnings;
}

export default function RoutePlanner() {
  const mapContainer = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef([]);
  const [mapReady, setMapReady] = useState(false);

  const [start, setStart] = useState("sather_gate");
  const [destination, setDestination] = useState("bancroft_tele");

  // Mobility profile controls
  const [wheelchairType, setWheelchairType] = useState("manual");
  const [avoidStairs, setAvoidStairs] = useState(true);
  const [maxSlope, setMaxSlope] = useState(8.33);
  const [minWidth, setMinWidth] = useState(0.91);

  // Request state machine: idle | loading | success | offline | validation | no-route | error
  const [status, setStatus] = useState("idle");
  const [route, setRoute] = useState(null);
  const [message, setMessage] = useState("");

  // --- Map init (once) ---
  useEffect(() => {
    if (!MAPBOX_TOKEN || mapRef.current) return;
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/streets-v12",
      center: GRAPH_CENTER,
      zoom: 16,
    });
    map.on("load", () => {
      // Fit the viewport to the whole demo network on first load.
      map.fitBounds(NETWORK_BOUNDS, { padding: 70, maxZoom: 17, duration: 0 });
      map.addSource("route", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ["get", "color"], "line-width": 6 },
      });
      setMapReady(true);
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // --- Draw route whenever it changes ---
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const src = map.getSource("route");
    if (!src) return;

    // clear old markers
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (!route || !route.found || route.steps.length === 0) {
      src.setData({ type: "FeatureCollection", features: [] });
      return;
    }

    const features = [];
    const allCoords = [];
    for (const step of route.steps) {
      // Prefer the backend-provided segment geometry (real path shape).
      // Fall back to a straight node-to-node line only if geometry is absent.
      let coords = step.segment.geometry?.coordinates;
      if (!coords || coords.length < 2) {
        const a = nodeLngLat(step.segment.start_node_id);
        const b = nodeLngLat(step.segment.end_node_id);
        if (!a || !b) continue;
        coords = [a, b];
      }
      features.push({
        type: "Feature",
        properties: { color: scoreColor(step.accessibility_score) },
        geometry: { type: "LineString", coordinates: coords },
      });
      allCoords.push(...coords);
    }
    src.setData({ type: "FeatureCollection", features });

    // start + end markers
    const startLngLat = nodeLngLat(route.steps[0].segment.start_node_id);
    const endLngLat = nodeLngLat(
      route.steps[route.steps.length - 1].segment.end_node_id
    );
    if (startLngLat)
      markersRef.current.push(
        new mapboxgl.Marker({ color: "#183e2c" })
          .setLngLat(startLngLat)
          .setPopup(
            new mapboxgl.Popup().setText(
              `Start: ${GRAPH_NODES[start]?.name ?? start}`
            )
          )
          .addTo(map)
      );
    if (endLngLat)
      markersRef.current.push(
        new mapboxgl.Marker({ color: "#d94444" })
          .setLngLat(endLngLat)
          .setPopup(
            new mapboxgl.Popup().setText(
              `Destination: ${GRAPH_NODES[destination]?.name ?? destination}`
            )
          )
          .addTo(map)
      );

    // fit map to the route
    if (allCoords.length > 0) {
      const bounds = allCoords.reduce(
        (b, c) => b.extend(c),
        new mapboxgl.LngLatBounds(allCoords[0], allCoords[0])
      );
      map.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
    }
  }, [route, mapReady, start, destination]);

  async function planRoute() {
    if (start === destination) {
      setStatus("validation");
      setRoute(null);
      setMessage("Start and destination must be different nodes.");
      return;
    }

    setStatus("loading");
    setMessage("");
    setRoute(null);

    const body = {
      start_node_id: start,
      end_node_id: destination,
      profile: {
        wheelchair_type: wheelchairType,
        avoid_stairs: avoidStairs,
        max_slope_pct: Number(maxSlope),
        min_width_m: Number(minWidth),
      },
    };

    let response;
    try {
      response = await fetch(`${API_URL}/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      setStatus("offline");
      setMessage("Wheelway backend is offline. Start it on 127.0.0.1:5000.");
      return;
    }

    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (response.status === 400) {
      setStatus("validation");
      setMessage(data?.error || "Invalid routing request.");
      return;
    }

    if (response.status === 404 || (data && data.found === false)) {
      setStatus("no-route");
      setMessage(
        data?.failure_reason ||
          "No accessible route found under these mobility settings."
      );
      return;
    }

    if (!response.ok || !data) {
      setStatus("error");
      setMessage(`Routing failed (HTTP ${response.status}).`);
      return;
    }

    setRoute(data);
    setStatus("success");
  }

  const warnings = route?.found ? deriveWarnings(route.steps) : [];
  const tokenMissing = !MAPBOX_TOKEN;

  return (
    <section className="route-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Accessibility algorithm demo · synthetic A*</p>
          <h2>Plan a route</h2>
          <p className="muted">
            Synthetic graph for the personalized A* scoring/avoidance prototype —
            NOT a real Berkeley pedestrian network. Coordinates are hand-mocked.
          </p>
        </div>
      </div>

      <div className="route-layout">
        <div className="route-controls">
          <div className="control-group">
            <label>
              Start
              <select
                value={start}
                onChange={(e) => setStart(e.target.value)}
              >
                {NODES.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Destination
              <select
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
              >
                {NODES.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <p className="control-subhead">Mobility settings</p>

          <div className="control-group">
            <label>
              Wheelchair type
              <select
                value={wheelchairType}
                onChange={(e) => setWheelchairType(e.target.value)}
              >
                {WHEELCHAIR_TYPES.map((w) => (
                  <option key={w.value} value={w.value}>
                    {w.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={avoidStairs}
                onChange={(e) => setAvoidStairs(e.target.checked)}
              />
              Avoid stairs
            </label>
          </div>

          <div className="control-group">
            <label>
              Max slope (%)
              <input
                type="number"
                step="0.1"
                min="0"
                max="40"
                value={maxSlope}
                onChange={(e) => setMaxSlope(e.target.value)}
              />
            </label>

            <label>
              Min width (m)
              <input
                type="number"
                step="0.01"
                min="0"
                value={minWidth}
                onChange={(e) => setMinWidth(e.target.value)}
              />
            </label>
          </div>

          <button
            className="route-button"
            onClick={planRoute}
            disabled={status === "loading"}
          >
            {status === "loading" ? "Finding route..." : "Find accessible route"}
          </button>

          {status === "loading" && (
            <div className="route-state state-loading">Computing route…</div>
          )}
          {status === "offline" && (
            <div className="route-state state-error">{message}</div>
          )}
          {status === "validation" && (
            <div className="route-state state-warn">{message}</div>
          )}
          {status === "no-route" && (
            <div className="route-state state-warn">No route: {message}</div>
          )}
          {status === "error" && (
            <div className="route-state state-error">{message}</div>
          )}

          {status === "success" && route && (
            <div className="route-summary">
              <div className="summary-stats">
                <div className="stat">
                  <span className="stat-label">Distance</span>
                  <strong>{route.total_distance_m} m</strong>
                </div>
                <div className="stat">
                  <span className="stat-label">Avg. score</span>
                  <strong>{route.average_accessibility_score}/100</strong>
                </div>
                <div className="stat">
                  <span className="stat-label">Segments</span>
                  <strong>{route.steps.length}</strong>
                </div>
              </div>

              <div className="warnings-block">
                <p className="control-subhead">
                  Warnings ({warnings.length})
                </p>
                {warnings.length === 0 ? (
                  <p className="no-warnings">
                    No accessibility warnings on this route.
                  </p>
                ) : (
                  <ul className="warning-list">
                    {warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="legend">
                <span>
                  <i style={{ background: "#2f9b5f" }} /> 80+
                </span>
                <span>
                  <i style={{ background: "#9bc53d" }} /> 60–79
                </span>
                <span>
                  <i style={{ background: "#e8af45" }} /> 40–59
                </span>
                <span>
                  <i style={{ background: "#d94444" }} /> &lt;40
                </span>
              </div>
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
