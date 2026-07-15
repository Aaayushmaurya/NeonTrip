"""
agent_logic.py  (Production v2)
--------------------------------
Groq LLM integration using MCP tool registry.
- Tools sourced from mcp_bridge.py (real APIs)
- Conversation history stored in SQLite via db.py
- Retry logic for transient API errors
"""

from __future__ import annotations
import json
import logging
import time
from typing import Any

from dotenv import load_dotenv
from groq import Groq

try:
    from groq import APIConnectionError, APIStatusError
except ImportError:
    from groq._exceptions import APIConnectionError, APIStatusError  # type: ignore

import db
from config import get_settings
from mcp_bridge import get_groq_tools, dispatch_tool

load_dotenv()
logger    = logging.getLogger(__name__)
_settings = get_settings()
client    = Groq(api_key=_settings.groq_api_key)

MAX_TOOL_ROUNDS = 6
MAX_RETRIES     = 2
RETRY_DELAY_S   = 1.5

# ── System Prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an elite AI travel agent specialising in Indian domestic travel.
You have access to REAL live data tools:
  - get_live_weather    → real Open-Meteo weather for destination
  - get_flight_prices   → distance-based travel pricing (always call this for km/distance info)
  - get_hotel_options   → real hotel names in 3 tiers from OpenStreetMap
  - get_exchange_rates  → live ECB/Frankfurter currency rates
  - geocode_city        → real GPS coordinates from Nominatim

════════════════════════════════════════════════════════════
CRITICAL RULE — TRAVEL MODE & COST ACCURACY:
════════════════════════════════════════════════════════════
The user's query will contain a tag like: [Travel mode: train / sl — Train Sleeper · ~Rs.0.50/km]
You MUST use this mode to calculate travel cost. NEVER show flight prices as travel cost
when the user chose train/bus/bike/car.

Travel cost formulas (use distance_km from get_flight_prices tool):
• Bike 110cc  → distance_km × 2 × number_of_bikes
• Bike 200cc  → distance_km × 2.9 × number_of_bikes
• Bike 300cc  → distance_km × 3.6 × number_of_bikes
• Bike 650cc  → distance_km × 4.6 × number_of_bikes
• Bike 1200cc → distance_km × 6.7 × number_of_bikes
• Car hatchback → distance_km × 5 (one-way) × 2 (return)
• Car sedan     → distance_km × 6.7 × 2
• Car suv       → distance_km × 8.3 × 2
• Car luxury    → distance_km × 12.5 × 2
• Train sleeper → distance_km × 0.50 × group_size × 2
• Train 3AC     → distance_km × 1.2 × group_size × 2
• Train 2AC     → distance_km × 2.0 × group_size × 2
• Train 1AC     → distance_km × 3.5 × group_size × 2
• Train Vande Bharat → distance_km × 2.8 × group_size × 2
• Flight economy → use economy_inr from tool × group_size
• Flight business → use business_inr from tool × group_size
• Bus state  → distance_km × 0.8 × group_size × 2
• Bus sleeper → distance_km × 1.5 × group_size × 2
• Bus volvo  → distance_km × 2.5 × group_size × 2

Show travel_cost_inr in flight_info even for non-flight modes. Set airline = mode name.

════════════════════════════════════════════════════════════
CRITICAL RULE — DAY-BY-DAY REALISM:
════════════════════════════════════════════════════════════
Each activity in day_by_day MUST follow this exact format:
  "Visit [Place Name] — entry ticket Rs.X/person · [Y hrs] | Brief description"
  "Adventure: [Activity] — Rs.X/person · [Y hrs] | What to expect"
  "Local transport: [Mode] from A to B — Rs.X per trip"

Examples:
  "Visit City Palace, Udaipur — entry Rs.250/person · [2 hrs] | 3-storey royal palace complex with museum and lake views"
  "Boat ride on Lake Pichola — Rs.400/person · [1 hr] | Sunset cruise past Jag Mandir island"
  "Fateh Sagar Lake cycling — Rs.50 cycle rental · [1.5 hrs] | Scenic lakeside path with mountain views"
  "Auto from hotel to Old City — Rs.50–80/trip · [20 min]"

Estimate estimated_cost_inr PER DAY realistically:
  = sum of entry tickets + local transport + food + activity fees
  Do NOT just write round numbers like 5000. Be specific e.g. 3250, 4800, 2600.

════════════════════════════════════════════════════════════
CRITICAL RULE — LOCAL FOOD SPECIFICITY:
════════════════════════════════════════════════════════════
NEVER say "lunch at local restaurant" or "dinner at restaurant".
For each meal on each day, name a SPECIFIC famous dish + restaurant:

Format: "[Dish Name] at [Restaurant Name] (~Rs.X/person)"

Rules:
• Rotate dishes every day — no dish repeated across breakfast/lunch/dinner of any day
• Use authentic local specialties of THAT destination
• Include street food, chaat, sweets as snacks
• Name real famous restaurants of that city when possible
• Add approximate price per person

Examples for Udaipur:
  Day 1 lunch: "Dal Baati Churma at Natraj Dining Hall (~Rs.180/person) — iconic Rajasthani thali"
  Day 1 dinner: "Laal Maas + Bajre ki Roti at Upre by 1559 AD (~Rs.600/person) — rooftop lake view"
  Day 2 breakfast: "Pyaaz Kachori + Lassi at Millets of Mewar (~Rs.120/person)"
  Day 2 lunch: "Gatte ki Sabzi + Missi Roti at Paras Pakwan (~Rs.160/person)"
  Day 2 dinner: "Mawa Kachori dessert + Kadhi Pakora at Jheel's Ginger Coffee Bar (~Rs.400/person)"
  Day 3 lunch: "Rajasthani Thali (full) at Bikanervala (~Rs.200/person)"

════════════════════════════════════════════════════════════
HOTEL DISPLAY RULE:
════════════════════════════════════════════════════════════
The hotel_info tool returns 3 tiers. Pass them through as-is in your JSON under hotel_info.
Pick the tier matching user's budget for cost calculations. Show all 3 tiers in hotel_info.

════════════════════════════════════════════════════════════
OUTPUT FORMAT (return ONLY raw JSON, no markdown fences, no extra text):
════════════════════════════════════════════════════════════
{
  "destination":              "string",
  "origin":                   "string (extracted from query)",
  "duration_days":            integer,
  "group_size":               integer,
  "travel_mode":              "string (e.g. Train Sleeper, Car SUV, Flight Economy)",
  "budget_total_inr":         integer,
  "summary":                  "string (3 sentences: what you planned, travel mode cost, key highlights)",
  "weather_info":             { ...from tool... },
  "flight_info": {
    "origin":                 "string",
    "destination":            "string",
    "distance_km":            integer,
    "airline":                "string (the travel mode e.g. Indian Railways / Bus / Car)",
    "economy_inr":            integer (per-person one-way ticket or equivalent),
    "business_inr":           integer or null,
    "duration_hrs":           number,
    "stops":                  "string",
    "travel_cost_inr":        integer (TOTAL cost for ALL passengers BOTH ways using travel mode formula above),
    "note":                   "string (e.g. 'Based on Train Sleeper @ Rs.0.50/km × 2 persons × 2 way')"
  },
  "hotel_info":               { ...3-tier structure from tool... },
  "currency_info":            { ...from tool, optional... },
  "day_by_day": [
    {
      "day":                  integer,
      "title":                "string",
      "activities":           ["string with price + time in format above", ...],
      "meals": {
        "breakfast":          "Specific Dish at Restaurant (~Rs.X/person)",
        "lunch":              "Specific Dish at Restaurant (~Rs.X/person)",
        "dinner":             "Specific Dish at Restaurant (~Rs.X/person)"
      },
      "day_cost_breakdown": {
        "entry_tickets_inr":  integer,
        "local_transport_inr":integer,
        "food_inr":           integer,
        "activities_inr":     integer,
        "misc_inr":           integer
      },
      "estimated_cost_inr":   integer (sum of day_cost_breakdown, per ALL persons)
    }
  ],
  "travel_cost_inr":          integer (same as flight_info.travel_cost_inr),
  "hotel_cost_inr":           integer (nightly_rate × duration_days for selected tier),
  "food_cost_inr":            integer (total food budget across all days),
  "activities_cost_inr":      integer (total activity/entry costs),
  "total_estimated_cost_inr": integer (travel + hotel + food + activities + misc, must be ≤ budget),
  "budget_fit":               "Within Budget | Slightly Over Budget | Over Budget",
  "packing_list":             ["string", ...],
  "tips":                     ["string", ...]
}"""


def _call_llm(messages: list[dict], use_tools: bool = True, final: bool = False) -> Any:
    last_exc: Exception | None = None
    # Use higher token limit for the final JSON answer (no tools needed)
    max_tok = 8192 if final else 4096
    
    # Fallback models in case of 429 Rate Limit
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
    
    for attempt in range(1, MAX_RETRIES + 1):
        for model in models:
            try:
                kwargs: dict[str, Any] = {
                    "model":       model,
                    "messages":    messages,
                    "temperature": 0.3,
                    "max_tokens":  max_tok,
                }
                if use_tools and not final:
                    kwargs["tools"]       = get_groq_tools()
                    kwargs["tool_choice"] = "auto"
                
                resp = client.chat.completions.create(**kwargs)
                fr = resp.choices[0].finish_reason
                logger.info("LLM [%s] finish_reason=%s tokens=%s", model, fr, getattr(resp.usage, 'completion_tokens', '?'))
                return resp
                
            except (APIConnectionError, APIStatusError) as exc:
                if "429" in str(exc) or "Rate limit" in str(exc):
                    logger.warning("LLM [%s] rate limited (429), trying fallback...", model)
                    last_exc = exc
                    continue # Try next model
                logger.warning("LLM [%s] attempt %d/%d failed: %s", model, attempt, MAX_RETRIES, exc)
                last_exc = exc
                break # Break model loop, wait and retry same attempt loop
                
            except Exception as exc:
                logger.error("LLM [%s] unexpected error attempt %d: %s", model, attempt, exc)
                last_exc = exc
                break # Break model loop
                
        if attempt < MAX_RETRIES:
            logger.info("Waiting %ds before retry attempt %d", RETRY_DELAY_S * attempt, attempt + 1)
            time.sleep(RETRY_DELAY_S * attempt)
            
    raise RuntimeError(f"LLM call failed after {MAX_RETRIES} attempts. Last error: {last_exc}") from last_exc


def run_agent(user_id: str, query: str) -> dict:
    """Full agentic loop: load memory → call LLM → dispatch tools → return itinerary."""
    history = db.get_history(user_id)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": query})
    db.append_message(user_id, "user", query)

    raw_content = ""
    for _round in range(MAX_TOOL_ROUNDS):
        # On the last round, force a plain text answer (no tools) so JSON is not cut off
        is_last = (_round == MAX_TOOL_ROUNDS - 1)
        response = _call_llm(messages, use_tools=(not is_last), final=is_last)
        choice   = response.choices[0]
        message  = choice.message

        if choice.finish_reason == "tool_calls" and message.tool_calls:
            messages.append({
                "role":       "assistant",
                "content":    message.content or "",
                "tool_calls": [
                    {
                        "id":       tc.id,
                        "type":     "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in message.tool_calls
                ],
            })
            for tc in message.tool_calls:
                result = dispatch_tool(tc.function.name, tc.function.arguments)
                logger.info("Tool: %s → %s chars", tc.function.name, len(result))
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tc.id,
                    "name":         tc.function.name,
                    "content":      result,
                })
            continue

        # Stop — model returned a content response
        raw_content = (message.content or "").strip()
        if not raw_content and message.tool_calls:
            # Edge case: model called tools on last round — extract what we have
            raw_content = message.content or ""
        break
    else:
        raise RuntimeError("Agent exceeded max tool rounds without final answer.")

    db.append_message(user_id, "assistant", raw_content)
    return _parse_json(raw_content)


def _parse_json(raw: str) -> dict:
    """Robust JSON parser — handles markdown fences, truncated JSON, trailing commas."""
    import re

    if not raw or not raw.strip():
        logger.error("LLM returned empty response")
        return {"destination": "Unknown", "summary": "Empty response from AI.", "parse_error": True}

    cleaned = raw.strip()

    # Strip markdown code fences  ```json ... ``` or ``` ... ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    # If there's no leading { but JSON is embedded somewhere, extract it
    if not cleaned.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            cleaned = m.group(0)

    # Remove JS-style trailing commas before } or ] (common LLM mistake)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

    # Attempt 1 — parse as-is
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt 2 — find largest {...} block
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end])
        except json.JSONDecodeError:
            pass

    # Attempt 3 — JSON is truncated; close open brackets
    fragment = cleaned[start:] if start != -1 else cleaned
    depth_c = depth_s = 0
    for ch in fragment:
        if ch == '{': depth_c += 1
        elif ch == '}': depth_c -= 1
        elif ch == '[': depth_s += 1
        elif ch == ']': depth_s -= 1
    # Close unclosed brackets
    fragment = fragment.rstrip(", \t\n")
    fragment += ']' * max(0, depth_s) + '}' * max(0, depth_c)
    # Strip trailing comma before newly added brackets
    fragment = re.sub(r",\s*([}\]])", r"\1", fragment)
    try:
        return json.loads(fragment)
    except json.JSONDecodeError as e:
        logger.error("Could not parse LLM response as JSON: %s | raw[:300]=%s", e, raw[:300])

    # Last resort — return raw text as summary so UI doesn't crash
    return {
        "destination":  "Parsing Error",
        "summary":      raw[:600] + ("..." if len(raw) > 600 else ""),
        "raw_response": raw,
        "parse_error":  True,
    }
