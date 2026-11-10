"""
Yoga calculation.
27 Yogas: each spans 13°20' of (Sun + Moon) combined longitude.
"""
from __future__ import annotations

from typing import Optional
from dataclasses import dataclass
from calculations.astronomy import get_solar_longitude, get_lunar_longitude

YOGA_NAMES_EN = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana",
    "Atiganda", "Sukarma", "Dhriti", "Shula", "Ganda",
    "Vriddhi", "Dhruva", "Vyaghata", "Harshana", "Vajra",
    "Siddhi", "Vyatipata", "Variyan", "Parigha", "Shiva",
    "Siddha", "Sadhya", "Shubha", "Shukla", "Brahma",
    "Indra", "Vaidhriti",
]

YOGA_NAMES_HI = [
    "विष्कम्भ", "प्रीति", "आयुष्मान", "सौभाग्य", "शोभन",
    "अतिगण्ड", "सुकर्मा", "धृति", "शूल", "गण्ड",
    "वृद्धि", "ध्रुव", "व्याघात", "हर्षण", "वज्र",
    "सिद्धि", "व्यतीपात", "वरीयान", "परिघ", "शिव",
    "सिद्ध", "साध्य", "शुभ", "शुक्ल", "ब्रह्म",
    "इन्द्र", "वैधृति",
]

YOGA_SPAN = 360 / 27  # 13.333... degrees


@dataclass
class YogaInfo:
    index: int
    number: int
    name_en: str
    name_hi: str
    combined_longitude: float


def get_yoga_at_jd(
    jd: float,
    sidereal: bool = True,
    ayanamsha_id: Optional[int] = None,
) -> YogaInfo:
    """Return the Yoga prevailing at jd."""
    sun_lon = get_solar_longitude(jd, sidereal, ayanamsha_id=ayanamsha_id)
    moon_lon = get_lunar_longitude(jd, sidereal, ayanamsha_id=ayanamsha_id)
    combined = (sun_lon + moon_lon) % 360
    idx = int(combined / YOGA_SPAN) % 27
    return YogaInfo(
        index=idx,
        number=idx + 1,
        name_en=YOGA_NAMES_EN[idx],
        name_hi=YOGA_NAMES_HI[idx],
        combined_longitude=combined,
    )
