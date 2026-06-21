import { useCallback, useEffect, useMemo, useState } from "react";
import { TopographicalAccessibilityMap } from "./components/topographical";
import "./App.css";

const API_URL = "http://127.0.0.1:5000";
const POLL_INTERVAL_MS = 2000;

// Completely flattened to match the exact mathematical requirements of topographicalUtils.js
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
    bumpHeightM: 0.12,
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

function StatusBadge({ online }) {
  return (
    <div
      className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold shadow-lg backdrop-blur-xl ${
        online
          ? "border-teal-400/30 bg-teal-500/15 text-teal-200"
          : "border-rose-400/30 bg-rose-500/15 text-rose-200"
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          online ? "animate-pulse bg-teal-300" : "bg-rose-400"
        }`}
      />
      {online ? "System Online" : "System Offline"}
    </div>
  );
}

function FloatingNavigation({
  activeTab,
  onTabChange,
  backendOnline,
}) {
  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-50 flex items-start justify-between gap-4 p-3 sm:p-5">
      <div className="pointer-events-auto rounded-2xl border border-white/10 bg-slate-950/75 px-4 py-3 shadow-2xl backdrop-blur-xl">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-300">
          Accessibility Digital Shadow
        </p>
        <h1 className="text-xl font-black tracking-tight text-white">
          WheelWay
        </h1>
      </div>

      <nav
        aria-label="Primary view"
        className="pointer-events-auto absolute left-1/2 top-3 -translate-x-1/2 rounded-xl border border-white/10 bg-slate-950/80 p-1 shadow-2xl backdrop-blur-xl sm:top-5"
      >
        <div className="flex">
          {[
            ["map", "Terrain Map"],
            ["hardware", "Hardware"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => onTabChange(value)}
              aria-pressed={activeTab === value}
              className={`rounded-lg px-3 py-2 text-xs font-semibold transition sm:px-4 sm:text-sm ${
                activeTab === value
                  ? "bg-teal-400 text-slate-950 shadow"
                  : "text-slate-300 hover:bg-white/10 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      <div className="pointer-events-auto hidden sm:block">
        <StatusBadge online={backendOnline} />
      </div>
    </header>
  );
}

// Error notification layout
function ErrorToast({ message, onDismiss }) {
  if (!message) return null;

  return (
    <div className="fixed left-1/2 top-24 z-[60] w-[min(32rem,calc(100%-2rem))] -translate-x-1/2 rounded-xl border border-rose-400/30 bg-rose-950/90 px-4 py-3 text-sm text-rose-100 shadow-2xl backdrop-blur-xl">
      <div className="flex items-start justify-between gap-4">
        <p>{message}</p>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded px-2 hover:bg-white/10"
          aria-label="Dismiss error"
        >
          ×
        </button>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  unit,
  description,
  accentClass = "text-white",
}) {
  return (
    <article className="rounded-2xl border border-white/10 bg-slate-900/80 p-5 shadow-xl backdrop-blur">
      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </p>
      <div
        className={`mt-2 flex items-baseline gap-1 text-4xl font-black ${accentClass}`}
      >
        <span>{value}</span>
        {unit && (
          <span className="text-lg font-medium text-slate-400">
            {unit}
          </span>
        )}
      </div>
      <p className="mt-2 text-xs leading-5 text-slate-400">
        {description}
      </p>
    </article>
  );
}

function HardwareDashboard({
  observations,
  latestObservation,
  backendOnline,
  loading,
  onSimulate,
  formatTime,
}) {
  const statusColor =
    latestObservation?.alert_level === "danger"
      ? "text-rose-300"
      : latestObservation?.alert_level === "warning"
        ? "text-amber-300"
        : "text-teal-300";

  return (
    <section className="absolute inset-0 overflow-y-auto bg-slate-950 px-4 pb-8 pt-28 text-slate-100 sm:px-6 sm:pt-32 lg:px-10">
      <div className="mx-auto max-w-7xl space-y-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-teal-300">
            Raspberry Pi and Sensor Pipeline
          </p>
          <h2 className="mt-1 text-3xl font-black tracking-tight text-white">
            Hardware Telemetry
          </h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">
            Live obstacle readings and device health are isolated here while
            terrain navigation remains full-screen in the map tab.
          </p>
        </div>

        <div className="sm:hidden">
          <StatusBadge online={backendOnline} />
        </div>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <MetricCard
            label="Nearest Obstacle"
            value={latestObservation?.distance_cm ?? "--"}
            unit="cm"
            description="HC-SR04 ultrasonic sensor telemetry."
          />
          <MetricCard
            label="Current Status"
            value={
              latestObservation
                ? latestObservation.alert_level.toUpperCase()
                : "WAITING"
            }
            description={
              latestObservation?.alert_message ??
              "No sensor readings received yet."
            }
            accentClass={statusColor}
          />
          <MetricCard
            label="Connected Device"
            value={latestObservation?.device_id ?? "No Device"}
            description={
              latestObservation
                ? `Last reading at ${formatTime(
                    latestObservation.timestamp,
                  )}`
                : "Waiting for the Raspberry Pi pipeline."
            }
          />
        </section>

        <section className="flex flex-col gap-4 rounded-2xl border border-white/10 bg-slate-900/80 p-5 shadow-xl backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-lg font-bold text-white">
              Hardware Simulator
            </h3>
            <p className="mt-1 text-sm text-slate-400">
              Generate a mock observation through the existing FastAPI endpoint.
            </p>
          </div>

          <button
            type="button"
            onClick={onSimulate}
            disabled={loading || !backendOnline}
            className="shrink-0 rounded-xl bg-teal-400 px-5 py-3 text-sm font-bold text-slate-950 shadow-lg transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
          >
            {loading ? "Generating..." : "Simulate Sensor Reading"}
          </button>
        </section>

        <section className="rounded-2xl border border-white/10 bg-slate-900/80 p-5 shadow-xl backdrop-blur">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-bold text-white">
                Observation Stream
              </h3>
              <p className="mt-1 text-sm text-slate-400">
                Newest readings appear first.
              </p>
            </div>
            <span className="rounded-full bg-slate-800 px-3 py-1 text-xs font-semibold text-slate-300">
              {observations.length} records
            </span>
          </div>

          {observations.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-700 px-4 py-10 text-center text-sm text-slate-500">
              No readings yet.
            </div>
          ) : (
            <div className="max-h-[32rem] space-y-2 overflow-y-auto pr-1">
              {[...observations].reverse().map((observation, index) => {
                const dotClass =
                  observation.alert_level === "danger"
                    ? "bg-rose-500"
                    : observation.alert_level === "warning"
                      ? "bg-amber-500"
                      : "bg-teal-500";

                return (
                  <article
                    key={`${observation.timestamp}-${index}`}
                    className="flex flex-col gap-3 rounded-xl border border-white/5 bg-slate-950/70 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex items-start gap-3">
                      <span
                        className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dotClass}`}
                      />
                      <div>
                        <p className="font-semibold text-slate-200">
                          {observation.distance_cm} cm
                        </p>
                        <p className="mt-0.5 text-sm text-slate-400">
                          {observation.alert_message}
                        </p>
                      </div>
                    </div>
                    <time className="text-xs font-mono text-slate-500">
                      {formatTime(observation.timestamp)}
                    </time>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState("map");
  const [observations, setObservations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const [error, setError] = useState("");

  const latestObservation = useMemo(
    () => observations.at(-1) ?? null,
    [observations],
  );

  const checkBackend = useCallback(async (signal) => {
    try {
      const response = await fetch(`${API_URL}/health`, { signal });
      if (!response.ok) throw new Error("Backend health check failed.");
      setBackendOnline(true);
      return true;
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setBackendOnline(false);
      }
      return false;
    }
  }, []);

  const loadObservations = useCallback(async (signal) => {
    try {
      const response = await fetch(`${API_URL}/observations`, {
        signal,
      });
      if (!response.ok) {
        throw new Error("Could not retrieve observations.");
      }

      const data = await response.json();
      setObservations(Array.isArray(data) ? data : []);
      setBackendOnline(true);
      setError("");
    } catch (requestError) {
      if (requestError.name === "AbortError") return;
      setBackendOnline(false);
      setError(requestError.message);
    }
  }, []);

  const refreshHardwareData = useCallback(
    async (signal) => {
      const online = await checkBackend(signal);
      if (online) {
        await loadObservations(signal);
      }
    },
    [checkBackend, loadObservations],
  );

  useEffect(() => {
    const controller = new AbortController();
    checkBackend(controller.signal);
    return () => controller.abort();
  }, [checkBackend]);

  useEffect(() => {
    if (activeTab !== "hardware") return undefined;

    const controller = new AbortController();
    refreshHardwareData(controller.signal);

    const intervalId = window.setInterval(() => {
      refreshHardwareData(controller.signal);
    }, POLL_INTERVAL_MS);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [activeTab, refreshHardwareData]);

  const simulateReading = useCallback(async () => {
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/simulate`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error("Could not generate simulated reading.");
      }
      await loadObservations();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, [loadObservations]);

  const formatTime = useCallback((timestamp) => {
    const date = new Date(timestamp);

    return Number.isNaN(date.getTime())
      ? "Unknown time"
      : date.toLocaleTimeString([], {
          hour: "numeric",
          minute: "2-digit",
          second: "2-digit",
        });
  }, []);

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      <FloatingNavigation
        activeTab={activeTab}
        onTabChange={setActiveTab}
        backendOnline={backendOnline}
      />

      <ErrorToast
        message={error}
        onDismiss={() => setError("")}
      />

      <section
        className={`absolute inset-0 ${
          activeTab === "map"
            ? "visible opacity-100"
            : "invisible opacity-0"
        }`}
        aria-hidden={activeTab !== "map"}
      >
        <TopographicalAccessibilityMap
          routeSegments={TOPOGRAPHICAL_DEMO_SEGMENTS}
          allSegments={TOPOGRAPHICAL_DEMO_SEGMENTS}
        />
      </section>

      {activeTab === "hardware" && (
        <HardwareDashboard
          observations={observations}
          latestObservation={latestObservation}
          backendOnline={backendOnline}
          loading={loading}
          onSimulate={simulateReading}
          formatTime={formatTime}
        />
      )}
    </main>
  );
}

export default App;