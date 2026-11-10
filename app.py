"""
Flask application — routes, validation, and API endpoints.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Dict, Optional

import pytz
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_caching import Cache
from werkzeug.middleware.proxy_fix import ProxyFix

from calculations.astronomy import init_ephemeris, set_ayanamsha
from calculations.birthday_dates import OBSERVANCE_LABELS
from config import Config, ProductionConfig, validate_production_config
from models.calculation import CalculationRequest
from services.export_service import export_csv, export_excel, export_ics, export_pdf
from services.location_service import geocode_location
from services.panchang_service import (
    ADHIKA_RULES,
    AYANAMSHA_NAMES,
    LUNAR_SYSTEMS,
    OBSERVANCE_METHODS,
    FullResult,
    calculate_panchang,
)
from services.supabase_service import (
    SupabaseAuthError,
    SupabaseConfigError,
    SupabaseServiceError,
    delete_supabase_user_account,
)
from services.timezone_service import get_timezone_str, localize_datetime

_MAX_YEAR_SPAN = 120
_MIN_SUPPORTED_YEAR = 1583
_MAX_SUPPORTED_YEAR = 2500


def create_app(config_override: Optional[Dict[str, Any]] = None) -> Flask:
    app = Flask(__name__)
    is_prod_env = (
        os.environ.get("RENDER", "").strip().lower() == "true"
        or os.environ.get("FLASK_ENV", "").strip().lower() == "production"
    )
    app.config.from_object(ProductionConfig if is_prod_env else Config)
    if config_override:
        app.config.from_mapping(config_override)

    # Validate production secrets unless running in debug mode or automated pytest
    if "PYTEST_CURRENT_TEST" not in os.environ:
        validate_production_config(app.config)

    # Respect X-Forwarded-* headers behind Render / reverse proxies for HTTPS URLs
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    cache = Cache(app)

    init_ephemeris(app.config["EPHE_PATH"])
    set_ayanamsha(app.config["DEFAULT_AYANAMSHA"])

    @app.context_processor
    def inject_public_supabase_config():
        """Expose only public Supabase URL & anon key to Jinja2 templates."""
        url = app.config.get("SUPABASE_URL", "")
        anon_key = app.config.get("SUPABASE_ANON_KEY", "")
        service_key = app.config.get("SUPABASE_SERVICE_ROLE_KEY", "")
        return {
            "SUPABASE_URL": url,
            "SUPABASE_ANON_KEY": anon_key,
            "supabase_url": url,
            "supabase_anon_key": anon_key,
            "supabase_configured": bool(url and anon_key),
            "supabase_account_deletion_enabled": bool(url and service_key),
        }

    # ------------------------------------------------------------------ #
    # Request parsing & validation
    # ------------------------------------------------------------------ #

    def _parse_calculation_request(data: Dict[str, Any]) -> CalculationRequest:
        if not isinstance(data, dict) or not data:
            raise ValueError("Request JSON payload is required.")

        birth_date_str = data.get("birth_date")
        if not birth_date_str:
            raise ValueError("birth_date is required.")
        birth_date = date.fromisoformat(str(birth_date_str))
        if not (_MIN_SUPPORTED_YEAR <= birth_date.year <= _MAX_SUPPORTED_YEAR):
            raise ValueError(
                f"birth_date year must be between {_MIN_SUPPORTED_YEAR} and {_MAX_SUPPORTED_YEAR}."
            )

        if "lat" not in data or "lon" not in data or data.get("lat") in (None, "") or data.get("lon") in (None, ""):
            raise ValueError("Latitude and longitude are required.")
        lat = float(data["lat"])
        lon = float(data["lon"])
        if not (-90.0 <= lat <= 90.0):
            raise ValueError("Latitude must be between -90 and 90.")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError("Longitude must be between -180 and 180.")

        timezone_str = str(data.get("timezone") or "").strip()
        if not timezone_str:
            timezone_str = get_timezone_str(lat, lon)
        try:
            pytz.timezone(timezone_str)
        except pytz.UnknownTimeZoneError as exc:
            raise ValueError(f"Invalid IANA timezone: '{timezone_str}'.") from exc

        location_name = str(data.get("location_name") or f"{lat:.4f}, {lon:.4f}").strip()[:200]
        ayanamsha_key = str(data.get("ayanamsha", "lahiri"))
        if ayanamsha_key not in AYANAMSHA_NAMES:
            raise ValueError(f"Unsupported ayanamsha: '{ayanamsha_key}'.")

        lunar_system = str(data.get("lunar_system", "amanta")).lower()
        if lunar_system not in LUNAR_SYSTEMS:
            raise ValueError(f"Unsupported lunar_system: '{lunar_system}'.")

        observance_method = str(data.get("observance_method", "sunrise")).lower()
        if observance_method not in OBSERVANCE_METHODS:
            raise ValueError(f"Unsupported observance_method: '{observance_method}'.")

        adhika_rule = str(data.get("adhika_rule", "nija")).lower()
        if adhika_rule not in ADHIKA_RULES:
            raise ValueError(f"Unsupported adhika_rule: '{adhika_rule}'.")

        birth_time_mode = str(data.get("birth_time_mode", "unknown")).lower()
        if birth_time_mode not in {"exact", "approximate", "unknown"}:
            raise ValueError(f"Unsupported birth_time_mode: '{birth_time_mode}'.")

        birth_time_local: Optional[datetime] = None
        birth_time_start: Optional[datetime] = None
        birth_time_end: Optional[datetime] = None

        if birth_time_mode == "exact":
            time_str = str(data.get("birth_time") or "").strip()
            if not time_str:
                raise ValueError("Exact birth time (HH:MM) is required in exact mode.")
            t = datetime.strptime(time_str, "%H:%M").time()
            birth_time_local = datetime.combine(birth_date, t)
        elif birth_time_mode == "approximate":
            start_str = str(data.get("birth_time_start") or "").strip()
            end_str = str(data.get("birth_time_end") or "").strip()
            if not start_str or not end_str:
                raise ValueError("Both start and end times are required in approximate mode.")
            t_start = datetime.strptime(start_str, "%H:%M").time()
            t_end = datetime.strptime(end_str, "%H:%M").time()
            if t_end <= t_start:
                raise ValueError("Approximate end time must be later than start time.")
            birth_time_start = datetime.combine(birth_date, t_start)
            birth_time_end = datetime.combine(birth_date, t_end)

        start_year_raw = data.get("start_year")
        end_year_raw = data.get("end_year")
        start_year = int(start_year_raw) if start_year_raw not in (None, "") else None
        end_year = int(end_year_raw) if end_year_raw not in (None, "") else None

        if start_year is not None and not (_MIN_SUPPORTED_YEAR <= start_year <= _MAX_SUPPORTED_YEAR):
            raise ValueError(f"start_year must be between {_MIN_SUPPORTED_YEAR} and {_MAX_SUPPORTED_YEAR}.")
        if end_year is not None and not (_MIN_SUPPORTED_YEAR <= end_year <= _MAX_SUPPORTED_YEAR):
            raise ValueError(f"end_year must be between {_MIN_SUPPORTED_YEAR} and {_MAX_SUPPORTED_YEAR}.")
        if start_year is not None and end_year is not None:
            if end_year < start_year:
                raise ValueError("Ending year must be greater than or equal to starting year.")
            if (end_year - start_year) > _MAX_YEAR_SPAN:
                raise ValueError(f"Year range cannot exceed {_MAX_YEAR_SPAN} years per calculation.")

        return CalculationRequest(
            birth_date=birth_date,
            birth_time_mode=birth_time_mode,
            birth_time_local=birth_time_local,
            birth_time_start=birth_time_start,
            birth_time_end=birth_time_end,
            lat=lat,
            lon=lon,
            timezone_str=timezone_str,
            location_name=location_name,
            ayanamsha_key=ayanamsha_key,
            lunar_system=lunar_system,
            observance_method=observance_method,
            adhika_rule=adhika_rule,
            start_year=start_year,
            end_year=end_year,
            language=str(data.get("language", "en")),
        )

    def _run_calculation_cached(req: CalculationRequest) -> FullResult:
        cache_key = (
            f"calc:{req.birth_date}:{req.birth_time_mode}:{req.birth_time_local}:"
            f"{req.birth_time_start}:{req.birth_time_end}:{req.lat:.5f}:{req.lon:.5f}:"
            f"{req.timezone_str}:{req.ayanamsha_key}:{req.lunar_system}:"
            f"{req.observance_method}:{req.adhika_rule}:{req.start_year}:{req.end_year}"
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        result = calculate_panchang(
            birth_date=req.birth_date,
            birth_time_local=req.birth_time_local,
            birth_time_mode=req.birth_time_mode,
            lat=req.lat,
            lon=req.lon,
            timezone_str=req.timezone_str,
            location_name=req.location_name,
            ayanamsha_key=req.ayanamsha_key,
            start_year=req.start_year,
            end_year=req.end_year,
            birth_time_start=req.birth_time_start,
            birth_time_end=req.birth_time_end,
            lunar_system=req.lunar_system,
            observance_method=req.observance_method,
            adhika_rule=req.adhika_rule,
        )
        cache.set(cache_key, result)
        return result

    # ------------------------------------------------------------------ #
    # Helper: serialize result for JSON
    # ------------------------------------------------------------------ #
    def _serialize_result(result: FullResult) -> dict:
        p = result.panchang
        tz_str = p.timezone_str
        today = result.today

        def fmt_dt(dt):
            if dt is None:
                return None
            return dt.strftime("%Y-%m-%d %H:%M %Z").strip()

        def fmt_local_from_utc(dt_utc):
            if dt_utc is None:
                return None
            local_dt = localize_datetime(dt_utc, tz_str)
            return fmt_dt(local_dt)

        def fmt_date(d):
            if d is None:
                return None
            return d.strftime("%d %B %Y")

        def serialize_tithi(t):
            return {
                "index": t.index,
                "number": t.number,
                "name_en": t.name_en,
                "name_hi": t.name_hi,
                "paksha_en": t.paksha_en,
                "paksha_hi": t.paksha_hi,
                "elongation": round(t.elongation, 4),
                "start_utc": fmt_dt(t.start_utc),
                "end_utc": fmt_dt(t.end_utc),
                "start_local": fmt_local_from_utc(t.start_utc),
                "end_local": fmt_local_from_utc(t.end_utc),
            }

        def serialize_entries(entries):
            out = []
            for entry in entries:
                out.append({
                    "year": entry.year,
                    "gregorian_date": entry.gregorian_date.isoformat() if entry.gregorian_date else None,
                    "gregorian_date_display": fmt_date(entry.gregorian_date),
                    "weekday": entry.weekday,
                    "weekday_hi": entry.weekday_hi,
                    "lunar_month_en": entry.lunar_month_en,
                    "tithi_name_en": entry.tithi_name_en,
                    "tithi_name_hi": entry.tithi_name_hi,
                    "tithi_start_utc": fmt_dt(entry.tithi_start_utc),
                    "tithi_end_utc": fmt_dt(entry.tithi_end_utc),
                    "tithi_start_local": fmt_local_from_utc(entry.tithi_start_utc),
                    "tithi_end_local": fmt_local_from_utc(entry.tithi_end_utc),
                    "status": entry.status,
                    "notes": entry.notes,
                    "alternate_dates": [d.isoformat() for d in entry.alternate_dates],
                    "is_past": entry.gregorian_date < today if entry.gregorian_date else None,
                    "is_today": entry.gregorian_date == today if entry.gregorian_date else False,
                })
            return out

        tithis_data = [serialize_tithi(t) for t in p.tithis]
        entries_data = serialize_entries(result.birthday_entries)

        candidate_calendars_data = []
        for cal in result.candidate_calendars:
            c_entries = serialize_entries(cal.entries)
            c_next = None
            c_days = None
            for e in cal.entries:
                if e.gregorian_date and e.gregorian_date >= today:
                    c_next = e.gregorian_date.isoformat()
                    c_days = (e.gregorian_date - today).days
                    break
            candidate_calendars_data.append({
                "tithi": serialize_tithi(cal.tithi),
                "lunar_month": {
                    "name_en": cal.lunar_month.month_name_en,
                    "name_hi": cal.lunar_month.month_name_hi,
                    "is_adhika": cal.lunar_month.is_adhika,
                    "solar_sign_en": cal.lunar_month.solar_sign_en,
                },
                "entries": c_entries,
                "next_birthday": {"date": c_next, "days_until": c_days},
            })

        nb = result.next_birthday
        return {
            "panchang": {
                "birth_date": p.birth_date.isoformat(),
                "birth_date_display": p.birth_date.strftime("%d %B %Y"),
                "birth_time_mode": p.birth_time_mode,
                "birth_time_local": fmt_dt(p.birth_time_local),
                "location_name": p.location_name,
                "lat": p.lat,
                "lon": p.lon,
                "timezone_str": p.timezone_str,
                "ayanamsha_name": p.ayanamsha_name,
                "lunar_system": p.lunar_system,
                "observance_method": p.observance_method,
                "observance_label": OBSERVANCE_LABELS.get(p.observance_method, p.observance_method),
                "adhika_rule": p.adhika_rule,
                "sunrise_local": fmt_dt(p.sunrise_local),
                "sunset_local": fmt_dt(p.sunset_local),
                "tithis": tithis_data,
                "nakshatra": {
                    "name_en": p.nakshatra.name_en,
                    "name_hi": p.nakshatra.name_hi,
                    "pada": p.nakshatra.pada,
                    "lord": p.nakshatra.lord,
                } if p.nakshatra else None,
                "yoga": {
                    "name_en": p.yoga.name_en,
                    "name_hi": p.yoga.name_hi,
                } if p.yoga else None,
                "karana": {
                    "name_en": p.karana.name_en,
                    "name_hi": p.karana.name_hi,
                } if p.karana else None,
                "lunar_month": {
                    "name_en": p.lunar_month.month_name_en,
                    "name_hi": p.lunar_month.month_name_hi,
                    "is_adhika": p.lunar_month.is_adhika,
                    "solar_sign_en": p.lunar_month.solar_sign_en,
                } if p.lunar_month else None,
                "tithi_at_sunrise": {
                    "name_en": p.tithi_at_sunrise.name_en,
                    "name_hi": p.tithi_at_sunrise.name_hi,
                    "paksha_en": p.tithi_at_sunrise.paksha_en,
                    "paksha_hi": p.tithi_at_sunrise.paksha_hi,
                } if p.tithi_at_sunrise else None,
                "is_ambiguous": p.is_ambiguous,
                "ambiguity_message": p.ambiguity_message,
                "confidence": p.confidence,
            },
            "birthday_entries": entries_data,
            "candidate_calendars": candidate_calendars_data,
            "start_year": result.start_year,
            "end_year": result.end_year,
            "today_iso": today.isoformat(),
            "next_birthday": {
                "date": nb.gregorian_date.isoformat() if nb and nb.gregorian_date else None,
                "days_until": result.days_until_next_birthday,
            },
        }

    # ------------------------------------------------------------------ #
    # Routes
    # ------------------------------------------------------------------ #

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            ayanamsha_options=AYANAMSHA_NAMES,
            observance_options=OBSERVANCE_LABELS,
            common_timezones=pytz.common_timezones,
            current_year=date.today().year,
        )

    @app.route("/geocode")
    def geocode():
        """AJAX endpoint: geocode a location string."""
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "Please enter a location to search."}), 400
        try:
            loc = geocode_location(query)
            if loc is None:
                return jsonify({"error": "Location not found. Try adding state or country, or enter coordinates manually."}), 404
            tz_str = get_timezone_str(loc.latitude, loc.longitude)
            return jsonify({
                "display_name": loc.display_name,
                "lat": loc.latitude,
                "lon": loc.longitude,
                "timezone": tz_str,
                "city": loc.city,
                "state": loc.state,
                "country": loc.country,
            })
        except RuntimeError as exc:
            app.logger.warning("Geocoding service unavailable: %s", exc)
            return jsonify({"error": "Geocoding service temporarily unavailable. You can enter coordinates manually."}), 503
        except Exception:
            app.logger.exception("Unexpected geocoding error")
            return jsonify({"error": "Unable to search location right now."}), 500

    @app.route("/timezone")
    def detect_timezone():
        """Detect IANA timezone from manual lat/lon coordinates."""
        try:
            lat = float(request.args.get("lat", ""))
            lon = float(request.args.get("lon", ""))
            if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
                return jsonify({"error": "Coordinates out of range."}), 400
            return jsonify({"timezone": get_timezone_str(lat, lon)})
        except ValueError:
            return jsonify({"error": "Invalid latitude or longitude."}), 400

    @app.route("/calculate", methods=["POST"])
    def calculate():
        """Main calculation endpoint. Accepts JSON POST."""
        try:
            data = request.get_json(silent=True) or {}
            req_model = _parse_calculation_request(data)
            result = _run_calculation_cached(req_model)
            return jsonify(_serialize_result(result))
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("Calculation error")
            return jsonify({"error": "An unexpected calculation error occurred. Please check your inputs."}), 500

    @app.route("/results")
    def results():
        return redirect(url_for("index") + "#calculator")

    @app.route("/account")
    def account():
        """Render the My Account dashboard (session & RLS handled client-side)."""
        return render_template("account.html")

    @app.route("/api/supabase-status")
    def supabase_status():
        """Safe diagnostic endpoint returning only booleans (never actual credentials)."""
        url = app.config.get("SUPABASE_URL", "")
        anon_key = app.config.get("SUPABASE_ANON_KEY", "")
        return jsonify({
            "supabase_url_loaded": bool(url),
            "supabase_anon_key_loaded": bool(anon_key),
            "supabase_configured": bool(url and anon_key),
        })

    @app.route("/api/validate-input", methods=["POST"])
    def validate_historical_input():
        """Validate saved historical calculation input payload before export/recalculation."""
        try:
            data = request.get_json(silent=True) or {}
            _parse_calculation_request(data)
            return jsonify({"valid": True})
        except (ValueError, TypeError) as exc:
            return jsonify({"valid": False, "error": str(exc)}), 400

    @app.route("/api/account/delete", methods=["POST"])
    def delete_account():
        """
        Permanently delete the authenticated user's Supabase Auth account
        (cascading to saved_birth_profiles and calculation_history).
        Requires a valid Supabase Bearer JWT and explicit confirmation.
        """
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Authentication required. Missing Bearer token."}), 401
        token = auth_header[7:].strip()
        if not token:
            return jsonify({"error": "Authentication required. Empty Bearer token."}), 401

        body = request.get_json(silent=True) or {}
        if str(body.get("confirm_text", "")).strip().upper() != "DELETE":
            return jsonify({"error": "Please type DELETE to confirm permanent account deletion."}), 400

        try:
            deleted = delete_supabase_user_account(
                access_token=token,
                supabase_url=app.config.get("SUPABASE_URL", ""),
                anon_key=app.config.get("SUPABASE_ANON_KEY", ""),
                service_role_key=app.config.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            )
            return jsonify({
                "deleted": True,
                "email": deleted.get("email"),
                "message": "Your account, saved birth profiles, and calculation history have been permanently deleted.",
            })
        except SupabaseAuthError as exc:
            return jsonify({"error": str(exc)}), 401
        except SupabaseConfigError as exc:
            return jsonify({"error": str(exc)}), 503
        except SupabaseServiceError as exc:
            app.logger.warning("Account deletion upstream error: %s", exc)
            return jsonify({"error": str(exc)}), 502
        except Exception:
            app.logger.exception("Unexpected error during account deletion")
            return jsonify({"error": "Unable to delete account right now."}), 500

    # ------------------------------------------------------------------ #
    # Export endpoints (stateless & multi-worker safe)
    # ------------------------------------------------------------------ #

    def _result_for_export():
        data = request.get_json(silent=True)
        if not data:
            return None
        req_model = _parse_calculation_request(data)
        return _run_calculation_cached(req_model)

    @app.route("/export/csv", methods=["POST"])
    def export_csv_route():
        try:
            result = _result_for_export()
            if result is None:
                abort(400)
            data = export_csv(result)
            return Response(
                data,
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=hindu_birthdays.csv"},
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/export/excel", methods=["POST"])
    def export_excel_route():
        try:
            result = _result_for_export()
            if result is None:
                abort(400)
            data = export_excel(result)
            return Response(
                data,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=hindu_birthdays.xlsx"},
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/export/pdf", methods=["POST"])
    def export_pdf_route():
        try:
            result = _result_for_export()
            if result is None:
                abort(400)
            data = export_pdf(result)
            return Response(
                data,
                mimetype="application/pdf",
                headers={"Content-Disposition": "attachment; filename=hindu_birthday_report.pdf"},
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.route("/export/ics", methods=["POST"])
    def export_ics_route():
        try:
            result = _result_for_export()
            if result is None:
                abort(400)
            data = export_ics(result)
            return Response(
                data,
                mimetype="text/calendar",
                headers={"Content-Disposition": "attachment; filename=hindu_birthdays.ics"},
            )
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", error="Page not found", code=404), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", error="Internal server error", code=500), 500

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    host = "127.0.0.1" if app.config["DEBUG"] else "0.0.0.0"
    app.run(host=host, debug=app.config["DEBUG"], port=port)
