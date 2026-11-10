"""
Dataclass models for calculation requests and validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class CalculationRequest:
    birth_date: date
    birth_time_mode: str = "unknown"          # "exact", "approximate", "unknown"
    birth_time_local: Optional[datetime] = None
    birth_time_start: Optional[datetime] = None
    birth_time_end: Optional[datetime] = None
    lat: float = 0.0
    lon: float = 0.0
    timezone_str: str = "Asia/Kolkata"
    location_name: str = ""
    ayanamsha_key: str = "lahiri"
    lunar_system: str = "amanta"              # "amanta" or "purnimanta"
    observance_method: str = "sunrise"        # "sunrise", "madhyahna", "sunset"
    adhika_rule: str = "nija"                 # "nija", "adhika", "both"
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    language: str = "en"
