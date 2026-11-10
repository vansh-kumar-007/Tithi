"""
Server-side Supabase integration helpers.

Used strictly for server-side JWT verification and permanent account deletion
using SUPABASE_SERVICE_ROLE_KEY (which is never exposed to the browser).
"""
from __future__ import annotations

from typing import Dict, Optional
import requests


class SupabaseAuthError(Exception):
    """Raised when the user's Supabase JWT is missing, invalid, or expired."""


class SupabaseConfigError(Exception):
    """Raised when required server-side Supabase configuration is missing."""


class SupabaseServiceError(Exception):
    """Raised when Supabase returns an unexpected upstream error."""


def verify_user_jwt(
    access_token: str,
    supabase_url: str,
    api_key: str,
    timeout: int = 10,
) -> Dict[str, object]:
    """
    Verify a Supabase Auth JWT by asking Supabase Auth (/auth/v1/user).
    Never trusts a client-supplied user_id; returns the verified user object.
    """
    if not supabase_url or not api_key:
        raise SupabaseConfigError("Supabase server authentication is not configured.")
    token = (access_token or "").strip()
    if not token:
        raise SupabaseAuthError("Authentication token is required.")

    url = f"{supabase_url.rstrip('/')}/auth/v1/user"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {token}",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise SupabaseServiceError("Could not reach authentication service.") from exc

    if resp.status_code in (401, 403):
        raise SupabaseAuthError("Your session has expired or is invalid. Please log in again.")
    if resp.status_code != 200:
        raise SupabaseServiceError(f"Unexpected authentication response (HTTP {resp.status_code}).")

    data = resp.json()
    if not isinstance(data, dict) or not data.get("id"):
        raise SupabaseAuthError("Unable to verify user identity from token.")
    return data


def delete_supabase_user_account(
    access_token: str,
    supabase_url: str,
    anon_key: str,
    service_role_key: str,
    timeout: int = 15,
) -> Dict[str, Optional[str]]:
    """
    Verify the caller's JWT and permanently delete their Supabase Auth user
    via the Admin API. PostgreSQL ON DELETE CASCADE removes all associated
    saved_birth_profiles and calculation_history rows automatically.
    """
    if not supabase_url or not service_role_key:
        raise SupabaseConfigError(
            "Server-side account deletion is not configured (missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY)."
        )

    # Verify JWT using anon_key (or service_role_key as apikey fallback)
    user = verify_user_jwt(
        access_token=access_token,
        supabase_url=supabase_url,
        api_key=anon_key or service_role_key,
        timeout=timeout,
    )
    verified_user_id = str(user["id"])
    verified_email = user.get("email")

    admin_url = f"{supabase_url.rstrip('/')}/auth/v1/admin/users/{verified_user_id}"
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.delete(admin_url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise SupabaseServiceError("Could not connect to Supabase Admin API.") from exc

    if resp.status_code not in (200, 204):
        raise SupabaseServiceError(f"Failed to delete account (HTTP {resp.status_code}).")

    return {"id": verified_user_id, "email": verified_email}
