"""Google Routes API tool for fetching walking/transit route candidates.

Calls the Routes API v2 computeRoutes endpoint and returns a list
of RouteCandidate schema objects.
"""

from datetime import datetime, timezone, timedelta

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
    body = {
        "origin": {
            "location": {
                "latLng": {
                    "latitude": origin.lat,
                    "longitude": origin.lng,
                }
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": destination.lat,
                    "longitude": destination.lng,
                }
            }
        },
        "travelMode": travel_mode,
        "computeAlternativeRoutes": alternatives,
        "polylineEncoding": "ENCODED_POLYLINE",
        "languageCode": "en-US",
        "units": "METRIC",
    }

    if travel_mode == "TRANSIT":
        # For TRANSIT, add departure time and transit preferences
        departure_time = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        body["departureTime"] = departure_time
        body["transitPreferences"] = {
            "routingPreference": "LESS_WALKING",
            "allowedTravelModes": ["BUS", "LIGHT_RAIL", "SUBWAY", "TRAIN", "RAIL"],
        }

    return body


def _parse_routes_response(data: dict, travel_mode: str) -> list[RouteCandidate]:
    """Parse the JSON response from Google Routes API into RouteCandidate objects.

    Args:
        data: The JSON response dict from the API.
        travel_mode: The travel mode used in the request (e.g., "WALK" or "TRANSIT").

    Returns:
        A list of RouteCandidate objects, one per route in the response.
    """
    candidates = []
    routes = data.get("routes", [])

    for route_index, route in enumerate(routes):
        # Extract basic route info
        distance_meters = float(route.get("distanceMeters", 0))
        duration_str = route.get("duration", "0s")

        # Parse duration: strip trailing 's' and convert to float seconds
        if isinstance(duration_str, str) and duration_str.endswith("s"):
            duration_str = duration_str[:-1]
        duration_seconds = float(duration_str) if duration_str else 0.0

        # Extract polyline
        encoded_polyline = route.get("polyline", {}).get("encodedPolyline", "")

        # Count total steps across all legs
        num_steps = 0
        legs = route.get("legs", [])
        for leg in legs:
            steps = leg.get("steps", [])
            num_steps += len(steps)

        candidate = RouteCandidate(
            route_index=route_index,
            encoded_polyline=encoded_polyline,
            distance_meters=distance_meters,
            duration_seconds=duration_seconds,
            num_steps=num_steps,
            travel_mode=travel_mode,
        )
        candidates.append(candidate)

    return candidates


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
    from accessroute.common.http import request_with_retry, ServiceDegraded

    url = "https://routes.googleapis.com/directions/v2:computeRoutes"

    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,routes.legs.steps",
    }

    body = _build_request_body(
        origin,
        destination,
        travel_mode=travel_mode,
        alternatives=alternatives,
    )

    resp = request_with_retry("POST", url, headers=headers, json=body)

    if not resp.ok:
        raise ServiceDegraded(
            f"Routes API HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    return _parse_routes_response(data, travel_mode)
