"""Orchestrator agent: coordinates the multi-agent wheelchair routing pipeline.

Receives a RouteEvaluationRequest from the client, fans out to the
route/elevation/places specialist agents, scores results, synthesizes
directions via LLM, and returns a FinalRoute.

Message flow:
    Client -> Orchestrator: RouteEvaluationRequest
    Orchestrator -> RouteAgent: RouteEvaluationRequest
    RouteAgent -> Orchestrator: RouteCandidates
    Orchestrator -> ElevationAgent: ElevationCheckRequest (per candidate)
    ElevationAgent -> Orchestrator: ElevationVerdict (per candidate)
    Orchestrator -> PlacesAgent: AccessibilityCheckRequest
    PlacesAgent -> Orchestrator: AccessibilityVerdict
    Orchestrator -> Client: FinalRoute
"""

import asyncio
import logging

from uagents import Agent, Context

from accessroute.addresses import (
    ELEVATION_AGENT_ADDRESS,
    PLACES_AGENT_ADDRESS,
    ROUTE_AGENT_ADDRESS,
)
from accessroute.config import ASI_ONE_API_KEY, ORCHESTRATOR
from accessroute.llm import synthesize_directions
from accessroute.schemas import (
    AccessibilityCheckRequest,
    AccessibilityVerdict,
    ElevationCheckRequest,
    ElevationVerdict,
    FinalRoute,
    RouteCandidates,
    RouteEvaluationRequest,
)
from accessroute.scoring import choose_best

logger = logging.getLogger(__name__)

orchestrator = Agent(
    name=ORCHESTRATOR.name,
    seed=ORCHESTRATOR.seed,
    port=ORCHESTRATOR.port,
    endpoint=[f"http://127.0.0.1:{ORCHESTRATOR.port}/submit"],
)


@orchestrator.on_event("startup")
async def on_startup(ctx: Context):
    """Log the orchestrator's address on startup."""
    addr = getattr(ctx, "address", None) or orchestrator.address
    ctx.logger.info(f"Orchestrator started at address: {addr}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_candidates(ctx: Context, msg: RouteEvaluationRequest):
    """Send the evaluation request to the route agent and return RouteCandidates.

    Returns:
        (RouteCandidates | None, service_degraded: bool, warning: str | None)
    """
    try:
        route_reply, _status = await ctx.send_and_receive(
            ROUTE_AGENT_ADDRESS, msg, response_type=RouteCandidates
        )
    except Exception as exc:
        logger.error("Route agent communication failed: %s", exc)
        return None, True, f"Route agent error: {exc}"

    if not isinstance(route_reply, RouteCandidates):
        return None, True, "Route agent returned unexpected response type."

    if route_reply.service_degraded:
        return route_reply, True, "Route service returned degraded results."

    return route_reply, False, None


async def _fetch_elevation(ctx: Context, session_id, candidate, profile):
    """Send an ElevationCheckRequest for one candidate. Returns (ElevationVerdict | None, warning | None)."""
    req = ElevationCheckRequest(
        session_id=session_id,
        route_index=candidate.route_index,
        encoded_polyline=candidate.encoded_polyline,
        distance_meters=candidate.distance_meters,
        profile=profile,
    )
    try:
        reply, _status = await ctx.send_and_receive(
            ELEVATION_AGENT_ADDRESS, req, response_type=ElevationVerdict
        )
    except Exception as exc:
        logger.error("Elevation agent error for route %d: %s", candidate.route_index, exc)
        return None, f"Elevation check failed for route {candidate.route_index}: {exc}"

    if not isinstance(reply, ElevationVerdict):
        return None, f"Elevation agent returned unexpected type for route {candidate.route_index}."

    warning = None
    if reply.service_degraded:
        warning = f"Elevation data degraded for route {candidate.route_index}."
    return reply, warning


async def _fetch_accessibility(ctx: Context, session_id, destination):
    """Send an AccessibilityCheckRequest. Returns (AccessibilityVerdict | None, warning | None)."""
    req = AccessibilityCheckRequest(
        session_id=session_id,
        destination=destination,
    )
    try:
        reply, _status = await ctx.send_and_receive(
            PLACES_AGENT_ADDRESS, req, response_type=AccessibilityVerdict
        )
    except Exception as exc:
        logger.error("Places agent error: %s", exc)
        return None, f"Accessibility check failed: {exc}"

    if not isinstance(reply, AccessibilityVerdict):
        return None, "Places agent returned unexpected type."

    warning = None
    if reply.service_degraded:
        warning = "Accessibility data is degraded."
    return reply, warning


async def _run_elevation_and_accessibility(ctx, session_id, candidates, profile, destination):
    """Run elevation checks for all candidates + accessibility check concurrently.

    Returns:
        (verdicts: list[ElevationVerdict], accessibility: AccessibilityVerdict | None,
         warnings: list[str], any_degraded: bool)
    """
    warnings = []
    any_degraded = False

    # Build all coroutines: one per candidate elevation + one accessibility
    elevation_coros = [
        _fetch_elevation(ctx, session_id, c, profile) for c in candidates
    ]
    accessibility_coro = _fetch_accessibility(ctx, session_id, destination)

    # Run concurrently
    all_results = await asyncio.gather(*elevation_coros, accessibility_coro)

    # Unpack elevation results (all but last)
    verdicts = []
    for result in all_results[:-1]:
        elev_verdict, elev_warning = result
        if elev_warning:
            warnings.append(elev_warning)
            any_degraded = True
        if elev_verdict is not None:
            if elev_verdict.service_degraded:
                any_degraded = True
            verdicts.append(elev_verdict)

    # Unpack accessibility result (last)
    accessibility, acc_warning = all_results[-1]
    if acc_warning:
        warnings.append(acc_warning)
        any_degraded = True
    if accessibility is not None and accessibility.service_degraded:
        any_degraded = True

    return verdicts, accessibility, warnings, any_degraded


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

@orchestrator.on_message(model=RouteEvaluationRequest)
async def handle_evaluation_request(ctx: Context, sender: str, msg: RouteEvaluationRequest):
    """Handle a route evaluation request from the client.

    Pipeline:
        1. Forward request to route agent, await RouteCandidates.
        2. For each candidate, send ElevationCheckRequest to elevation agent
           concurrently, plus one AccessibilityCheckRequest to places agent.
        3. Score and select the best compliant route via scoring module.
        4. If no compliant WALK routes, try TRANSIT fallback.
        5. Synthesize human-readable directions via LLM.
        6. Reply to the client with FinalRoute.
    """
    ctx.logger.info("Received RouteEvaluationRequest session=%s", msg.session_id)
    warnings: list[str] = []
    any_degraded = False

    # ---- Step 1: Fetch route candidates ----
    route_candidates, degraded, warning = await _fetch_candidates(ctx, msg)
    if warning:
        warnings.append(warning)
    if degraded:
        any_degraded = True
    if route_candidates is None or not route_candidates.candidates:
        await ctx.send(sender, FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose="Unable to retrieve route candidates from the routing service.",
            warnings=warnings,
            service_degraded=any_degraded,
        ))
        return

    candidates = route_candidates.candidates

    # ---- Step 2: Elevation + Accessibility checks (concurrent) ----
    verdicts, accessibility, step2_warnings, step2_degraded = (
        await _run_elevation_and_accessibility(
            ctx, msg.session_id, candidates, msg.profile, msg.destination
        )
    )
    warnings.extend(step2_warnings)
    if step2_degraded:
        any_degraded = True

    # ---- Step 3: Choose best route ----
    best_idx = choose_best(candidates, verdicts)

    # ---- Step 4: TRANSIT fallback if no compliant WALK routes ----
    if best_idx is None and msg.travel_mode == "WALK":
        ctx.logger.info("No compliant WALK routes; attempting TRANSIT fallback.")
        transit_msg = RouteEvaluationRequest(
            session_id=msg.session_id,
            origin=msg.origin,
            destination=msg.destination,
            profile=msg.profile,
            travel_mode="TRANSIT",
        )
        transit_candidates_result, t_degraded, t_warning = await _fetch_candidates(ctx, transit_msg)
        if t_warning:
            warnings.append(t_warning)
        if t_degraded:
            any_degraded = True

        if transit_candidates_result is not None and transit_candidates_result.candidates:
            t_verdicts, t_accessibility, t_warnings, t_deg = (
                await _run_elevation_and_accessibility(
                    ctx, msg.session_id, transit_candidates_result.candidates,
                    msg.profile, msg.destination
                )
            )
            warnings.extend(t_warnings)
            if t_deg:
                any_degraded = True

            t_best_idx = choose_best(transit_candidates_result.candidates, t_verdicts)
            if t_best_idx is not None:
                warnings.append(
                    "No wheelchair-accessible walking route was found. "
                    "A transit route has been selected as a fallback."
                )
                best_idx = t_best_idx
                candidates = transit_candidates_result.candidates
                verdicts = t_verdicts
                # Use transit accessibility if original was unavailable
                if t_accessibility is not None:
                    accessibility = t_accessibility

    # ---- No compliant route at all ----
    if best_idx is None:
        await ctx.send(sender, FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose=(
                "No wheelchair-accessible route could be found for this "
                "origin and destination. All candidate routes exceed the "
                "maximum grade limits in your wheelchair profile."
            ),
            warnings=warnings,
            service_degraded=any_degraded,
        ))
        return

    # ---- Step 5: Process accessibility warnings ----
    # Build a default accessibility if the places agent failed entirely
    if accessibility is None:
        accessibility = AccessibilityVerdict(
            session_id=msg.session_id,
            wheelchair_entrance=None,
            warning="Accessibility data unavailable.",
            service_degraded=True,
        )
        any_degraded = True

    if accessibility.wheelchair_entrance is None:
        unknown_warning = (
            "Wheelchair entrance accessibility at the destination is unknown. "
            "Please verify entrance accessibility before arriving."
        )
        # Dedupe: only add if not already present (places agent may have set a similar one)
        if not any(
            "unknown" in w.lower() and "entrance" in w.lower()
            for w in warnings
        ):
            warnings.append(unknown_warning)
    elif accessibility.wheelchair_entrance is False:
        entrance_warning = (
            "The destination entrance is not wheelchair accessible. "
            "Consider contacting the venue for alternative access."
        )
        if entrance_warning not in warnings:
            warnings.append(entrance_warning)

    # Include any warning from the accessibility verdict itself
    if accessibility.warning and accessibility.warning not in warnings:
        warnings.append(accessibility.warning)

    # ---- Step 6: Find chosen candidate and verdict for synthesis ----
    chosen_candidate = next(c for c in candidates if c.route_index == best_idx)
    chosen_verdict = next(v for v in verdicts if v.route_index == best_idx)

    # ---- Step 7: Synthesize directions ----
    prose = synthesize_directions(
        chosen_candidate,
        chosen_verdict,
        accessibility,
        warnings,
        api_key=ASI_ONE_API_KEY,
    )

    # ---- Step 8: Send final route ----
    await ctx.send(sender, FinalRoute(
        session_id=msg.session_id,
        success=True,
        chosen_route_index=best_idx,
        directions_prose=prose,
        warnings=warnings,
        total_distance_meters=chosen_candidate.distance_meters,
        travel_mode=chosen_candidate.travel_mode,
        service_degraded=any_degraded,
    ))
