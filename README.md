# WheelWay

Accessibility-first pedestrian navigation. WheelWay plans **real wheelchair-accessible
walking routes** from exact Mapbox geometry, enriches them with elevation grade and
destination accessibility data, scores them, and renders them on an interactive map —
alongside live obstacle sensing from a Raspberry Pi ultrasonic rig.

## Repository layout

| Folder | What it is | README |
|---|---|---|
| [`backend/`](backend/) | Flask API — real-route endpoint, offline A* demo, sensor observations | [backend/README.md](backend/README.md) |
| [`accessroute/`](accessroute/) | Routing engine + shared pipeline + uAgents (Agentverse/ASI:One) | [accessroute/README.md](accessroute/README.md) |
| [`frontend/`](frontend/) | React + Vite + Mapbox GL UI | [frontend/README.md](frontend/README.md) |

## Canonical real-route flow

There is **one** shared pipeline,
`accessroute.pipeline.compute_accessible_routes`, reused by every consumer
(Flask `/real-route`, the orchestrator, the local demo, the Agentverse mailbox):

```
Mapbox Walking Directions        (the ONLY route-geometry provider)
  → exact GeoJSON LineString [lng, lat]
  → Google Elevation enrichment  (sample → smooth → grade)        [optional]
  → Google Places enrichment     (destination wheelchair entrance) [optional]
  → WheelWay accessibility scoring (slope-derived, honest)
  → canonical Pydantic models
  → Flask / frontend / Agentverse response
```

Geometry is never fabricated. If the Mapbox token is missing the API fails loudly
(HTTP 503); if a Google key is missing, Mapbox geometry still succeeds and the
enrichment fields are marked `unavailable`. Google Routes is **not** used.

The frontend has two clearly separated modes:

- **Real route mode** (default) — draws backend-returned Mapbox GeoJSON verbatim.
- **Accessibility algorithm demo** — the offline A* router over a synthetic
  Berkeley graph, explicitly labeled as *not* real geometry.

## Environment variables

| Variable | Scope | Required | Purpose |
|---|---|---|---|
| `MAPBOX_ACCESS_TOKEN` | backend (`accessroute/.env`) | **Yes** | Walking route geometry |
| `VITE_MAPBOX_TOKEN` | frontend (`frontend/.env`) | **Yes** | Map rendering |
| `GOOGLE_MAPS_API_KEY` | backend (`accessroute/.env`) | Optional | Elevation + Places enrichment |
| `ASI_ONE_API_KEY` | backend (`accessroute/.env`) | Optional | LLM direction prose |

`.env` is loaded from a `__file__`-relative path; **process environment overrides
`.env`**; secrets are never printed; real `.env` files are git-ignored at every depth.
Copy `accessroute/.env.example` and `frontend/.env.example` to get started.

## Quick start

```bash
# 1. Backend API
cd backend
pip install -r ../requirements.txt -r ../accessroute/requirements.txt
python main.py                 # serves http://127.0.0.1:5000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev                    # serves http://127.0.0.1:5173
```

## Tests

```bash
cd backend     && python -m pytest -q     # Flask API + A* + scoring
cd accessroute && python -m pytest -q     # pipeline, Mapbox, elevation, schemas
cd frontend    && npm run build           # production build
```

## Note on running the uAgents

The uAgents demo/bureau/mailbox scripts require **Python ≤ 3.12** with
`uagents==0.25.2` (agent construction fails on Python 3.14). The shared pipeline
and the entire Flask path run on any supported Python.
