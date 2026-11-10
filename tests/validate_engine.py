"""Quick validation script for the calculation engine."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, datetime
from app import create_app
from services.panchang_service import calculate_panchang

app = create_app()
with app.app_context():
    result = calculate_panchang(
        birth_date=date(2004, 5, 28),
        birth_time_local=datetime(2004, 5, 28, 4, 0),
        birth_time_mode="exact",
        lat=29.3724,
        lon=78.1358,
        timezone_str="Asia/Kolkata",
        location_name="Bijnor, Uttar Pradesh, India",
        ayanamsha_key="lahiri",
        lunar_system="amanta",
        start_year=2024,
        end_year=2026,
    )
    p = result.panchang
    print("=== BIRTH PANCHANG for 28 May 2004, 04:00 AM IST, Bijnor ===")
    print(f"Tithi: {[(t.paksha_en, t.name_en) for t in p.tithis]}")
    print(f"Nakshatra: {p.nakshatra.name_en if p.nakshatra else None} Pada {p.nakshatra.pada if p.nakshatra else 'N/A'}")
    print(f"Yoga: {p.yoga.name_en if p.yoga else None}")
    print(f"Karana: {p.karana.name_en if p.karana else None}")
    print(f"Lunar Month: {p.lunar_month.month_name_en if p.lunar_month else None}")
    print(f"Sunrise (IST): {p.sunrise_local}")
    print()
    print("=== HINDU BIRTHDAYS ===")
    for entry in result.birthday_entries:
        print(f"{entry.year}: {entry.gregorian_date} ({entry.weekday}) -- {entry.lunar_month_en} {entry.tithi_name_en} -- {entry.status}")
