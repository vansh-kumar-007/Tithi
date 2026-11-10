"""
Tests for local-date sunrise and sunset calculations across timezones.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date
import pytz
import swisseph as swe

from calculations.astronomy import init_ephemeris, set_ayanamsha
from calculations.sunrise import get_sunrise_sunset_for_local_date

init_ephemeris()
set_ayanamsha(swe.SIDM_LAHIRI)


class TestSunrise:
    def test_bijnor_sunrise_28may2004(self):
        """Sunrise at Bijnor (29.37°N, 78.13°E) on May 28 2004 is ~05:19 IST."""
        sr, ss = get_sunrise_sunset_for_local_date(
            date(2004, 5, 28), 29.37, 78.13, "Asia/Kolkata"
        )
        assert sr is not None and ss is not None
        ist = pytz.timezone("Asia/Kolkata")
        sr_ist = sr.astimezone(ist)
        assert sr_ist.date() == date(2004, 5, 28)
        assert sr_ist.hour == 5 and 12 <= sr_ist.minute <= 25
        assert sr < ss

    def test_kolkata_summer_and_mumbai_winter_correct_local_date(self):
        """
        Regression test: Kolkata in June has sunrise before 00:00 UTC (23:2x UTC prev day),
        and Mumbai in Dec has midnight_utc on prev UTC day. Both must return the exact
        requested local date's sunrise!
        """
        sr_kol, ss_kol = get_sunrise_sunset_for_local_date(
            date(2024, 6, 15), 22.5726, 88.3639, "Asia/Kolkata"
        )
        ist = pytz.timezone("Asia/Kolkata")
        assert sr_kol is not None
        assert sr_kol.astimezone(ist).date() == date(2024, 6, 15)
        assert ss_kol.astimezone(ist).date() == date(2024, 6, 15)

        sr_mum, ss_mum = get_sunrise_sunset_for_local_date(
            date(2024, 12, 15), 19.0760, 72.8777, "Asia/Kolkata"
        )
        assert sr_mum is not None
        assert sr_mum.astimezone(ist).date() == date(2024, 12, 15)
        assert ss_mum.astimezone(ist).date() == date(2024, 12, 15)

    def test_tokyo_sunrise_correct_local_date(self):
        """Tokyo (UTC+9) sunrise is always ~19:30–22:00 UTC of previous UTC date."""
        sr, ss = get_sunrise_sunset_for_local_date(
            date(2024, 6, 21), 35.6762, 139.6503, "Asia/Tokyo"
        )
        jst = pytz.timezone("Asia/Tokyo")
        assert sr is not None and ss is not None
        assert sr.astimezone(jst).date() == date(2024, 6, 21)
        assert sr < ss

    def test_all_reference_cities(self):
        cases = [
            (date(2024, 3, 21), 28.6139, 77.2090, "Asia/Kolkata"),     # Delhi
            (date(2024, 6, 15), 19.0760, 72.8777, "Asia/Kolkata"),     # Mumbai
            (date(2024, 1, 15), 22.5726, 88.3639, "Asia/Kolkata"),     # Kolkata
            (date(2024, 6, 21), 51.5074, -0.1278, "Europe/London"),    # London
            (date(2024, 9, 1), 40.7128, -74.0060, "America/New_York"), # New York
        ]
        for d, lat, lon, tz_str in cases:
            sr, ss = get_sunrise_sunset_for_local_date(d, lat, lon, tz_str)
            tz = pytz.timezone(tz_str)
            assert sr is not None and ss is not None
            assert sr.astimezone(tz).date() == d
            assert sr < ss
