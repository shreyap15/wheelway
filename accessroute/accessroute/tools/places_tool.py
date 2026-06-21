"""Google Places (New) API tool for destination accessibility checks.

Uses the searchNearby endpoint to find the closest place to the
destination and inspect its wheelchair accessibility options.
"""

from accessroute.schemas import AccessibilityVerdict, LatLng


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
          and emit a warning: "Wheelchair entrance info unavailable;
          accessibility unknown."

    Conservative approach: absence of data is treated as UNKNOWN, not
    as accessible. The warning is surfaced to the user.

    Uses ``accessroute.common.http.request_with_retry`` for resilient calls.

    Args:
        destination: Coordinates to search near.
        api_key: Google Maps API key.
        radius_meters: Search radius in meters (default 50.0).

    Returns:
        AccessibilityVerdict with place info and wheelchair status.
    """
    raise NotImplementedError(
        "check_destination_accessibility: to be implemented by places-agent builder"
    )
