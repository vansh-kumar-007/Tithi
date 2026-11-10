"""
Tests for Tithi calculations and transitions.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone
import pytz
import swisseph as swe

from calculations.astronomy import (
    datetime_to_jd,
    get_elongation,
    init_ephemeris,
    jd_to_datetime_utc,
    set_ayanamsha,
)
from calculations.tithi import (
    PAKSHA_KRISHNA,
    PAKSHA_SHUKLA,
    TITHI_NAMES_EN,
    elongation_to_tithi_index,
    get_full_tithi_info,
    get_tithi_at_jd,
)

init_ephemeris()
set_ayanamsha(swe.SIDM_LAHIRI)


class TestTithiCalculation:
    def test_elongation_at_full_moon(self):
        """At Oct 17, 2024 full moon (~11:26 UTC), elongation is near 180°."""
        full_moon_dt = datetime(2024, 10, 17, 11, 26, tzinfo=timezone.utc)
        jd = datetime_to_jd(full_moon_dt)
        elong = get_elongation(jd, sidereal=True)
        assert 179.0 < elong < 181.0

    def test_purnima_tithi_at_full_moon(self):
        """Just before exact full moon peak, Tithi is Purnima (index 14)."""
        full_moon_dt = datetime(2024, 10, 17, 11, 0, tzinfo=timezone.utc)
        jd = datetime_to_jd(full_moon_dt)
        tithi = get_tithi_at_jd(jd, sidereal=True)
        assert tithi.index == 14
        assert tithi.name_en == "Purnima"
        assert tithi.paksha_en == PAKSHA_SHUKLA

    def test_amavasya_tithi_at_new_moon(self):
        """Just before Oct 2, 2024 new moon (~18:49 UTC), Tithi is Amavasya (index 29)."""
        new_moon_dt = datetime(2024, 10, 2, 18, 0, tzinfo=timezone.utc)
        jd = datetime_to_jd(new_moon_dt)
        tithi = get_tithi_at_jd(jd, sidereal=True)
        assert tithi.index == 29
        assert tithi.name_en == "Amavasya"
        assert tithi.paksha_en == PAKSHA_KRISHNA

    def test_tithi_index_mapping(self):
        assert elongation_to_tithi_index(0.0) == 0
        assert elongation_to_tithi_index(12.0) == 1
        assert elongation_to_tithi_index(180.0) == 15
        assert elongation_to_tithi_index(348.0) == 29
        assert elongation_to_tithi_index(359.9) == 29

    def test_tithi_names_length(self):
        assert len(TITHI_NAMES_EN) == 30

    def test_full_tithi_info_has_accurate_start_end(self):
        dt = datetime(2024, 5, 23, 10, 0, tzinfo=timezone.utc)
        jd = datetime_to_jd(dt)
        tithi = get_full_tithi_info(jd, sidereal=True)
        assert tithi.start_jd is not None and tithi.end_jd is not None
        assert tithi.start_jd < jd < tithi.end_jd
        duration_hours = (tithi.end_jd - tithi.start_jd) * 24.0
        assert 19.0 <= duration_hours <= 27.5

    def test_known_tithi_bijnor_28may2004_0400_ist(self):
        """
        Reference: 28 May 2004, 04:00 AM IST, Bijnor, UP, India.
        Exact Tithi at 04:00 IST (22:30 UTC May 27) is Jyeshtha Shukla Navami (index 8).
        """
        ist = pytz.timezone("Asia/Kolkata")
        birth_dt = ist.localize(datetime(2004, 5, 28, 4, 0, 0))
        jd = datetime_to_jd(birth_dt)
        tithi = get_full_tithi_info(jd, sidereal=True)
        assert tithi.paksha_en == PAKSHA_SHUKLA
        assert tithi.index == 8
        assert tithi.name_en == "Navami"
        assert tithi.start_utc < birth_dt.astimezone(timezone.utc) < tithi.end_utc

    def test_shukla_and_krishna_ranges(self):
        for i in range(15):
            assert elongation_to_tithi_index(i * 12 + 6) == i
        for i in range(15, 30):
            assert elongation_to_tithi_index(i * 12 + 6) == i


class TestJulianDayConversions:
    def test_round_trip(self):
        dt = datetime(2004, 5, 28, 10, 30, 0, tzinfo=timezone.utc)
        jd = datetime_to_jd(dt)
        dt2 = jd_to_datetime_utc(jd)
        assert abs((dt - dt2).total_seconds()) < 1.5
