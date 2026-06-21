"""Production deployment settings for Agentverse and cloud hosts."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DeploySettings:
    port: int
    public_base_url: str | None
    submit_endpoint: str | None
    use_mailbox: bool
    agentverse_name: str


def _normalize_public_url(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().rstrip("/")
    if not value:
        return None
    if not value.startswith("http"):
        value = f"https://{value}"
    return value


def get_deploy_settings() -> DeploySettings:
    """Resolve host/port/endpoint settings from common cloud environment variables."""
    port = int(os.getenv("PORT", os.getenv("UAGENTS_PORT", "8000")))

    public_base_url = _normalize_public_url(
        os.getenv("AGENT_PUBLIC_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("PUBLIC_URL")
        or (
            f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}"
            if os.getenv("RAILWAY_PUBLIC_DOMAIN")
            else None
        )
    )

    submit_endpoint = f"{public_base_url}/submit" if public_base_url else None
    use_mailbox = os.getenv("USE_MAILBOX", "").lower() in {"1", "true", "yes", "on"}

    agentverse_name = os.getenv("AGENTVERSE_NAME", "accessroute-orchestrator")[:30]

    return DeploySettings(
        port=port,
        public_base_url=public_base_url,
        submit_endpoint=submit_endpoint,
        use_mailbox=use_mailbox,
        agentverse_name=agentverse_name,
    )
