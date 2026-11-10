"""
Tithi calculation module.

Tithi = floor(elongation / 12) + 1  (1–30)

Tithi 1–15  : Shukla Paksha (Waxing Moon)
Tithi 16–30 : Krishna Paksha (Waning Moon)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from calculations.astronomy import (
    get_elongation,
    jd_to_datetime_utc,
)

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

TITHI_NAMES_EN = [
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Purnima",
    # Krishna Paksha (index 15–29)
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya",
]

TITHI_NAMES_HI = [
    "प्रतिपदा", "द्वितीया", "तृतीया", "चतुर्थी", "पञ्चमी",
    "षष्ठी", "सप्तमी", "अष्टमी", "नवमी", "दशमी",
    "एकादशी", "द्वादशी", "त्रयोदशी", "चतुर्दशी", "पूर्णिमा",
    "प्रतिपदा", "द्वितीया", "तृतीया", "चतुर्थी", "पञ्चमी",
    "षष्ठी", "सप्तमी", "अष्टमी", "नवमी", "दशमी",
    "एकादशी", "द्वादशी", "त्रयोदशी", "चतुर्दशी", "अमावस्या",
]

PAKSHA_SHUKLA = "Shukla"
PAKSHA_KRISHNA = "Krishna"
PAKSHA_SHUKLA_HI = "शुक्ल पक्ष"
PAKSHA_KRISHNA_HI = "कृष्ण पक्ष"

_TRANSITION_TOLERANCE_DAYS = 1.0 / 86400.0  # ~1 second precision


@dataclass
class TithiInfo:
    index: int            # 0–29
    number: int           # 1–30
    name_en: str
    name_hi: str
    paksha_en: str
    paksha_hi: str
    elongation: float     # degrees at calculation time
    start_jd: Optional[float] = None
    end_jd: Optional[float] = None
    start_utc: Optional[datetime] = None
    end_utc: Optional[datetime] = None

    @property
    def paksha_number(self) -> int:
        """1 = Shukla, 2 = Krishna"""
        return 1 if self.index < 15 else 2

    @property
    def tithi_in_paksha(self) -> int:
        """Tithi number within its Paksha (1–15)."""
        return self.index % 15 + 1


def elongation_to_tithi_index(elongation: float) -> int:
    """Return 0-based Tithi index (0–29) from elongation in degrees."""
    return int((elongation % 360.0) / 12.0) % 30


def get_tithi_at_jd(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> TithiInfo:
    """Calculate the Tithi prevailing at a given Julian Day."""
    elong = get_elongation(jd, sidereal, ayanamsha_id=ayanamsha_id)
    idx = elongation_to_tithi_index(elong)
    paksha = PAKSHA_SHUKLA if idx < 15 else PAKSHA_KRISHNA
    paksha_hi = PAKSHA_SHUKLA_HI if idx < 15 else PAKSHA_KRISHNA_HI
    return TithiInfo(
        index=idx,
        number=idx + 1,
        name_en=TITHI_NAMES_EN[idx],
        name_hi=TITHI_NAMES_HI[idx],
        paksha_en=paksha,
        paksha_hi=paksha_hi,
        elongation=elong,
    )


# ---------------------------------------------------------------------------
# Transition finding via binary search
# ---------------------------------------------------------------------------

def find_tithi_transition(
    jd_start: float,
    jd_end: float,
    target_elongation: float,
    sidereal: bool = True,
    tolerance_days: float = _TRANSITION_TOLERANCE_DAYS,
    ayanamsha_id: Optional[int] = None,
) -> Optional[float]:
    """
    Binary search for the JD in [jd_start, jd_end] at which elongation crosses
    target_elongation (a multiple of 12°).
    Returns JD of the crossing or None if no crossing exists in the interval.
    """
    target_mod = target_elongation % 360.0

    def is_at_or_after_target(jd: float) -> bool:
        e = get_elongation(jd, sidereal, ayanamsha_id=ayanamsha_id)
        diff = (e - target_mod) % 360.0
        return diff < 180.0

    start_after = is_at_or_after_target(jd_start)
    end_after = is_at_or_after_target(jd_end)

    # Crossing forward occurs when start is strictly before (< 0 mod 360) and end is at/after
    if start_after or not end_after:
        return None

    lo, hi = jd_start, jd_end
    while (hi - lo) > tolerance_days:
        mid = (lo + hi) / 2.0
        if is_at_or_after_target(mid):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def get_tithi_transitions_in_interval(
    jd_start: float,
    jd_end: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> List[Tuple[float, int]]:
    """
    Find all Tithi transition JDs within [jd_start, jd_end].
    Returns list of (jd_of_transition, new_tithi_index_0based).

    Uses 4-hour steps (much shorter than the ~19h minimum Tithi duration)
    and binary searches each changing bracket to ~1 second precision.
    """
    if jd_end <= jd_start:
        return []

    transitions: List[Tuple[float, int]] = []
    step = 4.0 / 24.0  # 4 hours
    jd = jd_start
    prev_idx = elongation_to_tithi_index(
        get_elongation(jd, sidereal, ayanamsha_id=ayanamsha_id)
    )

    while jd < jd_end:
        jd_next = min(jd + step, jd_end)
        curr_idx = elongation_to_tithi_index(
            get_elongation(jd_next, sidereal, ayanamsha_id=ayanamsha_id)
        )

        if curr_idx != prev_idx:
            # Target elongation is the boundary entering curr_idx (prev_idx + 1)
            next_expected_idx = (prev_idx + 1) % 30
            target_deg = (next_expected_idx * 12.0) % 360.0
            tr_jd = find_tithi_transition(
                jd, jd_next, target_deg,
                sidereal=sidereal,
                ayanamsha_id=ayanamsha_id,
            )
            if tr_jd is None:
                # Fallback direct index bisection
                lo, hi = jd, jd_next
                while (hi - lo) > _TRANSITION_TOLERANCE_DAYS:
                    mid = (lo + hi) / 2.0
                    mid_idx = elongation_to_tithi_index(
                        get_elongation(mid, sidereal, ayanamsha_id=ayanamsha_id)
                    )
                    if mid_idx == prev_idx:
                        lo = mid
                    else:
                        hi = mid
                tr_jd = (lo + hi) / 2.0

            transitions.append((tr_jd, next_expected_idx))
            prev_idx = curr_idx

        jd = jd_next

    return transitions


def get_full_tithi_info(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> TithiInfo:
    """
    Get TithiInfo at jd, including exact start and end times of that Tithi.
    """
    tithi = get_tithi_at_jd(jd, sidereal, ayanamsha_id=ayanamsha_id)
    idx = tithi.index
    target_start = (idx * 12.0) % 360.0
    target_end = ((idx + 1) * 12.0) % 360.0

    # Max Tithi duration is ~27 hours (~1.13 days); step backward up to 1.5 days
    start_jd: Optional[float] = None
    step = 0.25  # 6 hours
    probe = jd
    for _ in range(7):
        prev_probe = probe - step
        tr = find_tithi_transition(
            prev_probe, probe, target_start,
            sidereal=sidereal, ayanamsha_id=ayanamsha_id,
        )
        if tr is not None:
            start_jd = tr
            break
        probe = prev_probe

    # Step forward up to 1.5 days to find end crossing
    end_jd: Optional[float] = None
    probe = jd
    for _ in range(7):
        next_probe = probe + step
        tr = find_tithi_transition(
            probe, next_probe, target_end,
            sidereal=sidereal, ayanamsha_id=ayanamsha_id,
        )
        if tr is not None:
            end_jd = tr
            break
        probe = next_probe

    # Fallback approximation if extreme edge
    if start_jd is None:
        progress = (tithi.elongation - target_start) % 360.0
        start_jd = jd - progress / 12.2
    if end_jd is None:
        remaining = (target_end - tithi.elongation) % 360.0
        end_jd = jd + remaining / 12.2

    tithi.start_jd = start_jd
    tithi.end_jd = end_jd
    tithi.start_utc = jd_to_datetime_utc(start_jd)
    tithi.end_utc = jd_to_datetime_utc(end_jd)
    return tithi
