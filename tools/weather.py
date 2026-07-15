"""
tools/weather.py
----------------
Real weather data via Open-Meteo (https://open-meteo.com).
100% FREE — no API key, no signup. Used by millions of apps globally.
Provides current conditions + 7-day forecast.
"""

from __future__ import annotations
import logging
import requests
from datetime import datetime
from cache import cached_call
from tools.geocoding import geocode

logger = logging.getLogger(__name__)

OPEN_METEO_URL  = "https://api.open-meteo.com/v1/forecast"

# WMO Weather Code → human-readable description
WMO_CODES: dict[int, str] = {
    0:  "Clear sky",
    1:  "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

SEASON_MAP = {
    (12, 1, 2):   "Winter (Dec–Feb)",
    (3, 4, 5):    "Spring (Mar–May)",
    (6, 7, 8, 9): "Monsoon/Summer (Jun–Sep)",
    (10, 11):     "Autumn (Oct–Nov)",
}


def _current_season() -> str:
    m = datetime.now().month
    for months, label in SEASON_MAP.items():
        if m in months:
            return label
    return "Year-round"


def _fetch_weather(lat: float, lon: float, location_name: str) -> dict:
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude":  lat,
                "longitude": lon,
                "current":   "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature",
                "daily":     "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone":  "auto",
                "forecast_days": 7,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        current = data.get("current", {})
        daily   = data.get("daily", {})

        wmo_code    = current.get("weather_code", 0)
        condition   = WMO_CODES.get(wmo_code, "Variable conditions")
        temp_c      = current.get("temperature_2m", "--")
        feels_like  = current.get("apparent_temperature", "--")
        humidity    = current.get("relative_humidity_2m", "--")
        wind_kmh    = current.get("wind_speed_10m", "--")
        temp_f      = round(temp_c * 9 / 5 + 32, 1) if isinstance(temp_c, (int, float)) else "--"

        # Build 7-day forecast summary
        forecast = []
        dates     = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precips   = daily.get("precipitation_sum", [])
        wcodes    = daily.get("weather_code", [])
        for i in range(min(7, len(dates))):
            forecast.append({
                "date":        dates[i],
                "condition":   WMO_CODES.get(wcodes[i] if i < len(wcodes) else 0, "Variable"),
                "max_c":       max_temps[i] if i < len(max_temps) else "--",
                "min_c":       min_temps[i] if i < len(min_temps) else "--",
                "rain_mm":     precips[i]   if i < len(precips)   else 0,
            })

        return {
            "location":           location_name,
            "data_source":        "Open-Meteo (real-time)",
            "condition":          condition,
            "temp_c":             temp_c,
            "temp_f":             temp_f,
            "feels_like_c":       feels_like,
            "humidity_pct":       humidity,
            "wind_kmh":           wind_kmh,
            "current_season":     _current_season(),
            "seven_day_forecast": forecast,
            "travel_advisory":    _travel_advisory(wmo_code, temp_c),
        }
    except Exception as exc:
        logger.error("Open-Meteo failed for (%s, %s): %s", lat, lon, exc)
        return {
            "location":    location_name,
            "data_source": "fallback",
            "condition":   "Data unavailable — check closer to travel date",
            "temp_c":      "--",
            "temp_f":      "--",
        }


def _travel_advisory(wmo_code: int, temp_c: float) -> str:
    if wmo_code >= 95:
        return "⚠️ Thunderstorms expected — carry rain gear, check local alerts."
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return "❄️ Snowfall expected — pack warm clothes, road conditions may be affected."
    if wmo_code in (61, 63, 65, 80, 81, 82):
        return "🌧️ Rain expected — pack waterproof jacket and footwear."
    if isinstance(temp_c, (int, float)) and temp_c < 5:
        return "🧥 Very cold — pack heavy woolens, gloves, and thermal wear."
    if isinstance(temp_c, (int, float)) and temp_c > 35:
        return "☀️ Very hot — carry sunscreen, stay hydrated, prefer early morning activities."
    return "✅ Good travel conditions. Pack layers for temperature variation."


def get_live_weather(location: str) -> dict:
    """
    Fetch real current weather + 7-day forecast for any destination.
    Uses Nominatim for geocoding + Open-Meteo for weather data.
    Both APIs are 100% free with no key required.
    """
    coords = geocode(location)
    if not coords:
        return {"error": f"Could not find location: '{location}'", "location": location}

    cache_key = f"weather:{round(coords['lat'], 2)}:{round(coords['lon'], 2)}"
    return cached_call(cache_key, _fetch_weather, coords["lat"], coords["lon"], location)
