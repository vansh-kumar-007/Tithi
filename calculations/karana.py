"""
Karana calculation.
A Karana = half a Tithi (6° of elongation).
There are 11 Karanas: 4 fixed + 7 repeating (×8 cycles).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from calculations.astronomy import get_elongation

# Fixed Karanas (appear once each per lunar month)
FIXED_KARANAS = ["Kimstughna", "Shakuni", "Chatushpada", "Naga"]
FIXED_KARANAS_HI = ["किंस्तुघ्न", "शकुनि", "चतुष्पद", "नाग"]

# Repeating Karanas (each appears 8 times per lunar month)
REPEATING_KARANAS = [
    "Bava", "Balava", "Kaulava", "Taitila", "Garaja", "Vanija", "Vishti"
]
REPEATING_KARANAS_HI = [
    "बव", "बालव", "कौलव", "तैतिल", "गर", "वणिज", "विष्टि"
]


@dataclass
class KaranaInfo:
    index: int          # 0-based position in the lunar month (0–59)
    name_en: str
    name_hi: str
    is_fixed: bool
    elongation: float


def get_karana_at_jd(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> KaranaInfo:
    """
    Return the Karana prevailing at jd.

    Karana sequence in a lunar month (60 Karanas total):
    0: Kimstughna (fixed, first half of Shukla Pratipada)
    1–56: Repeating Karanas (7 × 8 cycles)
    57: Shakuni (fixed)
    58: Chatushpada (fixed)
    59: Naga (fixed)
    """
    elong = get_elongation(jd, sidereal, ayanamsha_id=ayanamsha_id)
    # 60 half-tithis per lunar month, each spans 6°
    karana_pos = int(elong / 6) % 60  # 0–59

    if karana_pos == 0:
        return KaranaInfo(karana_pos, FIXED_KARANAS[0], FIXED_KARANAS_HI[0], True, elong)
    elif karana_pos >= 57:
        fixed_idx = karana_pos - 57 + 1  # 1, 2, 3
        return KaranaInfo(karana_pos, FIXED_KARANAS[fixed_idx], FIXED_KARANAS_HI[fixed_idx], True, elong)
    else:
        # Repeating: positions 1–56
        rep_idx = (karana_pos - 1) % 7
        return KaranaInfo(
            karana_pos,
            REPEATING_KARANAS[rep_idx],
            REPEATING_KARANAS_HI[rep_idx],
            False,
            elong,
        )
