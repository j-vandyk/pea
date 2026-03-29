"""
Geocoder Module
===============
Converts extracted protest event locations to latitude/longitude coordinates
using the Nominatim OpenStreetMap API (free, no API key required).

Geocoding is attempted hierarchically, from most to least specific:
  1. venue + city + country  → geo_accuracy: "venue"
  2. city + country          → geo_accuracy: "city"
  3. region + country        → geo_accuracy: "region"
  4. country only            → geo_accuracy: "country"

Each level falls back to the next if Nominatim returns no result.

Nominatim usage policy:
  - Max 1 request/second (enforced via rate_limit_delay)
  - Must identify the application via user_agent
  - Do not cache-bust or hammer with retries on 429s
  Ref: https://operations.osmfoundation.org/policies/nominatim/
"""

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Accuracy tiers in priority order
_ACCURACY_TIERS = ["venue", "city", "region", "country"]

# Nominatim user-agent — identifies this application to OSM
_USER_AGENT = "protest-event-analysis/1.0 (research; contact: pea-pipeline)"


def _nominatim_lookup(query: str, session, user_agent: str) -> Optional[tuple]:
    """
    Query Nominatim for a single location string.
    Returns (lat, lon) floats or None if not found.
    """
    try:
        resp = session.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": user_agent},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        log.debug(f"Nominatim lookup failed for '{query}': {e}")
    return None


def geocode_event(event: dict, session, user_agent: str = _USER_AGENT) -> dict:
    """
    Attempt to geocode a single event dict in-place.
    Adds: latitude, longitude, geo_accuracy fields.
    Returns the event dict (modified in-place).
    """
    venue = (event.get("venue") or "").strip()
    city = (event.get("city") or "").strip()
    region = (event.get("region") or "").strip()
    country = (event.get("country") or "").strip()

    queries = []
    if venue and city and country:
        queries.append(("venue", f"{venue}, {city}, {country}"))
    elif venue and country:
        queries.append(("venue", f"{venue}, {country}"))
    if city and country:
        queries.append(("city", f"{city}, {country}"))
    if region and country:
        queries.append(("region", f"{region}, {country}"))
    if country:
        queries.append(("country", country))

    for accuracy, query in queries:
        coords = _nominatim_lookup(query, session, user_agent)
        if coords:
            event["latitude"] = round(coords[0], 6)
            event["longitude"] = round(coords[1], 6)
            event["geo_accuracy"] = accuracy
            log.debug(f"Geocoded '{query}' → {coords} ({accuracy})")
            return event

    # No result at any level
    event["latitude"] = None
    event["longitude"] = None
    event["geo_accuracy"] = None
    log.debug(f"Could not geocode event: city={city!r}, country={country!r}")
    return event


def geocode_events(
    events: list,
    rate_limit_delay: float = 1.1,
    user_agent: str = _USER_AGENT,
) -> list:
    """
    Geocode a list of extracted event dicts.
    Adds latitude, longitude, geo_accuracy to each event in-place.

    Args:
        events: list of event dicts (output of extract_events)
        rate_limit_delay: seconds between Nominatim requests (policy: ≥1s)
        user_agent: identifies your application to OSM Nominatim

    Returns:
        same list with geo fields populated
    """
    import requests

    session = requests.Session()
    success = 0
    venue_hits = 0

    log.info(f"Geocoding {len(events)} events via Nominatim OSM...")

    for i, event in enumerate(events):
        geocode_event(event, session, user_agent)

        accuracy = event.get("geo_accuracy")
        if accuracy:
            success += 1
            if accuracy == "venue":
                venue_hits += 1

        if i < len(events) - 1:
            time.sleep(rate_limit_delay)

    log.info(
        f"Geocoding complete: {success}/{len(events)} located "
        f"({venue_hits} at venue precision)"
    )
    return events
