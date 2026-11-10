"""
Server-side Supabase integration helpers.

Used strictly for server-side JWT verification, PostgREST / RPC operations with
SUPABASE_SERVICE_ROLE_KEY, and permanent account deletion.
SUPABASE_SERVICE_ROLE_KEY is NEVER exposed to the browser.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
import requests


class SupabaseAuthError(Exception):
    """Raised when the user's Supabase JWT is missing, invalid, or expired."""


class SupabaseConfigError(Exception):
    """Raised when required server-side Supabase configuration is missing."""


class SupabaseServiceError(Exception):
    """Raised when Supabase returns an unexpected upstream error."""


class SupabaseConstraintError(SupabaseServiceError):
    """Raised on PostgreSQL constraint/limit violations (e.g., duplicate or quota exceeded)."""


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
    before_delete: Optional[Callable[[str], None]] = None,
) -> Dict[str, Optional[str]]:
    """
    Verify the caller's JWT and permanently delete their Supabase Auth user
    via the Admin API. PostgreSQL ON DELETE CASCADE removes all associated
    Tithi database records automatically.
    """
    if not supabase_url or not service_role_key:
        raise SupabaseConfigError(
            "Server-side account deletion is not configured (missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY)."
        )

    user = verify_user_jwt(
        access_token=access_token,
        supabase_url=supabase_url,
        api_key=anon_key or service_role_key,
        timeout=timeout,
    )
    verified_user_id = str(user["id"])
    verified_email = user.get("email")

    if before_delete is not None:
        before_delete(verified_user_id)

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


class SupabaseAdminClient:
    """Minimal PostgREST & RPC client authenticated with SUPABASE_SERVICE_ROLE_KEY."""

    def __init__(self, supabase_url: str, service_role_key: str, timeout: int = 15):
        self.supabase_url = (supabase_url or "").strip().rstrip("/")
        self.service_role_key = (service_role_key or "").strip()
        self.timeout = timeout
        if not self.supabase_url or not self.service_role_key:
            raise SupabaseConfigError(
                "Server-side Supabase configuration is missing (SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY)."
            )

    def _headers(self, prefer: Optional[str] = None) -> Dict[str, str]:
        hdrs = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if prefer:
            hdrs["Prefer"] = prefer
        return hdrs

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, str]] = None,
        json_body: Any = None,
        prefer: Optional[str] = None,
    ) -> Any:
        url = f"{self.supabase_url}/rest/v1/{path.lstrip('/')}"
        try:
            resp = requests.request(
                method,
                url,
                headers=self._headers(prefer=prefer),
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SupabaseServiceError("Could not reach database service.") from exc

        if resp.status_code >= 400:
            err_text = ""
            err_code = ""
            try:
                body = resp.json()
                if isinstance(body, dict):
                    err_text = str(body.get("message") or body.get("hint") or body.get("details") or "")
                    err_code = str(body.get("code") or "")
            except Exception:
                err_text = (resp.text or "")[:200]

            if resp.status_code == 409 or err_code in {"23505", "P0001"} or "FREE_PROFILE_LIMIT_REACHED" in err_text:
                raise SupabaseConstraintError(err_text or f"Database constraint error (HTTP {resp.status_code}).")
            raise SupabaseServiceError(err_text or f"Database request failed (HTTP {resp.status_code}).")

        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def select(
        self,
        table: str,
        filters: Optional[Dict[str, str]] = None,
        columns: str = "*",
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, str] = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(int(limit))
        res = self._request("GET", table, params=params)
        return res if isinstance(res, list) else []

    def insert(
        self,
        table: str,
        payload: Any,
        upsert: bool = False,
        on_conflict: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        prefer_parts = ["return=representation"]
        params: Dict[str, str] = {}
        if upsert:
            prefer_parts.insert(0, "resolution=merge-duplicates")
            if on_conflict:
                params["on_conflict"] = on_conflict
        res = self._request(
            "POST",
            table,
            params=params or None,
            json_body=payload,
            prefer=",".join(prefer_parts),
        )
        return res if isinstance(res, list) else []

    def update(
        self,
        table: str,
        filters: Dict[str, str],
        values: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        res = self._request(
            "PATCH",
            table,
            params=filters,
            json_body=values,
            prefer="return=representation",
        )
        return res if isinstance(res, list) else []

    def delete(
        self,
        table: str,
        filters: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        res = self._request(
            "DELETE",
            table,
            params=filters,
            prefer="return=representation",
        )
        return res if isinstance(res, list) else []

    def rpc(self, fn_name: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", f"rpc/{fn_name}", json_body=payload or {})
