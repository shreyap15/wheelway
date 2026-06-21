"""Register the accessroute orchestrator on Agentverse."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from uagents_core.utils.registration import (
    AgentverseRequestError,
    RegistrationRequestCredentials,
    register_chat_agent,
)

from _bootstrap import ensure_project_root

ensure_project_root()
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> int:
    try:
        ok = register_chat_agent(
            "accessroute-orchestrator",
            "https://accessroute-orchestrator.onrender.com/submit",
            active=True,
            credentials=RegistrationRequestCredentials(
                agentverse_api_key=os.environ["AGENTVERSE_KEY"],
                agent_seed_phrase=os.environ["AGENT_SEED_PHRASE"],
            ),
        )
    except KeyError as exc:
        missing = str(exc).strip("'")
        print(
            f"Missing required environment variable: {missing}. "
            "Set AGENTVERSE_KEY and AGENT_SEED_PHRASE in accessroute/.env or your shell.",
            file=sys.stderr,
        )
        return 1
    except AgentverseRequestError as exc:
        print(f"Agentverse registration failed: {exc}", file=sys.stderr)
        return 1

    print("Agentverse registration succeeded." if ok else "Agentverse registration returned False.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
