# Deploy accessroute to Agentverse (public URL)

This guide deploys the orchestrator Bureau to a public HTTPS URL suitable for Agentverse registration.

## Quick deploy on Render (recommended)

1. Push this repo to GitHub.
2. Go to [https://dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**.
3. Connect the repo and select `accessroute/render.yaml`.
4. Add secret environment variables in Render:
   - `MAPBOX_ACCESS_TOKEN`
   - `GOOGLE_MAPS_API_KEY`
   - `ASI_ONE_API_KEY` (optional)
5. Deploy. Render sets `RENDER_EXTERNAL_URL` automatically.

Your public agent endpoint will be:

```text
https://<your-service-name>.onrender.com/submit
```

## Register on Agentverse

In **Agentverse → Add Agent**:

| Field | Value |
|-------|-------|
| Agent Name | `accessroute-orchestrator` |
| Agent Endpoint URL | `https://<your-service-name>.onrender.com/submit` |

Orchestrator address (for reference):

```text
agent1q0w75upwp2h5f4dzxqvzpfh78w39wys7krnke0mgupsrurz6rcer2qsl38g
```

## Local Docker test

```bash
cd accessroute
docker build -t accessroute .
docker run --rm -p 8000:8000 \
  -e AGENT_PUBLIC_URL=http://localhost:8000 \
  -e MAPBOX_ACCESS_TOKEN=... \
  -e GOOGLE_MAPS_API_KEY=... \
  accessroute
```

## Mailbox mode (no public URL)

If you cannot expose a public endpoint yet:

```bash
USE_MAILBOX=true python -m accessroute.deploy_bureau
```

Open the **Local Agent Inspector** link in the terminal and connect via **Mailbox**.

## Health check

Render uses `GET /agent_info` as the health check path.
