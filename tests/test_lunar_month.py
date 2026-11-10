"""
Tests for Hindu lunar month (Amanta, Purnimanta, and Adhika Masa).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone
import pytz
import swisseph as swe

from calculations.astronomy import datetime_to_jd, init_ephemeris, set_ayanamsha
from calculations.lunar_month import get_lunar_month_info

init_ephemeris()
set_ayanamsha(swe.SIDM_LAHIRI)


class TestLunarMonth:
    def test_28may2004_is_jyeshtha(self):
        """28 May 2004 (Shukla Navami) is Jyeshtha (index 2) in both Amanta & Purnimanta."""
        ist = pytz.timezone("Asia/Kolkata")
        jd = datetime_to_jd(ist.localize(datetime(2004, 5, 28, 4, 0, 0)))

        amanta = get_lunar_month_info(jd, sidereal=True, lunar_system="amanta")
        purnimanta = get_lunar_month_info(jd, sidereal=True, lunar_system="purnimanta")

        assert amanta.month_name_en == "Jyeshtha"
        assert amanta.month_index == 2
        assert amanta.is_adhika is False
        assert purnimanta.month_name_en == "Jyeshtha"

    def test_holi_and_after_holi_amanta_vs_purnimanta(self):
        """
        25 Mar 2024: Phalguna Purnima in both Amanta & Purnimanta.
        26 Mar 2024: Phalguna Krishna Pratipada in Amanta, Chaitra Krishna Pratipada in Purnimanta.
        """
        ist = pytz.timezone("Asia/Kolkata")
        holi_jd = datetime_to_jd(ist.localize(datetime(2024, 3, 25, 8, 0, 0)))
        after_holi_jd = datetime_to_jd(ist.localize(datetime(2024, 3, 26, 12, 0, 0)))

        assert get_lunar_month_info(holi_jd, lunar_system="amanta").month_name_en == "Phalguna"
        assert get_lunar_month_info(holi_jd, lunar_system="purnimanta").month_name_en == "Phalguna"

        assert get_lunar_month_info(after_holi_jd, lunar_system="amanta").month_name_en == "Phalguna"
        assert get_lunar_month_info(after_holi_jd, lunar_system="purnimanta").month_name_en == "Chaitra"

    def test_ugadi_2024_is_chaitra(self):
        """9 Apr 2024: Chaitra Shukla Pratipada."""
        jd = datetime_to_jd(datetime(2024, 4, 9, 6, 0, 0, tzinfo=timezone.utc))
        info = get_lunar_month_info(jd, lunar_system="amanta")
        assert info.month_name_en == "Chaitra"
        assert info.month_index == 0

    def test_diwali_2024_amanta_vs_purnimanta(self):
        """1 Nov 2024 (before Amavasya ends): Ashwina in Amanta, Kartika in Purnimanta."""
        ist = pytz.timezone("Asia/Kolkata")
        jd = datetime_to_jd(ist.localize(datetime(2024, 11, 1, 12, 0, 0)))
        assert get_lunar_month_info(jd, lunar_system="amanta").month_name_en == "Ashwina"
        assert get_lunar_month_info(jd, lunar_system="purnimanta").month_name_en == "Kartika"

    def test_adhika_shravana_2023(self):
        """July 18 – August 16, 2023 was Adhika Shravana; late August was Nija Shravana."""
        adhika_jd = datetime_to_jd(datetime(2023, 8, 1, 12, 0, 0, tzinfo=timezone.utc))
        nija_jd = datetime_to_jd(datetime(2023, 8, 25, 12, 0, 0, tzinfo=timezone.utc))

        adhika_info = get_lunar_month_info(adhika_jd, lunar_system="amanta")
        nija_info = get_lunar_month_info(nija_jd, lunar_system="amanta")

        assert adhika_info.month_name_en == "Shravana"
        assert adhika_info.is_adhika is True
        assert nija_info.month_name_en == "Shravana"
        assert nija_info.is_adhika is False

    def test_adhika_ashwina_2020(self):
        """September 18 – October 16, 2020 was Adhika Ashwina."""
        jd = datetime_to_jd(datetime(2020, 10, 1, 12, 0, 0, tzinfo=timezone.utc))
        info = get_lunar_month_info(jd, lunar_system="amanta")
        assert info.month_name_en == "Ashwina"
        assert info.is_adhika is True
