"""
Core astronomy module — thread-safe wrappers around pyswisseph for Sun/Moon
positions, ayanamsha, and Julian Day conversions.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import swisseph as swe

# Swiss Ephemeris C library maintains global sidereal/ephe state; guard access.
_SWE_LOCK = threading.RLock()
_CURRENT_AYANAMSHA_ID: int = swe.SIDM_LAHIRI


def init_ephemeris(ephe_path: str = "") -> None:
    """Point swisseph at ephemeris data files (thread-safe)."""
    with _SWE_LOCK:
        if ephe_path:
            swe.set_ephe_path(ephe_path)


def set_ayanamsha(ayanamsha_id: int = swe.SIDM_LAHIRI) -> None:
    """Set the default sidereal mode / ayanamsha (thread-safe)."""
    global _CURRENT_AYANAMSHA_ID
    with _SWE_LOCK:
        _CURRENT_AYANAMSHA_ID = ayanamsha_id
        swe.set_sid_mode(ayanamsha_id)


def _calc_ut_locked(
    jd: float,
    body: int,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
):
    """Calculate planetary position safely under _SWE_LOCK."""
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    if sidereal:
        flags |= swe.FLG_SIDEREAL

    with _SWE_LOCK:
        if sidereal:
            target_ayan = _CURRENT_AYANAMSHA_ID if ayanamsha_id is None else ayanamsha_id
            swe.set_sid_mode(target_ayan)
        result, _ = swe.calc_ut(jd, body, flags)
        return result


# ---------------------------------------------------------------------------
# Julian Day helpers
# ---------------------------------------------------------------------------

def datetime_to_jd(dt: datetime) -> float:
    """
    Convert a timezone-aware datetime to Julian Day (UT).
    If the datetime is naive, it is assumed to be UTC.
    """
    if dt.tzinfo is not None:
        dt_utc = dt.astimezone(timezone.utc)
    else:
        dt_utc = dt.replace(tzinfo=timezone.utc)

    hour_float = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + (dt_utc.second + dt_utc.microsecond / 1_000_000.0) / 3600.0
    )
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour_float)


def jd_to_datetime_utc(jd: float) -> datetime:
    """Convert a Julian Day (UT) to a UTC datetime, safely handling rounding."""
    year, month, day, hour_frac = swe.revjul(jd)
    if year < 1 or year > 9999:
        raise ValueError(f"Year {year} is outside Python datetime range [1, 9999].")

    base = datetime(year, month, day, tzinfo=timezone.utc)
    total_seconds = round(hour_frac * 3600.0)
    return base + timedelta(seconds=total_seconds)


# ---------------------------------------------------------------------------
# Planetary positions
# ---------------------------------------------------------------------------

def get_solar_longitude(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """Return the Sun's ecliptic longitude in degrees [0, 360)."""
    result = _calc_ut_locked(jd, swe.SUN, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
    return result[0] % 360.0


def get_lunar_longitude(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """Return the Moon's ecliptic longitude in degrees [0, 360)."""
    result = _calc_ut_locked(jd, swe.MOON, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
    return result[0] % 360.0


def get_lunar_speed(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """Return Moon's daily elongation rate relative to Sun (deg/day)."""
    moon_result = _calc_ut_locked(jd, swe.MOON, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
    sun_result = _calc_ut_locked(jd, swe.SUN, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
    return moon_result[3] - sun_result[3]


def get_elongation(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """
    Return (Moon longitude - Sun longitude) mod 360.
    This is the fundamental quantity for Tithi and Karana.
    """
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    if sidereal:
        flags |= swe.FLG_SIDEREAL

    with _SWE_LOCK:
        if sidereal:
            target_ayan = _CURRENT_AYANAMSHA_ID if ayanamsha_id is None else ayanamsha_id
            swe.set_sid_mode(target_ayan)
        moon_res, _ = swe.calc_ut(jd, swe.MOON, flags)
        sun_res, _ = swe.calc_ut(jd, swe.SUN, flags)
    return (moon_res[0] - sun_res[0]) % 360.0


def get_ayanamsha(jd: float, ayanamsha_id: Optional[int] = None) -> float:
    """Return the ayanamsha value in degrees for a given JD."""
    with _SWE_LOCK:
        target_ayan = _CURRENT_AYANAMSHA_ID if ayanamsha_id is None else ayanamsha_id
        swe.set_sid_mode(target_ayan)
        return swe.get_ayanamsa_ut(jd)
