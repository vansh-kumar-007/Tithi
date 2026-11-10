"""
Server-side Freemium Entitlement & 14-Day Plus Trial Service.

Every plan limit, trial expiration, and upgrade check is evaluated against
server-side timestamps and Supabase PostgreSQL records — never client state.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional

from services.supabase_service import SupabaseAdminClient

FREE_MAX_PROFILES = 3
FREE_MAX_SYNC_PROFILES = 1
FREE_UPCOMING_MONTHS = 12
TRIAL_DURATION_DAYS = 14


class EntitlementError(Exception):
    """Raised when an operation is blocked by plan limits or trial state."""

    def __init__(
        self,
        message: str,
        code: str = "ENTITLEMENT_REQUIRED",
        status_code: int = 403,
        extra: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.extra = extra or {}


def parse_utc_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into a timezone-aware UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_entitlement(
    row: Optional[Dict[str, Any]],
    now_utc: Optional[datetime] = None,
    profile_count: int = 0,
    synced_profile_count: int = 0,
) -> Dict[str, Any]:
    """
    Evaluate effective tier, trial status, remaining days, and feature limits
    from a `user_entitlements` database row using server UTC time.
    """
    now = now_utc or datetime.now(timezone.utc)
    row = row or {}

    plan = str(row.get("plan") or "free").lower()
    sub_status = str(row.get("subscription_status") or "none").lower()
    period_end = parse_utc_timestamp(row.get("current_period_end"))

    trial_used = bool(row.get("trial_used", False))
    trial_started = parse_utc_timestamp(row.get("trial_started_at"))
    trial_expires = parse_utc_timestamp(row.get("trial_expires_at"))
    stored_trial_status = str(row.get("trial_status") or ("used" if trial_used else "eligible")).lower()

    has_paid_plus = (
        plan == "plus"
        and sub_status == "active"
        and (period_end is None or period_end > now)
    )

    has_active_trial = (
        not has_paid_plus
        and trial_used
        and trial_started is not None
        and trial_expires is not None
        and now < trial_expires
    )

    if has_paid_plus:
        effective_tier = "plus"
        plus_source = "subscription"
        resolved_trial_status = "expired" if (trial_used and trial_expires and now >= trial_expires) else (
            "active" if (trial_used and trial_expires and now < trial_expires) else (
                "expired" if trial_used else "eligible"
            )
        )
        trial_days_remaining = 0
    elif has_active_trial:
        effective_tier = "plus"
        plus_source = "trial"
        resolved_trial_status = "active"
        seconds_left = max(0.0, (trial_expires - now).total_seconds())
        trial_days_remaining = max(1, math.ceil(seconds_left / 86400.0))
    elif trial_used:
        effective_tier = "free"
        plus_source = None
        resolved_trial_status = "expired"
        trial_days_remaining = 0
    else:
        effective_tier = "free"
        plus_source = None
        resolved_trial_status = "eligible"
        trial_days_remaining = 0

    is_plus = effective_tier == "plus"
    needs_expiry_sync = (
        not has_active_trial
        and trial_used
        and stored_trial_status == "active"
    )

    return {
        "plan": plan,
        "effective_tier": effective_tier,
        "is_plus": is_plus,
        "plus_source": plus_source,
        "ads_enabled": not is_plus,
        "trial_status": resolved_trial_status,
        "trial_used": trial_used,
        "trial_eligible": (not trial_used and not has_paid_plus),
        "trial_started_at": trial_started.isoformat() if trial_started else None,
        "trial_expires_at": trial_expires.isoformat() if trial_expires else None,
        "trial_days_remaining": trial_days_remaining,
        "trial_expired": (resolved_trial_status == "expired" and not has_paid_plus),
        "needs_expiry_sync": needs_expiry_sync,
        "subscription_status": sub_status,
        "subscription_provider": row.get("subscription_provider"),
        "subscription_reference": row.get("subscription_reference"),
        "current_period_end": period_end.isoformat() if period_end else None,
        "profile_count": profile_count,
        "synced_profile_count": synced_profile_count,
        "over_profile_limit": (not is_plus and profile_count > FREE_MAX_PROFILES),
        "can_create_profile": (is_plus or profile_count < FREE_MAX_PROFILES),
        "limits": {
            "max_profiles": None if is_plus else FREE_MAX_PROFILES,
            "max_sync_profiles": None if is_plus else FREE_MAX_SYNC_PROFILES,
            "upcoming_months": None if is_plus else FREE_UPCOMING_MONTHS,
            "allow_upcoming_years": is_plus,
            "allow_specific_year": is_plus,
            "allow_year_range": is_plus,
            "allow_bulk_sync": is_plus,
            "allow_year_range_delete": is_plus,
        },
    }


def _count_user_profiles_and_synced(admin: SupabaseAdminClient, user_id: str) -> tuple[int, int]:
    profiles = admin.select(
        "saved_birth_profiles",
        filters={"user_id": f"eq.{user_id}"},
        columns="id",
    )
    active_conns = admin.select(
        "google_calendar_connections",
        filters={"user_id": f"eq.{user_id}", "status": "eq.connected"},
        columns="id",
        limit=1,
    )
    if not active_conns:
        return len(profiles), 0

    conn_id = str(active_conns[0]["id"])
    events = admin.select(
        "google_calendar_events",
        filters={
            "user_id": f"eq.{user_id}",
            "google_connection_id": f"eq.{conn_id}",
            "sync_status": "eq.synced",
        },
        columns="saved_birth_profile_id",
    )
    synced_profile_ids = {
        str(ev["saved_birth_profile_id"])
        for ev in events
        if ev.get("saved_birth_profile_id")
    }
    return len(profiles), len(synced_profile_ids)


def get_user_entitlement(
    admin: SupabaseAdminClient,
    user_id: str,
    now_utc: Optional[datetime] = None,
    include_counts: bool = True,
) -> Dict[str, Any]:
    """
    Fetch (or lazily initialize) a user's entitlement row, automatically
    reconciling expired trials against server time.
    """
    rows = admin.select(
        "user_entitlements",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        created = admin.insert(
            "user_entitlements",
            {"user_id": user_id},
            upsert=True,
            on_conflict="user_id",
        )
        row = created[0] if created else {"user_id": user_id, "plan": "free", "trial_status": "eligible", "trial_used": False}
    else:
        row = rows[0]

    profile_count, synced_count = (
        _count_user_profiles_and_synced(admin, user_id) if include_counts else (0, 0)
    )
    evaluated = evaluate_entitlement(
        row,
        now_utc=now_utc,
        profile_count=profile_count,
        synced_profile_count=synced_count,
    )

    if evaluated["needs_expiry_sync"]:
        admin.update(
            "user_entitlements",
            filters={"user_id": f"eq.{user_id}", "trial_status": "eq.active"},
            values={"trial_status": "expired"},
        )

    evaluated.pop("needs_expiry_sync", None)
    return evaluated


def activate_plus_trial(
    admin: SupabaseAdminClient,
    user_id: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Atomically activate the one-time 14-day Tithi Plus trial via PostgreSQL RPC
    `activate_plus_trial`. Never allows a second trial on the same account.
    """
    current = get_user_entitlement(admin, user_id, now_utc=now_utc, include_counts=True)
    if current["plus_source"] == "subscription":
        raise EntitlementError(
            "Your account already has an active Tithi Plus subscription.",
            code="ALREADY_SUBSCRIBED",
            status_code=409,
        )
    if current["trial_used"]:
        raise EntitlementError(
            "Your 14-day free Tithi Plus trial has already been used for this account.",
            code="TRIAL_ALREADY_USED",
            status_code=409,
        )

    rpc_res = admin.rpc("activate_plus_trial", {"p_user_id": user_id})
    updated_rows: List[Dict[str, Any]] = rpc_res if isinstance(rpc_res, list) else []
    if not updated_rows:
        raise EntitlementError(
            "Your 14-day free Tithi Plus trial has already been used for this account.",
            code="TRIAL_ALREADY_USED",
            status_code=409,
        )

    evaluated = evaluate_entitlement(
        updated_rows[0],
        now_utc=now_utc,
        profile_count=current["profile_count"],
        synced_profile_count=current["synced_profile_count"],
    )
    evaluated.pop("needs_expiry_sync", None)
    return evaluated


def assert_can_create_birth_profile(
    admin: SupabaseAdminClient,
    user_id: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Enforce Free tier's max 3 saved birth profiles server-side."""
    entitlement = get_user_entitlement(admin, user_id, now_utc=now_utc, include_counts=True)
    if not entitlement["is_plus"] and entitlement["profile_count"] >= FREE_MAX_PROFILES:
        raise EntitlementError(
            f"Free accounts can save up to {FREE_MAX_PROFILES} birth profiles. "
            "Start your 14-day free Tithi Plus trial or remove an existing profile to add another.",
            code="PROFILE_LIMIT_REACHED",
            status_code=403,
            extra={
                "limit": FREE_MAX_PROFILES,
                "current_count": entitlement["profile_count"],
                "upgrade_required": True,
                "trial_eligible": entitlement["trial_eligible"],
            },
        )
    return entitlement
