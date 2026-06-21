"""Orchestrator agent: coordinates the multi-agent wheelchair routing pipeline.

Receives a RouteEvaluationRequest from the client, fans out to the
route/elevation/places specialist agents, scores results, synthesizes
directions via LLM, and returns a FinalRoute.

Message flow:
    Client -> Orchestrator: RouteEvaluationRequest
    Orchestrator: Mapbox walking directions (in-process)
    Orchestrator: Google Elevation sampling (in-process via check_route_elevation_async)
    Orchestrator -> PlacesAgent: AccessibilityCheckRequest
    PlacesAgent -> Orchestrator: AccessibilityVerdict
    Orchestrator -> Client: FinalRoute
"""

import asyncio
import json
import logging
from types import SimpleNamespace

from uagents import Agent, Context, Model
from uagents.dispatch import dispatcher
from uagents_core.identity import parse_identifier
from uagents_core.types import DeliveryStatus, MsgStatus

from accessroute.addresses import (
    ELEVATION_AGENT_ADDRESS,
    PLACES_AGENT_ADDRESS,
)
from accessroute.config import ASI_ONE_API_KEY, GOOGLE_MAPS_API_KEY, MAPBOX_ACCESS_TOKEN, ORCHESTRATOR
from accessroute.elevation_service import (
    ServiceDegraded,
    check_route_elevation_async,
    degraded_elevation_verdict,
)
from accessroute.llm import synthesize_directions
from accessroute.main import (
    degraded_route_candidates,
    fetch_route_candidates_async,
)
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

ELEVATION_REQUEST_TIMEOUT = 120


async def _send_and_receive_untyped(
    ctx: Context,
    destination: str,
    message: Model,
    *,
    timeout: int = ELEVATION_REQUEST_TIMEOUT,
):
    """Send a message and accept any response schema digest (avoids digest mismatch timeouts)."""
    schema_digest = Model.build_schema_digest(message)
    _, _, parsed_address = parse_identifier(destination)

    msg_status = await ctx.send_raw(
        destination=destination,
        message_schema_digest=schema_digest,
        message_body=message.model_dump_json(),
        wait_for_response=True,
        timeout=timeout,
        expected_response_digests=None,
    )

    if msg_status.status != DeliveryStatus.DELIVERED:
        dispatcher.cancel_pending_response(ctx.agent.address, parsed_address, ctx.session)
        return None, msg_status

    response_msg = await dispatcher.wait_for_response(
        ctx.agent.address, parsed_address, ctx.session, timeout
    )
    if response_msg is None:
        return None, MsgStatus(
            status=DeliveryStatus.FAILED,
            detail="Timeout waiting for response",
            destination=destination,
            endpoint="",
            session=ctx.session,
        )

    try:
        payload = json.loads(response_msg.message)
    except json.JSONDecodeError:
        return response_msg.message, msg_status

    return payload, msg_status

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
    try:
        from accessroute.deploy_config import get_deploy_settings

        settings = get_deploy_settings()
        if settings.submit_endpoint:
            ctx.logger.info("Agentverse endpoint URL: %s", settings.submit_endpoint)
            ctx.logger.info("Agentverse agent name: %s", settings.agentverse_name)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_candidates(ctx: Context, msg: RouteEvaluationRequest):
    """Fetch Mapbox walking route candidates directly (no route agent messaging).

    Returns:
        (RouteCandidates | None, service_degraded: bool, warning: str | None)
    """
    try:
        route_candidates = await fetch_route_candidates_async(
            msg,
            MAPBOX_ACCESS_TOKEN,
        )
    except ServiceDegraded as exc:
        logger.warning(
            "Mapbox routing degraded for session %s: %s",
            msg.session_id,
            exc,
        )
        return (
            degraded_route_candidates(msg),
            True,
            f"Route service returned degraded results: {exc}",
        )
    except Exception as exc:
        logger.error(
            "Mapbox routing failed for session %s: %s",
            msg.session_id,
            exc,
        )
        return (
            degraded_route_candidates(msg),
            True,
            f"Route service error: {exc}",
        )

    if not route_candidates.candidates:
        return (
            route_candidates,
            True,
            "Route service returned no Mapbox walking candidates.",
        )

    ctx.logger.info(
        "Mapbox returned %d walking candidate(s) for session %s",
        len(route_candidates.candidates),
        msg.session_id,
    )
    for candidate in route_candidates.candidates:
        ctx.logger.info(
            "  route_index=%s distance=%.0fm duration=%.0fs polyline_len=%d",
            candidate.route_index,
            candidate.distance_meters,
            candidate.duration_seconds,
            len(candidate.encoded_polyline),
        )

    return route_candidates, False, None


def _coerce_elevation_verdict(reply):
    """Normalize elevation replies for downstream scoring and synthesis."""
    if isinstance(reply, ElevationVerdict):
        return reply
    if isinstance(reply, dict):
        try:
            return ElevationVerdict.parse_obj(reply)
        except Exception:
            return SimpleNamespace(
                route_index=reply.get("route_index"),
                is_route_compliant=reply.get("is_route_compliant", False),
                max_grade_percentage=reply.get("max_grade_percentage", 0.0),
                service_degraded=reply.get("service_degraded", False),
                segments=reply.get("segments", []),
            )
    if hasattr(reply, "is_route_compliant"):
        return reply
    return None


async def _fetch_elevation(ctx: Context, session_id, candidate, profile):
    """Send an ElevationCheckRequest for one candidate. Returns (ElevationVerdict | None, warning | None)."""
    profile_data = profile if isinstance(profile, dict) else profile.dict()
    req = ElevationCheckRequest(
        session_id=session_id,
        route_index=candidate.route_index,
        encoded_polyline=candidate.encoded_polyline,
        distance_meters=candidate.distance_meters,
        profile=profile_data,
    )

    _, _, parsed_elevation = parse_identifier(ELEVATION_AGENT_ADDRESS)
    if dispatcher.contains(parsed_elevation):
        try:
            verdict = await check_route_elevation_async(req, GOOGLE_MAPS_API_KEY)
            ctx.logger.info(
                "Local elevation route=%s compliant=%s max_grade=%.2f%%",
                verdict.route_index,
                verdict.is_route_compliant,
                verdict.max_grade_percentage,
            )
            warning = None
            if verdict.service_degraded:
                warning = f"Elevation data degraded for route {candidate.route_index}."
            return verdict, warning
        except ServiceDegraded as exc:
            logger.warning(
                "Elevation API degraded for route %d: %s",
                candidate.route_index,
                exc,
            )
            return degraded_elevation_verdict(req), (
                f"Elevation data degraded for route {candidate.route_index}."
            )
        except Exception as exc:
            logger.error(
                "Local elevation error for route %d: %s",
                candidate.route_index,
                exc,
            )
            return None, f"Elevation check failed for route {candidate.route_index}: {exc}"

    try:
        reply, _status = await _send_and_receive_untyped(
            ctx, ELEVATION_AGENT_ADDRESS, req, timeout=ELEVATION_REQUEST_TIMEOUT
        )
    except Exception as exc:
        logger.error("Elevation agent error for route %d: %s", candidate.route_index, exc)
        return None, f"Elevation check failed for route {candidate.route_index}: {exc}"

    if reply is None:
        logger.error(
            "Elevation agent returned no reply for route %d (status=%s)",
            candidate.route_index,
            getattr(_status, "detail", _status),
        )
        return None, f"Elevation check failed for route {candidate.route_index}: no reply"

    if not hasattr(reply, "is_route_compliant") and not isinstance(reply, dict):
        return None, f"Elevation agent returned unexpected type for route {candidate.route_index}."

    warning = None
    service_degraded = (
        reply.get("service_degraded", False)
        if isinstance(reply, dict)
        else getattr(reply, "service_degraded", False)
    )
    if service_degraded:
        warning = f"Elevation data degraded for route {candidate.route_index}."
    verdict = _coerce_elevation_verdict(reply)
    if verdict is not None:
        ctx.logger.info(
            "Remote elevation route=%s compliant=%s max_grade=%.2f%%",
            getattr(verdict, "route_index", None),
            getattr(verdict, "is_route_compliant", None),
            getattr(verdict, "max_grade_percentage", 0.0),
        )
    return verdict, warning


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
    """Run elevation checks sequentially, then the accessibility check.

    Returns:
        (verdicts: list[ElevationVerdict], accessibility: AccessibilityVerdict | None,
         warnings: list[str], any_degraded: bool)
    """
    warnings = []
    any_degraded = False
    elevation_results = []

    for candidate in candidates:
        elevation_results.append(
            await _fetch_elevation(ctx, session_id, candidate, profile)
        )

    accessibility, acc_warning = await _fetch_accessibility(ctx, session_id, destination)

    verdicts = []
    for elev_verdict, elev_warning in elevation_results:
        if elev_warning:
            warnings.append(elev_warning)
            any_degraded = True
        if elev_verdict is not None:
            if getattr(elev_verdict, "service_degraded", False):
                any_degraded = True
            verdicts.append(elev_verdict)

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
        1. Fetch Mapbox walking route candidates in-process.
        2. Grade each candidate via check_route_elevation_async (Google Elevation).
        3. Check destination accessibility via places agent.
        4. Score and select the best compliant route via scoring module.
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
    if verdicts:
        ctx.logger.info(
            "Elevation summary: %s",
            [
                (
                    getattr(v, "route_index", None),
                    getattr(v, "is_route_compliant", None),
                    round(getattr(v, "max_grade_percentage", 0.0), 2),
                )
                for v in verdicts
            ],
        )
    else:
        ctx.logger.warning("No elevation verdicts received for %d candidates", len(candidates))

    best_idx = choose_best(candidates, verdicts)

    # ---- No compliant route among Mapbox walking alternatives ----
    if best_idx is None:
        peak_grades = [
            round(getattr(v, "max_grade_percentage", 0.0), 2)
            for v in verdicts
            if getattr(v, "max_grade_percentage", None) is not None
        ]
        if peak_grades:
            warnings.append(
                "All Mapbox walking alternatives exceeded the wheelchair grade limits "
                f"(peak grades: {', '.join(f'{g}%' for g in peak_grades)})."
            )
        await ctx.send(sender, FinalRoute(
            session_id=msg.session_id,
            success=False,
            directions_prose=(
                "No wheelchair-accessible route could be found for this "
                "origin and destination. All Mapbox walking alternatives exceed the "
                "maximum grade limits in your wheelchair profile."
            ),
            warnings=warnings,
            service_degraded=any_degraded,
        ))
        return

    # ---- Process accessibility warnings ----
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
