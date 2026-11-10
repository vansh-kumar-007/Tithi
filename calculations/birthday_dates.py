"""
Annual Hindu Birthday Date Calculator.

For each requested year, finds the Gregorian date(s) on which the person's
birth Tithi is observed in the matching lunar month and Paksha.

Lunation-first algorithm:
  1. Enumerate the ~13–14 lunations intersecting target_year.
  2. Determine each lunation's Amanta month index and Adhika status accurately.
  3. Select the lunation(s) corresponding to the birth lunar month & Paksha
     under the chosen lunar_system ("amanta" or "purnimanta") and adhika_rule.
  4. Scan only the dates in those matching lunations, evaluating Tithi at the
     selected local observance instant ("sunrise", "madhyahna", or "sunset")
     in the birthplace's IANA timezone.
  5. Detect and explain:
     - Confirmed (single match)
     - Vriddhi Tithi (2 consecutive days in the same Paksha)
     - Kshaya Tithi (skipped at observance instant; reports transition day)
     - Adhika Masa (separate observance rule options)
     - Multiple / Missing occurrences in a Gregorian year due to lunar-solar drift
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import pytz

from calculations.astronomy import datetime_to_jd, get_elongation, jd_to_datetime_utc
from calculations.lunar_month import (
    LUNAR_MONTH_NAMES_EN,
    find_new_moon_before,
    find_next_new_moon,
    get_amanta_lunation_info,
)
from calculations.sunrise import get_observance_jd_for_local_date
from calculations.tithi import (
    TITHI_NAMES_EN,
    TITHI_NAMES_HI,
    elongation_to_tithi_index,
    get_full_tithi_info,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS_HI = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]

OBSERVANCE_LABELS = {
    "sunrise": "Sunrise (Udaya Tithi)",
    "madhyahna": "Midday (Madhyahna)",
    "sunset": "Sunset (Sayahna)",
}


@dataclass
class BirthdayEntry:
    year: int
    gregorian_date: Optional[date]
    weekday: Optional[str]
    tithi_name_en: str
    tithi_name_hi: str
    tithi_start_utc: Optional[datetime]
    tithi_end_utc: Optional[datetime]
    tithi_start_local: Optional[datetime] = None
    tithi_end_local: Optional[datetime] = None
    weekday_hi: Optional[str] = None
    lunar_month_en: str = ""
    lunar_month_hi: str = ""
    is_adhika: bool = False
    status: str = "Confirmed"  # "Confirmed", "Kshaya", "Vriddhi", "Adhika", "Multiple Dates", "Not Found"
    notes: str = ""
    alternate_dates: List[date] = field(default_factory=list)


def _localize(dt_utc: Optional[datetime], tz) -> Optional[datetime]:
    if dt_utc is None:
        return None
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=pytz.utc)
    return dt_utc.astimezone(tz)


def _expected_amanta_month_for_search(
    birth_lunar_month_index: int,
    birth_tithi_index: int,
    lunar_system: str,
    is_adhika_lunation: bool,
) -> int:
    """
    Convert a user's birth lunar month index (in Amanta or Purnimanta) to the
    Amanta lunation index that contains the birth Tithi.

    In Purnimanta:
      - Shukla Paksha (tithi 0..14): Amanta month == Purnimanta month.
      - Krishna Paksha (tithi 15..29, non-Adhika): Purnimanta month M corresponds
        to Amanta month (M - 1) % 12.
      - Adhika Masa: Amanta and Purnimanta share the same lunation name.
    """
    is_krishna = birth_tithi_index >= 15
    if lunar_system == "purnimanta" and is_krishna and not is_adhika_lunation:
        return (birth_lunar_month_index - 1) % 12
    return birth_lunar_month_index


def _enumerate_lunations_for_year(
    target_year: int,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> List[Tuple[float, float, int, bool]]:
    """
    Return all Amanta lunations overlapping Gregorian target_year:
      [(nm_start_jd, nm_end_jd, amanta_month_index, is_adhika), ...]
    """
    # Start just before Jan 1 and walk forward until after Dec 31
    jd_jan1 = datetime_to_jd(datetime(target_year, 1, 1, 0, 0, 0, tzinfo=pytz.utc))
    jd_dec31 = datetime_to_jd(datetime(target_year, 12, 31, 23, 59, 59, tzinfo=pytz.utc))

    nm_start = find_new_moon_before(jd_jan1, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
    lunations: List[Tuple[float, float, int, bool]] = []

    while nm_start <= jd_dec31 + 2.0:
        nm_end = find_next_new_moon(nm_start, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
        if nm_end >= jd_jan1 - 2.0:
            amanta_idx, is_adhika, _ = get_amanta_lunation_info(
                nm_start, nm_end, sidereal=sidereal, ayanamsha_id=ayanamsha_id
            )
            lunations.append((nm_start, nm_end, amanta_idx, is_adhika))
        nm_start = nm_end

    return lunations


def _scan_lunation_for_tithi(
    nm_start_jd: float,
    nm_end_jd: float,
    birth_tithi_index: int,
    target_year: int,
    lat: float,
    lon: float,
    timezone_str: str,
    observance_method: str,
    sidereal: bool,
    ayanamsha_id: Optional[int],
) -> Tuple[List[Tuple[date, float]], Optional[Tuple[date, float]]]:
    """
    Scan the dates inside a single lunation [nm_start_jd, nm_end_jd] within target_year.
    Returns:
      (matching_days: [(date, obs_jd), ...],
       kshaya_candidate: (adjacent_date, obs_jd) or None)
    """
    tz = pytz.timezone(timezone_str)
    start_local_date = jd_to_datetime_utc(nm_start_jd).astimezone(tz).date() - timedelta(days=1)
    end_local_date = jd_to_datetime_utc(nm_end_jd).astimezone(tz).date() + timedelta(days=1)

    # Narrow to the half-lunation (Shukla or Krishna) for speed
    if birth_tithi_index < 15:
        scan_end = min(end_local_date, start_local_date + timedelta(days=19))
        scan_start = start_local_date
    else:
        scan_start = max(start_local_date, start_local_date + timedelta(days=12))
        scan_end = end_local_date

    # Clamp to target_year
    scan_start = max(scan_start, date(target_year, 1, 1))
    scan_end = min(scan_end, date(target_year, 12, 31))

    matches: List[Tuple[date, float]] = []
    day_tithis: List[Tuple[date, int, float]] = []

    current = scan_start
    while current <= scan_end:
        obs_jd = get_observance_jd_for_local_date(
            current, lat, lon, timezone_str, method=observance_method
        )
        if obs_jd is not None:
            # Ensure the observance instant actually belongs to this lunation
            if nm_start_jd - 0.1 <= obs_jd <= nm_end_jd + 0.1:
                elong = get_elongation(obs_jd, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
                t_idx = elongation_to_tithi_index(elong)
                day_tithis.append((current, t_idx, obs_jd))
                if t_idx == birth_tithi_index:
                    matches.append((current, obs_jd))
        current += timedelta(days=1)

    kshaya_candidate: Optional[Tuple[date, float]] = None
    if not matches and len(day_tithis) >= 2:
        # Check if birth_tithi_index was skipped between two consecutive days inside this lunation
        for i in range(len(day_tithis) - 1):
            d1, t1, jd1 = day_tithis[i]
            d2, t2, jd2 = day_tithis[i + 1]
            # Handle forward wrap 29 -> 0 -> 1
            step_forward = (t2 - t1) % 30
            dist_to_target = (birth_tithi_index - t1) % 30
            if 0 < dist_to_target < step_forward:
                # Skipped between d1 and d2! Traditional observance often takes d1 (or d2)
                kshaya_candidate = (d1, jd1)
                break

    return matches, kshaya_candidate


def find_hindu_birthday(
    birth_tithi_index: int,         # 0–29
    birth_lunar_month_index: int,   # 0–11 (Chaitra=0)
    birth_paksha: str,              # "Shukla" or "Krishna"
    target_year: int,
    lat: float,
    lon: float,
    timezone_str: str = "Asia/Kolkata",
    sidereal: bool = True,
    match_month: bool = True,
    lunar_system: str = "amanta",
    observance_method: str = "sunrise",
    adhika_rule: str = "nija",      # "nija", "adhika", "both"
    ayanamsha_id: Optional[int] = None,
) -> BirthdayEntry:
    """
    Find the Hindu birthday in target_year for the given birth Tithi & lunar month.
    """
    tz = pytz.timezone(timezone_str)
    tithi_en = TITHI_NAMES_EN[birth_tithi_index]
    tithi_hi = TITHI_NAMES_HI[birth_tithi_index]
    month_name_en = LUNAR_MONTH_NAMES_EN[birth_lunar_month_index]

    lunations = _enumerate_lunations_for_year(
        target_year, sidereal=sidereal, ayanamsha_id=ayanamsha_id
    )

    nija_matches: List[Tuple[date, float, bool]] = []
    adhika_matches: List[Tuple[date, float, bool]] = []
    kshaya_info: Optional[Tuple[date, float]] = None

    for nm_start, nm_end, amanta_idx, is_adhika in lunations:
        expected_amanta = _expected_amanta_month_for_search(
            birth_lunar_month_index, birth_tithi_index, lunar_system, is_adhika
        )
        if match_month and amanta_idx != expected_amanta:
            continue

        matches, kshaya_cand = _scan_lunation_for_tithi(
            nm_start, nm_end, birth_tithi_index, target_year,
            lat, lon, timezone_str, observance_method, sidereal, ayanamsha_id,
        )
        if is_adhika:
            for d, ojd in matches:
                adhika_matches.append((d, ojd, True))
        else:
            for d, ojd in matches:
                nija_matches.append((d, ojd, False))
            if not matches and kshaya_cand and kshaya_info is None:
                kshaya_info = kshaya_cand

    # Apply Adhika Masa observance preference
    selected_matches: List[Tuple[date, float, bool]] = []
    adhika_note = ""

    if adhika_rule == "adhika" and adhika_matches:
        selected_matches = adhika_matches
        adhika_note = f"Observed in Adhika {month_name_en} per selected rule. "
    elif adhika_rule == "both" and (adhika_matches or nija_matches):
        selected_matches = nija_matches + adhika_matches
        if adhika_matches and nija_matches:
            adhika_note = f"Adhika {month_name_en} also occurs in {target_year}; both regular and Adhika dates listed. "
    else:
        # Default "nija": observe in regular month; warn if Adhika also occurred
        selected_matches = nija_matches
        if adhika_matches and nija_matches:
            adhika_note = (
                f"Note: Adhika {month_name_en} also occurs in {target_year} "
                f"({', '.join(d.isoformat() for d, _, _ in adhika_matches)}); "
                "regular (Nija) month date shown. "
            )
        elif adhika_matches and not nija_matches:
            # e.g., regular month fell across year boundary, only Adhika landed in target_year
            selected_matches = adhika_matches
            adhika_note = f"Only Adhika {month_name_en} falls inside {target_year}. "

    # Deduplicate & sort chronologically
    selected_matches.sort(key=lambda item: item[0])

    if not selected_matches:
        if kshaya_info is not None:
            adj_date, adj_obs_jd = kshaya_info
            # Find the actual Tithi window (start/end) around adj_obs_jd + 0.5 day
            # Probe slightly after adj_obs_jd for the skipped Tithi itself
            tithi_full = get_full_tithi_info(adj_obs_jd + 0.35, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
            if tithi_full.index != birth_tithi_index:
                tithi_full = get_full_tithi_info(adj_obs_jd + 0.65, sidereal=sidereal, ayanamsha_id=ayanamsha_id)
            s_utc = tithi_full.start_utc if tithi_full.index == birth_tithi_index else None
            e_utc = tithi_full.end_utc if tithi_full.index == birth_tithi_index else None

            return BirthdayEntry(
                year=target_year,
                gregorian_date=adj_date,
                weekday=WEEKDAYS[adj_date.weekday()],
                weekday_hi=WEEKDAYS_HI[adj_date.weekday()],
                tithi_name_en=tithi_en,
                tithi_name_hi=tithi_hi,
                tithi_start_utc=s_utc,
                tithi_end_utc=e_utc,
                tithi_start_local=_localize(s_utc, tz),
                tithi_end_local=_localize(e_utc, tz),
                lunar_month_en=month_name_en,
                status="Kshaya",
                notes=(
                    f"Kshaya (skipped) Tithi: {birth_paksha} {tithi_en} started and ended between two "
                    f"consecutive {observance_method} moments in {month_name_en} {target_year}. "
                    f"Nearest preceding day ({adj_date.isoformat()}) is shown; adjacent day "
                    f"({(adj_date + timedelta(days=1)).isoformat()}) may also be observed depending on tradition."
                ),
                alternate_dates=[adj_date + timedelta(days=1)],
            )

        return BirthdayEntry(
            year=target_year,
            gregorian_date=None,
            weekday=None,
            tithi_name_en=tithi_en,
            tithi_name_hi=tithi_hi,
            tithi_start_utc=None,
            tithi_end_utc=None,
            lunar_month_en=month_name_en,
            status="Not Found",
            notes=(
                f"{month_name_en} {birth_paksha} {tithi_en} falls outside Gregorian calendar year {target_year} "
                "(occurs in late December of the prior year or early January of the next year due to lunar-solar drift)."
            ),
        )

    primary_date, primary_obs_jd, primary_is_adhika = selected_matches[0]
    tithi_full = get_full_tithi_info(primary_obs_jd, sidereal=sidereal, ayanamsha_id=ayanamsha_id)

    if len(selected_matches) == 1:
        status = "Adhika" if primary_is_adhika else "Confirmed"
        notes = adhika_note.strip()
        alt_dates: List[date] = []
    else:
        alt_dates = [d for d, _, _ in selected_matches[1:]]
        # Check whether the 2 dates are consecutive days (true Vriddhi) vs separate months
        is_consecutive = (len(selected_matches) == 2 and (alt_dates[0] - primary_date).days <= 2)
        if is_consecutive:
            status = "Vriddhi"
            notes = (
                adhika_note
                + f"Vriddhi (repeated) Tithi: prevails across two consecutive days in {month_name_en}. "
                "First day shown; second valid date listed as alternate."
            )
        else:
            status = "Multiple Dates"
            notes = (
                adhika_note
                + f"Multiple occurrences ({len(selected_matches)}) in {target_year} (e.g., lunar drift or Adhika Masa). "
                "First date shown; alternate dates listed."
            )

    return BirthdayEntry(
        year=target_year,
        gregorian_date=primary_date,
        weekday=WEEKDAYS[primary_date.weekday()],
        weekday_hi=WEEKDAYS_HI[primary_date.weekday()],
        tithi_name_en=tithi_en,
        tithi_name_hi=tithi_hi,
        tithi_start_utc=tithi_full.start_utc,
        tithi_end_utc=tithi_full.end_utc,
        tithi_start_local=_localize(tithi_full.start_utc, tz),
        tithi_end_local=_localize(tithi_full.end_utc, tz),
        lunar_month_en=month_name_en,
        is_adhika=primary_is_adhika,
        status=status,
        notes=notes,
        alternate_dates=alt_dates,
    )


def find_birthdays_range(
    birth_tithi_index: int,
    birth_lunar_month_index: int,
    birth_paksha: str,
    start_year: int,
    end_year: int,
    lat: float,
    lon: float,
    timezone_str: str = "Asia/Kolkata",
    sidereal: bool = True,
    match_month: bool = True,
    lunar_system: str = "amanta",
    observance_method: str = "sunrise",
    adhika_rule: str = "nija",
    ayanamsha_id: Optional[int] = None,
) -> List[BirthdayEntry]:
    """Find Hindu birthdays for all years in [start_year, end_year]."""
    results: List[BirthdayEntry] = []
    for year in range(start_year, end_year + 1):
        entry = find_hindu_birthday(
            birth_tithi_index=birth_tithi_index,
            birth_lunar_month_index=birth_lunar_month_index,
            birth_paksha=birth_paksha,
            target_year=year,
            lat=lat,
            lon=lon,
            timezone_str=timezone_str,
            sidereal=sidereal,
            match_month=match_month,
            lunar_system=lunar_system,
            observance_method=observance_method,
            adhika_rule=adhika_rule,
            ayanamsha_id=ayanamsha_id,
        )
        results.append(entry)
    return results
