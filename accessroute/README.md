# accessroute

A Fetch.ai uAgents multi-agent system for wheelchair-accessible routing.

## Architecture

The system runs four specialist agents in a single uAgents Bureau, coordinated by an orchestrator:

```
                        +-------------------+
  Client  ---------->  |   Orchestrator    |  ---------->  FinalRoute
  (RouteEvaluation      |   (port 8000)     |
   Request)             +--------+----------+
                                 |
                  +--------------+--------------+
                  |              |              |
           +------+------+ +----+-----+ +------+------+
           | Route Agent  | | Elevation| | Places Agent|
           | (port 8001)  | | Agent    | | (port 8003) |
           | Google Routes| | (8002)   | | Google      |
           | API          | | Google   | | Places (New)|
           +--------------+ | Elev API | +--------------+
                             +----------+
```

**Pipeline flow:**
1. Client sends `RouteEvaluationRequest` to the orchestrator.
2. Orchestrator forwards to the **Route Agent**, which fetches walking/transit candidates from the Google Routes API.
3. Orchestrator fans out concurrently to the **Elevation Agent** (grade compliance per candidate) and the **Places Agent** (destination wheelchair entrance check).
4. Orchestrator scores compliant routes, attempts TRANSIT fallback if no WALK routes pass.
5. Orchestrator synthesizes human-readable directions via ASI:One LLM (synthesis only -- the LLM does not make routing decisions).
6. Orchestrator returns `FinalRoute` to the client.

All agents communicate via shared `uagents.Model` message schemas defined in `accessroute/schemas.py`.

## Setup

```bash
cd accessroute/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your API keys:
#   GOOGLE_MAPS_API_KEY=your_google_maps_key
#   ASI_ONE_API_KEY=your_asi_one_key
```

## Run

### In-process demo (recommended)

The simplest way to run the full pipeline is the in-process demo, which starts all four agents plus a client in a single Bureau:

```bash
python scripts/run_demo.py
```

This sends a hardcoded Berkeley campus request (Sather Gate to north campus) through the full orchestrator pipeline and prints the `FinalRoute` result.

**With no API keys set**, the demo returns `success=False` with `service_degraded=True` by design -- this proves the wiring and graceful degradation work correctly. The route agent receives HTTP 403 from Google, raises `ServiceDegraded`, and the orchestrator returns an informative failure response instead of crashing.

**With valid API keys in `.env`**, the demo returns `success=True` with elevation-checked, accessibility-verified, LLM-narrated directions.

### Two-process mode (standalone client)

Start the agent bureau (all four agents) in one terminal:

```bash
python -m accessroute.bureau_main
```

In a separate terminal, send a test request:

```bash
python scripts/mock_client.py
```

Note: Two-process mode requires Almanac address resolution on the Fetch.ai testnet, which may not resolve immediately for local agents.

## Test

```bash
pytest
```

55 unit tests cover schemas, scoring, elevation math, and geographic utilities.

## PRD corrections implemented

Six corrections from the original PRD were incorporated based on API reality:

1. **routingPreference omitted for WALK** -- the Google Routes API rejects `routingPreference` when `travelMode` is `WALK`.
2. **Elevation 512-sample chunking** -- the Elevation API allows a maximum of 512 samples per request; routes requiring more are chunked into sub-paths.
3. **Places searchNearby for placeId** -- the Places (New) API's `searchNearby` endpoint is used to find the nearest place and its `placeId`, rather than a direct lookup.
4. **Conservative unknown-entrance handling** -- absence of `accessibilityOptions.wheelchairAccessibleEntrance` is treated as UNKNOWN (not accessible), with a warning surfaced to the user.
5. **TRANSIT fallback** -- if no compliant WALK routes exist, the orchestrator automatically attempts TRANSIT mode as a fallback.
6. **LLM is synthesis-only** -- the ASI:One LLM converts structured route data into natural-language prose; it does NOT make routing or safety decisions. On LLM failure, a deterministic template fallback is used.

## Project structure

```
accessroute/
  accessroute/
    __init__.py
    config.py           # Environment + agent configuration
    addresses.py        # Deterministic agent addresses from seeds
    schemas.py          # Frozen message contract (uagents.Model classes)
    scoring.py          # Route scoring and selection logic
    llm.py              # ASI:One LLM direction synthesis
    bureau_main.py      # Bureau launcher
    common/
      http.py           # Retry-decorated HTTP request helper
      geo.py            # Polyline decoding, haversine distance
    tools/
      routes_tool.py    # Google Routes API wrapper
      elevation_tool.py # Google Elevation API wrapper
      places_tool.py    # Google Places (New) API wrapper
    agents/
      orchestrator.py   # Orchestrator agent
      route_agent.py    # Route specialist agent
      elevation_agent.py # Elevation specialist agent
      places_agent.py   # Places specialist agent
  scripts/
    run_demo.py         # In-process smoke test (all agents + client in one Bureau)
    mock_client.py      # Standalone client for two-process mode
  tests/
    fixtures/           # Canned API responses for testing
  requirements.txt
  .env.example
  pytest.ini
```
