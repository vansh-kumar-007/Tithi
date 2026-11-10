"""
Google OAuth 2.0, CSRF State Binding & Fernet Token Encryption Service.

Security invariants:
- Google client secret, refresh tokens, access tokens, and Fernet encryption
  key NEVER leave the backend.
- Refresh and access tokens are encrypted via Fernet (AES-128-CBC + HMAC-SHA256)
  before persistence into `google_oauth_credentials`.
- OAuth `state` is single-use, hashed with SHA-256, stored server-side with TTL,
  and cryptographically bound to an HttpOnly SameSite=Lax browser cookie nonce.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
import requests

from services.entitlement_service import parse_utc_timestamp
from services.supabase_service import SupabaseAdminClient

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

GOOGLE_OAUTH_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "email",
)

OAUTH_STATE_TTL_SECONDS = 600


class GoogleConfigError(Exception):
    """Raised when Google OAuth or encryption environment variables are missing/invalid."""


class GoogleOAuthError(Exception):
    """Raised on OAuth validation, state, CSRF, or token exchange errors."""

    def __init__(self, message: str, code: str = "GOOGLE_OAUTH_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class GoogleReauthError(GoogleOAuthError):
    """Raised when stored Google refresh token was revoked or expired."""

    def __init__(self, message: str = "Google Calendar permission was revoked or expired. Please reconnect your Google account."):
        super().__init__(message, code="GOOGLE_REAUTH_REQUIRED", status_code=401)


def sha256_hex(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _build_cipher(encryption_key: str) -> MultiFernet:
    raw = (encryption_key or "").strip()
    if not raw:
        raise GoogleConfigError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY is missing. Configure a Fernet key in server environment variables."
        )
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise GoogleConfigError("GOOGLE_TOKEN_ENCRYPTION_KEY is empty.")
    try:
        fernets = [Fernet(k.encode("utf-8")) for k in keys]
    except Exception as exc:
        raise GoogleConfigError(
            "Invalid GOOGLE_TOKEN_ENCRYPTION_KEY format. Expected a 32-byte URL-safe base64 Fernet key."
        ) from exc
    return MultiFernet(fernets)


def encrypt_token(plaintext: Optional[str], encryption_key: str) -> Optional[str]:
    """Encrypt an OAuth token with Fernet; returns ciphertext string."""
    if not plaintext:
        return None
    cipher = _build_cipher(encryption_key)
    return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: Optional[str], encryption_key: str) -> Optional[str]:
    """Decrypt a Fernet-encrypted OAuth token."""
    if not ciphertext:
        return None
    cipher = _build_cipher(encryption_key)
    try:
        return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise GoogleOAuthError(
            "Stored Google credentials could not be decrypted with the current server key. Please reconnect Google Calendar.",
            code="TOKEN_DECRYPT_FAILED",
            status_code=500,
        ) from exc


def require_google_oauth_config(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    encryption_key: str,
) -> None:
    if not (client_id or "").strip():
        raise GoogleConfigError("GOOGLE_CLIENT_ID is not configured.")
    if not (client_secret or "").strip():
        raise GoogleConfigError("GOOGLE_CLIENT_SECRET is not configured.")
    if not (redirect_uri or "").strip():
        raise GoogleConfigError("GOOGLE_REDIRECT_URI is not configured.")
    _build_cipher(encryption_key)


def get_active_connection(
    admin: SupabaseAdminClient,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    rows = admin.select(
        "google_calendar_connections",
        filters={"user_id": f"eq.{user_id}", "status": "eq.connected"},
        limit=1,
    )
    return rows[0] if rows else None


def get_latest_connection(
    admin: SupabaseAdminClient,
    user_id: str,
) -> Optional[Dict[str, Any]]:
    active = get_active_connection(admin, user_id)
    if active:
        return active
    rows = admin.select(
        "google_calendar_connections",
        filters={"user_id": f"eq.{user_id}"},
        order="updated_at.desc",
        limit=1,
    )
    return rows[0] if rows else None


def start_google_oauth_flow(
    admin: SupabaseAdminClient,
    user_id: str,
    client_id: str,
    redirect_uri: str,
    encryption_key: str,
    client_secret: str,
    now_utc: Optional[datetime] = None,
) -> Dict[str, str]:
    """
    Generate a single-use OAuth state and browser-bound nonce, persist hashed
    copies server-side, and return Google's authorization URL.
    """
    require_google_oauth_config(client_id, client_secret, redirect_uri, encryption_key)

    existing = get_active_connection(admin, user_id)
    if existing:
        raise GoogleOAuthError(
            "A Google Calendar account is already connected. Disconnect it first before connecting another account.",
            code="ALREADY_CONNECTED",
            status_code=409,
        )

    now = now_utc or datetime.now(timezone.utc)
    # Opportunistic cleanup of expired states for this user
    try:
        admin.delete(
            "oauth_states",
            filters={
                "user_id": f"eq.{user_id}",
                "expires_at": f"lt.{now.isoformat()}",
            },
        )
    except Exception:
        pass

    raw_state = secrets.token_urlsafe(32)
    browser_nonce = secrets.token_urlsafe(32)
    expires_at = now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)

    admin.insert(
        "oauth_states",
        {
            "user_id": user_id,
            "state_hash": sha256_hex(raw_state),
            "browser_nonce_hash": sha256_hex(browser_nonce),
            "expires_at": expires_at.isoformat(),
        },
    )

    params = {
        "client_id": client_id.strip(),
        "redirect_uri": redirect_uri.strip(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "state": raw_state,
    }
    return {
        "auth_url": f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}",
        "browser_nonce": browser_nonce,
    }


def complete_google_oauth_callback(
    admin: SupabaseAdminClient,
    raw_state: str,
    browser_nonce: str,
    code: str,
    error_param: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    encryption_key: str,
    now_utc: Optional[datetime] = None,
    timeout: int = 15,
) -> Dict[str, Any]:
    """
    Validate single-use OAuth CSRF state + browser nonce cookie, exchange the
    authorization code for tokens server-side, encrypt tokens with Fernet, and
    upsert connection + credential rows in Supabase.
    """
    require_google_oauth_config(client_id, client_secret, redirect_uri, encryption_key)

    state_clean = (raw_state or "").strip()
    nonce_clean = (browser_nonce or "").strip()
    if not state_clean or not nonce_clean:
        raise GoogleOAuthError(
            "Missing OAuth state or security cookie. Please initiate Google Calendar connection from My Account.",
            code="INVALID_STATE",
            status_code=400,
        )

    now = now_utc or datetime.now(timezone.utc)
    consumed_rows = admin.update(
        "oauth_states",
        filters={
            "state_hash": f"eq.{sha256_hex(state_clean)}",
            "consumed_at": "is.null",
        },
        values={"consumed_at": now.isoformat()},
    )
    if not consumed_rows:
        raise GoogleOAuthError(
            "Invalid, expired, or already-used OAuth state. Please try connecting again.",
            code="INVALID_STATE",
            status_code=400,
        )

    state_row = consumed_rows[0]
    expires_at = parse_utc_timestamp(state_row.get("expires_at"))
    if expires_at is None or now > expires_at:
        raise GoogleOAuthError(
            "Google connection request timed out. Please try again.",
            code="EXPIRED_STATE",
            status_code=400,
        )

    expected_nonce_hash = str(state_row.get("browser_nonce_hash") or "")
    actual_nonce_hash = sha256_hex(nonce_clean)
    if not hmac.compare_digest(expected_nonce_hash, actual_nonce_hash):
        raise GoogleOAuthError(
            "Security verification failed (OAuth browser binding mismatch).",
            code="CSRF_MISMATCH",
            status_code=400,
        )

    if error_param:
        raise GoogleOAuthError(
            f"Google authorization was cancelled or denied ({error_param}).",
            code="ACCESS_DENIED",
            status_code=400,
        )

    code_clean = (code or "").strip()
    if not code_clean:
        raise GoogleOAuthError("Missing Google authorization code.", code="MISSING_CODE", status_code=400)

    verified_user_id = str(state_row["user_id"])

    # Enforce active connection invariant right before linking
    existing_active = get_active_connection(admin, verified_user_id)
    if existing_active:
        raise GoogleOAuthError(
            "Another Google Calendar account is already active on this Tithi account.",
            code="ALREADY_CONNECTED",
            status_code=409,
        )

    # Exchange code -> tokens strictly server-to-server
    try:
        tok_resp = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code_clean,
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "redirect_uri": redirect_uri.strip(),
                "grant_type": "authorization_code",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError("Could not reach Google token service.", code="GOOGLE_NETWORK_ERROR", status_code=502) from exc

    if tok_resp.status_code != 200:
        raise GoogleOAuthError(
            "Failed to exchange Google authorization code for tokens.",
            code="TOKEN_EXCHANGE_FAILED",
            status_code=400,
        )

    tok_data = tok_resp.json() if tok_resp.content else {}
    access_token = str(tok_data.get("access_token") or "").strip()
    refresh_token = str(tok_data.get("refresh_token") or "").strip()
    expires_in = int(tok_data.get("expires_in") or 3600)
    scope = str(tok_data.get("scope") or " ".join(GOOGLE_OAUTH_SCOPES))
    token_type = str(tok_data.get("token_type") or "Bearer")

    if not access_token:
        raise GoogleOAuthError("Google did not return an access token.", code="MISSING_ACCESS_TOKEN", status_code=400)

    # Fetch connected Google user's subject ID & primary email
    try:
        info_resp = requests.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError("Could not fetch Google account profile.", code="GOOGLE_NETWORK_ERROR", status_code=502) from exc

    if info_resp.status_code != 200:
        raise GoogleOAuthError("Unable to verify Google account email.", code="USERINFO_FAILED", status_code=400)

    info_data = info_resp.json() if info_resp.content else {}
    google_sub = str(info_data.get("sub") or "").strip()
    google_email = str(info_data.get("email") or "").strip()
    if not google_sub or not google_email:
        raise GoogleOAuthError("Google account email/ID unavailable.", code="USERINFO_INCOMPLETE", status_code=400)

    existing_sub_rows = admin.select(
        "google_calendar_connections",
        filters={
            "user_id": f"eq.{verified_user_id}",
            "google_account_sub": f"eq.{google_sub}",
        },
        limit=1,
    )

    encrypted_refresh = encrypt_token(refresh_token, encryption_key) if refresh_token else None
    if not encrypted_refresh and existing_sub_rows:
        old_creds = admin.select(
            "google_oauth_credentials",
            filters={"connection_id": f"eq.{existing_sub_rows[0]['id']}"},
            limit=1,
        )
        if old_creds and old_creds[0].get("encrypted_refresh_token"):
            encrypted_refresh = old_creds[0]["encrypted_refresh_token"]

    if not encrypted_refresh:
        raise GoogleOAuthError(
            "Google did not issue an offline refresh token. Please remove Tithi in your Google Account third-party access settings and reconnect.",
            code="MISSING_REFRESH_TOKEN",
            status_code=400,
        )

    encrypted_access = encrypt_token(access_token, encryption_key)
    token_expires_at = (now + timedelta(seconds=max(60, expires_in))).isoformat()

    conn_rows = admin.insert(
        "google_calendar_connections",
        {
            "user_id": verified_user_id,
            "google_account_sub": google_sub,
            "google_email": google_email,
            "calendar_id": "primary",
            "scope": scope,
            "status": "connected",
            "connected_at": now.isoformat(),
            "disconnected_at": None,
            "last_sync_error": None,
        },
        upsert=True,
        on_conflict="user_id,google_account_sub",
    )
    conn = conn_rows[0]

    admin.insert(
        "google_oauth_credentials",
        {
            "connection_id": conn["id"],
            "user_id": verified_user_id,
            "encrypted_refresh_token": encrypted_refresh,
            "encrypted_access_token": encrypted_access,
            "token_expires_at": token_expires_at,
            "token_type": token_type,
        },
        upsert=True,
        on_conflict="connection_id",
    )

    admin.insert(
        "google_sync_logs",
        {
            "user_id": verified_user_id,
            "google_connection_id": conn["id"],
            "action_type": "connect",
            "status": "success",
        },
    )

    return {
        "user_id": verified_user_id,
        "connection": conn,
    }


def get_valid_access_token(
    admin: SupabaseAdminClient,
    user_id: str,
    connection_id: str,
    client_id: str,
    client_secret: str,
    encryption_key: str,
    now_utc: Optional[datetime] = None,
    force_refresh: bool = False,
    timeout: int = 15,
) -> str:
    """
    Return a valid decrypted Google access token, refreshing automatically
    with the encrypted refresh token when needed.
    """
    creds_rows = admin.select(
        "google_oauth_credentials",
        filters={
            "connection_id": f"eq.{connection_id}",
            "user_id": f"eq.{user_id}",
        },
        limit=1,
    )
    if not creds_rows:
        raise GoogleReauthError("Google credentials not found. Please reconnect your Google Calendar.")

    creds = creds_rows[0]
    now = now_utc or datetime.now(timezone.utc)
    expires_at = parse_utc_timestamp(creds.get("token_expires_at"))

    if (
        not force_refresh
        and creds.get("encrypted_access_token")
        and expires_at is not None
        and (expires_at - timedelta(seconds=90)) > now
    ):
        cached_access = decrypt_token(creds["encrypted_access_token"], encryption_key)
        if cached_access:
            return cached_access

    refresh_token = decrypt_token(creds.get("encrypted_refresh_token"), encryption_key)
    if not refresh_token:
        raise GoogleReauthError("Google refresh token is missing. Please reconnect Google Calendar.")

    if not client_id or not client_secret:
        raise GoogleConfigError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required to refresh tokens.")

    try:
        resp = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError("Could not reach Google to refresh access token.", code="GOOGLE_NETWORK_ERROR", status_code=502) from exc

    if resp.status_code in (400, 401):
        err_json = {}
        try:
            err_json = resp.json()
        except Exception:
            pass
        if err_json.get("error") in {"invalid_grant", "unauthorized_client"} or resp.status_code == 401:
            msg = "Google Calendar access expired or was revoked. Please reconnect your Google account."
            admin.update(
                "google_calendar_connections",
                filters={"id": f"eq.{connection_id}", "user_id": f"eq.{user_id}"},
                values={"status": "revoked", "last_sync_status": "error", "last_sync_error": msg},
            )
            raise GoogleReauthError(msg)
        raise GoogleOAuthError("Failed to refresh Google access token.", code="REFRESH_FAILED", status_code=502)

    if resp.status_code != 200:
        raise GoogleOAuthError(f"Unexpected Google token refresh error (HTTP {resp.status_code}).", code="REFRESH_FAILED", status_code=502)

    data = resp.json() if resp.content else {}
    new_access = str(data.get("access_token") or "").strip()
    if not new_access:
        raise GoogleOAuthError("Google refresh response did not include an access token.", code="REFRESH_FAILED", status_code=502)

    expires_in = int(data.get("expires_in") or 3600)
    new_expires_at = (now + timedelta(seconds=max(60, expires_in))).isoformat()
    update_vals: Dict[str, Any] = {
        "encrypted_access_token": encrypt_token(new_access, encryption_key),
        "token_expires_at": new_expires_at,
    }
    if data.get("refresh_token"):
        update_vals["encrypted_refresh_token"] = encrypt_token(str(data["refresh_token"]).strip(), encryption_key)

    admin.update(
        "google_oauth_credentials",
        filters={"connection_id": f"eq.{connection_id}", "user_id": f"eq.{user_id}"},
        values=update_vals,
    )
    return new_access


def revoke_google_token_best_effort(token: Optional[str], timeout: int = 8) -> bool:
    """Ask Google OAuth revocation endpoint to revoke a token without leaking secrets."""
    if not token:
        return False
    try:
        resp = requests.post(
            GOOGLE_REVOKE_ENDPOINT,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def disconnect_google_connection(
    admin: SupabaseAdminClient,
    user_id: str,
    encryption_key: str,
    delete_events_first: bool = False,
    delete_events_callback: Optional[Callable[[str], Dict[str, Any]]] = None,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Revoke Google OAuth access, remove stored encrypted credentials, and mark
    the connection disconnected. Optionally removes Tithi-created events first
    only when explicitly requested.
    """
    conn = get_active_connection(admin, user_id)
    if not conn:
        latest = get_latest_connection(admin, user_id)
        if latest and latest.get("status") == "revoked":
            conn = latest
        else:
            raise GoogleOAuthError(
                "No active Google Calendar connection found.",
                code="NOT_CONNECTED",
                status_code=404,
            )

    conn_id = str(conn["id"])
    deleted_summary: Dict[str, Any] = {"deleted_count": 0, "failed_count": 0}
    if delete_events_first and delete_events_callback is not None:
        deleted_summary = delete_events_callback(conn_id)

    creds_rows = admin.select(
        "google_oauth_credentials",
        filters={"connection_id": f"eq.{conn_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    revoked = False
    if creds_rows and encryption_key:
        for field in ("encrypted_refresh_token", "encrypted_access_token"):
            cipher_val = creds_rows[0].get(field)
            if cipher_val:
                try:
                    plain = decrypt_token(cipher_val, encryption_key)
                    if revoke_google_token_best_effort(plain):
                        revoked = True
                        break
                except GoogleOAuthError:
                    continue

    admin.delete(
        "google_oauth_credentials",
        filters={"connection_id": f"eq.{conn_id}", "user_id": f"eq.{user_id}"},
    )

    now = now_utc or datetime.now(timezone.utc)
    admin.update(
        "google_calendar_connections",
        filters={"id": f"eq.{conn_id}", "user_id": f"eq.{user_id}"},
        values={
            "status": "disconnected",
            "disconnected_at": now.isoformat(),
            "last_sync_error": None,
        },
    )

    admin.insert(
        "google_sync_logs",
        {
            "user_id": user_id,
            "google_connection_id": conn_id,
            "action_type": "disconnect",
            "deleted_count": int(deleted_summary.get("deleted_count", 0)),
            "failed_count": int(deleted_summary.get("failed_count", 0)),
            "status": "success",
        },
    )

    return {
        "disconnected": True,
        "google_token_revoked": revoked,
        "deleted_events_count": int(deleted_summary.get("deleted_count", 0)),
    }


def revoke_all_user_google_tokens_before_account_delete(
    supabase_url: str,
    service_role_key: str,
    encryption_key: str,
    user_id: str,
) -> None:
    """
    Best-effort revocation of Google OAuth credentials prior to permanent Tithi
    account deletion. Never leaves unrevoked tokens dangling when possible and
    never deletes external Google Calendar events silently.
    """
    if not supabase_url or not service_role_key or not encryption_key:
        return
    try:
        admin = SupabaseAdminClient(supabase_url, service_role_key)
        creds = admin.select(
            "google_oauth_credentials",
            filters={"user_id": f"eq.{user_id}"},
        )
        for row in creds:
            for field in ("encrypted_refresh_token", "encrypted_access_token"):
                cipher_val = row.get(field)
                if not cipher_val:
                    continue
                try:
                    plain = decrypt_token(cipher_val, encryption_key)
                    if revoke_google_token_best_effort(plain):
                        break
                except Exception:
                    continue
    except Exception:
        # Never block user-initiated account deletion if Google revoke fails
        return
