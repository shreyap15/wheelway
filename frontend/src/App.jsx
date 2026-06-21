import { useEffect, useState } from "react";
import { TopographicalAccessibilityMap } from "./components/topographical";
import "./App.css";

const API_URL = "http://127.0.0.1:5000";

const TOPOGRAPHICAL_DEMO_SEGMENTS = [
  {
    id: "hearst-gentle-approach",
    coordinates: [
      [-122.2686, 37.8717, 84],
      [-122.2679, 37.8715, 86],
      [-122.2671, 37.8712, 88],
    ],
    accessibilityScore: 92,
    runningSlopePct: 2.4,
    crossSlopePct: 1.1,
    type: "sidewalk",
    surface: "concrete",
  },
  {
    id: "campus-cross-slope-warning",
    coordinates: [
      [-122.2671, 37.8712, 88],
      [-122.2664, 37.8709, 92],
      [-122.2658, 37.8706, 97],
    ],
    accessibilityScore: 68,
    runningSlopePct: 5.7,
    crossSlopePct: 2.6,
    type: "sidewalk",
    surface: "pavers",
  },
  {
    id: "curb-without-ramp-barrier",
    coordinates: [
      [-122.2658, 37.8706, 97],
      [-122.2653, 37.8702, 105],
    ],
    accessibilityScore: 24,
    runningSlopePct: 9.8,
    crossSlopePct: 4.1,
    type: "curb_no_ramp",
    surface: "asphalt",
  },
  {
    id: "south-detour-recovery",
    coordinates: [
      [-122.2653, 37.8702, 105],
      [-122.266, 37.8698, 101],
      [-122.267, 37.8696, 96],
    ],
    accessibilityScore: 83,
    runningSlopePct: 3.2,
    crossSlopePct: 1.4,
    type: "sidewalk",
    surface: "concrete",
  },
];

function App() {
  const [observations, setObservations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [error, setError] = useState("");

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
    const refresh = () => {
      checkBackend();
      loadObservations();
    };

    const initialRefresh = setTimeout(refresh, 0);
    const interval = setInterval(refresh, 1000);

    return () => {
      clearTimeout(initialRefresh);
      clearInterval(interval);
    };
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

        <p>
          This button temporarily acts like the Raspberry Pi.
        </p>
      </section>

      <section className="topographical-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Topographical routing</p>
            <h2>Terrain-aware accessibility</h2>
          </div>

          <span>{TOPOGRAPHICAL_DEMO_SEGMENTS.length} route segments</span>
        </div>

        <TopographicalAccessibilityMap
          routeSegments={TOPOGRAPHICAL_DEMO_SEGMENTS}
          allSegments={TOPOGRAPHICAL_DEMO_SEGMENTS}
        />
      </section>

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
