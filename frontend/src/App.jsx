import { lazy, Suspense, useEffect, useState } from "react";
import "./App.css";
import RealRoutePlanner from "./RealRoutePlanner";
import VoiceAlerts from "./components/VoiceAlerts";
import VisionStatus from "./components/VisionStatus";
import SponsorDiagnostics from "./components/SponsorDiagnostics";
import {
  REAL_MODE_LABEL,
  SYNTHETIC_MODE_LABEL,
  SYNTHETIC_MODE_SUBLABEL,
  syntheticDemoEnabled,
} from "./syntheticMode";

const API_URL = "http://127.0.0.1:5000";

// Synthetic A* demo is dev-flag-gated and lazy-loaded, so its code is never
// fetched in the normal presentation build.
const RoutePlanner = lazy(() => import("./RoutePlanner"));

// Evaluated once at module load from the Vite env.
const SYNTHETIC_ENABLED = syntheticDemoEnabled(import.meta.env);

function App() {
  const [observations, setObservations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [error, setError] = useState("");
  // "real" = API-derived geometry; "demo" = synthetic A* prototype (dev only).
  const [routeMode, setRouteMode] = useState("real");
  const showSynthetic = SYNTHETIC_ENABLED && routeMode === "demo";

  const latestObservation =
    observations.length > 0
      ? observations[observations.length - 1]
      : null;

  async function checkBackend() {
    try {
      const response = await fetch(`${API_URL}/health`);

      if (!response.ok) {
        throw new Error("Backend health check failed.");
      }

      setBackendOnline(true);
      setError("");
    } catch {
      setBackendOnline(false);
      setError("Wheelway backend is offline.");
    }
  }

  async function loadObservations() {
    try {
      const response = await fetch(`${API_URL}/observations`);

      if (!response.ok) {
        throw new Error("Could not retrieve observations.");
      }

      const data = await response.json();
      setObservations(data);
      setBackendOnline(true);
      setError("");
    } catch (err) {
      setBackendOnline(false);
      setError(err.message);
    }
  }

  async function simulateReading() {
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/simulate`, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error("Could not generate simulated reading.");
      }

      await loadObservations();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    checkBackend();
    loadObservations();

    const interval = setInterval(loadObservations, 1000);

    return () => clearInterval(interval);
  }, []);

  function formatTime(timestamp) {
    return new Date(timestamp).toLocaleTimeString();
  }

  return (
    <main className="app">
      <header className="header">
        <div>
          <p className="eyebrow">Accessibility Digital Shadow</p>
          <h1>Wheelway</h1>
          <p className="subtitle">
            Live environmental sensing for accessible navigation
          </p>
        </div>

        <div
          className={`status ${
            backendOnline ? "status-online" : "status-offline"
          }`}
        >
          <span className="status-dot" />
          {backendOnline ? "System online" : "System offline"}
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {/* Dev-only mode switch. Absent from the presentation UI, so it opens
          directly into the Real Accessible Route. */}
      {SYNTHETIC_ENABLED && (
        <section className="mode-switch">
          <button
            className={routeMode === "real" ? "active" : ""}
            onClick={() => setRouteMode("real")}
          >
            {REAL_MODE_LABEL}
            <span>Mapbox geometry · Google elevation · live data</span>
          </button>
          <button
            className={routeMode === "demo" ? "active" : ""}
            onClick={() => setRouteMode("demo")}
          >
            {SYNTHETIC_MODE_LABEL}
            <span>{SYNTHETIC_MODE_SUBLABEL}</span>
          </button>
        </section>
      )}

      {/* Primary surface: the real accessible route. The synthetic component is
          only mounted (and only its chunk fetched) when the dev flag is on. */}
      {showSynthetic ? (
        <Suspense fallback={<div className="route-state state-loading">Loading demo…</div>}>
          <RoutePlanner />
        </Suspense>
      ) : (
        <RealRoutePlanner />
      )}

      {/* Live camera obstacle-detection status + hazard banner (vision_modal). */}
      <VisionStatus observations={observations} />

      {/* Voice alerts: real-route and camera hazards both emit voice triggers. */}
      <VoiceAlerts />

      <section className="dashboard-grid">
        <article className="card distance-card">
          <p className="card-label">Nearest obstacle</p>

          <div className="distance-value">
            {latestObservation
              ? latestObservation.distance_cm
              : "--"}
            <span>cm</span>
          </div>

          <p className="card-description">
            HC-SR04 ultrasonic distance reading
          </p>
        </article>

        <article
          className={`card alert-card ${
            latestObservation
              ? `alert-${latestObservation.alert_level}`
              : ""
          }`}
        >
          <p className="card-label">Current status</p>

          <h2>
            {latestObservation
              ? latestObservation.alert_level.toUpperCase()
              : "WAITING"}
          </h2>

          <p>
            {latestObservation
              ? latestObservation.alert_message
              : "No sensor readings received yet."}
          </p>
        </article>

        <article className="card device-card">
          <p className="card-label">Connected device</p>

          <h2>
            {latestObservation
              ? latestObservation.device_id
              : "No device"}
          </h2>

          <p>
            {latestObservation
              ? `Last reading at ${formatTime(
                  latestObservation.timestamp
                )}`
              : "Waiting for Raspberry Pi connection"}
          </p>
        </article>
      </section>

      <section className="controls">
        <button
          onClick={simulateReading}
          disabled={loading || !backendOnline}
        >
          {loading ? "Generating..." : "Simulate sensor reading"}
        </button>
      </section>

      {/* Dev diagnostics: self-hidden unless VITE_SHOW_DIAGNOSTICS is set. */}
      <SponsorDiagnostics />

      <section className="history-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Digital shadow history</p>
            <h2>Recent observations</h2>
          </div>

          <span>{observations.length} readings</span>
        </div>

        {observations.length === 0 ? (
          <div className="empty-state">
            No observations yet. Generate a simulated reading.
          </div>
        ) : (
          <div className="observation-list">
            {[...observations]
              .reverse()
              .map((observation, index) => (
                <article
                  className="observation-row"
                  key={`${observation.timestamp}-${index}`}
                >
                  <div
                    className={`severity-indicator severity-${observation.alert_level}`}
                  />

                  <div className="observation-main">
                    <strong>
                      {observation.distance_cm} cm
                    </strong>
                    <span>{observation.alert_message}</span>
                  </div>

                  <div className="observation-meta">
                    <span>{observation.device_id}</span>
                    <span>
                      {formatTime(observation.timestamp)}
                    </span>
                  </div>
                </article>
              ))}
          </div>
        )}
      </section>
    </main>
  );
}

export default App;