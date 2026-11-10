"""
Tests for Supabase configuration safety, /account dashboard, input validation,
account deletion security, and schema RLS invariants.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app


class TestSupabaseIntegration:
    def setup_method(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def test_service_role_key_never_exposed_in_templates(self):
        secret_marker = "super-secret-service-role-key-do-not-leak"
        self.app.config["SUPABASE_URL"] = "https://example.supabase.co"
        self.app.config["SUPABASE_ANON_KEY"] = "public-anon-key-example"
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = secret_marker

        for route in ("/", "/account"):
            resp = self.client.get(route)
            assert resp.status_code == 200
            html = resp.data.decode("utf-8")
            assert secret_marker not in html
            assert "public-anon-key-example" in html
            assert "https://example.supabase.co" in html

    def test_anonymous_calculator_works_without_supabase_config(self):
        self.app.config["SUPABASE_URL"] = ""
        self.app.config["SUPABASE_ANON_KEY"] = ""
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = ""

        payload = {
            "birth_date": "2004-05-28",
            "lat": 29.3724,
            "lon": 78.1358,
            "timezone": "Asia/Kolkata",
            "location_name": "Bijnor",
            "ayanamsha": "lahiri",
            "birth_time_mode": "exact",
            "birth_time": "04:00",
            "start_year": 2024,
            "end_year": 2025,
        }
        resp = self.client.post("/calculate", data=json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["panchang"]["tithis"][0]["name_en"] == "Navami"

    def test_account_page_renders(self):
        resp = self.client.get("/account")
        assert resp.status_code == 200
        assert b"My Account" in resp.data
        assert b"Delete My Account" in resp.data

    def test_historical_input_validation_endpoint(self):
        good = {
            "birth_date": "2004-05-28",
            "lat": 29.3724,
            "lon": 78.1358,
            "timezone": "Asia/Kolkata",
            "birth_time_mode": "unknown",
        }
        r1 = self.client.post("/api/validate-input", data=json.dumps(good), content_type="application/json")
        assert r1.status_code == 200
        assert json.loads(r1.data)["valid"] is True

        bad = {
            "birth_date": "not-a-date",
            "lat": "bad-lat",
            "lon": 78.1358,
        }
        r2 = self.client.post("/api/validate-input", data=json.dumps(bad), content_type="application/json")
        assert r2.status_code == 400
        assert json.loads(r2.data)["valid"] is False

    def test_account_delete_requires_auth_and_confirmation(self):
        r_no_auth = self.client.post("/api/account/delete", data=json.dumps({"confirm_text": "DELETE"}), content_type="application/json")
        assert r_no_auth.status_code == 401

        r_bad_confirm = self.client.post(
            "/api/account/delete",
            headers={"Authorization": "Bearer fake-token"},
            data=json.dumps({"confirm_text": "no"}),
            content_type="application/json",
        )
        assert r_bad_confirm.status_code == 400

    def test_account_delete_verifies_jwt_and_ignores_client_user_id(self):
        self.app.config["SUPABASE_URL"] = "https://example.supabase.co"
        self.app.config["SUPABASE_ANON_KEY"] = "anon-key"
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = "service-role-key"

        verified_uid = "11111111-2222-3333-4444-555555555555"
        spoofed_uid = "99999999-9999-9999-9999-999999999999"

        mock_get_resp = MagicMock(status_code=200)
        mock_get_resp.json.return_value = {"id": verified_uid, "email": "user@example.com"}
        mock_del_resp = MagicMock(status_code=200)

        with patch("services.supabase_service.requests.get", return_value=mock_get_resp) as mock_get, \
             patch("services.supabase_service.requests.delete", return_value=mock_del_resp) as mock_del:
            resp = self.client.post(
                "/api/account/delete",
                headers={"Authorization": "Bearer valid-jwt-token"},
                data=json.dumps({"confirm_text": "DELETE", "user_id": spoofed_uid}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert json.loads(resp.data)["deleted"] is True

            mock_get.assert_called_once()
            # Must call admin delete ONLY on verified_uid, never spoofed_uid
            del_url = mock_del.call_args[0][0]
            assert verified_uid in del_url
            assert spoofed_uid not in del_url

    def test_account_delete_rejects_expired_jwt(self):
        self.app.config["SUPABASE_URL"] = "https://example.supabase.co"
        self.app.config["SUPABASE_ANON_KEY"] = "anon-key"
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = "service-role-key"

        mock_get_resp = MagicMock(status_code=401)
        with patch("services.supabase_service.requests.get", return_value=mock_get_resp):
            resp = self.client.post(
                "/api/account/delete",
                headers={"Authorization": "Bearer expired-token"},
                data=json.dumps({"confirm_text": "DELETE"}),
                content_type="application/json",
            )
            assert resp.status_code == 401

    def test_schema_sql_contains_rls_and_cascade_delete(self):
        schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "supabase", "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as fh:
            sql = fh.read()
        assert "ALTER TABLE public.saved_birth_profiles ENABLE ROW LEVEL SECURITY" in sql
        assert "ALTER TABLE public.calculation_history ENABLE ROW LEVEL SECURITY" in sql
        assert "auth.uid() = user_id" in sql
        assert "REFERENCES auth.users(id) ON DELETE CASCADE" in sql

    def test_config_exposes_module_and_class_supabase_attributes(self):
        import config

        supabase_vars = [k for k in dir(config) if "SUPABASE" in k]
        assert "SUPABASE_URL" in supabase_vars
        assert "SUPABASE_ANON_KEY" in supabase_vars
        assert "SUPABASE_SERVICE_ROLE_KEY" in supabase_vars

        assert hasattr(config.Config, "SUPABASE_URL")
        assert hasattr(config.Config, "SUPABASE_ANON_KEY")
        assert hasattr(config.Config, "SUPABASE_SERVICE_ROLE_KEY")
        assert isinstance(config.SUPABASE_URL, str)
        assert isinstance(config.SUPABASE_ANON_KEY, str)
        assert isinstance(config.SUPABASE_SERVICE_ROLE_KEY, str)

    def test_safe_diagnostic_endpoints_never_leak_secrets(self):
        import config

        diag = config.get_supabase_diagnostic()
        assert set(diag.keys()) == {
            "env_file_path",
            "env_file_exists",
            "supabase_url_loaded",
            "supabase_anon_key_loaded",
            "supabase_service_role_key_loaded",
            "supabase_configured",
        }
        assert isinstance(diag["supabase_url_loaded"], bool)
        assert isinstance(diag["supabase_anon_key_loaded"], bool)

        self.app.config["SUPABASE_URL"] = "https://example.supabase.co"
        self.app.config["SUPABASE_ANON_KEY"] = "public-anon-key-example"
        self.app.config["SUPABASE_SERVICE_ROLE_KEY"] = "secret-service-role-should-never-appear"

        resp = self.client.get("/api/supabase-status")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8")
        assert "secret-service-role-should-never-appear" not in body
        assert "public-anon-key-example" not in body
        parsed = json.loads(body)
        assert parsed == {
            "supabase_url_loaded": True,
            "supabase_anon_key_loaded": True,
            "supabase_configured": True,
        }

    def test_env_loaded_from_project_root_regardless_of_cwd(self):
        import importlib
        import config

        orig_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            reloaded = importlib.reload(config)
            assert reloaded.ENV_PATH.name == ".env"
            assert str(reloaded.ENV_PATH).lower().endswith(os.path.join("tithi", ".env"))
        finally:
            os.chdir(orig_cwd)

    def test_production_config_validation_and_defaults(self):
        import pytest
        import config

        # Missing or placeholder SECRET_KEY must fail when DEBUG=False and TESTING=False
        with pytest.raises(RuntimeError):
            config.validate_production_config({"DEBUG": False, "TESTING": False, "SECRET_KEY": "dev-secret-change-in-production"})
        with pytest.raises(RuntimeError):
            config.validate_production_config({"DEBUG": False, "TESTING": False, "SECRET_KEY": "short"})

        # Strong SECRET_KEY passes cleanly
        config.validate_production_config({
            "DEBUG": False,
            "TESTING": False,
            "SECRET_KEY": "a-very-strong-random-production-secret-key-xyz",
        })

    def test_wsgi_proxy_fix_and_deployment_files(self):
        from werkzeug.middleware.proxy_fix import ProxyFix
        import wsgi

        assert isinstance(wsgi.app.wsgi_app, ProxyFix)

        root = os.path.dirname(os.path.dirname(__file__))
        with open(os.path.join(root, "Procfile"), "r", encoding="utf-8") as fh:
            procfile = fh.read().strip()
        assert procfile == "web: gunicorn -w 1 --timeout 120 --bind 0.0.0.0:$PORT wsgi:app"

        with open(os.path.join(root, ".python-version"), "r", encoding="utf-8") as fh:
            assert fh.read().strip().startswith("3.11")

        with open(os.path.join(root, "requirements.txt"), "r", encoding="utf-8") as fh:
            reqs = fh.read()
        assert "gunicorn" in reqs

        with open(os.path.join(root, "static", "js", "supabase_auth.js"), "r", encoding="utf-8") as fh:
            js = fh.read()
        assert "openRenameModal('" not in js
        assert "btn-edit-profile" in js
