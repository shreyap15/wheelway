import { useCallback, useEffect, useState } from "react";
import "./App.css";
import { TopographicalAccessibilityMap } from "./components/topographical";
import { DEMO_ROUTE } from "./data/demoRoute";
import { snapRouteToStreets } from "./services/snapRouteToStreets";

const API_URL = "http://127.0.0.1:5000";
const MAPBOX_ACCESS_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;

async function fetchDemoRoute() {
  const response = await fetch(`${API_URL}/routes/demo`);

  if (!response.ok) {
    throw new Error("Could not retrieve the demo accessibility route.");
  }

  return response.json();
}

async function loadBaseRoute() {
  try {
    return {
      route: await fetchDemoRoute(),
      warning: "",
    };
  } catch (err) {
    return {
      route: DEMO_ROUTE,
      warning: `${err.message} Showing bundled demo geometry.`,
    };
  }
}

async function prepareDisplayRoute() {
  const { route, warning } = await loadBaseRoute();
  const snapOptions = {
    accessToken: MAPBOX_ACCESS_TOKEN,
    mode: "directions",
    profile: "walking",
  };

  if (!MAPBOX_ACCESS_TOKEN) {
    return {
      route: await snapRouteToStreets(route, snapOptions),
      warning: `${warning ? `${warning} ` : ""}Set VITE_MAPBOX_TOKEN to snap broad nodes to the Mapbox walking network.`,
    };
  }

  try {
    return {
      route: await snapRouteToStreets(route, snapOptions),
      warning,
    };
  } catch (err) {
    return {
      route: await snapRouteToStreets(route, {
        mode: "directions",
        profile: "walking",
      }),
      warning: `${warning ? `${warning} ` : ""}${err.message} Showing unsnapped fallback geometry.`,
    };
  }
}

function App() {
  const [selectedRoute, setSelectedRoute] = useState(DEMO_ROUTE);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadDemoRoute = useCallback(async () => {
    setLoading(true);
    try {
      const { route, warning } = await prepareDisplayRoute();
      setSelectedRoute(route);
      setError(warning);
    } catch (err) {
      setSelectedRoute(DEMO_ROUTE);
      setError(`${err.message} Showing bundled demo geometry.`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let isCancelled = false;

    prepareDisplayRoute()
      .then(({ route, warning }) => {
        if (!isCancelled) {
          setSelectedRoute(route);
          setError(warning);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          setSelectedRoute(DEMO_ROUTE);
          setError(`${err.message} Showing bundled demo geometry.`);
        }
      })
      .finally(() => {
        if (!isCancelled) {
          setLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, []);

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