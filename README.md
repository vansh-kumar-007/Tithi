# Hindu Tithi Birthday Calculator

A production-quality Python/Flask web application that calculates Hindu Panchang birth details and annual Hindu Tithi birthdays using Swiss Ephemeris astronomical calculations.

## Features

- **Accurate Tithi & Panchang Engine** via Swiss Ephemeris (`pyswisseph`) with thread-safe ayanamsha support (Lahiri default, plus Raman, Krishnamurti, Yukteshwar, True Citra).
- **Three Birth-Time Modes**:
  - **Exact**: Computes exact Tithi, Nakshatra, Yoga, Karana, Lunar Month, and Sunrise/Sunset.
  - **Approximate**: Scans the entire custom or preset time window and reports all Tithis if a transition occurred.
  - **Unknown**: Scans the entire local calendar day (no arbitrary 12:00 PM/midnight assumption) and generates candidate birthday calendars for every possible Tithi.
- **Configurable Traditional Conventions**:
  - **Amanta** (New Moon to New Moon) and **Purnimanta** (Full Moon to Full Moon) lunar month systems.
  - **Annual Observance Rule**: Sunrise (Udaya Tithi — default), Midday (Madhyahna), or Sunset (Sayahna).
  - **Adhika Masa Rule**: Regular (Nija) month, Adhika month, or Both.
- **Lunation-First Birthday Search & Edge-Case Handling**:
  - Accurately detects and explains **Confirmed**, **Vriddhi** (repeated Tithi), **Kshaya** (skipped Tithi), **Adhika** (leap month), **Multiple Dates**, and Gregorian year-boundary shifts.
- **Location & Timezone Support**:
  - Rate-limited, cached Nominatim geocoding, quick-pick presets, manual coordinate entry, automatic IANA timezone detection (`/timezone`), and manual timezone override.
- **Visual Calendar & Exports**:
  - Year-by-year visual calendar grid + detailed table with **local timezone** timestamps.
  - Download **PDF**, **Excel (.xlsx)**, **CSV**, **ICS** calendar files, or print directly.
- **Bilingual**: Instant English / Hindi toggle that preserves and re-renders active results.

## Installation & Local Setup

```bash
conda create -n tithi_env python=3.11 -y
conda activate tithi_env
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** in your browser.

### Optional Swiss Ephemeris Data Files
Without `.se1` files in `ephe/`, `pyswisseph` uses the built-in Moshier ephemeris (accurate for ~3000 BCE – 3000 CE). For maximum precision or extended historical spans, download `seas_18.se1`, `semo_18.se1`, and `sepl_18.se1` from [astro.com](https://www.astro.com/ftp/swisseph/ephe/) into `ephe/`.

## Running Tests

```bash
conda activate tithi_env
python -m pytest tests/ -v
```

## Validation Summary

Validated against standard Lahiri Drik Panchang references across Bijnor, Delhi, Mumbai, Kolkata, London, New York, and Tokyo:
- **28 May 2004, 04:00 AM IST, Bijnor**: Jyeshtha Shukla Navami (Purva Phalguni Pada 3, Harshana Yoga, Balava Karana, Sunrise 05:19 IST). Annual Jyeshtha Shukla Navami dates: **2024-06-15**, **2025-06-04**, **2026-06-23**.
- **Unknown birth time on 28 May 2004**: Correctly identifies both Shukla Ashtami and Shukla Navami (transition at ~01:36 IST) and generates two candidate birthday calendars.
- **Amanta vs Purnimanta**: Verified against Holi/Chaitra (25–26 Mar 2024), Diwali (1 Nov 2024), and Janmashtami (26 Aug 2024).
- **Adhika Masa**: Verified against Adhika Shravana (Jul–Aug 2023) and Adhika Ashwina (Sep–Oct 2020).

## Known Limitations

- Timezone accuracy before ~1900 depends on `pytz` historical LMT/zone database coverage.
- Geocoding uses OpenStreetMap Nominatim (requires internet, throttled to ~1 req/s). Manual coordinates work offline.
- Circumpolar locations during polar day/night fall back cleanly when sunrise/sunset does not occur.
- Built-in PDF Devanagari rendering uses system TTF fonts when available (`mangal.ttf` on Windows or `NotoSansDevanagari` on Linux); complex Devanagari conjunct shaping depends on ReportLab's TTF renderer.

## Deployment

```bash
# Production environment variables
SECRET_KEY=replace-with-strong-random-secret
DEBUG=false
EPHE_PATH=/app/ephe

# Run with Gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 "app:create_app()"
```
