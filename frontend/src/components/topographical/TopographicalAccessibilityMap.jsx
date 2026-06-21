import { useMemo, useState } from "react";
import DeckTerrainOverlay from "./DeckTerrainOverlay";
import ElevationProfilePanel from "./ElevationProfilePanel";
import { flattenOrderedRoute } from "./topographicalUtils";

function routeStats(routeSegments, sampledRoute) {
  const totalDistanceM =
    sampledRoute.at(-1)?.cumulativeDistanceM ??
    routeSegments.reduce((sum, segment) => sum + Number(segment.length_m ?? segment.lengthM ?? 0), 0);
  const scores = routeSegments
    .map((segment) =>
      Number(segment.accessibility_score ?? segment.accessibilityScore ?? NaN),
    )
    .filter(Number.isFinite);
  const averageScore =
    scores.length > 0
      ? scores.reduce((sum, score) => sum + score, 0) / scores.length
      : null;

  return {
    totalDistanceM,
    averageScore,
  };
}

function ValidationBadge({ routeSegments, sampledRoute }) {
  const hasGeometry = routeSegments.every(
    (segment) =>
      (segment.geometry?.type === "LineString" &&
        segment.geometry.coordinates?.length >= 2) ||
      segment.coordinates?.length >= 2,
  );
  const hasZ = sampledRoute.some((sample) => sample.elevationM !== null);
  const hasMeasuredOffsets = sampledRoute.some(
    (sample) => Math.abs(sample.surfaceOffsetM ?? 0) > 0 || Math.abs(sample.bumpHeightM ?? 0) > 0,
  );

  return (
    <aside className="validation-badge">
      <p className="eyebrow">Digital shadow inputs</p>
      <ul>
        <li className={hasGeometry ? "valid" : "missing"}>
          Full sidewalk LineString
        </li>
        <li className={hasZ ? "valid" : "missing"}>
          Terrain or backend elevation
        </li>
        <li className={hasMeasuredOffsets ? "valid" : "missing"}>
          Measured bump/surface offsets
        </li>
      </ul>
    </aside>
  );
}

export default function TopographicalAccessibilityMap({
  routeSegments = [],
  routeSummary = null,
}) {
  const [sampledRoute, setSampledRoute] = useState([]);
  const [hoveredDistanceM, setHoveredDistanceM] = useState(null);
  const orderedRoute = useMemo(
    () => flattenOrderedRoute(routeSegments),
    [routeSegments],
  );
  const stats = routeStats(routeSegments, sampledRoute);

  if (!routeSegments.length || orderedRoute.length < 2) {
    return (
      <main className="topographical-shell empty-topographical-shell">
        <div className="empty-state">
          No routed sidewalk geometry is available yet.
        </div>
      </main>
    );
  }

  return (
    <main className="topographical-shell">
      <DeckTerrainOverlay
        routeSegments={routeSegments}
        sampledRoute={sampledRoute}
        setSampledRoute={setSampledRoute}
        hoveredDistanceM={hoveredDistanceM}
        setHoveredDistanceM={setHoveredDistanceM}
      />

      <section className="map-title-card">
        <p className="eyebrow">Accessibility Digital Shadow</p>
        <h1>Wheelway terrain route</h1>
        <p>
          {Math.round(stats.totalDistanceM)} m
          {stats.averageScore !== null
            ? ` | ${stats.averageScore.toFixed(1)}/100 average accessibility`
            : ""}
        </p>
        {routeSummary?.snapping && (
          <p className="route-snapping-status">
            {routeSummary.snapping.snapped
              ? `Snapped to Mapbox ${routeSummary.snapping.profile} network`
              : "Using fallback route geometry"}
          </p>
        )}
        {routeSummary?.failure_reason && (
          <p className="route-warning">{routeSummary.failure_reason}</p>
        )}
      </section>

      <aside className="route-legend">
        <p className="eyebrow">Ribbon score</p>
        <div>
          <span className="legend-swatch accessible" />
          Accessible
        </div>
        <div>
          <span className="legend-swatch caution" />
          Caution
        </div>
        <div>
          <span className="legend-swatch barrier" />
          Barrier
        </div>
      </aside>

      <ValidationBadge routeSegments={routeSegments} sampledRoute={sampledRoute} />

      <ElevationProfilePanel
        sampledRoute={sampledRoute}
        hoveredDistanceM={hoveredDistanceM}
        setHoveredDistanceM={setHoveredDistanceM}
      />
    </main>
  );
}
