"""
Timezone detection and safe localization helpers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytz
from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()


def get_timezone_str(lat: float, lon: float) -> str:
    """Return IANA timezone string for given coordinates. Defaults to UTC."""
    tz_str = _tf.timezone_at(lat=lat, lng=lon)
    return tz_str or "UTC"


def localize_naive_datetime(naive_dt: datetime, timezone_str: str) -> datetime:
    """Attach timezone to a naive local datetime, handling DST edge cases safely."""
    tz = pytz.timezone(timezone_str)
    dt_clean = naive_dt.replace(tzinfo=None)
    try:
        return tz.localize(dt_clean, is_dst=None)
    except pytz.AmbiguousTimeError:
        return tz.localize(dt_clean, is_dst=False)
    except pytz.NonExistentTimeError:
        return tz.localize(dt_clean, is_dst=True)


def get_utc_offset_hours(timezone_str: str, dt: Optional[datetime] = None) -> float:
    """Return the UTC offset in hours for the timezone (considering DST if dt provided)."""
    tz = pytz.timezone(timezone_str)
    if dt is None:
        dt = datetime.now(tz)
    elif dt.tzinfo is None:
        dt = localize_naive_datetime(dt, timezone_str)
    else:
        dt = dt.astimezone(tz)
    offset = dt.utcoffset()
    return offset.total_seconds() / 3600.0 if offset else 0.0


def localize_datetime(dt_utc: Optional[datetime], timezone_str: str) -> Optional[datetime]:
    """Convert a UTC datetime to the given local timezone."""
    if dt_utc is None:
        return None
    tz = pytz.timezone(timezone_str)
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=pytz.utc)
    return dt_utc.astimezone(tz)
