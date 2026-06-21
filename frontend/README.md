# WheelWay frontend

React + Vite + Mapbox GL UI for WheelWay. Renders accessible pedestrian routes and
the live obstacle-sensing dashboard. Talks to the Flask backend at
`http://127.0.0.1:5000`.

## Route modes

- **Real route mode** (`RealRoutePlanner.jsx`, default) — calls `POST /real-route`
  and draws the **backend-returned Mapbox GeoJSON verbatim**. It fits map bounds to
  the route geometry, lists route alternatives, and shows distance, duration, slope,
  accessibility score, warnings, explanation, and per-field data-source provenance.
  It does **not** import `graphNodes.js` and never reconstructs geometry from node
  endpoints. Streets/Satellite toggle, mobility controls, and CV detection markers
  are included. Configuration/API failures (503/502/404/400, backend offline) are
  surfaced clearly.
- **Accessibility algorithm demo** (`RoutePlanner.jsx`) — the offline A* router over
  a synthetic Berkeley graph (`graphNodes.js`), explicitly labeled as *not* a real
  Berkeley network. Kept only as an algorithm demo.

## Environment

Copy `.env.example` to `.env` and set:

```
VITE_MAPBOX_TOKEN=your_mapbox_public_token
```

Without it the map shows a placeholder prompting for the token. The token is read at
build time via `import.meta.env.VITE_MAPBOX_TOKEN`.

## Develop

```bash
npm install
npm run dev          # http://127.0.0.1:5173 (proxies to backend on :5000)
```

Start the backend first (`cd backend && python main.py`) so `/real-route`,
`/health`, and `/observations` are available.

## Build

```bash
npm run build        # production bundle in dist/
npm run preview      # serve the built bundle locally
```

## Key files

```
frontend/src/
  App.jsx                # Shell: sensor dashboard + real/demo mode switch
  RealRoutePlanner.jsx   # Real route mode — draws backend Mapbox GeoJSON
  RoutePlanner.jsx       # A* algorithm demo (synthetic graph)
  graphNodes.js          # Synthetic demo graph (demo mode ONLY)
  App.css                # Styles
```

Built with Vite (`@vitejs/plugin-react`) and `mapbox-gl`.
