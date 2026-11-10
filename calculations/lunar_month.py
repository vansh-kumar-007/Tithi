"""
Hindu lunar month determination (Amanta and Purnimanta systems).

Amanta (South / West Indian): month runs from New Moon to New Moon (Amavasya end).
  - Named after the Sankranti (solar ingress) falling inside the lunar month,
    i.e., if the New Moon starts while the Sun is in solar sign S (e.g. Meena=11),
    the Sankranti entering (S + 1) % 12 (Mesha=0 -> Chaitra) occurs during the month,
    giving Amanta month index (S + 1) % 12.
  - Adhika Masa: if no Sankranti occurs between consecutive New Moons
    (sign_at_start_nm == sign_at_end_nm), that lunar month is Adhika and shares
    the name of the immediately following regular (Nija) month: (sign_at_start_nm + 1) % 12.

Purnimanta (North Indian): month runs from Full Moon to Full Moon (Purnima end).
  - Shukla Paksha has the same month name as Amanta.
  - Krishna Paksha in a regular (non-Adhika) month carries the NEXT month's name
    relative to Amanta: (amanta_month_index + 1) % 12.
  - During an Adhika Masa (Shukla + Krishna), both Pakshas share the Adhika month name.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from calculations.astronomy import get_elongation, get_solar_longitude

# Solar zodiac sign names (for Sankranti reference)
RASHI_NAMES_EN = [
    "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
    "Tula", "Vrishchika", "Dhanu", "Makara", "Kumbha", "Meena",
]
RASHI_NAMES_HI = [
    "मेष", "वृषभ", "मिथुन", "कर्क", "सिंह", "कन्या",
    "तुला", "वृश्चिक", "धनु", "मकर", "कुम्भ", "मीन",
]

# Lunar month names (traditional order, starting with Chaitra)
LUNAR_MONTH_NAMES_EN = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha",
    "Shravana", "Bhadrapada", "Ashwina", "Kartika",
    "Margashirsha", "Pausha", "Magha", "Phalguna",
]
LUNAR_MONTH_NAMES_HI = [
    "चैत्र", "वैशाख", "ज्येष्ठ", "आषाढ़",
    "श्रावण", "भाद्रपद", "आश्विन", "कार्तिक",
    "मार्गशीर्ष", "पौष", "माघ", "फाल्गुन",
]

_NM_TOLERANCE_DAYS = 1.0 / 86400.0  # ~1 second


@dataclass
class LunarMonthInfo:
    month_index: int        # 0 = Chaitra … 11 = Phalguna (in selected lunar_system)
    month_name_en: str
    month_name_hi: str
    is_adhika: bool         # True if intercalary month
    paksha_en: str          # "Shukla" or "Krishna"
    solar_sign_index: int   # 0 = Mesha … 11 = Meena
    solar_sign_en: str
    solar_sign_hi: str
    lunar_system: str = "amanta"      # "amanta" or "purnimanta"
    amanta_month_index: int = 0       # Underlying Amanta index (0–11)
    is_kshaya_masa: bool = False
    start_nm_jd: float = 0.0
    end_nm_jd: float = 0.0


def get_solar_sign(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> int:
    """Return 0-based solar sign index (0=Mesha, 11=Meena)."""
    sun_lon = get_solar_longitude(jd, sidereal, ayanamsha_id=ayanamsha_id)
    return int(sun_lon / 30.0) % 12


def _bisect_new_moon(
    lo: float,
    hi: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """Binary search for exact elongation == 0°/360° inside [lo, hi]."""
    while (hi - lo) > _NM_TOLERANCE_DAYS:
        mid = (lo + hi) / 2.0
        e = get_elongation(mid, sidereal, ayanamsha_id=ayanamsha_id)
        if e > 180.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def find_new_moon_before(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """
    Find the exact JD of the most recent New Moon (elongation = 0°) at or before jd.
    Walks backward in 0.5-day steps (~6°–7° elongation per step) so a New Moon
    crossing can never be skipped.
    """
    curr_jd = jd
    curr_e = get_elongation(curr_jd, sidereal, ayanamsha_id=ayanamsha_id)

    # If right at New Moon (within ~2 minutes), resolve whether just before or after
    if curr_e < 0.05:
        return curr_jd

    step = 0.5
    for _ in range(65):  # up to 32.5 days covers max synodic month (~29.93d)
        prev_jd = curr_jd - step
        prev_e = get_elongation(prev_jd, sidereal, ayanamsha_id=ayanamsha_id)
        # Walking backward, elongation decreases and wraps from ~0° to ~354°
        if prev_e > 180.0 and curr_e <= 180.0:
            return _bisect_new_moon(prev_jd, curr_jd, sidereal, ayanamsha_id=ayanamsha_id)
        curr_jd = prev_jd
        curr_e = prev_e

    return curr_jd


def find_new_moon_after(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """
    Find the exact JD of the next New Moon strictly after jd.
    """
    # If jd is right near a New Moon, jump past it slightly first, or start from jd + 27.5
    # when finding end of a lunation starting at nm_jd.
    curr_jd = jd
    curr_e = get_elongation(curr_jd, sidereal, ayanamsha_id=ayanamsha_id)
    step = 0.5

    for _ in range(65):
        next_jd = curr_jd + step
        next_e = get_elongation(next_jd, sidereal, ayanamsha_id=ayanamsha_id)
        # Walking forward, elongation increases and wraps from ~354° to ~0°
        if curr_e > 180.0 and next_e <= 180.0:
            return _bisect_new_moon(curr_jd, next_jd, sidereal, ayanamsha_id=ayanamsha_id)
        curr_jd = next_jd
        curr_e = next_e

    return curr_jd


def find_next_new_moon(
    nm_jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> float:
    """Given a New Moon JD, return the exact JD of the following New Moon (~29.18–29.93d later)."""
    return find_new_moon_after(nm_jd + 28.0, sidereal=sidereal, ayanamsha_id=ayanamsha_id)


def get_amanta_lunation_info(
    nm_start_jd: float,
    nm_end_jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> tuple[int, bool, bool]:
    """
    Given the start and end New Moon JDs of an Amanta lunation, return:
      (amanta_month_index, is_adhika, is_kshaya_masa)
    """
    # Offset by +1 minute inside boundaries to avoid exact Sankranti instant noise
    eps = 1.0 / 1440.0
    sign_start = get_solar_sign(nm_start_jd + eps, sidereal, ayanamsha_id=ayanamsha_id)
    sign_end = get_solar_sign(nm_end_jd - eps, sidereal, ayanamsha_id=ayanamsha_id)

    is_adhika = (sign_start == sign_end)
    sign_diff = (sign_end - sign_start) % 12
    is_kshaya_masa = (sign_diff == 2)

    # Standard Sankranti naming: month containing Sankranti entering S+1 is named for S+1
    # Adhika Masa (sign_diff == 0) shares the name of the following regular month (S+1).
    amanta_month_index = (sign_start + 1) % 12
    return amanta_month_index, is_adhika, is_kshaya_masa


def get_lunar_month_info(
    jd: float,
    sidereal: bool = True,
    lunar_system: str = "amanta",
    ayanamsha_id: Optional[int] = None,
) -> LunarMonthInfo:
    """
    Determine the Hindu lunar month (Amanta or Purnimanta) for the given JD.
    """
    solar_sign_idx = get_solar_sign(jd, sidereal, ayanamsha_id=ayanamsha_id)
    elong = get_elongation(jd, sidereal, ayanamsha_id=ayanamsha_id)
    paksha = "Shukla" if elong < 180.0 else "Krishna"

    nm_start_jd = find_new_moon_before(jd, sidereal, ayanamsha_id=ayanamsha_id)
    # Ensure nm_start_jd is strictly before jd when jd is on the next lunation boundary
    if nm_start_jd > jd + 1e-6:
        nm_start_jd = find_new_moon_before(jd - 1.0, sidereal, ayanamsha_id=ayanamsha_id)
    nm_end_jd = find_next_new_moon(nm_start_jd, sidereal, ayanamsha_id=ayanamsha_id)

    amanta_month_index, is_adhika, is_kshaya_masa = get_amanta_lunation_info(
        nm_start_jd, nm_end_jd, sidereal=sidereal, ayanamsha_id=ayanamsha_id
    )

    system = lunar_system.lower()
    if system == "purnimanta" and paksha == "Krishna" and not is_adhika:
        month_index = (amanta_month_index + 1) % 12
    else:
        month_index = amanta_month_index

    return LunarMonthInfo(
        month_index=month_index,
        month_name_en=LUNAR_MONTH_NAMES_EN[month_index],
        month_name_hi=LUNAR_MONTH_NAMES_HI[month_index],
        is_adhika=is_adhika,
        paksha_en=paksha,
        solar_sign_index=solar_sign_idx,
        solar_sign_en=RASHI_NAMES_EN[solar_sign_idx],
        solar_sign_hi=RASHI_NAMES_HI[solar_sign_idx],
        lunar_system=system,
        amanta_month_index=amanta_month_index,
        is_kshaya_masa=is_kshaya_masa,
        start_nm_jd=nm_start_jd,
        end_nm_jd=nm_end_jd,
    )
