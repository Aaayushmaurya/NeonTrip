"""
tools/geocoding.py
------------------
Converts city/place names → latitude & longitude using Nominatim (OpenStreetMap).
100% FREE — no API key required.
Rate limit: 1 req/sec — handled automatically by our TTL cache.
"""

from __future__ import annotations
import logging
import requests
from cache import cached_call

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "AutonomousTravelAgent/2.0 (production; contact@travelagent.local)"}


def _fetch_geocode(location: str) -> dict | None:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1, "addressdetails": 1},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            item = data[0]
            addr = item.get("address", {})
            return {
                "lat":          float(item["lat"]),
                "lon":          float(item["lon"]),
                "display_name": item.get("display_name", location),
                "country":      addr.get("country", ""),
                "state":        addr.get("state", ""),
                "city":         addr.get("city") or addr.get("town") or addr.get("village") or location,
            }
    except Exception as exc:
        logger.warning("Geocoding failed for '%s': %s", location, exc)
    return None


def geocode(location: str) -> dict | None:
    """Return lat/lon for a city name. Cached for 5 minutes."""
    key = f"geocode:{location.lower().strip()}"
    return cached_call(key, _fetch_geocode, location)
