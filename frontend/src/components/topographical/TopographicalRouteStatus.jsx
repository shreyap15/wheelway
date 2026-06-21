import { memo } from "react";

function Metric({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function TopographicalRouteStatus({ summary }) {
  const statusClass = summary.hasObstacle
    ? "topographical-validation topographical-validation-obstacle"
    : "topographical-validation topographical-validation-accessible";

  return (
    <aside className="topographical-panel topographical-route-status">
      <div className={statusClass}>
        <div className="topographical-validation-label">
          Topographical route validation
        </div>
        <div className="topographical-validation-value">
          {summary.hasObstacle ? "Obstacle Encountered" : "Accessible"}
        </div>
      </div>

      <dl>
        <Metric
          label="Distance"
          value={`${Math.round(summary.totalDistanceMeters)} m`}
        />

        <Metric
          label="Max incline"
          value={`${summary.maximumInclinePct.toFixed(1)}%`}
        />

        <Metric
          label="Avg score"
          value={`${Math.round(summary.averageAccessibilityScore)}/100`}
        />
      </dl>
    </aside>
  );
}

export default memo(TopographicalRouteStatus);
