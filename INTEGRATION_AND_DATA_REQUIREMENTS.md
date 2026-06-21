# Topographical accessibility integration requirements

This integration renders a terrain-conforming sidewalk ribbon from routed graph
edges. It depends on real path geometry and measured surface data where
available; a start node and end node are not enough to represent a physical
sidewalk route.

## Frontend

Render the map with routed segments:

```jsx
import { TopographicalAccessibilityMap } from "./components/topographical";

export default function App() {
  return (
    <TopographicalAccessibilityMap routeSegments={selectedRoute.segments} />
  );
}
```

Set `VITE_MAPBOX_TOKEN` for terrain, buildings, and Deck.gl rendering. The map
uses Mapbox's camera internally; React state is only used for route samples and
hover synchronization.

Global CSS must allow the map to fill the viewport:

```css
html,
body,
#root {
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
}
```

## API route response

Every routed segment returned by the backend must retain its full ordered
sidewalk LineString:

```json
{
  "geometry": {
    "type": "LineString",
    "coordinates": [
      [-122.268, 37.87, 52.1],
      [-122.26795, 37.87008, 52.16],
      [-122.26789, 37.87017, 52.24]
    ]
  }
}
```

Coordinates are `[longitude, latitude]` or `[longitude, latitude, elevationM]`.
If elevation is absent, the frontend queries unexaggerated Mapbox terrain. If
both are absent, it falls back to zero elevation.

Broad graph nodes must be converted into dense infrastructure-following
geometry before rendering. This branch provides both frontend and backend
helpers named `snapRouteToStreets` / `snap_segments_to_streets` that:

1. Take each broad segment's first and last coordinate by default.
2. Request `mapbox/walking` Directions geometry (`overview=full`,
   `geometries=geojson`) when a Mapbox token is available.
3. Preserve the returned dense GeoJSON LineString.
4. Interpolate Z values along cumulative route distance.
5. Return both backend-compatible `geometry.coordinates` and mesh-friendly
   `coordinates: [[lng, lat, z], ...]`.

Backend route endpoints support:

- `?snap=true|false` (default `true`)
- `?profile=walking|driving|cycling` (aliases such as `pedestrian` and
  `vehicle` are normalized)
- `?mode=directions|matching`
- `?waypoints=endpoints|all` (default `endpoints`; use `all` for trace-style
  map matching/waypoint preservation)

## Segment model

The existing `Segment` model keeps its scoring fields and adds:

- `geometry: RouteGeometry`
- `surface_samples: list[SurfaceSample]`

`SurfaceSample` values can provide camera/depth, LiDAR, surveyed, or
photogrammetry measurements:

```json
{
  "longitude": -122.26791,
  "latitude": 37.87014,
  "elevation_m": 52.24,
  "surface_offset_m": 0.08,
  "confidence": 0.94
}
```

The frontend uses this priority for vertical placement:

1. Backend or sensor-provided Z coordinate / surface sample elevation
2. Mapbox terrain elevation
3. Zero-elevation fallback

Small accessibility obstacles such as curb lips, cracks, buckling, tactile
pavement, and drainage depressions require measured samples. Mapbox terrain is
not detailed enough to infer centimeter-scale sidewalk conditions.

## PostGIS

Graph edges should store true traversable geometry:

```sql
ALTER TABLE accessibility_segments
ADD COLUMN IF NOT EXISTS geom geometry(LineStringZ, 4326);
```

Use `LineStringZ` when elevation is known. If a source initially provides 2D
geometry, populate Z as measurements become available instead of replacing the
LineString with endpoint-only data.

## Buildings

The terrain overlay attempts to add a Mapbox `fill-extrusion` layer from:

- `source: "composite"`
- `source-layer: "building"`
- `height` / `min_height` attributes

For stronger building support, use `mapbox://styles/mapbox/standard` with 3D
buildings enabled or a Mapbox Studio style with compatible building data.
