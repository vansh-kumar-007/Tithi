# Hindu Tithi Birthday Calculator

A production-quality Python/Flask web application that calculates Hindu Panchang birth details and annual Hindu Tithi birthdays using Swiss Ephemeris astronomical calculations.

## Live Website

- **Production App:** [https://tithi-f24b.onrender.com/](https://tithi-f24b.onrender.com/) *(Hosted on Render with Supabase Auth & PostgreSQL)*

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
- **Optional User Accounts & Cloud Storage (Supabase)**:
  - Email/Password Sign Up, Log In, Log Out, and persistent sessions via Supabase Auth.
  - **"My Account"** dashboard (`/account`) to manage saved family birth profiles and revisit calculation history.
  - Explicit **"Save Birth Profile"** and **"Save to Calculation History"** controls (calculator remains usable anonymously without login).
  - Row Level Security (`auth.uid() = user_id`) and server-verified permanent account deletion (`/api/account/delete`).
- **Google Calendar Sync & Freemium Plus Plan (V1.1)**:
  - Secure server-side Google OAuth 2.0 (`calendar.events`, `openid`, `email`) with CSRF state binding and Fernet-encrypted token storage.
  - **Free Tier:** Up to 3 saved birth profiles, 1 connected Google account, sync 1 birth profile for upcoming 12 months, manage/delete Tithi events, and disconnect anytime.
  - **14-Day Tithi Plus Trial & Plus Entitlements:** Once-per-account 14-day free trial (no card required, zero auto-charge) unlocking unlimited saved profiles, bulk multi-profile sync, upcoming N years, specific year (`1583–2500`), custom year ranges (up to 120 years per calculation), and year-range deletion.
  - Privacy-respecting all-day Google Calendar events (omitting DOB, exact birth time, and coordinates) with duplicate prevention and ownership-verified deletion.
  - Dedicated bilingual Privacy Policy (`/privacy`) and Google Cloud setup guide ([`docs/google_calendar_setup.md`](docs/google_calendar_setup.md)).

## Installation & Local Setup

```bash
conda create -n tithi_env python=3.11 -y
conda activate tithi_env
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000** in your browser.

### Supabase Setup (Optional — for User Accounts & Cloud Storage)

The calculator works without Supabase configured. To enable accounts, saved birth profiles, calculation history, and account deletion:

1. Create a project at [supabase.com](https://supabase.com).
2. Open **SQL Editor** in your Supabase Dashboard and execute [`supabase/schema.sql`](supabase/schema.sql), followed by the V1.1 migration [`supabase/migrations/v1_1_google_calendar_entitlements.sql`](supabase/migrations/v1_1_google_calendar_entitlements.sql).
   This creates all user-owned tables with strict Row Level Security (`auth.uid() = user_id`), server-only encrypted OAuth tables, atomic trial activation, Free 3-profile database/backend enforcement, and `ON DELETE CASCADE` links to `auth.users`.
3. In **Authentication -> Providers -> Email**, ensure Email provider is enabled. Under **Authentication -> URL Configuration**, add your local/production `/account` URL (e.g. `http://localhost:5000/account`) to Redirect URLs.
4. Copy `.env.example` to `.env` (never commit `.env`) and fill in your credentials from **Project Settings -> API** and **Google Cloud Console** (see [`docs/google_calendar_setup.md`](docs/google_calendar_setup.md)):
   ```env
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_ANON_KEY=your-publishable-or-anon-key
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-secret-key
   GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
   GOOGLE_REDIRECT_URI=http://localhost:5000/auth/google/callback
   GOOGLE_TOKEN_ENCRYPTION_KEY=replace-with-32-byte-url-safe-base64-fernet-key
   ```
   > **Security note:** `SUPABASE_SERVICE_ROLE_KEY`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_TOKEN_ENCRYPTION_KEY` stay strictly server-side and are never exposed to browsers or templates.

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

## Deployment (Render Free Tier)

1. Push the project to a **private GitHub repository** (verify `.env` is excluded by `.gitignore`).
2. On [Render](https://render.com), create a **Free Web Service** connected to your repository:
   - **Runtime:** Python (`3.11.11` pinned via `.python-version`)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn -w 1 --timeout 120 --bind 0.0.0.0:$PORT wsgi:app` (configured in `Procfile`)
3. Set these **Environment Variables** in the Render Dashboard:
   ```env
   SECRET_KEY=<generate-strong-random-32+-char-string>
   DEBUG=false
   SUPABASE_URL=https://your-project-ref.supabase.co
   SUPABASE_ANON_KEY=your-publishable-or-anon-key
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-secret-key
   GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
   GOOGLE_CLIENT_SECRET=<your-google-oauth-client-secret>
   GOOGLE_REDIRECT_URI=https://tithi-f24b.onrender.com/auth/google/callback
   GOOGLE_TOKEN_ENCRYPTION_KEY=<generated-fernet-key>
   ```
4. Configure **Supabase Dashboard → Authentication → URL Configuration** for the live deployment (`https://tithi-f24b.onrender.com`):
   - **Site URL:** `https://tithi-f24b.onrender.com`
   - **Redirect URLs:**
     - `https://tithi-f24b.onrender.com/account`
     - `https://tithi-f24b.onrender.com/*`
     - `http://localhost:5000/account` *(for local development)*
