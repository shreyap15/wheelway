import { useCallback, useEffect, useState } from "react";
import "./App.css";
import { TopographicalAccessibilityMap } from "./components/topographical";

const API_URL = "http://127.0.0.1:5000";

function App() {
  const [selectedRoute, setSelectedRoute] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadDemoRoute = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/routes/demo`);

      if (!response.ok) {
        throw new Error("Could not retrieve the demo accessibility route.");
      }

      const data = await response.json();
      setSelectedRoute(data);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDemoRoute();
  }, [loadDemoRoute]);

  if (loading && !selectedRoute) {
    return (
      <main className="topographical-shell empty-topographical-shell">
        <div className="empty-state">Loading terrain route...</div>
      </main>
    );
  }

  return (
    <>
      {error && (
        <div className="global-error-banner">
          {error}
          <button onClick={loadDemoRoute} type="button">
            Retry
          </button>
        </div>
      )}
      <TopographicalAccessibilityMap
        routeSegments={selectedRoute?.segments ?? []}
        routeSummary={selectedRoute}
      />
    </>
  );
}

export default App;