"""LLM-powered direction synthesis via ASI:One (asi1-mini).

Uses the ASI:One API (OpenAI-compatible) for SYNTHESIS ONLY -- the LLM
does NOT make routing decisions; it converts structured route/elevation/
accessibility data into human-friendly prose directions.
"""

import logging

from accessroute.common.http import ServiceDegraded, request_with_retry
from accessroute.config import ASI_ONE_BASE_URL, ASI_ONE_MODEL
from accessroute.schemas import (
    AccessibilityVerdict,
    ElevationVerdict,
    RouteCandidate,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _entrance_status(accessibility: AccessibilityVerdict) -> str:
    """Human-readable entrance accessibility status."""
    if accessibility.wheelchair_entrance is True:
        return "accessible"
    elif accessibility.wheelchair_entrance is False:
        return "not accessible"
    return "unknown"


def _steep_segment_count(verdict: ElevationVerdict) -> int:
    """Count segments that are not compliant."""
    return sum(1 for seg in verdict.segments if not seg.is_compliant)


def _build_structured_summary(
    chosen: RouteCandidate,
    verdict: ElevationVerdict,
    accessibility: AccessibilityVerdict,
    warnings: list[str],
) -> str:
    """Build a structured data summary for the LLM user prompt."""
    minutes = chosen.duration_seconds / 60.0
    entrance = _entrance_status(accessibility)
    steep_count = _steep_segment_count(verdict)

    lines = [
        f"Total distance: {chosen.distance_meters:.0f} meters",
        f"Estimated duration: {minutes:.1f} minutes",
        f"Travel mode: {chosen.travel_mode}",
        f"Maximum grade: {verdict.max_grade_percentage:.1f}%",
        f"Steep segments: {steep_count}",
        f"Destination entrance wheelchair accessibility: {entrance}",
    ]
    if warnings:
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


def _fallback_directions(
    chosen: RouteCandidate,
    verdict: ElevationVerdict,
    accessibility: AccessibilityVerdict,
    warnings: list[str],
) -> str:
    """Deterministic template-based fallback when the LLM is unavailable."""
    minutes = chosen.duration_seconds / 60.0
    entrance = _entrance_status(accessibility)
    steep_count = _steep_segment_count(verdict)

    parts = [
        f"Wheelchair-accessible route summary ({chosen.travel_mode}):",
        f"  Distance: {chosen.distance_meters:.0f} meters",
        f"  Estimated time: {minutes:.1f} minutes",
        f"  Maximum grade encountered: {verdict.max_grade_percentage:.1f}%",
    ]

    if steep_count > 0:
        parts.append(
            f"  Note: {steep_count} segment(s) have steep grades. Proceed with caution."
        )

    parts.append(f"  Destination entrance: {entrance}")

    if warnings:
        parts.append("  Warnings:")
        for w in warnings:
            parts.append(f"    - {w}")

    parts.append(
        "For detailed turn-by-turn navigation, please consult your map application."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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

    On failure or empty api_key, returns a deterministic template-based
    fallback so the system always produces directions.

    Args:
        chosen: The selected RouteCandidate.
        verdict: The ElevationVerdict for the chosen route.
        accessibility: The AccessibilityVerdict for the destination.
        warnings: Accumulated warnings from all agents.
        api_key: ASI:One API key.

    Returns:
        A human-readable directions string.
    """
    # Guard: no API key -> immediate fallback
    if not api_key or not api_key.strip():
        logger.info("No ASI:One API key provided; using template fallback.")
        return _fallback_directions(chosen, verdict, accessibility, warnings)

    system_prompt = (
        "You write clear, reassuring, step-by-step wheelchair-accessible "
        "walking directions. Do not invent streets; only use the data given."
    )
    user_prompt = _build_structured_summary(chosen, verdict, accessibility, warnings)

    payload = {
        "model": ASI_ONE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
        "stream": False,
    }

    try:
        resp = request_with_retry(
            "POST",
            ASI_ONE_BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise ValueError("Empty LLM response content")
        return content.strip()
    except ServiceDegraded:
        logger.warning("ASI:One API degraded; using template fallback.")
        return _fallback_directions(chosen, verdict, accessibility, warnings)
    except Exception as exc:
        logger.warning("LLM synthesis failed (%s); using template fallback.", exc)
        return _fallback_directions(chosen, verdict, accessibility, warnings)
