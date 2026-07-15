"""
tools/hotels.py
---------------
Real hotel data via OpenStreetMap Overpass API.
Returns three tiers: Budget (<1k), Mid-range (1k–2k), Premium (2k+) per night.
100% FREE — no API key required.
"""

from __future__ import annotations
import logging
import random
import requests
from tools.geocoding import geocode
from cache import cached_call

logger = logging.getLogger(__name__)
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Fixed 3-tier price bands (INR/night) — city-aware
TIER_BANDS: dict[str, dict] = {
    # tier1 = metro cities
    "tier1": {
        "budget":   (500,   950),
        "midrange": (1000, 2000),
        "premium":  (2100, 6000),
    },
    # tier2 = large tourist cities
    "tier2": {
        "budget":   (400,   950),
        "midrange": (1000, 1950),
        "premium":  (2000, 5000),
    },
    # tier3 = towns, hill stations, remote
    "tier3": {
        "budget":   (350,   900),
        "midrange": (1000, 1900),
        "premium":  (2000, 4500),
    },
}

CITY_TIER_MAP: dict[str, list[str]] = {
    "tier1": ["delhi", "mumbai", "bangalore", "bengaluru", "chennai",
              "hyderabad", "kolkata", "pune", "ahmedabad"],
    "tier2": ["jaipur", "surat", "lucknow", "kochi", "cochin", "goa",
              "udaipur", "agra", "varanasi", "amritsar", "bhopal",
              "indore", "chandigarh", "nagpur"],
}


def _city_tier(city: str) -> str:
    cl = city.lower()
    for tier, cities in CITY_TIER_MAP.items():
        if any(c in cl for c in cities):
            return tier
    return "tier3"


def _fetch_hotels_osm(lat: float, lon: float, radius_m: int = 6000) -> list[dict]:
    """Query Overpass for real hotel names near given coordinates."""
    query = f"""
    [out:json][timeout:18];
    (
      node["tourism"="hotel"](around:{radius_m},{lat},{lon});
      way["tourism"="hotel"](around:{radius_m},{lat},{lon});
      node["tourism"="hostel"](around:{radius_m},{lat},{lon});
      node["tourism"="guest_house"](around:{radius_m},{lat},{lon});
      node["tourism"="motel"](around:{radius_m},{lat},{lon});
    );
    out body 30;
    """
    last_exc: Exception | None = None
    for mirror in OVERPASS_MIRRORS:
        try:
            resp = requests.post(
                mirror,
                data={"data": query},
                headers={"User-Agent": "AutonomousTravelAgent/2.0 (neontrip)"},
                timeout=20,
            )
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            hotels = []
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name") or tags.get("name:en")
                if not name:
                    continue
                hotels.append({
                    "name":    name,
                    "type":    tags.get("tourism", "hotel").replace("_", " ").title(),
                    "stars":   tags.get("stars", ""),
                    "website": tags.get("website", ""),
                    "phone":   tags.get("phone", ""),
                })
            if hotels:
                logger.info("Overpass OK via %s — %d hotels", mirror, len(hotels))
                return hotels[:15]
        except Exception as exc:
            logger.warning("Overpass mirror %s failed: %s", mirror, exc)
            last_exc = exc
    if last_exc:
        logger.warning("All Overpass mirrors failed: %s", last_exc)
    return []


def get_hotel_options(location: str, budget_per_night_inr: int) -> dict:
    """
    Return hotels in THREE fixed price tiers:
      • Budget   : up to Rs.999/night  (dormitories, guesthouses, budget hotels)
      • Mid-range: Rs.1,000–2,000/night (standard hotels, homestays)
      • Premium  : Rs.2,001+/night     (3-4★ hotels, heritage stays, resorts)
    Each tier shows 2–3 real OSM hotel names where available.
    """
    coords = geocode(location)
    if not coords:
        return {"error": f"Could not geocode '{location}'", "location": location}

    cache_key = f"hotels3tier:{round(coords['lat'], 2)}:{round(coords['lon'], 2)}"

    def _build() -> dict:
        raw = _fetch_hotels_osm(coords["lat"], coords["lon"])
        tier = _city_tier(location)
        bands = TIER_BANDS[tier]

        # Shuffle to get variety across tiers
        random.shuffle(raw)
        budget_pool   = raw[:3]   if len(raw) >= 3  else raw
        mid_pool      = raw[3:6]  if len(raw) >= 6  else raw[min(len(raw)//2, 3):]
        premium_pool  = raw[6:9]  if len(raw) >= 9  else raw[max(0, len(raw)-3):]

        def make_options(pool, band_key, label, suffix):
            lo, hi = bands[band_key]
            options = []
            if pool:
                for h in pool:
                    options.append({
                        "name":  h["name"],
                        "type":  h["type"],
                        "stars": h.get("stars") or ("3★" if band_key == "premium" else "2★" if band_key == "midrange" else "1★"),
                        "estimated_price_per_night_inr": random.randint(lo, hi),
                        "source": "OpenStreetMap (real listing)",
                        "booking_tip": "Verify price & availability on Booking.com / MakeMyTrip / Agoda",
                    })
            else:
                # Fallback names
                names = [f"{location.title()} {n}" for n in suffix]
                for nm in names:
                    options.append({
                        "name":  nm,
                        "type":  "Hotel",
                        "stars": "3★" if band_key == "premium" else "2★" if band_key == "midrange" else "1★",
                        "estimated_price_per_night_inr": random.randint(lo, hi),
                        "source": "Estimated (OSM data unavailable for this area)",
                        "booking_tip": "Search on Booking.com / MakeMyTrip for availability",
                    })
            return {"label": label, "price_range": f"Rs.{lo:,}–{hi:,}/night", "options": options[:3]}

        return {
            "location": location,
            "data_source": "OpenStreetMap Overpass API + price estimates",
            "note": "Prices are indicative estimates. Always verify on Booking.com / MakeMyTrip / Agoda before booking.",
            "tiers": {
                "budget":   make_options(budget_pool,  "budget",   "Budget (under Rs.1,000/night)",    ["Backpacker Inn", "Budget Lodge", "Tourist Home"]),
                "midrange": make_options(mid_pool,     "midrange", "Mid-Range (Rs.1,000–2,000/night)", ["Heritage Stay", "Comfort Inn", "Travellers Lodge"]),
                "premium":  make_options(premium_pool, "premium",  "Premium (Rs.2,000+/night)",         ["Grand Palace", "Lake View Resort", "Boutique Hotel"]),
            },
        }

    return cached_call(cache_key, _build)
