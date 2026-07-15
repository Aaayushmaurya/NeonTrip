"""
mcp_bridge.py
-------------
MCP (Model Context Protocol) Tool Registry + Groq Function-Calling Bridge.

Architecture:
  - Defines all travel tools using MCP-compatible JSON Schema format
  - Translates tool schemas → Groq/OpenAI function-calling format (1:1 mapping)
  - Dispatches LLM tool calls → real Python implementations
  - Exposes an SSE endpoint so external MCP clients can connect to our server

This means:
  1. Our agent uses these tools via Groq function calling
  2. Any MCP-compatible client (Claude Desktop, Cursor, etc.) can also
     connect to our /mcp/sse endpoint and use the same tools
"""

from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Import real tool implementations ─────────────────────────────────────────
from tools.weather   import get_live_weather
from tools.flights   import get_flight_prices
from tools.hotels    import get_hotel_options
from tools.currency  import get_exchange_rates
from tools.geocoding import geocode

# ── MCP-Compatible Tool Schema Registry ──────────────────────────────────────
# Each entry follows the MCP tool schema specification:
# { name, description, inputSchema (JSON Schema) }

MCP_TOOLS: list[dict] = [
    {
        "name":        "get_live_weather",
        "description": (
            "Fetch real current weather conditions and a 7-day forecast for any "
            "travel destination. Returns temperature, humidity, wind, WMO weather "
            "condition, travel advisory, and daily highs/lows. Uses Open-Meteo API "
            "(free, real-time data)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type":        "string",
                    "description": "City or destination name, e.g. 'Manali', 'Shimla', 'Darjeeling'.",
                }
            },
            "required": ["location"],
        },
    },
    {
        "name":        "get_flight_prices",
        "description": (
            "Estimate flight prices and duration between two Indian cities using "
            "real great-circle distance (via Nominatim geocoding) and Indian aviation "
            "pricing model. Returns economy/business fares in INR, airline, duration, "
            "and IATA codes where available."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin":      {"type": "string", "description": "Departure city name."},
                "destination": {"type": "string", "description": "Arrival/destination city name."},
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name":        "get_hotel_options",
        "description": (
            "Find real hotel names at a destination (from OpenStreetMap) with "
            "budget-appropriate price estimates. Categorises as budget/midrange/luxury "
            "based on the per-night budget provided."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type":        "string",
                    "description": "Destination city.",
                },
                "budget_per_night_inr": {
                    "type":        "integer",
                    "description": "Maximum budget per night per room in Indian Rupees.",
                },
            },
            "required": ["location", "budget_per_night_inr"],
        },
    },
    {
        "name":        "get_exchange_rates",
        "description": (
            "Fetch live currency exchange rates from the European Central Bank "
            "via Frankfurter API (free, updated daily). Useful for converting "
            "international prices to INR or vice versa."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_currency": {
                    "type":        "string",
                    "description": "Base currency code, e.g. 'USD', 'EUR', 'INR'.",
                    "default":     "USD",
                },
                "target_currencies": {
                    "type":        "array",
                    "items":       {"type": "string"},
                    "description": "List of target currency codes, e.g. ['INR', 'EUR'].",
                },
            },
            "required": [],
        },
    },
    {
        "name":        "geocode_city",
        "description": (
            "Convert a city or place name to geographic coordinates (latitude/longitude) "
            "using OpenStreetMap Nominatim. Useful for calculating distances or "
            "verifying a location exists."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "location": {
                    "type":        "string",
                    "description": "City or place name to geocode.",
                }
            },
            "required": ["location"],
        },
    },
]

# ── Python dispatch table ─────────────────────────────────────────────────────
_REGISTRY: dict[str, Any] = {
    "get_live_weather":  get_live_weather,
    "get_flight_prices": get_flight_prices,
    "get_hotel_options": get_hotel_options,
    "get_exchange_rates": get_exchange_rates,
    "geocode_city":      geocode,
}


# ── Groq/OpenAI function-calling format ──────────────────────────────────────
def get_groq_tools() -> list[dict]:
    """
    Convert MCP tool schemas → Groq/OpenAI function-calling format.
    The conversion is 1:1 because MCP inputSchema IS JSON Schema.
    """
    return [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t["description"],
                "parameters":  t["inputSchema"],
            },
        }
        for t in MCP_TOOLS
    ]


# ── Tool Dispatcher ───────────────────────────────────────────────────────────
def dispatch_tool(name: str, arguments: str | dict) -> str:
    """
    Execute a tool by name with given arguments.
    Returns JSON string result for feeding back to the LLM.
    """
    func = _REGISTRY.get(name)
    if func is None:
        logger.warning("Unknown tool requested: %s", name)
        return json.dumps({"error": f"Tool '{name}' not found in MCP registry."})

    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
        result = func(**args)
        logger.info("MCP tool '%s' succeeded | args=%s", name, args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.error("MCP tool '%s' raised: %s", name, exc)
        return json.dumps({"error": str(exc), "tool": name})


# ── MCP Server via FastMCP (SSE transport) ───────────────────────────────────
# This exposes all tools as a proper MCP server that external clients
# (Claude Desktop, Cursor IDE, etc.) can connect to via SSE.

def create_mcp_app():
    """
    Create a FastMCP server that exposes all travel tools over SSE.
    Mount at /mcp in the main FastAPI app.
    """
    try:
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("Travel Agent Tools")

        @mcp.tool()
        def get_weather(location: str) -> dict:
            """Fetch real current weather and 7-day forecast for any destination."""
            return get_live_weather(location)

        @mcp.tool()
        def get_flights(origin: str, destination: str) -> dict:
            """Estimate flight prices between two Indian cities using real distance model."""
            return get_flight_prices(origin, destination)

        @mcp.tool()
        def get_hotels(location: str, budget_per_night_inr: int) -> dict:
            """Find real hotels at destination with budget-appropriate pricing."""
            return get_hotel_options(location, budget_per_night_inr)

        @mcp.tool()
        def get_currency(base_currency: str = "USD") -> dict:
            """Fetch live exchange rates from European Central Bank."""
            return get_exchange_rates(base_currency)

        @mcp.tool()
        def find_location(location: str) -> dict:
            """Geocode a city name to coordinates using OpenStreetMap."""
            result = geocode(location)
            return result or {"error": f"Location not found: {location}"}

        return mcp

    except ImportError:
        logger.warning("mcp package not installed — SSE MCP server not available. "
                       "Install with: pip install mcp")
        return None
