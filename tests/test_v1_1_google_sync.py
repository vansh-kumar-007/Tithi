"""
Comprehensive V1.1 tests for:
- Google OAuth 2.0 state/CSRF validation & connection workflow
- Fernet token encryption, decryption & refresh/revocation handling
- Freemium tier limits (Free 3 profiles, 1 synced profile, upcoming 12m)
- Atomic once-per-account 14-day Plus trial activation & server-side expiry
- Plus multi-profile / upcoming years / specific year / custom year range sync
- Bounded batching, Google API retries, duplicate prevention & manual-delete recovery
- Ownership-verified event deletion & non-Tithi event protection
- Cross-user isolation, SQL migration RLS/grants & account deletion revocation
- Secret non-exposure & bilingual EN/HI UI support
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
import re
import sys
import uuid
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app
from services.entitlement_service import (
    EntitlementError,
    activate_plus_trial,
    evaluate_entitlement,
    get_user_entitlement,
)
from services.google_oauth_service import (
    GoogleConfigError,
    GoogleOAuthError,
    GoogleReauthError,
    complete_google_oauth_callback,
    decrypt_token,
    disconnect_google_connection,
    encrypt_token,
    get_valid_access_token,
    start_google_oauth_flow,
)
from services.google_sync_service import (
    delete_tithi_calendar_events,
    execute_google_sync_batch,
    preview_google_sync,
)


class FakeSupabaseAdmin:
    """In-memory PostgREST / RPC simulator enforcing filtering & uniqueness for tests."""

    def __init__(self):
        self.tables = {
            "user_entitlements": [],
            "saved_birth_profiles": [],
            "google_calendar_connections": [],
            "google_oauth_credentials": [],
            "oauth_states": [],
            "google_calendar_events": [],
            "google_sync_logs": [],
        }
        self.now_fn = lambda: datetime.now(timezone.utc)

    @staticmethod
    def _matches(row: dict, filters: dict | None) -> bool:
        if not filters:
            return True
        for col, expr in filters.items():
            val = row.get(col)
            if expr == "is.null":
                if val is not None:
                    return False
            elif expr.startswith("eq."):
                target = expr[3:]
                if str(val) != target and not (val is False and target == "false") and not (val is True and target == "true"):
                    return False
                if val is None:
                    return False
            elif expr.startswith("neq."):
                target = expr[4:]
                if str(val) == target:
                    return False
            elif expr.startswith("lt."):
                if val is None or str(val) >= expr[3:]:
                    return False
        return True

    def select(self, table, filters=None, columns="*", order=None, limit=None):
        rows = [dict(r) for r in self.tables[table] if self._matches(r, filters)]
        if order:
            first_order = order.split(",")[0]
            col, _, direction = first_order.partition(".")
            rows.sort(key=lambda r: str(r.get(col) or ""), reverse=(direction == "desc"))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def insert(self, table, payload, upsert=False, on_conflict=None):
        items = payload if isinstance(payload, list) else [payload]
        out = []
        now_iso = self.now_fn().isoformat()
        for raw in items:
            row = dict(raw)
            if upsert and on_conflict:
                keys = [k.strip() for k in on_conflict.split(",")]
                matched = None
                for existing in self.tables[table]:
                    if all(str(existing.get(k)) == str(row.get(k)) for k in keys):
                        matched = existing
                        break
                if matched is not None:
                    matched.update(row)
                    matched["updated_at"] = now_iso
                    out.append(dict(matched))
                    continue

            if table != "user_entitlements" and table != "google_oauth_credentials":
                row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", now_iso)
            row.setdefault("updated_at", now_iso)
            if table == "user_entitlements":
                row.setdefault("plan", "free")
                row.setdefault("trial_status", "eligible")
                row.setdefault("trial_used", False)
                row.setdefault("subscription_status", "none")

            self.tables[table].append(row)
            out.append(dict(row))
        return out

    def update(self, table, filters, values):
        updated = []
        now_iso = self.now_fn().isoformat()
        for row in self.tables[table]:
            if self._matches(row, filters):
                row.update(values)
                row["updated_at"] = now_iso
                updated.append(dict(row))
        return updated

    def delete(self, table, filters):
        kept = []
        removed = []
        for row in self.tables[table]:
            if self._matches(row, filters):
                removed.append(dict(row))
            else:
                kept.append(row)
        self.tables[table] = kept
        return removed

    def rpc(self, fn_name, payload=None):
        payload = payload or {}
        if fn_name == "activate_plus_trial":
            uid = str(payload["p_user_id"])
            rows = self.select("user_entitlements", {"user_id": f"eq.{uid}"})
            if not rows:
                rows = self.insert("user_entitlements", {"user_id": uid})
            row = rows[0]
            if row.get("trial_used") or row.get("trial_started_at"):
                return []
            now = self.now_fn()
            return self.update(
                "user_entitlements",
                {"user_id": f"eq.{uid}"},
                {
                    "trial_used": True,
                    "trial_status": "active",
                    "trial_started_at": now.isoformat(),
                    "trial_expires_at": (now + timedelta(days=14)).isoformat(),
                },
            )
        raise NotImplementedError(fn_name)


def _sample_profile_payload(label="Mom"):
    return {
        "label": label,
        "birth_date": "2004-05-28",
        "lat": 29.3724,
        "lon": 78.1358,
        "timezone": "Asia/Kolkata",
        "location_name": "Bijnor, Uttar Pradesh, India",
        "ayanamsha": "lahiri",
        "lunar_system": "amanta",
        "observance_method": "sunrise",
        "adhika_rule": "nija",
        "birth_time_mode": "exact",
        "birth_time": "04:00",
        "start_year": 2024,
        "end_year": 2030,
    }


def _make_app_with_google(fernet_key: str):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key-at-least-16-chars",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "public-anon-test-key",
        "SUPABASE_SERVICE_ROLE_KEY": "server-only-service-role-secret",
        "GOOGLE_CLIENT_ID": "test-google-client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "super-secret-google-client-secret",
        "GOOGLE_REDIRECT_URI": "http://localhost:5000/auth/google/callback",
        "GOOGLE_TOKEN_ENCRYPTION_KEY": fernet_key,
    })


class TestTokenEncryptionAndSecurity:
    def test_token_encryption_decryption_and_key_validation(self):
        key = Fernet.generate_key().decode("utf-8")
        plaintext = "1//0g-refresh-token-very-secret"
        cipher = encrypt_token(plaintext, key)
        assert cipher is not None
        assert cipher != plaintext
        assert plaintext not in cipher
        assert decrypt_token(cipher, key) == plaintext

        with pytest.raises(GoogleConfigError):
            encrypt_token(plaintext, "")
        with pytest.raises(GoogleConfigError):
            encrypt_token(plaintext, "not-a-valid-fernet-key")
        with pytest.raises(GoogleOAuthError):
            decrypt_token("tampered-ciphertext", key)

    def test_secrets_never_exposed_in_templates_js_or_diagnostics(self):
        key = Fernet.generate_key().decode("utf-8")
        app = _make_app_with_google(key)
        client = app.test_client()

        for route in ("/", "/account", "/privacy", "/api/supabase-status", "/api/google-status"):
            resp = client.get(route)
            assert resp.status_code == 200
            body = resp.data.decode("utf-8")
            assert "super-secret-google-client-secret" not in body
            assert "server-only-service-role-secret" not in body
            assert key not in body

        auth_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "js", "supabase_auth.js")
        with open(auth_js_path, "r", encoding="utf-8") as fh:
            js = fh.read()
        assert "GOOGLE_CLIENT_SECRET" not in js
        assert "GOOGLE_TOKEN_ENCRYPTION_KEY" not in js
        assert "refresh_token" not in js


class TestAuthAndOAuthFlow:
    def setup_method(self):
        self.key = Fernet.generate_key().decode("utf-8")
        self.app = _make_app_with_google(self.key)
        self.client = self.app.test_client()
        self.fake_admin = FakeSupabaseAdmin()

    def test_protected_endpoints_reject_missing_and_expired_jwt(self):
        endpoints = [
            ("GET", "/api/entitlements"),
            ("POST", "/api/entitlements/start-trial"),
            ("GET", "/api/profiles"),
            ("POST", "/api/profiles"),
            ("GET", "/api/google/status"),
            ("POST", "/api/google/oauth/start"),
            ("POST", "/api/google/sync/preview"),
            ("POST", "/api/google/sync/execute"),
            ("POST", "/api/google/events/delete"),
            ("POST", "/api/google/disconnect"),
        ]
        for method, path in endpoints:
            r = self.client.open(path, method=method, json={})
            assert r.status_code == 401

        with patch("app.verify_user_jwt", side_effect=Exception("should not reach")):
            pass

        expired_resp = MagicMock(status_code=401)
        with patch("services.supabase_service.requests.get", return_value=expired_resp):
            for method, path in endpoints:
                r = self.client.open(
                    path,
                    method=method,
                    headers={"Authorization": "Bearer expired-token"},
                    json={},
                )
                assert r.status_code == 401

    def test_oauth_state_validation_and_csrf_protection(self):
        uid = "11111111-1111-1111-1111-111111111111"

        with patch("app._get_admin_client", create=True), \
             patch("app.SupabaseAdminClient", return_value=self.fake_admin), \
             patch("services.supabase_service.requests.get", return_value=MagicMock(status_code=200, json=lambda: {"id": uid, "email": "u1@example.com"})):

            # 1. Start OAuth flow
            start_resp = self.client.post(
                "/api/google/oauth/start",
                headers={"Authorization": "Bearer valid-jwt"},
                json={},
            )
            assert start_resp.status_code == 200
            auth_url = json.loads(start_resp.data)["auth_url"]
            assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar.events+openid+email" in auth_url
            assert "access_type=offline" in auth_url
            assert "prompt=consent" in auth_url
            m = re.search(r"state=([^&]+)", auth_url)
            assert m
            state_val = m.group(1)

            # 2. Missing nonce cookie -> fails CSRF binding
            c2 = self.app.test_client()
            r_no_cookie = c2.get(f"/auth/google/callback?state={state_val}&code=authcode123")
            assert r_no_cookie.status_code == 302
            assert "google_error=INVALID_STATE" in r_no_cookie.location
            assert self.fake_admin.tables["google_calendar_connections"] == []

            # 3. Wrong nonce cookie -> fails CSRF mismatch (note state was already consumed? Let's start a fresh state)
            start_resp2 = self.client.post(
                "/api/google/oauth/start",
                headers={"Authorization": "Bearer valid-jwt"},
                json={},
            )
            state_val2 = re.search(r"state=([^&]+)", json.loads(start_resp2.data)["auth_url"]).group(1)
            c2.set_cookie("tithi_google_oauth_nonce", "attacker-forged-nonce", path="/auth/google/callback")
            r_csrf = c2.get(f"/auth/google/callback?state={state_val2}&code=authcode123")
            assert "google_error=CSRF_MISMATCH" in r_csrf.location
            assert self.fake_admin.tables["google_calendar_connections"] == []

            # 4. Replay of same consumed state fails
            r_replay = self.client.get(f"/auth/google/callback?state={state_val2}&code=authcode123")
            assert "google_error=INVALID_STATE" in r_replay.location

            # 5. Happy-path callback connects & encrypts tokens
            start_resp3 = self.client.post(
                "/api/google/oauth/start",
                headers={"Authorization": "Bearer valid-jwt"},
                json={},
            )
            state_val3 = re.search(r"state=([^&]+)", json.loads(start_resp3.data)["auth_url"]).group(1)

            mock_tok = MagicMock(status_code=200, content=b"{}")
            mock_tok.json.return_value = {
                "access_token": "plain-access-xyz",
                "refresh_token": "plain-refresh-xyz",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.events openid email",
                "token_type": "Bearer",
            }
            mock_info = MagicMock(status_code=200, content=b"{}")
            mock_info.json.return_value = {"sub": "google-sub-123", "email": "devotee@gmail.com"}

            with patch("services.google_oauth_service.requests.post", return_value=mock_tok), \
                 patch("services.google_oauth_service.requests.get", return_value=mock_info):
                cb = self.client.get(f"/auth/google/callback?state={state_val3}&code=valid-code")

            assert cb.status_code == 302
            assert "google_connected=1" in cb.location
            conns = self.fake_admin.tables["google_calendar_connections"]
            creds = self.fake_admin.tables["google_oauth_credentials"]
            assert len(conns) == 1
            assert conns[0]["google_email"] == "devotee@gmail.com"
            assert conns[0]["status"] == "connected"
            assert len(creds) == 1
            # Plaintext tokens MUST NEVER appear in stored DB rows
            assert creds[0]["encrypted_refresh_token"] != "plain-refresh-xyz"
            assert creds[0]["encrypted_access_token"] != "plain-access-xyz"
            assert decrypt_token(creds[0]["encrypted_refresh_token"], self.key) == "plain-refresh-xyz"

    def test_token_refresh_and_revoked_grant_handling(self):
        uid = "11111111-1111-1111-1111-111111111111"
        conn = self.fake_admin.insert("google_calendar_connections", {
            "user_id": uid,
            "google_account_sub": "sub-1",
            "google_email": "u@gmail.com",
            "status": "connected",
        })[0]
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.fake_admin.insert("google_oauth_credentials", {
            "connection_id": conn["id"],
            "user_id": uid,
            "encrypted_refresh_token": encrypt_token("ref-tok-1", self.key),
            "encrypted_access_token": encrypt_token("old-access", self.key),
            "token_expires_at": expired_at,
        })

        mock_ref = MagicMock(status_code=200, content=b"{}")
        mock_ref.json.return_value = {"access_token": "fresh-access-2", "expires_in": 3600}
        with patch("services.google_oauth_service.requests.post", return_value=mock_ref):
            tok = get_valid_access_token(
                admin=self.fake_admin,
                user_id=uid,
                connection_id=conn["id"],
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
            )
        assert tok == "fresh-access-2"
        stored_cred = self.fake_admin.tables["google_oauth_credentials"][0]
        assert decrypt_token(stored_cred["encrypted_access_token"], self.key) == "fresh-access-2"

        # Invalid grant marks connection revoked and raises GoogleReauthError
        mock_bad = MagicMock(status_code=400, content=b"{}")
        mock_bad.json.return_value = {"error": "invalid_grant"}
        with patch("services.google_oauth_service.requests.post", return_value=mock_bad):
            with pytest.raises(GoogleReauthError):
                get_valid_access_token(
                    admin=self.fake_admin,
                    user_id=uid,
                    connection_id=conn["id"],
                    client_id="cid",
                    client_secret="csec",
                    encryption_key=self.key,
                    force_refresh=True,
                )
        assert self.fake_admin.tables["google_calendar_connections"][0]["status"] == "revoked"


class TestFreemiumLimitsTrialAndSync:
    def setup_method(self):
        self.key = Fernet.generate_key().decode("utf-8")
        self.app = _make_app_with_google(self.key)
        self.client = self.app.test_client()
        self.admin = FakeSupabaseAdmin()
        self.uid1 = "11111111-1111-1111-1111-111111111111"
        self.uid2 = "22222222-2222-2222-2222-222222222222"

    def _connect_user_google(self, uid: str, email: str = "devotee@gmail.com") -> str:
        conn = self.admin.insert("google_calendar_connections", {
            "user_id": uid,
            "google_account_sub": f"sub-{uid}",
            "google_email": email,
            "status": "connected",
        })[0]
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        self.admin.insert("google_oauth_credentials", {
            "connection_id": conn["id"],
            "user_id": uid,
            "encrypted_refresh_token": encrypt_token("refresh-secret", self.key),
            "encrypted_access_token": encrypt_token("access-secret", self.key),
            "token_expires_at": future,
        })
        return conn["id"]

    def test_free_profile_limit_enforced_server_side_and_preserves_existing(self):
        with patch("app.SupabaseAdminClient", return_value=self.admin), \
             patch("services.supabase_service.requests.get", return_value=MagicMock(status_code=200, json=lambda: {"id": self.uid1, "email": "u1@example.com"})):

            for i in range(1, 4):
                r = self.client.post(
                    "/api/profiles",
                    headers={"Authorization": "Bearer jwt1"},
                    json={**_sample_profile_payload(f"Profile {i}"), "user_id": self.uid2},
                )
                assert r.status_code == 201
                assert json.loads(r.data)["profile"]["user_id"] == self.uid1

            # 4th profile blocked on backend
            r4 = self.client.post(
                "/api/profiles",
                headers={"Authorization": "Bearer jwt1"},
                json=_sample_profile_payload("Profile 4"),
            )
            assert r4.status_code == 403
            assert json.loads(r4.data)["code"] == "PROFILE_LIMIT_REACHED"

            # Legacy / post-trial user with >3 profiles keeps existing data
            self.admin.insert("saved_birth_profiles", {**_sample_profile_payload("Legacy 4"), "user_id": self.uid1})
            get_r = self.client.get("/api/profiles", headers={"Authorization": "Bearer jwt1"})
            assert get_r.status_code == 200
            body = json.loads(get_r.data)
            assert len(body["profiles"]) == 4
            assert body["entitlement"]["over_profile_limit"] is True
            assert body["entitlement"]["can_create_profile"] is False

    def test_trial_activation_atomic_once_per_account_and_expiration(self):
        t0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        self.admin.now_fn = lambda: t0

        ent0 = get_user_entitlement(self.admin, self.uid1, now_utc=t0)
        assert ent0["effective_tier"] == "free"
        assert ent0["trial_eligible"] is True
        assert ent0["ads_enabled"] is True

        ent1 = activate_plus_trial(self.admin, self.uid1, now_utc=t0)
        assert ent1["effective_tier"] == "plus"
        assert ent1["plus_source"] == "trial"
        assert ent1["trial_days_remaining"] == 14
        assert ent1["ads_enabled"] is False

        # Second trial activation must fail
        with pytest.raises(EntitlementError) as exc_info:
            activate_plus_trial(self.admin, self.uid1, now_utc=t0 + timedelta(days=2))
        assert exc_info.value.code == "TRIAL_ALREADY_USED"

        # 15 days later -> automatically reverts to Free & reconciles trial_status
        t_after = t0 + timedelta(days=15)
        self.admin.now_fn = lambda: t_after
        ent_exp = get_user_entitlement(self.admin, self.uid1, now_utc=t_after)
        assert ent_exp["effective_tier"] == "free"
        assert ent_exp["trial_status"] == "expired"
        assert ent_exp["trial_expired"] is True
        assert ent_exp["trial_eligible"] is False
        assert ent_exp["ads_enabled"] is True
        assert self.admin.tables["user_entitlements"][0]["trial_status"] == "expired"

    def test_free_calendar_sync_limits_enforced(self):
        self._connect_user_google(self.uid1)
        p1 = self.admin.insert("saved_birth_profiles", {
            "user_id": self.uid1,
            "label": "Self",
            "birth_date": "2004-05-28",
            "birth_time_mode": "exact",
            "birth_time": "04:00",
            "location_name": "Bijnor",
            "latitude": 29.3724,
            "longitude": 78.1358,
            "timezone": "Asia/Kolkata",
            "ayanamsha": "lahiri",
            "lunar_system": "amanta",
            "observance_method": "sunrise",
            "adhika_rule": "nija",
        })[0]
        p2 = self.admin.insert("saved_birth_profiles", {**p1, "id": str(uuid.uuid4()), "label": "Mom"})[0]

        # Blocked: multiple profiles on Free
        with pytest.raises(EntitlementError) as e_multi:
            preview_google_sync(self.admin, self.uid1, [p1["id"], p2["id"]], sync_mode="upcoming_12m")
        assert e_multi.value.code == "PLUS_REQUIRED"

        # Blocked: specific_year / year_range / upcoming_years on Free
        for bad_mode, kwargs in [
            ("specific_year", {"specific_year": 2027}),
            ("year_range", {"start_year": 2024, "end_year": 2026}),
            ("upcoming_years", {"years_ahead": 3}),
        ]:
            with pytest.raises(EntitlementError) as e_mode:
                preview_google_sync(self.admin, self.uid1, [p1["id"]], sync_mode=bad_mode, **kwargs)
            assert e_mode.value.code == "PLUS_REQUIRED"

        # Allowed: 1 profile upcoming_12m using exact astronomical calculation
        prev = preview_google_sync(
            self.admin,
            self.uid1,
            [p1["id"]],
            sync_mode="upcoming_12m",
            today_override=date(2026, 1, 1),
        )
        assert prev["counts"]["create"] == 1
        assert prev["items"][0]["gregorian_date"] == "2026-06-23"  # Known Lahiri Bijnor Jyeshtha Shukla Navami 2026

        # Simulate p1 already synced; Free user blocked from syncing p2 until p1 deleted or upgraded
        self.admin.insert("google_calendar_events", {
            "user_id": self.uid1,
            "google_connection_id": self.admin.tables["google_calendar_connections"][0]["id"],
            "saved_birth_profile_id": p1["id"],
            "profile_label_snapshot": "Self",
            "google_calendar_id": "primary",
            "google_event_id": "g-ev-1",
            "hindu_year": 2026,
            "gregorian_date": "2026-06-23",
            "sync_status": "synced",
        })
        with pytest.raises(EntitlementError) as e_2nd:
            preview_google_sync(self.admin, self.uid1, [p2["id"]], sync_mode="upcoming_12m")
        assert e_2nd.value.code == "SYNC_PROFILE_LIMIT_REACHED"

    def test_plus_sync_modes_batching_privacy_and_duplicate_prevention(self):
        self._connect_user_google(self.uid1)
        activate_plus_trial(self.admin, self.uid1)

        p_mom = self.admin.insert("saved_birth_profiles", {
            "user_id": self.uid1,
            "label": "Mom",
            "birth_date": "2004-05-28",
            "birth_time_mode": "exact",
            "birth_time": "04:00",
            "location_name": "Bijnor, Uttar Pradesh, India",
            "latitude": 29.3724,
            "longitude": 78.1358,
            "timezone": "Asia/Kolkata",
            "ayanamsha": "lahiri",
            "lunar_system": "amanta",
            "observance_method": "sunrise",
            "adhika_rule": "nija",
        })[0]
        p_dad = self.admin.insert("saved_birth_profiles", {**p_mom, "id": str(uuid.uuid4()), "label": "Dad"})[0]

        # Enforce max 120-year span limit from existing calculator
        with pytest.raises(ValueError):
            preview_google_sync(
                self.admin,
                self.uid1,
                [p_mom["id"]],
                sync_mode="year_range",
                start_year=1900,
                end_year=2050,
            )

        # Specific historical year works on Plus
        hist_prev = preview_google_sync(
            self.admin,
            self.uid1,
            [p_mom["id"]],
            sync_mode="specific_year",
            specific_year=1995,
        )
        assert hist_prev["counts"]["create"] == 1
        assert hist_prev["items"][0]["hindu_year"] == 1995

        # Bulk multi-profile sync over 2024-2025 -> 4 events, run in bounded chunks of 2
        created_payloads = []
        created_counter = {"n": 0}

        def fake_google_api(method, url, headers=None, json=None, timeout=15):
            if method == "POST" and url.endswith("/events"):
                created_counter["n"] += 1
                created_payloads.append(json)
                r = MagicMock(status_code=201, content=b"{}")
                r.json.return_value = {"id": f"gcal-ev-{created_counter['n']}"}
                return r
            if method == "PATCH":
                r = MagicMock(status_code=200, content=b"{}")
                r.json.return_value = {"id": url.rsplit("/", 1)[-1], "status": "confirmed"}
                return r
            raise AssertionError(f"Unexpected {method} {url}")

        with patch("services.google_sync_service.requests.request", side_effect=fake_google_api):
            chunk1 = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p_mom["id"], p_dad["id"]],
                sync_mode="year_range",
                start_year=2024,
                end_year=2025,
                offset=0,
                limit=2,
                sleep_fn=lambda _: None,
            )
            assert chunk1["processed"] == 2
            assert chunk1["created"] == 2
            assert chunk1["done"] is False

            chunk2 = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p_mom["id"], p_dad["id"]],
                sync_mode="year_range",
                start_year=2024,
                end_year=2025,
                offset=chunk1["next_offset"],
                limit=2,
                accumulated={"created": chunk1["created"], "updated": chunk1["updated"], "failed": 0},
                sleep_fn=lambda _: None,
            )
            assert chunk2["processed"] == 2
            assert chunk2["created"] == 2
            assert chunk2["done"] is True

        assert len(self.admin.tables["google_calendar_events"]) == 4
        assert len(self.admin.tables["google_sync_logs"]) == 1
        assert self.admin.tables["google_sync_logs"][0]["created_count"] == 4

        # Verify all-day format, markers, and strict privacy omission of sensitive birth details
        ev0 = created_payloads[0]
        assert ev0["summary"] == "Hindu Birthday – Mom"
        assert ev0["start"]["date"] == "2024-06-15"
        assert ev0["end"]["date"] == "2024-06-16"
        assert "2004-05-28" not in ev0["description"]
        assert "04:00" not in ev0["description"]
        assert "29.3724" not in ev0["description"]
        assert "Bijnor" not in ev0["description"]
        assert ev0["extendedProperties"]["private"]["tithi_managed"] == "true"
        assert ev0["extendedProperties"]["private"]["tithi_user_id"] == self.uid1

        # Re-syncing same profiles & years updates existing events instead of duplicating
        prev_resync = preview_google_sync(
            self.admin,
            self.uid1,
            [p_mom["id"], p_dad["id"]],
            sync_mode="year_range",
            start_year=2024,
            end_year=2025,
        )
        assert prev_resync["counts"]["create"] == 0
        assert prev_resync["counts"]["update"] == 4

        with patch("services.google_sync_service.requests.request", side_effect=fake_google_api):
            resync = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p_mom["id"], p_dad["id"]],
                sync_mode="year_range",
                start_year=2024,
                end_year=2025,
                offset=0,
                limit=10,
                sleep_fn=lambda _: None,
            )
        assert resync["updated"] == 4
        assert resync["created"] == 0
        assert len(self.admin.tables["google_calendar_events"]) == 4

        # Manual Google deletion (PATCH returns 404) triggers seamless recreate & updates DB event ID
        def fake_recreate_on_404(method, url, headers=None, json=None, timeout=15):
            if method == "PATCH":
                return MagicMock(status_code=404, content=b"{}")
            if method == "POST":
                created_counter["n"] += 1
                r = MagicMock(status_code=201, content=b"{}")
                r.json.return_value = {"id": f"recreated-{created_counter['n']}"}
                return r
            raise AssertionError(method)

        with patch("services.google_sync_service.requests.request", side_effect=fake_recreate_on_404):
            rec = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p_mom["id"]],
                sync_mode="specific_year",
                specific_year=2024,
                sleep_fn=lambda _: None,
            )
        assert rec["recreated"] == 1
        row_2024 = [r for r in self.admin.tables["google_calendar_events"] if r["saved_birth_profile_id"] == p_mom["id"] and r["hindu_year"] == 2024][0]
        assert row_2024["google_event_id"].startswith("recreated-")

    def test_safe_deletion_scopes_ownership_marker_and_post_expiry_management(self):
        conn_id = self._connect_user_google(self.uid1)
        # Seed 3 events: 2024 (valid Tithi event), 2025 (missing Tithi marker - must refuse!), 2026 (belongs to uid1, already gone 404)
        ev_valid = self.admin.insert("google_calendar_events", {
            "user_id": self.uid1,
            "google_connection_id": conn_id,
            "saved_birth_profile_id": "prof-a",
            "profile_label_snapshot": "Mom",
            "google_calendar_id": "primary",
            "google_event_id": "g-valid-2024",
            "hindu_year": 2024,
            "gregorian_date": "2024-06-15",
            "sync_status": "synced",
        })[0]
        ev_foreign = self.admin.insert("google_calendar_events", {
            "user_id": self.uid1,
            "google_connection_id": conn_id,
            "saved_birth_profile_id": "prof-a",
            "profile_label_snapshot": "Mom",
            "google_calendar_id": "primary",
            "google_event_id": "g-personal-untagged",
            "hindu_year": 2025,
            "gregorian_date": "2025-06-04",
            "sync_status": "synced",
        })[0]
        # Another user's event row
        self.admin.insert("google_calendar_events", {
            "user_id": self.uid2,
            "google_connection_id": "other-conn",
            "saved_birth_profile_id": "prof-b",
            "profile_label_snapshot": "Other",
            "google_calendar_id": "primary",
            "google_event_id": "g-other-user",
            "hindu_year": 2024,
            "gregorian_date": "2024-06-15",
            "sync_status": "synced",
        })

        # Trial expired -> reverted to Free: year_range delete blocked (403), single/profile/all delete still allowed!
        past = datetime.now(timezone.utc) - timedelta(days=2)
        self.admin.insert("user_entitlements", {
            "user_id": self.uid1,
            "plan": "free",
            "trial_used": True,
            "trial_status": "expired",
            "trial_started_at": (past - timedelta(days=14)).isoformat(),
            "trial_expires_at": past.isoformat(),
        })
        with pytest.raises(EntitlementError) as e_yr:
            delete_tithi_calendar_events(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                scope="year_range",
                year_start=2024,
                year_end=2025,
            )
        assert e_yr.value.code == "PLUS_REQUIRED"

        deleted_urls = []

        def fake_del_api(method, url, headers=None, json=None, timeout=15):
            if method == "GET" and url.endswith("/g-valid-2024"):
                r = MagicMock(status_code=200, content=b"{}")
                r.json.return_value = {
                    "id": "g-valid-2024",
                    "status": "confirmed",
                    "extendedProperties": {"private": {"tithi_managed": "true", "tithi_user_id": self.uid1}},
                }
                return r
            if method == "GET" and url.endswith("/g-personal-untagged"):
                r = MagicMock(status_code=200, content=b"{}")
                # Unrelated personal event lacking Tithi ownership marker!
                r.json.return_value = {"id": "g-personal-untagged", "status": "confirmed"}
                return r
            if method == "DELETE":
                deleted_urls.append(url)
                return MagicMock(status_code=204, content=b"")
            raise AssertionError(f"Unexpected {method} {url}")

        with patch("services.google_sync_service.requests.request", side_effect=fake_del_api):
            res = delete_tithi_calendar_events(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                scope="all",
            )

        assert res["deleted_count"] == 1
        assert res["failed_count"] == 1
        assert len(deleted_urls) == 1 and deleted_urls[0].endswith("/g-valid-2024")
        # Untagged event and user2 event were NEVER touched
        assert not any("g-personal-untagged" in u or "g-other-user" in u for u in deleted_urls)

        # User1 trying to delete User2's event record ID deletes 0 rows
        with patch("services.google_sync_service.requests.request", side_effect=fake_del_api):
            other_res = delete_tithi_calendar_events(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                scope="single",
                event_record_id=self.admin.tables["google_calendar_events"][-1]["id"],
            )
        assert other_res["deleted_count"] == 0

    def test_google_api_rate_limit_retries_and_errors(self):
        self._connect_user_google(self.uid1)
        p1 = self.admin.insert("saved_birth_profiles", {
            "user_id": self.uid1,
            "label": "Self",
            "birth_date": "2004-05-28",
            "birth_time_mode": "exact",
            "birth_time": "04:00",
            "location_name": "Bijnor",
            "latitude": 29.3724,
            "longitude": 78.1358,
            "timezone": "Asia/Kolkata",
        })[0]

        calls = {"n": 0}

        def flaky_google(method, url, headers=None, json=None, timeout=15):
            calls["n"] += 1
            if calls["n"] < 3:
                return MagicMock(status_code=429, content=b'{"error":{"message":"Rate Limit Exceeded"}}')
            r = MagicMock(status_code=201, content=b"{}")
            r.json.return_value = {"id": "recovered-after-429"}
            return r

        with patch("services.google_sync_service.requests.request", side_effect=flaky_google):
            res = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p1["id"]],
                sync_mode="upcoming_12m",
                today_override=date(2026, 1, 1),
                sleep_fn=lambda _: None,
            )
        assert calls["n"] == 3
        assert res["created"] == 1
        assert res["failed"] == 0

        # Persistent failure surfaces in failed_count and error log
        p2 = self.admin.insert("saved_birth_profiles", {**p1, "id": str(uuid.uuid4()), "label": "Brother"})[0]
        activate_plus_trial(self.admin, self.uid1)
        always_503 = MagicMock(status_code=503, content=b'{"error":{"message":"Backend Error"}}')
        with patch("services.google_sync_service.requests.request", return_value=always_503):
            fail_res = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p2["id"]],
                sync_mode="specific_year",
                specific_year=2026,
                sleep_fn=lambda _: None,
            )
        assert fail_res["failed"] == 1
        assert len(fail_res["errors"]) == 1
        assert self.admin.tables["google_sync_logs"][-1]["status"] == "error"

    def test_disconnect_and_account_delete_revoke_tokens_preserve_calendar_events(self):
        self._connect_user_google(self.uid1)
        ev = self.admin.insert("google_calendar_events", {
            "user_id": self.uid1,
            "google_connection_id": self.admin.tables["google_calendar_connections"][0]["id"],
            "saved_birth_profile_id": "p1",
            "profile_label_snapshot": "Mom",
            "google_calendar_id": "primary",
            "google_event_id": "g-keep-me",
            "hindu_year": 2026,
            "gregorian_date": "2026-06-23",
            "sync_status": "synced",
        })[0]

        revoke_calls = []

        def fake_revoke(url, data=None, headers=None, timeout=8):
            revoke_calls.append(data.get("token"))
            return MagicMock(status_code=200)

        with patch("app.SupabaseAdminClient", return_value=self.admin), \
             patch("services.supabase_service.requests.get", return_value=MagicMock(status_code=200, json=lambda: {"id": self.uid1, "email": "u1@example.com"})), \
             patch("services.google_oauth_service.requests.post", side_effect=fake_revoke):
            r = self.client.post(
                "/api/google/disconnect",
                headers={"Authorization": "Bearer jwt1"},
                json={"delete_events": False},
            )
        assert r.status_code == 200
        body = json.loads(r.data)
        assert body["disconnected"] is True
        assert body["google_token_revoked"] is True
        assert body["deleted_events_count"] == 0
        assert self.admin.tables["google_oauth_credentials"] == []
        assert self.admin.tables["google_calendar_connections"][0]["status"] == "disconnected"
        assert self.admin.tables["google_calendar_events"][0]["sync_status"] == "synced"

        # Account deletion revokes Google tokens without calling Calendar DELETE on external events
        self.admin.tables["google_calendar_connections"] = []
        self._connect_user_google(self.uid1)
        revoke_calls.clear()
        with patch("services.google_oauth_service.SupabaseAdminClient", return_value=self.admin), \
             patch("services.supabase_service.requests.get", return_value=MagicMock(status_code=200, json=lambda: {"id": self.uid1, "email": "u1@example.com"})), \
             patch("services.supabase_service.requests.delete", return_value=MagicMock(status_code=204)) as mock_auth_del, \
             patch("services.google_oauth_service.requests.post", side_effect=fake_revoke):
            del_r = self.client.post(
                "/api/account/delete",
                headers={"Authorization": "Bearer jwt1"},
                json={"confirm_text": "DELETE"},
            )
        assert del_r.status_code == 200
        assert len(revoke_calls) == 1
        assert self.uid1 in mock_auth_del.call_args[0][0]

    def test_google_account_switching_and_reconnecting_original_account(self):
        # Free user connects Account A, syncs Mom -> disconnects Account A ->
        # connects Account B -> Account A's events must stay preserved & untouched,
        # Free sync limit must NOT be consumed by disconnected Account A, and
        # reconnecting Account A must restore original mappings without duplicates.
        def _oauth_connect(sub: str, email: str, tok_prefix: str):
            started = start_google_oauth_flow(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                redirect_uri="http://localhost:5000/auth/google/callback",
                encryption_key=self.key,
                client_secret="csec",
            )
            state_val = re.search(r"state=([^&]+)", started["auth_url"]).group(1)
            tok_resp = MagicMock(status_code=200, content=b"{}")
            tok_resp.json.return_value = {
                "access_token": f"{tok_prefix}-access",
                "refresh_token": f"{tok_prefix}-refresh",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.events openid email",
            }
            info_resp = MagicMock(status_code=200, content=b"{}")
            info_resp.json.return_value = {"sub": sub, "email": email}
            with patch("services.google_oauth_service.requests.post", return_value=tok_resp), \
                 patch("services.google_oauth_service.requests.get", return_value=info_resp):
                return complete_google_oauth_callback(
                    admin=self.admin,
                    raw_state=state_val,
                    browser_nonce=started["browser_nonce"],
                    code="code-1",
                    error_param="",
                    client_id="cid",
                    client_secret="csec",
                    redirect_uri="http://localhost:5000/auth/google/callback",
                    encryption_key=self.key,
                )["connection"]

        base_db_prof = {
            "user_id": self.uid1,
            "birth_date": "2004-05-28",
            "birth_time_mode": "exact",
            "birth_time": "04:00",
            "location_name": "Bijnor",
            "latitude": 29.3724,
            "longitude": 78.1358,
            "timezone": "Asia/Kolkata",
            "ayanamsha": "lahiri",
            "lunar_system": "amanta",
            "observance_method": "sunrise",
            "adhika_rule": "nija",
        }
        p_mom = self.admin.insert("saved_birth_profiles", {**base_db_prof, "label": "Mom"})[0]
        p_dad = self.admin.insert("saved_birth_profiles", {**base_db_prof, "label": "Dad"})[0]

        conn_a = _oauth_connect("sub-A", "accountA@gmail.com", "acctA")

        def _sync_api(prefix: str):
            seq = {"n": 0}
            def _fn(method, url, headers=None, json=None, timeout=15):
                if method == "POST":
                    seq["n"] += 1
                    r = MagicMock(status_code=201, content=b"{}")
                    r.json.return_value = {"id": f"{prefix}-ev-{seq['n']}"}
                    return r
                if method == "PATCH":
                    r = MagicMock(status_code=200, content=b"{}")
                    r.json.return_value = {"id": url.rsplit("/", 1)[-1], "status": "confirmed"}
                    return r
                raise AssertionError(method)
            return _fn

        with patch("services.google_sync_service.requests.request", side_effect=_sync_api("A")):
            sync_a = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p_mom["id"]],
                sync_mode="upcoming_12m",
                today_override=date(2026, 1, 1),
                sleep_fn=lambda _: None,
            )
        assert sync_a["created"] == 1

        # Disconnect Account A without deleting its events
        with patch("services.google_oauth_service.requests.post", return_value=MagicMock(status_code=200)):
            disconnect_google_connection(self.admin, self.uid1, self.key, delete_events_first=False)

        # Connect Account B on the SAME Free user -> must allow syncing Dad without being blocked by Account A's historical event
        conn_b = _oauth_connect("sub-B", "accountB@gmail.com", "acctB")
        assert conn_b["id"] != conn_a["id"]

        ent_b = get_user_entitlement(self.admin, self.uid1)
        assert ent_b["synced_profile_count"] == 0

        with patch("services.google_sync_service.requests.request", side_effect=_sync_api("B")):
            sync_b = execute_google_sync_batch(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                profile_ids=[p_dad["id"]],
                sync_mode="upcoming_12m",
                today_override=date(2026, 1, 1),
                sleep_fn=lambda _: None,
            )
        assert sync_b["created"] == 1

        # /api/google/status & /api/profiles while connected to B must show ONLY B's events/counts
        with patch("app.SupabaseAdminClient", return_value=self.admin), \
             patch("services.supabase_service.requests.get", return_value=MagicMock(status_code=200, json=lambda: {"id": self.uid1, "email": "u1@example.com"})):
            st_b = json.loads(self.client.get("/api/google/status", headers={"Authorization": "Bearer jwt1"}).data)
            pr_b = json.loads(self.client.get("/api/profiles", headers={"Authorization": "Bearer jwt1"}).data)
        assert st_b["connection"]["google_email"] == "accountB@gmail.com"
        assert len(st_b["events"]) == 1
        assert st_b["events"][0]["profile_label_snapshot"] == "Dad"
        assert pr_b["synced_counts_by_profile"] == {p_dad["id"]: 1}

        # Deleting all events while connected to B must NEVER touch A's event IDs or tokens
        seen_urls = []
        seen_auths = []

        def _del_b_only(method, url, headers=None, json=None, timeout=15):
            seen_urls.append(url)
            seen_auths.append(headers.get("Authorization"))
            if method == "GET":
                r = MagicMock(status_code=200, content=b"{}")
                r.json.return_value = {
                    "id": "B-ev-1",
                    "status": "confirmed",
                    "extendedProperties": {"private": {"tithi_managed": "true", "tithi_user_id": self.uid1}},
                }
                return r
            if method == "DELETE":
                return MagicMock(status_code=204, content=b"")
            raise AssertionError(method)

        with patch("services.google_sync_service.requests.request", side_effect=_del_b_only):
            del_b = delete_tithi_calendar_events(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                scope="all",
            )
        assert del_b["deleted_count"] == 1
        assert all("B-ev-1" in u for u in seen_urls)
        assert not any("A-ev-1" in u for u in seen_urls)
        assert all(a == "Bearer acctB-access" for a in seen_auths)

        ev_a_row = [r for r in self.admin.tables["google_calendar_events"] if r["google_event_id"] == "A-ev-1"][0]
        assert ev_a_row["sync_status"] == "synced"

        # Targeted single deletion of Account A's row while connected to Account B must be a no-op
        with patch("services.google_sync_service.requests.request") as mock_req_no_touch:
            no_touch = delete_tithi_calendar_events(
                admin=self.admin,
                user_id=self.uid1,
                client_id="cid",
                client_secret="csec",
                encryption_key=self.key,
                scope="single",
                event_record_id=ev_a_row["id"],
            )
        assert no_touch["deleted_count"] == 0
        mock_req_no_touch.assert_not_called()
        assert [r for r in self.admin.tables["google_calendar_events"] if r["id"] == ev_a_row["id"]][0]["sync_status"] == "synced"

        # Disconnect B and reconnect original Account A -> preserves A's connection & updates A-ev-1 instead of duplicating
        with patch("services.google_oauth_service.requests.post", return_value=MagicMock(status_code=200)):
            disconnect_google_connection(self.admin, self.uid1, self.key, delete_events_first=False)
        reconn_a = _oauth_connect("sub-A", "accountA@gmail.com", "acctA2")
        assert reconn_a["id"] == conn_a["id"]

        prev_reconn = preview_google_sync(
            admin=self.admin,
            user_id=self.uid1,
            profile_ids=[p_mom["id"]],
            sync_mode="upcoming_12m",
            today_override=date(2026, 1, 1),
        )
        assert prev_reconn["counts"]["update"] == 1
        assert prev_reconn["counts"]["create"] == 0


class TestMigrationRlsAndUiParity:
    def _read_migration_sql(self) -> str:
        mig_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "supabase",
            "migrations",
            "v1_1_google_calendar_entitlements.sql",
        )
        with open(mig_path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_migration_sql_rls_and_grants(self):
        sql = self._read_migration_sql()

        for tbl in (
            "user_entitlements",
            "google_calendar_connections",
            "google_oauth_credentials",
            "oauth_states",
            "google_calendar_events",
            "google_sync_logs",
        ):
            assert f"ALTER TABLE public.{tbl} ENABLE ROW LEVEL SECURITY" in sql

        # Browser clients must NEVER read credentials or OAuth CSRF states
        assert "REVOKE ALL ON public.google_oauth_credentials FROM anon, authenticated, PUBLIC" in sql
        assert "REVOKE ALL ON public.oauth_states FROM anon, authenticated, PUBLIC" in sql
        assert "public.can_create_birth_profile()" in sql
        assert "ON DELETE CASCADE" in sql
        assert "ON DELETE SET NULL" in sql

    def test_cross_user_rpc_access_prevention_in_sql(self):
        sql = self._read_migration_sql()

        # 1-arg helpers must NOT be callable by authenticated or anon users
        assert "REVOKE ALL ON FUNCTION public.has_active_plus_access(uuid) FROM PUBLIC, anon, authenticated;" in sql
        assert "GRANT EXECUTE ON FUNCTION public.has_active_plus_access(uuid) TO service_role;" in sql
        assert "REVOKE ALL ON FUNCTION public.activate_plus_trial(uuid) FROM PUBLIC, anon, authenticated;" in sql
        assert "GRANT EXECUTE ON FUNCTION public.activate_plus_trial(uuid) TO service_role;" in sql
        assert "REVOKE ALL ON FUNCTION public.enforce_saved_birth_profile_limit() FROM PUBLIC, anon, authenticated;" in sql
        assert "DROP FUNCTION IF EXISTS public.can_create_birth_profile(uuid);" in sql

        # Zero-arg helpers bind strictly to auth.uid() with anon/PUBLIC revoked
        assert "CREATE OR REPLACE FUNCTION public.has_active_plus_access()\nRETURNS boolean" in sql
        assert "REVOKE ALL ON FUNCTION public.has_active_plus_access() FROM PUBLIC, anon;" in sql
        assert "GRANT EXECUTE ON FUNCTION public.has_active_plus_access() TO authenticated, service_role;" in sql
        assert "CREATE OR REPLACE FUNCTION public.can_create_birth_profile()\nRETURNS boolean" in sql
        assert "REVOKE ALL ON FUNCTION public.can_create_birth_profile() FROM PUBLIC, anon;" in sql
        assert "GRANT EXECUTE ON FUNCTION public.can_create_birth_profile() TO authenticated, service_role;" in sql

    def test_explicit_service_role_table_permissions_in_sql(self):
        sql = self._read_migration_sql()
        for tbl in (
            "user_entitlements",
            "saved_birth_profiles",
            "calculation_history",
            "google_calendar_connections",
            "google_oauth_credentials",
            "oauth_states",
            "google_calendar_events",
            "google_sync_logs",
        ):
            assert f"GRANT ALL ON TABLE public.{tbl} TO service_role;" in sql

        # Confirm authenticated never receives INSERT/UPDATE/DELETE grants on server-managed tables
        for srv_tbl in (
            "user_entitlements",
            "google_calendar_connections",
            "google_calendar_events",
            "google_sync_logs",
        ):
            assert f"REVOKE ALL ON public.{srv_tbl} FROM authenticated;" in sql
            assert f"GRANT SELECT ON public.{srv_tbl} TO authenticated;" in sql

    def test_bilingual_keys_parity_and_privacy_route(self):
        auth_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "js", "supabase_auth.js")
        with open(auth_js_path, "r", encoding="utf-8") as fh:
            js = fh.read()
        en_block = re.search(r"en:\s*\{(.*?)\},\s*hi:", js, re.S).group(1)
        hi_block = re.search(r"hi:\s*\{(.*?)\},\s*\};", js, re.S).group(1)
        en_keys = set(re.findall(r"^\s*([a-zA-Z0-9_]+):", en_block, re.M))
        hi_keys = set(re.findall(r"^\s*([a-zA-Z0-9_]+):", hi_block, re.M))
        assert en_keys and en_keys == hi_keys

        app = create_app({"TESTING": True})
        r = app.test_client().get("/privacy")
        assert r.status_code == 200
        assert b"calendar.events" in r.data
        assert b"Privacy Policy" in r.data
