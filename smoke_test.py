import sys
sys.path.insert(0, '.')

print("Testing imports...")
import config; print("  config          OK")
import db; print("  db              OK")
import cache; print("  cache           OK")
import auth; print("  auth            OK")
from tools import geocoding, weather, flights, hotels, currency
print("  tools/*         OK")
import mcp_bridge; print("  mcp_bridge      OK")
import agent_logic; print("  agent_logic     OK")
import main; print("  main            OK")

print()
print("Testing real API tools (no keys needed)...")

# Geocoding
coords = geocoding.geocode("Manali")
print("  geocode(Manali)  lat={:.2f}, lon={:.2f}".format(coords["lat"], coords["lon"]))

# Currency
fx = currency.get_exchange_rates("USD", ["INR"])
inr = fx["rates"].get("INR", "?")
print("  USD -> INR rate  = {}".format(inr))

# Flight distance model
f = flights.get_flight_prices("Patna", "Manali")
print("  Patna->Manali    = Rs.{:,} economy, {} km".format(f["economy_inr"], f["distance_km"]))

# Weather (real)
w = weather.get_live_weather("Manali")
print("  Manali weather   = {} {}C".format(w.get("condition","?"), w.get("temp_c","?")))

print()
print("All checks passed!")
