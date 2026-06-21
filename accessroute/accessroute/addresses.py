"""Deterministic agent addresses derived from seeds.

Derives each agent's on-chain address from its seed WITHOUT running a
Bureau or starting any network listeners. Uses uagents.crypto.Identity
to generate the keypair from the seed and extract the address.

Approach: ``Identity.from_seed(seed, 0)`` produces a deterministic
keypair; ``.address`` gives the ``agent1q...`` bech32 address.

These constants are importable by any module (including the mock client)
to address messages to agents by their well-known addresses.
"""

from uagents.crypto import Identity

from accessroute.config import (
    ORCHESTRATOR,
    ROUTE_AGENT,
    ELEVATION_AGENT,
    PLACES_AGENT,
)


def _address_from_seed(seed: str) -> str:
    """Derive the deterministic agent address from a seed string."""
    identity = Identity.from_seed(seed, 0)
    return identity.address


ORCHESTRATOR_ADDRESS: str = _address_from_seed(ORCHESTRATOR.seed)
ROUTE_AGENT_ADDRESS: str = _address_from_seed(ROUTE_AGENT.seed)
ELEVATION_AGENT_ADDRESS: str = _address_from_seed(ELEVATION_AGENT.seed)
PLACES_AGENT_ADDRESS: str = _address_from_seed(PLACES_AGENT.seed)
