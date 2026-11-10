"""
Google Calendar Event Generation, Batch Synchronization & Safe Deletion Service.

Design invariants:
- Reuses `services.panchang_service.calculate_panchang` directly without
  modifying or duplicating astronomical calculation logic.
- Creates individual all-day Google Calendar events (never annual RRULEs).
- Omits sensitive DOB, exact birth time, and birthplace coordinates/address from
  Google Calendar descriptions.
- Enforces Free vs Plus entitlements strictly server-side.
- Tracks every event in `google_calendar_events` and stamps
  `extendedProperties.private` so Tithi never modifies or deletes unrelated events.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytz
import requests

from calculations.birthday_dates import OBSERVANCE_LABELS, BirthdayEntry
from services.entitlement_service import (
    EntitlementError,
    FREE_MAX_SYNC_PROFILES,
    FREE_UPCOMING_MONTHS,
    get_user_entitlement,
)
from services.google_oauth_service import (
    GoogleOAuthError,
    GoogleReauthError,
    get_active_connection,
    get_valid_access_token,
)
from services.panchang_service import CandidateBirthdayCalendar, FullResult, calculate_panchang
from services.supabase_service import SupabaseAdminClient
from services.timezone_service import localize_datetime

GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

_MIN_SUPPORTED_YEAR = 1583
_MAX_SUPPORTED_YEAR = 2500
_MAX_YEAR_SPAN = 120
_DEFAULT_BATCH_SIZE = 20
_MAX_BATCH_SIZE = 25


class GoogleApiError(Exception):
    """Raised when Google Calendar API fails after retries or rejects a request."""

    def __init__(self, message: str, status_code: int = 502, reason: str = ""):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.reason = reason


def _add_years_safe(d: date, years: int) -> date:
    target_year = min(_MAX_SUPPORTED_YEAR, d.year + years)
    last_day = calendar.monthrange(target_year, d.month)[1]
    return date(target_year, d.month, min(d.day, last_day))


def _add_months_safe(d: date, months: int) -> date:
    total_months = (d.year * 12 + (d.month - 1)) + months
    target_year = min(_MAX_SUPPORTED_YEAR, total_months // 12)
    target_month = (total_months % 12) + 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    return date(target_year, target_month, min(d.day, last_day))


def _fmt_local_window(dt_utc: Optional[datetime], tz_str: str) -> str:
    local_dt = localize_datetime(dt_utc, tz_str)
    if local_dt is None:
        return ""
    return local_dt.strftime("%Y-%m-%d %H:%M %Z").strip()


def _parse_profile_time(time_val: Optional[str], base_date: date) -> Optional[datetime]:
    if not time_val:
        return None
    parts = str(time_val).strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    return datetime(base_date.year, base_date.month, base_date.day, hour, minute)


def _calculate_for_profile(
    profile: Dict[str, Any],
    start_year: int,
    end_year: int,
    calculate_fn: Callable[..., FullResult] = calculate_panchang,
) -> FullResult:
    """Invoke the untouched astronomical calculation engine for a saved profile."""
    bdate = date.fromisoformat(str(profile["birth_date"]))
    mode = str(profile.get("birth_time_mode") or "unknown").lower()

    birth_time_local = None
    birth_time_start = None
    birth_time_end = None
    if mode == "exact":
        birth_time_local = _parse_profile_time(profile.get("birth_time"), bdate)
    elif mode == "approximate":
        birth_time_start = _parse_profile_time(profile.get("birth_time_start"), bdate)
        birth_time_end = _parse_profile_time(profile.get("birth_time_end"), bdate)

    return calculate_fn(
        birth_date=bdate,
        birth_time_local=birth_time_local,
        birth_time_mode=mode,
        lat=float(profile["latitude"]),
        lon=float(profile["longitude"]),
        timezone_str=str(profile["timezone"]),
        location_name=str(profile["location_name"]),
        ayanamsha_key=str(profile.get("ayanamsha") or "lahiri"),
        start_year=start_year,
        end_year=end_year,
        birth_time_start=birth_time_start,
        birth_time_end=birth_time_end,
        lunar_system=str(profile.get("lunar_system") or "amanta"),
        observance_method=str(profile.get("observance_method") or "sunrise"),
        adhika_rule=str(profile.get("adhika_rule") or "nija"),
    )


def build_google_event_payload(
    user_id: str,
    profile_id: str,
    profile_label: str,
    result: FullResult,
    cal: CandidateBirthdayCalendar,
    entry: BirthdayEntry,
) -> Dict[str, Any]:
    """
    Build a Google Calendar all-day event payload for one Hindu birthday year.
    Deliberately excludes DOB, birth time, and birthplace address/coordinates.
    """
    assert entry.gregorian_date is not None
    p = result.panchang
    obs_label = OBSERVANCE_LABELS.get(p.observance_method, p.observance_method)
    tithi_desc = f"{cal.tithi.paksha_en} {entry.tithi_name_en} ({entry.tithi_name_hi})"
    month_label = entry.lunar_month_en or cal.lunar_month.month_name_en
    adhika_tag = " (Adhika)" if entry.is_adhika else ""

    lines = [
        f"Hindu Tithi Birthday – {profile_label}",
        "",
        f"Birth Profile: {profile_label}",
        f"Lunar Month: {month_label}{adhika_tag}",
        f"Tithi: {tithi_desc}",
        f"Calculation System: {p.lunar_system.title()} · {obs_label} · {p.ayanamsha_name}",
    ]

    s_loc = _fmt_local_window(entry.tithi_start_utc, p.timezone_str)
    e_loc = _fmt_local_window(entry.tithi_end_utc, p.timezone_str)
    if s_loc and e_loc:
        lines.append(f"Tithi Window ({p.timezone_str}): {s_loc} to {e_loc}")

    lines.append(f"Status: {entry.status}")
    if entry.alternate_dates:
        lines.append("Alternate Dates: " + ", ".join(d.isoformat() for d in entry.alternate_dates))
    if entry.notes:
        lines.append(f"Notes: {entry.notes}")

    lines.extend(["", "Synced by Tithi (Hindu Tithi Birthday Calculator)"])

    start_iso = entry.gregorian_date.isoformat()
    end_iso = (entry.gregorian_date + timedelta(days=1)).isoformat()

    return {
        "summary": f"Hindu Birthday – {profile_label}"[:250],
        "description": "\n".join(lines),
        "start": {"date": start_iso},
        "end": {"date": end_iso},
        "reminders": {"useDefault": True},
        "extendedProperties": {
            "private": {
                "tithi_managed": "true",
                "tithi_user_id": str(user_id),
                "tithi_profile_id": str(profile_id),
                "tithi_hindu_year": str(entry.year),
            }
        },
    }


def _resolve_sync_window_and_validate(
    entitlement: Dict[str, Any],
    profile_ids: List[str],
    sync_mode: str,
    years_ahead: Optional[int],
    specific_year: Optional[int],
    start_year: Optional[int],
    end_year: Optional[int],
    active_synced_profile_ids: set[str],
) -> str:
    """Validate entitlements & sync parameters strictly server-side."""
    if not profile_ids:
        raise ValueError("Please select at least one saved birth profile to synchronize.")

    mode = (sync_mode or "upcoming_12m").strip().lower()
    if mode not in {"upcoming_12m", "upcoming_years", "specific_year", "year_range"}:
        raise ValueError(f"Unsupported sync_mode: '{mode}'.")

    is_plus = bool(entitlement.get("is_plus"))

    if not is_plus:
        if len(profile_ids) > FREE_MAX_SYNC_PROFILES:
            raise EntitlementError(
                f"Free plan supports synchronizing only {FREE_MAX_SYNC_PROFILES} birth profile. Upgrade to Tithi Plus to sync multiple profiles.",
                code="PLUS_REQUIRED",
                status_code=403,
            )
        if mode != "upcoming_12m":
            raise EntitlementError(
                "Custom year, year-range, and multi-year sync require Tithi Plus. Free plan supports upcoming 12 months only.",
                code="PLUS_REQUIRED",
                status_code=403,
            )
        target_pid = profile_ids[0]
        other_synced = active_synced_profile_ids - {target_pid}
        if len(other_synced) >= FREE_MAX_SYNC_PROFILES:
            raise EntitlementError(
                "Free plan allows 1 synchronized birth profile at a time. Upgrade to Tithi Plus or remove previously synchronized events for another profile first.",
                code="SYNC_PROFILE_LIMIT_REACHED",
                status_code=403,
            )
        return mode

    # Plus validation
    if mode == "upcoming_years":
        if years_ahead is None or not (1 <= int(years_ahead) <= _MAX_YEAR_SPAN):
            raise ValueError(f"years_ahead must be between 1 and {_MAX_YEAR_SPAN}.")
    elif mode == "specific_year":
        if specific_year is None or not (_MIN_SUPPORTED_YEAR <= int(specific_year) <= _MAX_SUPPORTED_YEAR):
            raise ValueError(f"Year must be between {_MIN_SUPPORTED_YEAR} and {_MAX_SUPPORTED_YEAR}.")
    elif mode == "year_range":
        if start_year is None or end_year is None:
            raise ValueError("Both start_year and end_year are required for year_range mode.")
        sy = int(start_year)
        ey = int(end_year)
        if not (_MIN_SUPPORTED_YEAR <= sy <= _MAX_SUPPORTED_YEAR) or not (_MIN_SUPPORTED_YEAR <= ey <= _MAX_SUPPORTED_YEAR):
            raise ValueError(f"Years must be between {_MIN_SUPPORTED_YEAR} and {_MAX_SUPPORTED_YEAR}.")
        if ey < sy:
            raise ValueError("Ending year must be greater than or equal to starting year.")
        if (ey - sy) > _MAX_YEAR_SPAN:
            raise ValueError(f"Year range cannot exceed {_MAX_YEAR_SPAN} years per sync request.")

    return mode


def _compute_plan_for_profiles(
    admin: SupabaseAdminClient,
    user_id: str,
    connection_id: str,
    profiles: List[Dict[str, Any]],
    mode: str,
    years_ahead: Optional[int],
    specific_year: Optional[int],
    start_year: Optional[int],
    end_year: Optional[int],
    candidate_selections: Dict[str, int],
    today_override: Optional[date] = None,
    calculate_fn: Callable[..., FullResult] = calculate_panchang,
) -> Dict[str, Any]:
    """Compute exact sync plan using the astronomical engine and existing DB event map."""
    existing_rows = admin.select(
        "google_calendar_events",
        filters={
            "user_id": f"eq.{user_id}",
            "google_connection_id": f"eq.{connection_id}",
            "sync_status": "neq.deleted",
        },
    )
    existing_map: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in existing_rows:
        if r.get("saved_birth_profile_id") is not None:
            existing_map[(str(r["saved_birth_profile_id"]), int(r["hindu_year"]))] = r

    planned_items: List[Dict[str, Any]] = []
    skipped_items: List[Dict[str, Any]] = []
    profile_summaries: List[Dict[str, Any]] = []

    min_greg: Optional[date] = None
    max_greg: Optional[date] = None
    min_year: Optional[int] = None
    max_year: Optional[int] = None

    for prof in profiles:
        pid = str(prof["id"])
        plabel = str(prof["label"])
        tz = pytz.timezone(str(prof["timezone"]))
        local_today = today_override or datetime.now(tz).date()

        cutoff_start: Optional[date] = None
        cutoff_end: Optional[date] = None
        if mode == "upcoming_12m":
            cutoff_start = local_today
            cutoff_end = _add_months_safe(local_today, FREE_UPCOMING_MONTHS)
            calc_start_y = local_today.year
            calc_end_y = min(_MAX_SUPPORTED_YEAR, cutoff_end.year)
        elif mode == "upcoming_years":
            yrs = int(years_ahead or 1)
            cutoff_start = local_today
            cutoff_end = _add_years_safe(local_today, yrs)
            calc_start_y = local_today.year
            calc_end_y = min(_MAX_SUPPORTED_YEAR, cutoff_end.year)
        elif mode == "specific_year":
            yr = int(specific_year)  # type: ignore[arg-type]
            calc_start_y = yr
            calc_end_y = yr
        else:
            calc_start_y = int(start_year)  # type: ignore[arg-type]
            calc_end_y = int(end_year)  # type: ignore[arg-type]

        if (calc_end_y - calc_start_y) > _MAX_YEAR_SPAN:
            raise ValueError(f"Year range cannot exceed {_MAX_YEAR_SPAN} years per calculation request.")

        full_result = _calculate_for_profile(prof, calc_start_y, calc_end_y, calculate_fn=calculate_fn)
        cals = full_result.candidate_calendars or []
        if not cals:
            continue

        sel_idx = int(candidate_selections.get(pid, 0) or 0)
        if sel_idx < 0 or sel_idx >= len(cals):
            sel_idx = 0
        chosen_cal = cals[sel_idx]

        candidate_options = [
            {
                "index": idx,
                "label": f"Option {idx + 1}: {c.lunar_month.month_name_en} {c.tithi.paksha_en} {c.tithi.name_en}",
                "lunar_month_en": c.lunar_month.month_name_en,
                "tithi_en": f"{c.tithi.paksha_en} {c.tithi.name_en}",
                "tithi_hi": f"{c.tithi.paksha_hi} {c.tithi.name_hi}",
            }
            for idx, c in enumerate(cals)
        ]

        profile_create = 0
        profile_update = 0
        for entry in chosen_cal.entries:
            if entry.gregorian_date is None:
                skipped_items.append({
                    "profile_id": pid,
                    "profile_label": plabel,
                    "hindu_year": entry.year,
                    "reason": entry.notes or "Outside Gregorian calendar year due to lunar-solar drift.",
                })
                continue

            if cutoff_start and cutoff_end:
                if not (cutoff_start <= entry.gregorian_date <= cutoff_end):
                    continue

            min_greg = entry.gregorian_date if min_greg is None else min(min_greg, entry.gregorian_date)
            max_greg = entry.gregorian_date if max_greg is None else max(max_greg, entry.gregorian_date)
            min_year = entry.year if min_year is None else min(min_year, entry.year)
            max_year = entry.year if max_year is None else max(max_year, entry.year)

            existing = existing_map.get((pid, int(entry.year)))
            action = "update" if existing else "create"
            if action == "create":
                profile_create += 1
            else:
                profile_update += 1

            payload = build_google_event_payload(
                user_id=user_id,
                profile_id=pid,
                profile_label=plabel,
                result=full_result,
                cal=chosen_cal,
                entry=entry,
            )

            planned_items.append({
                "profile_id": pid,
                "profile_label": plabel,
                "hindu_year": int(entry.year),
                "candidate_index": sel_idx,
                "gregorian_date": entry.gregorian_date.isoformat(),
                "weekday": entry.weekday,
                "lunar_month_en": entry.lunar_month_en or chosen_cal.lunar_month.month_name_en,
                "tithi_label": f"{chosen_cal.tithi.paksha_en} {entry.tithi_name_en}",
                "observance_status": entry.status,
                "notes": entry.notes,
                "action": action,
                "existing_row_id": existing["id"] if existing else None,
                "existing_google_event_id": existing["google_event_id"] if existing else None,
                "google_calendar_id": (existing.get("google_calendar_id") if existing else None) or "primary",
                "event_payload": payload,
            })

        profile_summaries.append({
            "profile_id": pid,
            "label": plabel,
            "has_multiple_candidates": len(cals) > 1,
            "candidate_index": sel_idx,
            "candidate_options": candidate_options,
            "tithi_summary": f"{chosen_cal.lunar_month.month_name_en} {chosen_cal.tithi.paksha_en} {chosen_cal.tithi.name_en}",
            "create_count": profile_create,
            "update_count": profile_update,
        })

    create_total = sum(1 for it in planned_items if it["action"] == "create")
    update_total = sum(1 for it in planned_items if it["action"] == "update")

    return {
        "mode": mode,
        "profiles": profile_summaries,
        "planned_items": planned_items,
        "skipped_items": skipped_items,
        "counts": {
            "create": create_total,
            "update": update_total,
            "remove": 0,
            "skipped": len(skipped_items),
            "total": len(planned_items),
        },
        "year_start": min_year,
        "year_end": max_year,
        "date_range": {
            "start": min_greg.isoformat() if min_greg else None,
            "end": max_greg.isoformat() if max_greg else None,
        },
    }


def _extract_google_error_reason(resp: requests.Response) -> Tuple[str, str]:
    try:
        body = resp.json()
        err = body.get("error", {}) if isinstance(body, dict) else {}
        msg = str(err.get("message") or "")
        errors = err.get("errors") or []
        reason = str(errors[0].get("reason") or "") if errors and isinstance(errors[0], dict) else ""
        return msg, reason
    except Exception:
        return (resp.text or "")[:200], ""


def _google_calendar_request(
    method: str,
    url: str,
    token_getter: Callable[[bool], str],
    json_body: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
    max_attempts: int = 4,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> requests.Response:
    """
    Execute a Google Calendar HTTP request with automatic single-time 401 token
    refresh and exponential backoff on rate-limit / transient 5xx responses.
    """
    refreshed_once = False
    last_exc: Optional[Exception] = None

    for attempt in range(max_attempts):
        access_token = token_getter(refreshed_once)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                sleep_fn(0.4 * (2 ** attempt))
                continue
            raise GoogleApiError("Could not reach Google Calendar API. Please try again.") from exc

        if resp.status_code == 401 and not refreshed_once:
            refreshed_once = True
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt < max_attempts - 1:
                sleep_fn(0.5 * (2 ** attempt))
                continue
            msg, reason = _extract_google_error_reason(resp)
            raise GoogleApiError(
                msg or f"Google Calendar API temporarily unavailable (HTTP {resp.status_code}).",
                status_code=503 if resp.status_code >= 500 else 429,
                reason=reason,
            )

        if resp.status_code == 403:
            msg, reason = _extract_google_error_reason(resp)
            if reason in {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"} and attempt < max_attempts - 1:
                sleep_fn(0.6 * (2 ** attempt))
                continue
            if reason in {"insufficientPermissions", "forbidden"}:
                raise GoogleApiError(
                    "Google Calendar permission insufficient. Please disconnect and reconnect with calendar permissions.",
                    status_code=403,
                    reason=reason,
                )

        return resp

    raise GoogleApiError("Google Calendar API request failed after retries.") from last_exc


def _fetch_owned_profiles_and_validate_sync(
    admin: SupabaseAdminClient,
    user_id: str,
    profile_ids: List[str],
    sync_mode: str,
    years_ahead: Optional[int],
    specific_year: Optional[int],
    start_year: Optional[int],
    end_year: Optional[int],
    candidate_selections: Dict[str, int],
    today_override: Optional[date] = None,
    calculate_fn: Callable[..., FullResult] = calculate_panchang,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    entitlement = get_user_entitlement(admin, user_id, include_counts=True)
    conn = get_active_connection(admin, user_id)
    if not conn:
        raise GoogleOAuthError(
            "Please connect your Google Calendar account before synchronizing.",
            code="NOT_CONNECTED",
            status_code=400,
        )

    clean_ids: List[str] = []
    seen = set()
    for pid in profile_ids:
        p = str(pid or "").strip()
        if p and p not in seen:
            seen.add(p)
            clean_ids.append(p)

    all_events = admin.select(
        "google_calendar_events",
        filters={
            "user_id": f"eq.{user_id}",
            "google_connection_id": f"eq.{conn['id']}",
            "sync_status": "eq.synced",
        },
        columns="saved_birth_profile_id",
    )
    active_synced_pids = {str(r["saved_birth_profile_id"]) for r in all_events if r.get("saved_birth_profile_id")}

    mode = _resolve_sync_window_and_validate(
        entitlement=entitlement,
        profile_ids=clean_ids,
        sync_mode=sync_mode,
        years_ahead=years_ahead,
        specific_year=specific_year,
        start_year=start_year,
        end_year=end_year,
        active_synced_profile_ids=active_synced_pids,
    )

    user_profiles = admin.select(
        "saved_birth_profiles",
        filters={"user_id": f"eq.{user_id}"},
    )
    prof_by_id = {str(p["id"]): p for p in user_profiles}
    selected_profiles: List[Dict[str, Any]] = []
    for pid in clean_ids:
        if pid not in prof_by_id:
            raise ValueError("One or more selected birth profiles were not found for your account.")
        selected_profiles.append(prof_by_id[pid])

    plan = _compute_plan_for_profiles(
        admin=admin,
        user_id=user_id,
        connection_id=str(conn["id"]),
        profiles=selected_profiles,
        mode=mode,
        years_ahead=years_ahead,
        specific_year=specific_year,
        start_year=start_year,
        end_year=end_year,
        candidate_selections=candidate_selections,
        today_override=today_override,
        calculate_fn=calculate_fn,
    )
    return entitlement, conn, plan


def preview_google_sync(
    admin: SupabaseAdminClient,
    user_id: str,
    profile_ids: List[str],
    sync_mode: str = "upcoming_12m",
    years_ahead: Optional[int] = None,
    specific_year: Optional[int] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    candidate_selections: Optional[Dict[str, int]] = None,
    today_override: Optional[date] = None,
    calculate_fn: Callable[..., FullResult] = calculate_panchang,
) -> Dict[str, Any]:
    """Generate a non-mutating preview of calendar events to create/update."""
    entitlement, conn, plan = _fetch_owned_profiles_and_validate_sync(
        admin=admin,
        user_id=user_id,
        profile_ids=profile_ids,
        sync_mode=sync_mode,
        years_ahead=years_ahead,
        specific_year=specific_year,
        start_year=start_year,
        end_year=end_year,
        candidate_selections=candidate_selections or {},
        today_override=today_override,
        calculate_fn=calculate_fn,
    )

    preview_items = [
        {
            "profile_id": it["profile_id"],
            "profile_label": it["profile_label"],
            "hindu_year": it["hindu_year"],
            "gregorian_date": it["gregorian_date"],
            "weekday": it["weekday"],
            "lunar_month_en": it["lunar_month_en"],
            "tithi_label": it["tithi_label"],
            "observance_status": it["observance_status"],
            "action": it["action"],
            "notes": it["notes"],
        }
        for it in plan["planned_items"]
    ]

    return {
        "effective_tier": entitlement["effective_tier"],
        "connected_email": conn.get("google_email"),
        "mode": plan["mode"],
        "profiles": plan["profiles"],
        "counts": plan["counts"],
        "year_start": plan["year_start"],
        "year_end": plan["year_end"],
        "date_range": plan["date_range"],
        "items": preview_items,
        "skipped_items": plan["skipped_items"],
    }


def execute_google_sync_batch(
    admin: SupabaseAdminClient,
    user_id: str,
    client_id: str,
    client_secret: str,
    encryption_key: str,
    profile_ids: List[str],
    sync_mode: str = "upcoming_12m",
    years_ahead: Optional[int] = None,
    specific_year: Optional[int] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    candidate_selections: Optional[Dict[str, int]] = None,
    offset: int = 0,
    limit: int = _DEFAULT_BATCH_SIZE,
    accumulated: Optional[Dict[str, int]] = None,
    today_override: Optional[date] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    calculate_fn: Callable[..., FullResult] = calculate_panchang,
) -> Dict[str, Any]:
    """
    Execute a bounded chunk (`[offset : offset + limit]`) of calendar event
    creations/updates against Google Calendar API with duplicate prevention,
    manual-deletion auto-recovery, and retry handling.
    """
    _, conn, plan = _fetch_owned_profiles_and_validate_sync(
        admin=admin,
        user_id=user_id,
        profile_ids=profile_ids,
        sync_mode=sync_mode,
        years_ahead=years_ahead,
        specific_year=specific_year,
        start_year=start_year,
        end_year=end_year,
        candidate_selections=candidate_selections or {},
        today_override=today_override,
        calculate_fn=calculate_fn,
    )

    conn_id = str(conn["id"])
    all_items = plan["planned_items"]
    total = len(all_items)
    safe_offset = max(0, int(offset))
    safe_limit = max(1, min(_MAX_BATCH_SIZE, int(limit)))
    chunk = all_items[safe_offset : safe_offset + safe_limit]

    state_cache = {"token": None}

    def token_getter(force_refresh: bool) -> str:
        if state_cache["token"] and not force_refresh:
            return state_cache["token"]
        tok = get_valid_access_token(
            admin=admin,
            user_id=user_id,
            connection_id=conn_id,
            client_id=client_id,
            client_secret=client_secret,
            encryption_key=encryption_key,
            force_refresh=force_refresh,
        )
        state_cache["token"] = tok
        return tok

    created_count = 0
    updated_count = 0
    recreated_count = 0
    failed_count = 0
    errors: List[str] = []
    now = datetime.now(timezone.utc)

    for item in chunk:
        cal_id = item["google_calendar_id"] or "primary"
        payload = item["event_payload"]

        try:
            if item["action"] == "update" and item["existing_google_event_id"]:
                patch_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{cal_id}/events/{item['existing_google_event_id']}"
                resp = _google_calendar_request("PATCH", patch_url, token_getter, json_body=payload, sleep_fn=sleep_fn)

                needs_recreate = resp.status_code in (404, 410)
                if not needs_recreate and resp.status_code == 200:
                    body = resp.json() if resp.content else {}
                    if body.get("status") == "cancelled":
                        needs_recreate = True

                if needs_recreate:
                    create_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{cal_id}/events"
                    c_resp = _google_calendar_request("POST", create_url, token_getter, json_body=payload, sleep_fn=sleep_fn)
                    if c_resp.status_code not in (200, 201):
                        msg, _ = _extract_google_error_reason(c_resp)
                        raise GoogleApiError(msg or f"Recreate failed (HTTP {c_resp.status_code})", status_code=c_resp.status_code)
                    new_event = c_resp.json()
                    new_gid = str(new_event["id"])
                    admin.update(
                        "google_calendar_events",
                        filters={"id": f"eq.{item['existing_row_id']}", "user_id": f"eq.{user_id}"},
                        values={
                            "google_event_id": new_gid,
                            "profile_label_snapshot": item["profile_label"],
                            "candidate_index": item["candidate_index"],
                            "gregorian_date": item["gregorian_date"],
                            "lunar_month_en": item["lunar_month_en"],
                            "tithi_label": item["tithi_label"],
                            "observance_status": item["observance_status"],
                            "sync_status": "synced",
                            "last_error": None,
                            "last_synced_at": now.isoformat(),
                        },
                    )
                    created_count += 1
                    recreated_count += 1
                elif resp.status_code in (200, 201):
                    admin.update(
                        "google_calendar_events",
                        filters={"id": f"eq.{item['existing_row_id']}", "user_id": f"eq.{user_id}"},
                        values={
                            "profile_label_snapshot": item["profile_label"],
                            "candidate_index": item["candidate_index"],
                            "gregorian_date": item["gregorian_date"],
                            "lunar_month_en": item["lunar_month_en"],
                            "tithi_label": item["tithi_label"],
                            "observance_status": item["observance_status"],
                            "sync_status": "synced",
                            "last_error": None,
                            "last_synced_at": now.isoformat(),
                        },
                    )
                    updated_count += 1
                else:
                    msg, _ = _extract_google_error_reason(resp)
                    raise GoogleApiError(msg or f"Update failed (HTTP {resp.status_code})", status_code=resp.status_code)
            else:
                create_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{cal_id}/events"
                c_resp = _google_calendar_request("POST", create_url, token_getter, json_body=payload, sleep_fn=sleep_fn)
                if c_resp.status_code not in (200, 201):
                    msg, _ = _extract_google_error_reason(c_resp)
                    raise GoogleApiError(msg or f"Create failed (HTTP {c_resp.status_code})", status_code=c_resp.status_code)
                created_ev = c_resp.json()
                gid = str(created_ev["id"])
                admin.insert(
                    "google_calendar_events",
                    {
                        "user_id": user_id,
                        "google_connection_id": conn_id,
                        "saved_birth_profile_id": item["profile_id"],
                        "profile_label_snapshot": item["profile_label"],
                        "google_calendar_id": cal_id,
                        "google_event_id": gid,
                        "hindu_year": item["hindu_year"],
                        "candidate_index": item["candidate_index"],
                        "gregorian_date": item["gregorian_date"],
                        "lunar_month_en": item["lunar_month_en"],
                        "tithi_label": item["tithi_label"],
                        "observance_status": item["observance_status"],
                        "sync_status": "synced",
                        "last_error": None,
                        "last_synced_at": now.isoformat(),
                    },
                )
                created_count += 1
        except (GoogleReauthError, GoogleApiError) as exc:
            failed_count += 1
            errors.append(f"{item['profile_label']} ({item['hindu_year']}): {exc.message}")
            if isinstance(exc, GoogleReauthError):
                raise

    next_offset = min(total, safe_offset + len(chunk))
    done = next_offset >= total

    if done:
        prev = accumulated or {}
        total_created = int(prev.get("created", 0)) + created_count
        total_updated = int(prev.get("updated", 0)) + updated_count
        total_failed = int(prev.get("failed", 0)) + failed_count
        final_status = "error" if (total_failed > 0 and total_created == 0 and total_updated == 0) else (
            "partial" if total_failed > 0 else "success"
        )
        err_summary = "; ".join(errors[:5]) if errors else None

        admin.update(
            "google_calendar_connections",
            filters={"id": f"eq.{conn_id}", "user_id": f"eq.{user_id}"},
            values={
                "last_synced_at": now.isoformat(),
                "last_sync_status": final_status,
                "last_sync_error": err_summary,
            },
        )
        admin.insert(
            "google_sync_logs",
            {
                "user_id": user_id,
                "google_connection_id": conn_id,
                "action_type": "sync",
                "sync_mode": plan["mode"],
                "profile_count": len(plan["profiles"]),
                "year_start": plan["year_start"],
                "year_end": plan["year_end"],
                "created_count": total_created,
                "updated_count": total_updated,
                "deleted_count": 0,
                "failed_count": total_failed,
                "status": final_status,
                "error_message": err_summary,
            },
        )

    return {
        "processed": len(chunk),
        "created": created_count,
        "updated": updated_count,
        "recreated": recreated_count,
        "failed": failed_count,
        "errors": errors,
        "offset": safe_offset,
        "next_offset": next_offset,
        "total": total,
        "done": done,
    }


def delete_tithi_calendar_events(
    admin: SupabaseAdminClient,
    user_id: str,
    client_id: str,
    client_secret: str,
    encryption_key: str,
    scope: str = "single",
    event_record_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    connection_id_filter: Optional[str] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """
    Safely delete ONLY Tithi-created events tracked in `google_calendar_events`
    for the verified `user_id` AND verified to hold Tithi's `tithi_managed`
    private extendedProperty marker on Google Calendar.
    """
    scope_clean = (scope or "single").strip().lower()
    if scope_clean not in {"single", "profile", "year_range", "all"}:
        raise ValueError(f"Unsupported delete scope: '{scope_clean}'.")

    entitlement = get_user_entitlement(admin, user_id, include_counts=False)
    if scope_clean == "year_range" and not entitlement["is_plus"]:
        raise EntitlementError(
            "Deleting events by custom year range requires Tithi Plus.",
            code="PLUS_REQUIRED",
            status_code=403,
        )

    conn = get_active_connection(admin, user_id)
    if not conn:
        raise GoogleOAuthError(
            "Please connect your Google Calendar account to delete events from Google Calendar.",
            code="NOT_CONNECTED",
            status_code=400,
        )
    conn_id = connection_id_filter or str(conn["id"])

    filters: Dict[str, str] = {
        "user_id": f"eq.{user_id}",
        "google_connection_id": f"eq.{conn_id}",
        "sync_status": "neq.deleted",
    }
    if scope_clean == "single":
        if not event_record_id:
            raise ValueError("event_record_id is required for single event deletion.")
        filters["id"] = f"eq.{event_record_id}"
    elif scope_clean == "profile":
        if not profile_id:
            raise ValueError("profile_id is required for profile event deletion.")
        filters["saved_birth_profile_id"] = f"eq.{profile_id}"
    elif scope_clean == "year_range":
        if year_start is None or year_end is None:
            raise ValueError("year_start and year_end are required for year_range deletion.")
        ys, ye = int(year_start), int(year_end)
        if ye < ys:
            raise ValueError("year_end must be greater than or equal to year_start.")
        # Fetch user's active tracked events and filter range deterministically in Python
        if profile_id:
            filters["saved_birth_profile_id"] = f"eq.{profile_id}"

    rows = admin.select("google_calendar_events", filters=filters)
    if scope_clean == "year_range":
        ys, ye = int(year_start), int(year_end)  # type: ignore[arg-type]
        rows = [r for r in rows if ys <= int(r["hindu_year"]) <= ye]

    if not rows:
        return {"deleted_count": 0, "failed_count": 0, "already_missing_count": 0, "errors": []}

    state_cache = {"token": None}

    def token_getter(force_refresh: bool) -> str:
        if state_cache["token"] and not force_refresh:
            return state_cache["token"]
        tok = get_valid_access_token(
            admin=admin,
            user_id=user_id,
            connection_id=conn_id,
            client_id=client_id,
            client_secret=client_secret,
            encryption_key=encryption_key,
            force_refresh=force_refresh,
        )
        state_cache["token"] = tok
        return tok

    deleted_count = 0
    already_missing_count = 0
    failed_count = 0
    errors: List[str] = []

    for row in rows:
        cal_id = row.get("google_calendar_id") or "primary"
        gid = row.get("google_event_id")
        row_id = row["id"]
        if not gid:
            admin.update(
                "google_calendar_events",
                filters={"id": f"eq.{row_id}", "user_id": f"eq.{user_id}"},
                values={"sync_status": "deleted"},
            )
            deleted_count += 1
            continue

        event_url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{cal_id}/events/{gid}"
        try:
            # Verify Google event belongs to Tithi & this user before issuing DELETE
            get_resp = _google_calendar_request("GET", event_url, token_getter, sleep_fn=sleep_fn)
            if get_resp.status_code in (404, 410):
                admin.update(
                    "google_calendar_events",
                    filters={"id": f"eq.{row_id}", "user_id": f"eq.{user_id}"},
                    values={"sync_status": "deleted", "last_error": None},
                )
                deleted_count += 1
                already_missing_count += 1
                continue

            if get_resp.status_code == 200:
                g_ev = get_resp.json() if get_resp.content else {}
                if g_ev.get("status") == "cancelled":
                    admin.update(
                        "google_calendar_events",
                        filters={"id": f"eq.{row_id}", "user_id": f"eq.{user_id}"},
                        values={"sync_status": "deleted", "last_error": None},
                    )
                    deleted_count += 1
                    already_missing_count += 1
                    continue

                priv = (g_ev.get("extendedProperties") or {}).get("private") or {}
                if priv.get("tithi_managed") != "true" or str(priv.get("tithi_user_id") or "") != str(user_id):
                    failed_count += 1
                    errors.append(
                        f"Refused to delete {row.get('profile_label_snapshot')} ({row.get('hindu_year')}): "
                        "event is missing Tithi ownership marker."
                    )
                    continue

            elif get_resp.status_code >= 400:
                msg, _ = _extract_google_error_reason(get_resp)
                raise GoogleApiError(msg or f"Failed verifying event (HTTP {get_resp.status_code})", status_code=get_resp.status_code)

            del_resp = _google_calendar_request("DELETE", event_url, token_getter, sleep_fn=sleep_fn)
            if del_resp.status_code in (200, 204, 404, 410):
                admin.update(
                    "google_calendar_events",
                    filters={"id": f"eq.{row_id}", "user_id": f"eq.{user_id}"},
                    values={"sync_status": "deleted", "last_error": None},
                )
                deleted_count += 1
            else:
                msg, _ = _extract_google_error_reason(del_resp)
                raise GoogleApiError(msg or f"Google Calendar delete failed (HTTP {del_resp.status_code})", status_code=del_resp.status_code)
        except (GoogleReauthError, GoogleApiError) as exc:
            failed_count += 1
            errors.append(f"{row.get('profile_label_snapshot')} ({row.get('hindu_year')}): {exc.message}")
            if isinstance(exc, GoogleReauthError):
                raise

    admin.insert(
        "google_sync_logs",
        {
            "user_id": user_id,
            "google_connection_id": conn_id,
            "action_type": "delete",
            "sync_mode": scope_clean,
            "year_start": int(year_start) if year_start is not None else None,
            "year_end": int(year_end) if year_end is not None else None,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "status": "error" if (failed_count > 0 and deleted_count == 0) else ("partial" if failed_count > 0 else "success"),
            "error_message": "; ".join(errors[:5]) if errors else None,
        },
    )

    return {
        "deleted_count": deleted_count,
        "already_missing_count": already_missing_count,
        "failed_count": failed_count,
        "errors": errors,
    }
