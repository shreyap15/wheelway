# accessroute

A Fetch.ai uAgents multi-agent system for wheelchair-accessible routing.

## Architecture

The system runs four agents in a single uAgents Bureau:

- **Orchestrator** (port 8000) -- receives route evaluation requests from clients, coordinates the pipeline, scores results, synthesizes directions via LLM, and returns a final route.
- **Route Agent** (port 8001) -- fetches walking/transit route candidates from the Google Routes API.
- **Elevation Agent** (port 8002) -- samples elevation profiles along route polylines and checks grade compliance against the user's wheelchair profile.
- **Places Agent** (port 8003) -- checks destination wheelchair accessibility via the Google Places (New) API.

All agents communicate via shared `uagents.Model` message schemas defined in `accessroute/schemas.py`.

## Setup

```bash
cd accessroute/
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your API keys:
#   GOOGLE_MAPS_API_KEY=your_key_here
#   ASI_ONE_API_KEY=your_key_here
```

## Run

Start the agent bureau (all four agents):

```bash
python -m accessroute.bureau_main
```

In a separate terminal, send a test request:

```bash
python scripts/mock_client.py
```

## Test

```bash
pytest
```

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
    mock_client.py      # Test client agent
  tests/
    fixtures/           # Canned API responses for testing
  requirements.txt
  .env.example
  pytest.ini
```
