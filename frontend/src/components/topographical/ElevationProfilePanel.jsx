import { memo, useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function ElevationTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;

  const point = payload[0].payload;

  return (
    <div className="topographical-chart-tooltip">
      <div className="topographical-chart-tooltip-title">
        {point.distanceMeters} m along route
      </div>
      <div>Elevation: {point.elevationMeters.toFixed(1)} m</div>
      <div>Running slope: {point.runningSlopePct.toFixed(1)}%</div>
      <div>Cross slope: {point.crossSlopePct.toFixed(1)}%</div>
    </div>
  );
}

function ElevationProfilePanel({ data }) {
  const violationRanges = useMemo(
    () =>
      data.slice(1).flatMap((point, index) => {
        if (!point.exceedsRunningSlope && !point.exceedsCrossSlope) {
          return [];
        }

        return [
          {
            start: data[index].distanceMeters,
            end: point.distanceMeters,
          },
        ];
      }),
    [data],
  );

  return (
    <aside className="topographical-panel topographical-elevation-panel">
      <div className="topographical-elevation-heading">
        <h2>Topographical route profile</h2>
        <p>
          Crimson bands mark running slope above 5% or cross slope above 2%.
        </p>
      </div>

      <div className="topographical-elevation-chart">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={data}
            margin={{
              top: 8,
              right: 12,
              bottom: 0,
              left: -12,
            }}
          >
            <defs>
              <linearGradient
                id="wheelwayTopographicalElevation"
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.04} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke="rgba(148,163,184,0.12)" vertical={false} />

            <XAxis
              dataKey="distanceMeters"
              type="number"
              domain={["dataMin", "dataMax"]}
              tick={{
                fill: "#94a3b8",
                fontSize: 11,
              }}
              axisLine={false}
              tickLine={false}
              unit="m"
            />

            <YAxis
              yAxisId="elevation"
              dataKey="elevationMeters"
              domain={["dataMin - 3", "dataMax + 3"]}
              tick={{
                fill: "#94a3b8",
                fontSize: 11,
              }}
              axisLine={false}
              tickLine={false}
              unit="m"
            />

            <YAxis yAxisId="slope" orientation="right" domain={[0, "dataMax + 2"]} hide />

            {violationRanges.map((range, index) => (
              <ReferenceArea
                key={`${range.start}-${range.end}-${index}`}
                yAxisId="elevation"
                x1={range.start}
                x2={range.end}
                fill="#e11d48"
                fillOpacity={0.2}
                strokeOpacity={0}
              />
            ))}

            <Area
              yAxisId="elevation"
              type="monotone"
              dataKey="elevationMeters"
              stroke="#2dd4bf"
              strokeWidth={2}
              fill="url(#wheelwayTopographicalElevation)"
              isAnimationActive={false}
            />

            <Line
              yAxisId="slope"
              type="stepAfter"
              dataKey="runningSlopePct"
              stroke="#f59e0b"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />

            <Tooltip content={<ElevationTooltip />} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </aside>
  );
}

export default memo(ElevationProfilePanel);
