# WheelWay backend (Flask)

The HTTP API for WheelWay. Serves real Mapbox walking routes, the offline A*
accessibility demo, and the Raspberry Pi sensor stream. CORS-enabled for the
Vite dev server.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/` | Service banner |
| `GET`  | `/health` | Liveness check |
| `POST` | `/real-route` | **Real Mapbox walking routes** + elevation/places enrichment |
| `POST` | `/route` | Offline A* algorithm demo over a synthetic Berkeley graph |
| `POST` | `/simulate` | Generate a fake ultrasonic distance reading |
| `POST` | `/observations` | Ingest a CV/sensor observation |
| `GET`  | `/observations` | Last 100 observations |

### `POST /real-route`

A thin adapter over the shared pipeline
`accessroute.pipeline.compute_accessible_routes` — the routing/enrichment/scoring
logic is **not** duplicated here. Geometry comes only from Mapbox walking
directions and is rendered verbatim; geometry is never fabricated on failure.

Request:

```json
{
  "origin":      { "latitude": 37.8694, "longitude": -122.2592 },
  "destination": { "latitude": 37.8683, "longitude": -122.2585 },
  "profile": {
    "wheelchair_type": "manual",
    "avoid_stairs": true,
    "max_slope_pct": 8.33,
    "min_width_m": 0.91
  },
  "cv_observations": []
}
```

Each route in the `routes[]` response carries: `route_id`, `geometry`
(GeoJSON `LineString`, coordinates in `[longitude, latitude]`), `distance_m`,
`duration_s`, `max_slope_pct`, `avg_slope_pct`, `steep_sections`,
`exceeds_max_slope`, `stairs_detected` (`null` when unknown),
`accessibility_score`, `accessibility_warnings`, `explanation`, and per-field
`sources` provenance tags.

Structured errors:

| Status | `error` | Cause |
|---|---|---|
| `400` | `validation_error` | Bad/missing request body |
| `404` | `no_route` | Mapbox returned no walking geometry |
| `502` | `routing_unavailable` | Mapbox Directions API failed |
| `503` | `configuration_error` | `MAPBOX_ACCESS_TOKEN` not set |

### `POST /route`

The accessibility-weighted A* router over the in-memory mock graph
(`app/data/mock_graph.py`). A separately labeled **algorithm demo** — its
geometry is synthetic and must not be presented as real sidewalks. Body is a
`RouteRequest` (`start_node_id`, `end_node_id`, optional `profile`); `?k=N`
returns up to N alternatives.

## Layout

```
backend/
  main.py              # Flask app: blueprints + sensor endpoints
  app/
    api/
      real_route.py    # /real-route adapter over the shared pipeline
      routes.py        # /route A* endpoint
    routing/           # astar.py, graph.py (offline router)
    scoring/           # accessibility scoring engine + constants
    models/            # pydantic request/response models
    data/mock_graph.py # synthetic Berkeley graph fixture
    tests/             # endpoint + scoring + routing tests
```

The sibling `accessroute/` package is added to `sys.path` at startup so
`/real-route` can import the shared pipeline.

## Run

```bash
pip install -r ../requirements.txt -r ../accessroute/requirements.txt
python main.py                 # http://0.0.0.0:5000
```

Set `MAPBOX_ACCESS_TOKEN` (and optionally `GOOGLE_MAPS_API_KEY`) in
`accessroute/.env` for `/real-route`. See the [root README](../README.md) for the
full environment-variable table.

## Test

```bash
python -m pytest -q            # 31 tests: A*, scoring, /real-route (APIs mocked)
```
