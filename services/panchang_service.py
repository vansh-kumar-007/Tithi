"""
Panchang orchestration service.

Coordinates all Panchang calculations for a given date/time/location.
Handles exact, approximate, and unknown birth-time modes, plus Amanta/Purnimanta,
observance rules, Adhika Masa rules, and multi-candidate birthday calendars.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

import pytz
import swisseph as swe

from calculations.astronomy import datetime_to_jd, init_ephemeris
from calculations.birthday_dates import (
    OBSERVANCE_LABELS,
    BirthdayEntry,
    find_birthdays_range,
)
from calculations.karana import KaranaInfo, get_karana_at_jd
from calculations.lunar_month import LunarMonthInfo, get_lunar_month_info
from calculations.nakshatra import NakshatraInfo, get_nakshatra_at_jd
from calculations.sunrise import get_sunrise_sunset_for_local_date
from calculations.tithi import (
    TithiInfo,
    get_full_tithi_info,
    get_tithi_transitions_in_interval,
)
from calculations.yoga import YogaInfo, get_yoga_at_jd
from config import Config
from services.timezone_service import localize_datetime, localize_naive_datetime


@dataclass
class CandidateBirthdayCalendar:
    """Birthday calendar corresponding to one candidate birth Tithi."""
    tithi: TithiInfo
    lunar_month: LunarMonthInfo
    entries: List[BirthdayEntry]


@dataclass
class PanchangResult:
    """Birth Panchang data."""
    birth_date: date
    birth_time_known: bool
    birth_time_mode: str          # "exact", "approximate", "unknown"
    birth_time_local: Optional[datetime]
    location_name: str
    lat: float
    lon: float
    timezone_str: str
    ayanamsha_name: str
    lunar_system: str             # "amanta" or "purnimanta"
    observance_method: str        # "sunrise", "madhyahna", "sunset"
    adhika_rule: str              # "nija", "adhika", "both"

    # Sunrise/Sunset
    sunrise_utc: Optional[datetime]
    sunset_utc: Optional[datetime]
    sunrise_local: Optional[datetime]
    sunset_local: Optional[datetime]

    # Panchang elements
    tithis: List[TithiInfo]
    nakshatra: Optional[NakshatraInfo]
    yoga: Optional[YogaInfo]
    karana: Optional[KaranaInfo]
    lunar_month: Optional[LunarMonthInfo]

    # Tithi at sunrise (traditional observance reference)
    tithi_at_sunrise: Optional[TithiInfo]

    # Ambiguity & confidence
    is_ambiguous: bool = False
    ambiguity_message: str = ""
    confidence: str = "High"      # "High", "Medium", "Low"
    birth_time_start_local: Optional[datetime] = None
    birth_time_end_local: Optional[datetime] = None


@dataclass
class FullResult:
    """Complete calculation result."""
    panchang: PanchangResult
    birthday_entries: List[BirthdayEntry]
    start_year: int
    end_year: int
    candidate_calendars: List[CandidateBirthdayCalendar] = field(default_factory=list)
    today: date = field(default_factory=date.today)

    @property
    def next_birthday(self) -> Optional[BirthdayEntry]:
        for entry in self.birthday_entries:
            if entry.gregorian_date and entry.gregorian_date >= self.today:
                return entry
        return None

    @property
    def days_until_next_birthday(self) -> Optional[int]:
        nb = self.next_birthday
        if nb and nb.gregorian_date:
            return (nb.gregorian_date - self.today).days
        return None


AYANAMSHA_MAP = {
    "lahiri": swe.SIDM_LAHIRI,
    "raman": swe.SIDM_RAMAN,
    "krishnamurti": swe.SIDM_KRISHNAMURTI,
    "yukteshwar": swe.SIDM_YUKTESHWAR,
    "true_citra": swe.SIDM_TRUE_CITRA,
}

AYANAMSHA_NAMES = {
    "lahiri": "Lahiri (Chitrapaksha)",
    "raman": "B.V. Raman",
    "krishnamurti": "Krishnamurti (KP)",
    "yukteshwar": "Yukteshwar",
    "true_citra": "True Citra",
}

LUNAR_SYSTEMS = {"amanta", "purnimanta"}
OBSERVANCE_METHODS = set(OBSERVANCE_LABELS.keys())
ADHIKA_RULES = {"nija", "adhika", "both"}


def calculate_panchang(
    birth_date: date,
    birth_time_local: Optional[datetime],
    birth_time_mode: str,
    lat: float,
    lon: float,
    timezone_str: str,
    location_name: str,
    ayanamsha_key: str = "lahiri",
    ephe_path: str = "",
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    birth_time_start: Optional[datetime] = None,
    birth_time_end: Optional[datetime] = None,
    lunar_system: str = "amanta",
    observance_method: str = "sunrise",
    adhika_rule: str = "nija",
) -> FullResult:
    """
    Main entry point for all Panchang and Hindu birthday calculations.
    """
    init_ephemeris(ephe_path or Config.EPHE_PATH)
    ayanamsha_id = AYANAMSHA_MAP.get(ayanamsha_key, swe.SIDM_LAHIRI)
    ayanamsha_name = AYANAMSHA_NAMES.get(ayanamsha_key, "Lahiri (Chitrapaksha)")
    sidereal = True

    if lunar_system not in LUNAR_SYSTEMS:
        raise ValueError(f"Unsupported lunar_system: {lunar_system}")
    if observance_method not in OBSERVANCE_METHODS:
        raise ValueError(f"Unsupported observance_method: {observance_method}")
    if adhika_rule not in ADHIKA_RULES:
        raise ValueError(f"Unsupported adhika_rule: {adhika_rule}")
    if birth_time_mode not in {"exact", "approximate", "unknown"}:
        raise ValueError(f"Unsupported birth_time_mode: {birth_time_mode}")

    tz = pytz.timezone(timezone_str)
    local_today = datetime.now(tz).date()

    # --- Sunrise / Sunset for the exact local birth date ---
    sunrise_utc, sunset_utc = get_sunrise_sunset_for_local_date(
        birth_date, lat, lon, timezone_str
    )
    sunrise_local = localize_datetime(sunrise_utc, timezone_str)
    sunset_local = localize_datetime(sunset_utc, timezone_str)

    # --- Tithi at Sunrise ---
    tithi_at_sunrise = None
    if sunrise_utc:
        sr_jd = datetime_to_jd(sunrise_utc)
        tithi_at_sunrise = get_full_tithi_info(sr_jd, sidereal, ayanamsha_id=ayanamsha_id)

    # --- Main Panchang calculation based on birth_time_mode ---
    tithis: List[TithiInfo] = []
    candidate_jds: List[float] = []
    nakshatra: Optional[NakshatraInfo] = None
    yoga: Optional[YogaInfo] = None
    karana: Optional[KaranaInfo] = None
    lunar_month: Optional[LunarMonthInfo] = None
    is_ambiguous = False
    ambiguity_message = ""
    confidence = "High"
    aware_birth_time: Optional[datetime] = None
    aware_start_time: Optional[datetime] = None
    aware_end_time: Optional[datetime] = None

    if birth_time_mode == "exact":
        if birth_time_local is None:
            raise ValueError("birth_time is required when birth_time_mode is 'exact'.")
        aware_birth_time = localize_naive_datetime(birth_time_local, timezone_str)
        birth_jd = datetime_to_jd(aware_birth_time)

        tithi = get_full_tithi_info(birth_jd, sidereal, ayanamsha_id=ayanamsha_id)
        tithis = [tithi]
        candidate_jds = [birth_jd]
        nakshatra = get_nakshatra_at_jd(birth_jd, sidereal, ayanamsha_id=ayanamsha_id)
        yoga = get_yoga_at_jd(birth_jd, sidereal, ayanamsha_id=ayanamsha_id)
        karana = get_karana_at_jd(birth_jd, sidereal, ayanamsha_id=ayanamsha_id)
        lunar_month = get_lunar_month_info(
            birth_jd, sidereal, lunar_system=lunar_system, ayanamsha_id=ayanamsha_id
        )
        confidence = "High"

    elif birth_time_mode == "approximate":
        if birth_time_start is None or birth_time_end is None:
            raise ValueError("birth_time_start and birth_time_end are required in 'approximate' mode.")
        aware_start_time = localize_naive_datetime(birth_time_start, timezone_str)
        aware_end_time = localize_naive_datetime(birth_time_end, timezone_str)
        jd_start = datetime_to_jd(aware_start_time)
        jd_end = datetime_to_jd(aware_end_time)
        if jd_end <= jd_start:
            raise ValueError("Approximate end time must be after start time.")

        transitions = get_tithi_transitions_in_interval(
            jd_start, jd_end, sidereal, ayanamsha_id=ayanamsha_id
        )
        # Segment boundaries within [jd_start, jd_end]
        boundaries = [jd_start] + [tr_jd for tr_jd, _ in transitions] + [jd_end]
        seen_indices = set()
        for i in range(len(boundaries) - 1):
            seg_mid = (boundaries[i] + boundaries[i + 1]) / 2.0
            t = get_full_tithi_info(seg_mid, sidereal, ayanamsha_id=ayanamsha_id)
            if t.index not in seen_indices:
                tithis.append(t)
                candidate_jds.append(seg_mid)
                seen_indices.add(t.index)

        jd_mid = (jd_start + jd_end) / 2.0
        nakshatra = get_nakshatra_at_jd(jd_mid, sidereal, ayanamsha_id=ayanamsha_id)
        yoga = get_yoga_at_jd(jd_mid, sidereal, ayanamsha_id=ayanamsha_id)
        karana = get_karana_at_jd(jd_mid, sidereal, ayanamsha_id=ayanamsha_id)
        lunar_month = get_lunar_month_info(
            jd_mid, sidereal, lunar_system=lunar_system, ayanamsha_id=ayanamsha_id
        )

        if len(tithis) == 1:
            confidence = "High"
        else:
            is_ambiguous = True
            confidence = "Medium"
            ambiguity_message = (
                f"Your approximate birth time window contains {len(tithis)} Tithis. "
                "All possible Tithis and corresponding birthday calendars are shown below."
            )

    else:
        # Unknown birth time — scan the entire local calendar day [00:00:00, 23:59:59]
        day_start_local = localize_naive_datetime(
            datetime(birth_date.year, birth_date.month, birth_date.day, 0, 0, 0),
            timezone_str,
        )
        day_end_local = localize_naive_datetime(
            datetime(birth_date.year, birth_date.month, birth_date.day, 23, 59, 59),
            timezone_str,
        )
        jd_start = datetime_to_jd(day_start_local)
        jd_end = datetime_to_jd(day_end_local)

        transitions = get_tithi_transitions_in_interval(
            jd_start, jd_end, sidereal, ayanamsha_id=ayanamsha_id
        )
        boundaries = [jd_start] + [tr_jd for tr_jd, _ in transitions] + [jd_end]
        seen_indices = set()
        for i in range(len(boundaries) - 1):
            seg_mid = (boundaries[i] + boundaries[i + 1]) / 2.0
            t = get_full_tithi_info(seg_mid, sidereal, ayanamsha_id=ayanamsha_id)
            if t.index not in seen_indices:
                tithis.append(t)
                candidate_jds.append(seg_mid)
                seen_indices.add(t.index)

        jd_mid = (jd_start + jd_end) / 2.0
        nakshatra = get_nakshatra_at_jd(jd_mid, sidereal, ayanamsha_id=ayanamsha_id)
        yoga = get_yoga_at_jd(jd_mid, sidereal, ayanamsha_id=ayanamsha_id)
        karana = get_karana_at_jd(jd_mid, sidereal, ayanamsha_id=ayanamsha_id)
        lunar_month = get_lunar_month_info(
            jd_mid, sidereal, lunar_system=lunar_system, ayanamsha_id=ayanamsha_id
        )

        if len(tithis) == 1:
            confidence = "High"
            ambiguity_message = (
                "Birth time is unknown. Only one Tithi prevailed throughout your entire local "
                "birth date, so your birth Tithi is determined with high confidence "
                "(time-dependent details such as Nakshatra, Yoga, and Karana remain approximate)."
            )
        else:
            is_ambiguous = True
            confidence = "Low"
            ambiguity_message = (
                f"Your birth time is unknown. {len(tithis)} Tithis occurred on your date of birth, "
                "so we cannot determine your exact birth Tithi without a birth time or approximate period. "
                "All possible Hindu birthday calendars are shown below."
            )

    panchang = PanchangResult(
        birth_date=birth_date,
        birth_time_known=(birth_time_mode == "exact"),
        birth_time_mode=birth_time_mode,
        birth_time_local=aware_birth_time,
        location_name=location_name,
        lat=lat,
        lon=lon,
        timezone_str=timezone_str,
        ayanamsha_name=ayanamsha_name,
        lunar_system=lunar_system,
        observance_method=observance_method,
        adhika_rule=adhika_rule,
        sunrise_utc=sunrise_utc,
        sunset_utc=sunset_utc,
        sunrise_local=sunrise_local,
        sunset_local=sunset_local,
        tithis=tithis,
        nakshatra=nakshatra,
        yoga=yoga,
        karana=karana,
        lunar_month=lunar_month,
        tithi_at_sunrise=tithi_at_sunrise,
        is_ambiguous=is_ambiguous,
        ambiguity_message=ambiguity_message,
        confidence=confidence,
        birth_time_start_local=aware_start_time,
        birth_time_end_local=aware_end_time,
    )

    # --- Annual Birthday Calculations for every candidate Tithi ---
    _start_year = start_year if start_year is not None else (local_today.year - 5)
    _end_year = end_year if end_year is not None else (local_today.year + 10)
    if _end_year < _start_year:
        raise ValueError("end_year must be greater than or equal to start_year.")

    candidate_calendars: List[CandidateBirthdayCalendar] = []
    for cand_tithi, cand_jd in zip(tithis, candidate_jds):
        cand_month = get_lunar_month_info(
            cand_jd, sidereal, lunar_system=lunar_system, ayanamsha_id=ayanamsha_id
        )
        entries = find_birthdays_range(
            birth_tithi_index=cand_tithi.index,
            birth_lunar_month_index=cand_month.month_index,
            birth_paksha=cand_tithi.paksha_en,
            start_year=_start_year,
            end_year=_end_year,
            lat=lat,
            lon=lon,
            timezone_str=timezone_str,
            sidereal=sidereal,
            lunar_system=lunar_system,
            observance_method=observance_method,
            adhika_rule=adhika_rule,
            ayanamsha_id=ayanamsha_id,
        )
        candidate_calendars.append(
            CandidateBirthdayCalendar(
                tithi=cand_tithi,
                lunar_month=cand_month,
                entries=entries,
            )
        )

    primary_entries = candidate_calendars[0].entries if candidate_calendars else []

    return FullResult(
        panchang=panchang,
        birthday_entries=primary_entries,
        start_year=_start_year,
        end_year=_end_year,
        candidate_calendars=candidate_calendars,
        today=local_today,
    )
