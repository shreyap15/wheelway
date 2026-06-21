"""Google Routes API tool for fetching walking/transit route candidates.

Calls the Routes API v2 computeRoutes endpoint and returns a list
of RouteCandidate schema objects.
"""

from accessroute.schemas import LatLng, RouteCandidate


def _build_request_body(
    origin: LatLng,
    destination: LatLng,
    *,
    travel_mode: str = "WALK",
    alternatives: bool = True,
) -> dict:
    """Build the JSON request body for the Google Routes API.

    Endpoint: POST https://routes.googleapis.com/directions/v2:computeRoutes

    Body structure:
        - origin/destination as {"location":{"latLng":{"latitude":..,"longitude":..}}}
        - travelMode: "WALK" or "TRANSIT"
        - computeAlternativeRoutes: true (for WALK)
        - polylineEncoding: "ENCODED_POLYLINE"

    IMPORTANT: Do NOT send ``routingPreference`` when travelMode is WALK
    (the Routes API rejects it as invalid for walking).

    For TRANSIT mode, add:
        - transitPreferences.routingPreference: "LESS_WALKING"
        - transitPreferences.allowedTravelModes:
          ["BUS","LIGHT_RAIL","SUBWAY","TRAIN","RAIL"]
        - departureTime: RFC 3339 string

    Args:
        origin: Starting coordinate.
        destination: Ending coordinate.
        travel_mode: "WALK" or "TRANSIT".
        alternatives: Whether to request alternative routes.

    Returns:
        dict suitable for ``json=`` in a POST request.
    """
    raise NotImplementedError("_build_request_body: to be implemented by route-agent builder")


def compute_routes(
    origin: LatLng,
    destination: LatLng,
    *,
    api_key: str,
    travel_mode: str = "WALK",
    alternatives: bool = True,
) -> list[RouteCandidate]:
    """Fetch route candidates from the Google Routes API.

    Endpoint: POST https://routes.googleapis.com/directions/v2:computeRoutes
    Headers:
        - X-Goog-Api-Key: <api_key>
        - X-Goog-FieldMask: routes.duration,routes.distanceMeters,
          routes.polyline.encodedPolyline

    Body: see _build_request_body.

    Response parsing:
        - Each route has ``polyline.encodedPolyline``, ``distanceMeters``,
          ``duration`` (e.g. "300s"), and ``legs[].steps`` (count for num_steps).
        - Decode polyline via ``accessroute.common.geo.decode_polyline``.

    IMPORTANT: ``routingPreference`` must be OMITTED for travelMode WALK
    (the API returns an error otherwise).

    For TRANSIT fallback, set:
        - travelMode: "TRANSIT"
        - transitPreferences:
            routingPreference: "LESS_WALKING"
            allowedTravelModes: ["BUS","LIGHT_RAIL","SUBWAY","TRAIN","RAIL"]
        - departureTime: RFC 3339 timestamp

    Uses ``accessroute.common.http.request_with_retry`` for resilient calls.
    On ServiceDegraded, the caller (route agent) should return
    RouteCandidates with service_degraded=True.

    Args:
        origin: Starting coordinate.
        destination: Ending coordinate.
        api_key: Google Maps API key.
        travel_mode: "WALK" or "TRANSIT".
        alternatives: Whether to request alternative routes.

    Returns:
        A list of RouteCandidate objects.
    """
    raise NotImplementedError("compute_routes: to be implemented by route-agent builder")
