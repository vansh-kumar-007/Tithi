"""
Sunrise, sunset, and observance-moment calculations using Swiss Ephemeris rise_trans.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional, Tuple

import pytz
import swisseph as swe

from calculations.astronomy import _SWE_LOCK, datetime_to_jd, jd_to_datetime_utc


def get_sunrise_jd(
    jd_start: float,
    lat: float,
    lon: float,
    alt: float = 0.0,
) -> Optional[float]:
    """
    Return JD of the next sunrise at or after jd_start for the given location.
    Uses standard upper-limb solar disc rise with atmospheric refraction (swe.CALC_RISE),
    matching traditional Drik Panchang civil sunrise.
    Returns None if circumpolar (polar regions).
    """
    geopos = (lon, lat, alt)
    rsmi = swe.CALC_RISE
    try:
        with _SWE_LOCK:
            ret = swe.rise_trans(jd_start, swe.SUN, rsmi, geopos, 1013.25, 15.0)
        if ret[0] == 0:
            return ret[1][0]
    except Exception:
        pass
    return None


def get_sunset_jd(
    jd_start: float,
    lat: float,
    lon: float,
    alt: float = 0.0,
) -> Optional[float]:
    """Return JD of the next sunset at or after jd_start for the given location."""
    geopos = (lon, lat, alt)
    rsmi = swe.CALC_SET
    try:
        with _SWE_LOCK:
            ret = swe.rise_trans(jd_start, swe.SUN, rsmi, geopos, 1013.25, 15.0)
        if ret[0] == 0:
            return ret[1][0]
    except Exception:
        pass
    return None


def get_sunrise_sunset(
    start_utc: datetime,
    lat: float,
    lon: float,
    alt: float = 0.0,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Return the next (sunrise_utc, sunset_utc) occurring at or after start_utc.
    Sunset is searched starting from sunrise (when available) so both belong
    to the same local solar day.
    """
    jd_start = datetime_to_jd(start_utc)
    sr_jd = get_sunrise_jd(jd_start, lat, lon, alt)
    ss_start_jd = sr_jd if sr_jd is not None else jd_start
    ss_jd = get_sunset_jd(ss_start_jd, lat, lon, alt)

    sr = jd_to_datetime_utc(sr_jd) if sr_jd else None
    ss = jd_to_datetime_utc(ss_jd) if ss_jd else None
    return sr, ss


def get_jd_at_local_midnight(
    local_date: date,
    timezone_str: str,
) -> float:
    """
    Return JD (UT) corresponding to local midnight (00:00) for local_date
    in the given IANA timezone (accurately handling DST and historical offsets).
    """
    tz = pytz.timezone(timezone_str)
    naive_midnight = datetime(local_date.year, local_date.month, local_date.day, 0, 0, 0)
    try:
        local_midnight = tz.localize(naive_midnight, is_dst=None)
    except pytz.AmbiguousTimeError:
        local_midnight = tz.localize(naive_midnight, is_dst=False)
    except pytz.NonExistentTimeError:
        local_midnight = tz.localize(naive_midnight, is_dst=True)
    return datetime_to_jd(local_midnight.astimezone(pytz.utc))


def get_sunrise_sunset_for_local_date(
    local_date: date,
    lat: float,
    lon: float,
    timezone_str: str,
    alt: float = 0.0,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Return (sunrise_utc, sunset_utc) for a local calendar date in timezone_str.
    Searches forward from local 00:00 so locations in any hemisphere or timezone
    (e.g. Tokyo UTC+9, Kolkata UTC+5:30, New York UTC-5) always receive that
    specific local calendar date's sunrise and sunset.
    """
    jd_local_midnight = get_jd_at_local_midnight(local_date, timezone_str)
    sr_jd = get_sunrise_jd(jd_local_midnight, lat, lon, alt)
    # Guard: ensure the found sunrise falls on the same local date (not next day in polar edge cases)
    if sr_jd is not None:
        sr_utc = jd_to_datetime_utc(sr_jd)
        tz = pytz.timezone(timezone_str)
        if sr_utc.astimezone(tz).date() != local_date:
            sr_jd = None
            sr_utc = None
    else:
        sr_utc = None

    ss_start_jd = sr_jd if sr_jd is not None else jd_local_midnight
    ss_jd = get_sunset_jd(ss_start_jd, lat, lon, alt)
    ss_utc = jd_to_datetime_utc(ss_jd) if ss_jd else None
    return sr_utc, ss_utc


def get_observance_jd_for_local_date(
    local_date: date,
    lat: float,
    lon: float,
    timezone_str: str,
    method: str = "sunrise",
    alt: float = 0.0,
) -> Optional[float]:
    """
    Return the JD (UT) at which Tithi observance is evaluated on local_date.
    Supported methods:
      - "sunrise"   : Udaya Tithi (local sunrise) [default]
      - "madhyahna" : Local solar midday (midpoint between sunrise and sunset)
      - "sunset"    : Sayahna Tithi (local sunset)
    """
    sr_utc, ss_utc = get_sunrise_sunset_for_local_date(
        local_date, lat, lon, timezone_str, alt=alt
    )
    if method == "sunrise":
        return datetime_to_jd(sr_utc) if sr_utc else None
    if method == "sunset":
        return datetime_to_jd(ss_utc) if ss_utc else None
    if method == "madhyahna":
        if sr_utc and ss_utc:
            return (datetime_to_jd(sr_utc) + datetime_to_jd(ss_utc)) / 2.0
        # Polar fallback: local 12:00 noon
        tz = pytz.timezone(timezone_str)
        noon = tz.localize(datetime(local_date.year, local_date.month, local_date.day, 12, 0, 0))
        return datetime_to_jd(noon.astimezone(pytz.utc))
    return datetime_to_jd(sr_utc) if sr_utc else None
