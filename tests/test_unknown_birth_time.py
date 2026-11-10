"""
Tests for unknown, approximate, and exact birth-time handling + multi-candidate calendars.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, datetime
import pytest
import pytz
import swisseph as swe

from calculations.astronomy import datetime_to_jd, init_ephemeris, set_ayanamsha
from calculations.karana import get_karana_at_jd
from calculations.nakshatra import get_nakshatra_at_jd
from calculations.tithi import get_tithi_transitions_in_interval
from calculations.yoga import get_yoga_at_jd
from services.panchang_service import calculate_panchang

init_ephemeris()
set_ayanamsha(swe.SIDM_LAHIRI)


class TestBirthTimeModes:
    def test_unknown_mode_28may2004_produces_both_candidate_calendars(self):
        """
        On 28 May 2004 (Bijnor), Ashtami transitioned to Navami at ~01:36 IST.
        Unknown birth time must detect both Tithis and produce 2 candidate birthday calendars.
        """
        result = calculate_panchang(
            birth_date=date(2004, 5, 28),
            birth_time_local=None,
            birth_time_mode="unknown",
            lat=29.3724,
            lon=78.1358,
            timezone_str="Asia/Kolkata",
            location_name="Bijnor, Uttar Pradesh, India",
            start_year=2024,
            end_year=2026,
        )
        names = [t.name_en for t in result.panchang.tithis]
        assert names == ["Ashtami", "Navami"]
        assert result.panchang.is_ambiguous is True
        assert len(result.candidate_calendars) == 2
        assert result.candidate_calendars[0].tithi.name_en == "Ashtami"
        assert result.candidate_calendars[1].tithi.name_en == "Navami"
        assert len(result.candidate_calendars[1].entries) == 3

    def test_exact_mode_requires_time(self):
        with pytest.raises(ValueError):
            calculate_panchang(
                birth_date=date(2004, 5, 28),
                birth_time_local=None,
                birth_time_mode="exact",
                lat=29.37,
                lon=78.13,
                timezone_str="Asia/Kolkata",
                location_name="Bijnor",
            )

    def test_approximate_mode_validates_window(self):
        with pytest.raises(ValueError):
            calculate_panchang(
                birth_date=date(2004, 5, 28),
                birth_time_local=None,
                birth_time_mode="approximate",
                lat=29.37,
                lon=78.13,
                timezone_str="Asia/Kolkata",
                location_name="Bijnor",
                birth_time_start=datetime(2004, 5, 28, 8, 0),
                birth_time_end=datetime(2004, 5, 28, 6, 0),
            )

    def test_exact_mode_returns_single_tithi_and_aware_time(self):
        result = calculate_panchang(
            birth_date=date(2004, 5, 28),
            birth_time_local=datetime(2004, 5, 28, 4, 0, 0),
            birth_time_mode="exact",
            lat=29.3724,
            lon=78.1358,
            timezone_str="Asia/Kolkata",
            location_name="Bijnor, Uttar Pradesh, India",
            start_year=2024,
            end_year=2026,
        )
        assert len(result.panchang.tithis) == 1
        assert result.panchang.tithis[0].name_en == "Navami"
        assert result.panchang.lunar_month.month_name_en == "Jyeshtha"
        assert result.panchang.birth_time_local.tzinfo is not None
        assert result.panchang.confidence == "High"

    def test_approximate_mode_narrow_window_single_tithi(self):
        result = calculate_panchang(
            birth_date=date(2004, 5, 28),
            birth_time_local=None,
            birth_time_mode="approximate",
            lat=29.3724,
            lon=78.1358,
            timezone_str="Asia/Kolkata",
            location_name="Bijnor",
            start_year=2024,
            end_year=2025,
            birth_time_start=datetime(2004, 5, 28, 4, 0),
            birth_time_end=datetime(2004, 5, 28, 6, 0),
        )
        assert len(result.panchang.tithis) == 1
        assert result.panchang.tithis[0].name_en == "Navami"


class TestNakshatraYogaKarana:
    def test_ranges(self):
        tz = pytz.timezone("UTC")
        jd = datetime_to_jd(tz.localize(datetime(2004, 5, 28, 4, 0)))
        n = get_nakshatra_at_jd(jd)
        y = get_yoga_at_jd(jd)
        k = get_karana_at_jd(jd)
        assert 0 <= n.index <= 26 and 1 <= n.pada <= 4
        assert 0 <= y.index <= 26
        assert 0 <= k.index <= 59
        transitions = get_tithi_transitions_in_interval(jd, jd + 1.0)
        assert len(transitions) <= 2
