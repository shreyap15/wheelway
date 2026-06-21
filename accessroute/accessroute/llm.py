"""LLM-powered direction synthesis via ASI:One (asi1-mini).

Uses the ASI:One API (OpenAI-compatible) for SYNTHESIS ONLY -- the LLM
does NOT make routing decisions; it converts structured route/elevation/
accessibility data into human-friendly prose directions.
"""

from accessroute.schemas import (
    AccessibilityVerdict,
    ElevationVerdict,
    RouteCandidate,
)


def synthesize_directions(
    chosen: RouteCandidate,
    verdict: ElevationVerdict,
    accessibility: AccessibilityVerdict,
    warnings: list[str],
    *,
    api_key: str,
) -> str:
    """Generate human-readable wheelchair-accessible directions via ASI:One.

    This function is for SYNTHESIS ONLY. The LLM receives pre-computed
    route data and converts it to natural-language prose. It does NOT
    make routing or safety decisions.

    ASI:One API (OpenAI-compatible):
        - Base URL: https://api.asi1.ai/v1/chat/completions
        - Model: asi1-mini
        - Auth: Bearer token in Authorization header
        - Request body: standard OpenAI chat completions format with
          ``model``, ``messages`` (system + user), ``temperature``.

    The system prompt should instruct the LLM to:
        - Describe the route in clear, step-by-step prose.
        - Highlight any steep segments from the elevation verdict.
        - Mention accessibility warnings (entrance status, unknowns).
        - Include total distance and estimated duration.
        - Keep the tone helpful and reassuring.

    Uses ``accessroute.common.http.request_with_retry`` for resilient calls.
    On failure, returns a fallback template-based directions string
    rather than raising, so the user always gets some output.

    Args:
        chosen: The selected RouteCandidate.
        verdict: The ElevationVerdict for the chosen route.
        accessibility: The AccessibilityVerdict for the destination.
        warnings: Accumulated warnings from all agents.
        api_key: ASI:One API key.

    Returns:
        A human-readable directions string.
    """
    raise NotImplementedError("synthesize_directions: to be implemented by llm builder")
