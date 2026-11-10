"""
Nakshatra (lunar mansion) calculation.
27 Nakshatras, each spanning 13°20' (= 360/27 degrees) of sidereal Moon longitude.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from calculations.astronomy import get_lunar_longitude

NAKSHATRA_NAMES_EN = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira",
    "Ardra", "Punarvasu", "Pushya", "Ashlesha", "Magha",
    "Purva Phalguni", "Uttara Phalguni", "Hasta", "Chitra", "Swati",
    "Vishakha", "Anuradha", "Jyeshtha", "Mula", "Purva Ashadha",
    "Uttara Ashadha", "Shravana", "Dhanishtha", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

NAKSHATRA_NAMES_HI = [
    "अश्विनी", "भरणी", "कृत्तिका", "रोहिणी", "मृगशिरा",
    "आर्द्रा", "पुनर्वसु", "पुष्य", "आश्लेषा", "मघा",
    "पूर्व फाल्गुनी", "उत्तर फाल्गुनी", "हस्त", "चित्रा", "स्वाती",
    "विशाखा", "अनुराधा", "ज्येष्ठा", "मूल", "पूर्व आषाढ़ा",
    "उत्तर आषाढ़ा", "श्रवण", "धनिष्ठा", "शतभिषा",
    "पूर्व भाद्रपदा", "उत्तर भाद्रपदा", "रेवती",
]

NAKSHATRA_LORDS = [
    "Ketu", "Venus", "Sun", "Moon", "Mars",
    "Rahu", "Jupiter", "Saturn", "Mercury", "Ketu",
    "Venus", "Sun", "Moon", "Mars", "Rahu",
    "Jupiter", "Saturn", "Mercury", "Ketu", "Venus",
    "Sun", "Moon", "Mars", "Rahu", "Jupiter",
    "Saturn", "Mercury",
]

NAKSHATRA_SPAN = 360 / 27  # 13.333... degrees


@dataclass
class NakshatraInfo:
    index: int            # 0–26
    number: int           # 1–27
    name_en: str
    name_hi: str
    lord: str
    pada: int             # 1–4
    moon_longitude: float


def get_nakshatra_at_jd(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> NakshatraInfo:
    """Return the Nakshatra in which the Moon resides at jd."""
    moon_lon = get_lunar_longitude(jd, sidereal, ayanamsha_id=ayanamsha_id)
    idx = int(moon_lon / NAKSHATRA_SPAN) % 27
    # Pada: each Nakshatra is divided into 4 padas of 3°20' each
    position_in_nakshatra = moon_lon - idx * NAKSHATRA_SPAN
    pada = int(position_in_nakshatra / (NAKSHATRA_SPAN / 4)) + 1
    pada = min(pada, 4)

    return NakshatraInfo(
        index=idx,
        number=idx + 1,
        name_en=NAKSHATRA_NAMES_EN[idx],
        name_hi=NAKSHATRA_NAMES_HI[idx],
        lord=NAKSHATRA_LORDS[idx],
        pada=pada,
        moon_longitude=moon_lon,
    )
