import { memo } from "react";

function TopographicalLegend() {
  return (
    <aside className="topographical-panel topographical-legend">
      <h2>Topographical accessibility</h2>

      <div className="topographical-legend-items">
        <div className="topographical-legend-row">
          <span className="topographical-swatch topographical-swatch-safe" />
          <span>Accessible</span>
          <span className="topographical-range">75-100</span>
        </div>

        <div className="topographical-legend-row">
          <span className="topographical-swatch topographical-swatch-caution" />
          <span>Caution</span>
          <span className="topographical-range">40-74</span>
        </div>

        <div className="topographical-legend-row">
          <span className="topographical-swatch topographical-swatch-danger" />
          <span>Danger</span>
          <span className="topographical-range">0-39</span>
        </div>
      </div>

      <p>
        Crimson walls are literal terrain barriers. Wall height increases with
        lower score, steeper slope, stairs, and missing curb ramps.
      </p>
    </aside>
  );
}

export default memo(TopographicalLegend);
