"""
cache.py
--------
Thread-safe TTL cache for external API responses.
Prevents hammering free APIs with repeated identical requests.
"""

from __future__ import annotations
import threading
from typing import Any

from cachetools import TTLCache
from config import get_settings

_settings = get_settings()

_cache: TTLCache = TTLCache(
    maxsize=_settings.cache_max_size,
    ttl=_settings.cache_ttl_seconds,
)
_lock = threading.Lock()


def cache_get(key: str) -> Any | None:
    with _lock:
        return _cache.get(key)


def cache_set(key: str, value: Any) -> None:
    with _lock:
        _cache[key] = value


def cached_call(key: str, fn, *args, **kwargs) -> Any:
    """Call fn(*args, **kwargs) unless result is already cached under key."""
    hit = cache_get(key)
    if hit is not None:
        return hit
    result = fn(*args, **kwargs)
    cache_set(key, result)
    return result


def cache_clear() -> None:
    with _lock:
        _cache.clear()
