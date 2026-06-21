"""Google Places (New) API tool for destination accessibility checks.

Uses the searchNearby endpoint to find the closest place to the
destination and inspect its wheelchair accessibility options.
"""

from accessroute.common.http import request_with_retry, ServiceDegraded
from accessroute.schemas import AccessibilityVerdict, LatLng


def _parse_places_response(data: dict) -> AccessibilityVerdict:
    """Parse Google Places API response into AccessibilityVerdict.

    Pure helper function for parsing (no network call). Used for both
    live API responses and offline testing with fixtures.

    Takes the first (closest) place from the response.
    - If no places found: verdict with all fields None/empty.
    - If place found: extract id, displayName.text, and check
      accessibilityOptions.wheelchairAccessibleEntrance:
      - If present and True: wheelchair_entrance=True, no warning.
      - If present and False: wheelchair_entrance=False, warning about
        non-accessible entrance.
      - If absent/None (key missing at any level): wheelchair_entrance=None,
        warning about unknown accessibility (conservative).

    Args:
        data: Parsed JSON response from Google Places searchNearby API.

    Returns:
        AccessibilityVerdict with session_id="". The caller (agent) will
        set the real session_id by reconstructing the verdict.
    """
    places = data.get("places", [])

    if not places:
        return AccessibilityVerdict(
            session_id="",
            place_id=None,
            display_name=None,
            wheelchair_entrance=None,
            warning="No place found near destination; entrance accessibility unknown.",
        )

    place = places[0]  # Closest (rankPreference=DISTANCE)
    place_id = place.get("id")
    display_name_obj = place.get("displayName", {})
    display_name = display_name_obj.get("text")

    # Parse wheelchair accessibility (conservative: assume unknown if missing)
    accessibility_opts = place.get("accessibilityOptions")
    wheelchair_entrance = None
    warning = None

    if accessibility_opts is not None:
        wheelchair_entrance = accessibility_opts.get(
            "wheelchairAccessibleEntrance"
        )

        if wheelchair_entrance is True:
            # Explicitly accessible
            warning = None
        elif wheelchair_entrance is False:
            # Explicitly not accessible
            warning = (
                "Destination entrance is not wheelchair accessible; "
                "consider a secondary entrance or drop-off zone."
            )
        else:
            # Null or missing within the object
            wheelchair_entrance = None
            warning = (
                "Entrance compliance unknown; requires visual confirmation upon arrival."
            )
    else:
        # accessibilityOptions object itself is missing
        wheelchair_entrance = None
        warning = (
            "Entrance compliance unknown; requires visual confirmation upon arrival."
        )

    return AccessibilityVerdict(
        session_id="",
        place_id=place_id,
        display_name=display_name,
        wheelchair_entrance=wheelchair_entrance,
        warning=warning,
    )


def check_destination_accessibility(
    destination: LatLng,
    *,
    api_key: str,
    radius_meters: float = 50.0,
) -> AccessibilityVerdict:
    """Check wheelchair accessibility of the nearest place to a destination.

    Endpoint: POST https://places.googleapis.com/v1/places:searchNearby
    Headers:
        - X-Goog-Api-Key: <api_key>
        - X-Goog-FieldMask: places.id,places.location,places.displayName,
          places.accessibilityOptions

    Body:
        {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": .., "longitude": ..},
                    "radius": <radius_meters>
                }
            },
            "maxResultCount": 5,
            "rankPreference": "DISTANCE"
        }

    Response parsing:
        - Take the first (closest) place.
        - Check ``accessibilityOptions.wheelchairAccessibleEntrance``
          which is Optional[bool] and often absent entirely.
        - If the field is absent or null, set wheelchair_entrance=None
          and emit a warning: "Entrance compliance unknown; requires visual
          confirmation upon arrival."

    Conservative approach: absence of data is treated as UNKNOWN, not
    as accessible. The warning is surfaced to the user.

    Uses ``accessroute.common.http.request_with_retry`` for resilient calls.

    Args:
        destination: Coordinates to search near.
        api_key: Google Maps API key.
        radius_meters: Search radius in meters (default 50.0).

    Returns:
        AccessibilityVerdict with place info and wheelchair status.
        Note: session_id is set to "" in the tool; the agent will fill it.
    """
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json",
        "X-Goog-FieldMask": (
            "places.id,places.location,places.displayName,"
            "places.accessibilityOptions"
        ),
    }
    body = {
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": destination.lat,
                    "longitude": destination.lng,
                },
                "radius": radius_meters,
            }
        },
        "maxResultCount": 5,
        "rankPreference": "DISTANCE",
    }

    try:
        resp = request_with_retry("POST", url, headers=headers, json=body)
        if not resp.ok:
            raise ServiceDegraded(
                f"Places API HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        return _parse_places_response(data)
    except ServiceDegraded:
        return AccessibilityVerdict(
            session_id="",
            place_id=None,
            display_name=None,
            wheelchair_entrance=None,
            warning="Accessibility service unavailable.",
            service_degraded=True,
        )
