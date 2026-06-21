import { useMemo } from "react";

import DeckTerrainOverlay from "./DeckTerrainOverlay";
import ElevationProfilePanel from "./ElevationProfilePanel";
import TopographicalLegend from "./TopographicalLegend";
import TopographicalRouteStatus from "./TopographicalRouteStatus";
import {
  buildElevationProfile,
  summarizeTopographicalRoute,
} from "./topographicalUtils";

/**
 * App-facing topographical visualization component.
 *
 * DeckTerrainOverlay owns the Mapbox + Deck.gl viewport and animated ramp mesh.
 * This wrapper adds the WheelWay legend, route status, and elevation profile.
 */
export default function TopographicalAccessibilityMap({
  routeSegments = [],
  className = "",
  initialViewState,
  meshOptions,
}) {
  const elevationProfile = useMemo(
    () => buildElevationProfile(routeSegments),
    [routeSegments],
  );

  const routeSummary = useMemo(
    () => summarizeTopographicalRoute(routeSegments),
    [routeSegments],
  );

  return (
    <section className={`topographical-map-shell ${className}`}>
      <DeckTerrainOverlay
        routeSegments={routeSegments}
        meshOptions={meshOptions}
        initialViewState={initialViewState}
        className="topographical-map-viewport"
      />

      <div className="topographical-map-overlay">
        <TopographicalLegend />
        <TopographicalRouteStatus summary={routeSummary} />
        <ElevationProfilePanel data={elevationProfile} />
      </div>
    </section>
  );
}
