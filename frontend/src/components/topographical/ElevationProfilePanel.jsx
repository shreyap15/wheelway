import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function formatDistance(value) {
  if (!Number.isFinite(Number(value))) {
    return "";
  }

  return `${Math.round(Number(value))} m`;
}

function formatElevation(value) {
  if (!Number.isFinite(Number(value))) {
    return "";
  }

  return `${Number(value).toFixed(1)} m`;
}

function chartDataForRoute(sampledRoute) {
  return sampledRoute.map((sample) => ({
    distanceM: Number(sample.cumulativeDistanceM.toFixed(1)),
    elevationM: Number(sample.elevationM.toFixed(2)),
    terrainElevationM: Number(sample.terrainElevationM.toFixed(2)),
    surfaceOffsetM: Number(sample.surfaceOffsetM.toFixed(2)),
  }));
}

export default function ElevationProfilePanel({
  sampledRoute,
  hoveredDistanceM,
  setHoveredDistanceM,
}) {
  const chartData = chartDataForRoute(sampledRoute);

  function handleMouseMove(state) {
    if (state?.activeLabel === null || state?.activeLabel === undefined) {
      return;
    }

    setHoveredDistanceM(Number(state.activeLabel));
  }

  return (
    <section className="elevation-profile-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Route profile</p>
          <h2>Terrain-conforming elevation</h2>
        </div>

        <span>{formatDistance(sampledRoute.at(-1)?.cumulativeDistanceM ?? 0)}</span>
      </div>

      <div className="profile-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={chartData}
            margin={{ top: 8, right: 12, bottom: 0, left: -12 }}
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setHoveredDistanceM(null)}
          >
            <CartesianGrid stroke="rgba(255,255,255,0.16)" vertical={false} />
            <XAxis
              dataKey="distanceM"
              tickFormatter={formatDistance}
              stroke="rgba(255,255,255,0.68)"
              tick={{ fontSize: 11 }}
              type="number"
              domain={["dataMin", "dataMax"]}
            />
            <YAxis
              tickFormatter={formatElevation}
              stroke="rgba(255,255,255,0.68)"
              tick={{ fontSize: 11 }}
              width={62}
            />
            <Tooltip
              cursor={{ stroke: "rgba(100, 190, 255, 0.7)", strokeWidth: 1 }}
              contentStyle={{
                background: "rgba(12, 20, 22, 0.92)",
                border: "1px solid rgba(255,255,255,0.16)",
                borderRadius: 12,
                color: "#f4fbf8",
              }}
              formatter={(value, name) => {
                return [formatElevation(value), name];
              }}
              labelFormatter={(value) => `Distance ${formatDistance(value)}`}
            />
            <Area
              dataKey="terrainElevationM"
              fill="rgba(89, 142, 116, 0.25)"
              stroke="transparent"
              name="Terrain"
            />
            <Line
              dataKey="elevationM"
              dot={false}
              stroke="#5ec2ff"
              strokeWidth={2.4}
              name="Surface"
              type="monotone"
            />
            {hoveredDistanceM !== null && hoveredDistanceM !== undefined && (
              <ReferenceLine
                x={Number(hoveredDistanceM.toFixed(1))}
                stroke="#8dd9ff"
                strokeWidth={1.4}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="profile-note">
        Elevation prioritizes backend/sensor Z, then Mapbox terrain, then zero
        fallback. Centimeter-scale bumps require measured samples.
      </p>
    </section>
  );
}
