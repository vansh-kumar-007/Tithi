"""
Tests for annual Hindu birthday calculation across years, systems, and edge cases.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
import swisseph as swe

from calculations.astronomy import init_ephemeris, set_ayanamsha
from calculations.birthday_dates import find_birthdays_range, find_hindu_birthday

init_ephemeris()
set_ayanamsha(swe.SIDM_LAHIRI)

BIJNOR_LAT = 29.3724
BIJNOR_LON = 78.1358
BIJNOR_TZ = "Asia/Kolkata"


class TestBirthdayCalculation:
    def test_28may2004_jyeshtha_shukla_navami_stays_in_may_june(self):
        """
        Regression test: A birth on 28 May 2004 (Jyeshtha Shukla Navami) must match
        in May/June every year (including 2024, 2025, 2026) and NEVER return Jan 7.
        """
        entries = find_birthdays_range(
            birth_tithi_index=8,           # Shukla Navami
            birth_lunar_month_index=2,     # Jyeshtha
            birth_paksha="Shukla",
            start_year=2004,
            end_year=2028,
            lat=BIJNOR_LAT,
            lon=BIJNOR_LON,
            timezone_str=BIJNOR_TZ,
        )
        assert len(entries) == 25
        # Birth year 2004 must recover 2004-05-28
        assert entries[0].gregorian_date == date(2004, 5, 28)
        for e in entries:
            if e.gregorian_date is not None:
                assert e.gregorian_date.month in (5, 6), (
                    f"Jyeshtha Shukla Navami in {e.year} landed in wrong month: {e.gregorian_date}"
                )

    def test_birthday_weekday_and_local_times(self):
        entry = find_hindu_birthday(
            birth_tithi_index=0,
            birth_lunar_month_index=0,
            birth_paksha="Shukla",
            target_year=2024,
            lat=BIJNOR_LAT,
            lon=BIJNOR_LON,
            timezone_str=BIJNOR_TZ,
        )
        assert entry.gregorian_date == date(2024, 4, 9)  # Ugadi / Chaitra Shukla Pratipada 2024
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        assert entry.weekday == days[entry.gregorian_date.weekday()]
        assert entry.tithi_start_local is not None
        assert entry.tithi_end_local is not None

    def test_purnimanta_vs_amanta_krishna_paksha(self):
        """
        Janmashtami (Krishna Ashtami, index 22):
          - Shravana Krishna Ashtami in Amanta (month 4)
          - Bhadrapada Krishna Ashtami in Purnimanta (month 5)
        Both must resolve to the same August 26, 2024 date!
        """
        e_amanta = find_hindu_birthday(
            birth_tithi_index=22,
            birth_lunar_month_index=4,
            birth_paksha="Krishna",
            target_year=2024,
            lat=BIJNOR_LAT,
            lon=BIJNOR_LON,
            timezone_str=BIJNOR_TZ,
            lunar_system="amanta",
        )
        e_purnimanta = find_hindu_birthday(
            birth_tithi_index=22,
            birth_lunar_month_index=5,
            birth_paksha="Krishna",
            target_year=2024,
            lat=BIJNOR_LAT,
            lon=BIJNOR_LON,
            timezone_str=BIJNOR_TZ,
            lunar_system="purnimanta",
        )
        assert e_amanta.gregorian_date == date(2024, 8, 26)
        assert e_purnimanta.gregorian_date == date(2024, 8, 26)

    def test_adhika_masa_rules_2023_shravana(self):
        """
        In 2023 there was Adhika Shravana (July–Aug) and Nija Shravana (Aug–Sep).
        Test nija, adhika, and both rules for Shravana Purnima (index 14, month 4).
        """
        nija = find_hindu_birthday(
            14, 4, "Shukla", 2023, BIJNOR_LAT, BIJNOR_LON, BIJNOR_TZ, adhika_rule="nija"
        )
        adhika = find_hindu_birthday(
            14, 4, "Shukla", 2023, BIJNOR_LAT, BIJNOR_LON, BIJNOR_TZ, adhika_rule="adhika"
        )
        both = find_hindu_birthday(
            14, 4, "Shukla", 2023, BIJNOR_LAT, BIJNOR_LON, BIJNOR_TZ, adhika_rule="both"
        )
        # Purnima started 2023-08-30 10:58 IST and ended 2023-08-31 07:05 IST,
        # so at sunrise (Udaya Tithi) it falls on 2023-08-31.
        assert nija.gregorian_date == date(2023, 8, 31)
        assert adhika.gregorian_date == date(2023, 8, 1)  # Adhika Shravana Purnima
        assert len(both.alternate_dates) >= 1

    def test_observance_methods(self):
        for method in ("sunrise", "madhyahna", "sunset"):
            entry = find_hindu_birthday(
                8, 2, "Shukla", 2024, BIJNOR_LAT, BIJNOR_LON, BIJNOR_TZ, observance_method=method
            )
            assert entry.gregorian_date is not None

    def test_leap_year_and_status_values(self):
        valid_statuses = {"Confirmed", "Kshaya", "Vriddhi", "Adhika", "Multiple Dates", "Not Found"}
        entries = find_birthdays_range(
            8, 2, "Shukla", 2019, 2026, BIJNOR_LAT, BIJNOR_LON, BIJNOR_TZ
        )
        for entry in entries:
            assert entry.status in valid_statuses
