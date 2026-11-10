"""
Location geocoding service using Nominatim with thread-safe rate limiting and caching.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim

from config import Config


@dataclass
class LocationResult:
    display_name: str
    latitude: float
    longitude: float
    country: str
    city: str
    state: str


_geocoder = Nominatim(user_agent=Config.GEOCODER_USER_AGENT)
_RATE_LOCK = threading.Lock()
_LAST_REQUEST_TS = 0.0
_MIN_INTERVAL_SEC = 1.05  # Nominatim usage policy: max 1 request/sec


@lru_cache(maxsize=256)
def _cached_geocode(normalized_query: str) -> Optional[LocationResult]:
    global _LAST_REQUEST_TS
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _LAST_REQUEST_TS)
        if wait > 0:
            time.sleep(wait)
        try:
            location = _geocoder.geocode(normalized_query, addressdetails=True, timeout=10)
        except (GeocoderTimedOut, GeocoderUnavailable) as exc:
            raise RuntimeError(f"Geocoding service unavailable: {exc}") from exc
        finally:
            _LAST_REQUEST_TS = time.monotonic()

    if location is None:
        return None

    addr = location.raw.get("address", {})
    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("county")
        or ""
    )
    state = addr.get("state", "")
    country = addr.get("country", "")

    return LocationResult(
        display_name=location.address,
        latitude=float(location.latitude),
        longitude=float(location.longitude),
        country=country,
        city=city,
        state=state,
    )


def geocode_location(query: str) -> Optional[LocationResult]:
    """
    Geocode a free-text location string (cached & rate-limited).
    Returns LocationResult or None if not found.
    """
    normalized = " ".join(query.strip().lower().split())
    if not normalized:
        return None
    return _cached_geocode(normalized)
