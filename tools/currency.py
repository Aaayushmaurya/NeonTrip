"""
tools/currency.py
-----------------
Live currency exchange rates via Frankfurter API (https://frankfurter.dev).
100% FREE — no API key, data from European Central Bank, updated daily.
"""

from __future__ import annotations
import logging
import requests
from cache import cached_call

logger = logging.getLogger(__name__)
BASE_URL = "https://api.frankfurter.app/latest"


def _fetch_rates(base: str, targets: list[str]) -> dict:
    try:
        resp = requests.get(
            BASE_URL,
            params={"base": base, "symbols": ",".join(targets)},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "base":        data.get("base", base),
            "rates":       data.get("rates", {}),
            "date":        data.get("date", ""),
            "data_source": "Frankfurter / European Central Bank (real-time)",
        }
    except Exception as exc:
        logger.warning("Frankfurter API error: %s", exc)
        return {"base": base, "rates": {t: None for t in targets}, "error": str(exc)}


def get_exchange_rates(base_currency: str = "USD", target_currencies: list[str] | None = None) -> dict:
    """
    Fetch live exchange rates.
    Default: USD → INR, EUR, GBP.
    """
    targets = target_currencies or ["INR", "EUR", "GBP"]
    key = f"fx:{base_currency}:{'_'.join(sorted(targets))}"
    return cached_call(key, _fetch_rates, base_currency, targets)


def convert_to_inr(amount_usd: float) -> float | None:
    """Quick helper: convert USD amount to INR using live rates."""
    rates = get_exchange_rates("USD", ["INR"])
    inr_rate = rates.get("rates", {}).get("INR")
    if inr_rate:
        return round(amount_usd * inr_rate, 2)
    return None
