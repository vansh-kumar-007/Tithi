"""
Application configuration.

Loads environment variables from the project root `.env` file (`BASE_DIR / ".env"`)
regardless of the terminal's current working directory, and exposes configuration
both at module level and on the `Config` classes for Flask.
"""
import os
from pathlib import Path
from typing import Any, Dict, Mapping

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Load project-root .env regardless of caller's working directory
load_dotenv(dotenv_path=ENV_PATH, override=False)

_INSECURE_SECRET_PLACEHOLDERS = {
    "",
    "dev-secret-change-in-production",
    "replace-with-a-long-random-secret-key",
}

# Module-level configuration variables (also exposed via Config class)
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
# Safe default: DEBUG is disabled unless explicitly enabled (e.g. DEBUG=true in local .env)
DEBUG = os.environ.get("DEBUG", "false").strip().lower() == "true"
if os.environ.get("RENDER", "").strip().lower() == "true" or os.environ.get("FLASK_ENV", "").strip().lower() == "production":
    DEBUG = False

CACHE_TYPE = "SimpleCache"
CACHE_DEFAULT_TIMEOUT = 300
EPHE_PATH = os.environ.get("EPHE_PATH", str(BASE_DIR / "ephe"))
GEOCODER_USER_AGENT = "hindu-tithi-birthday-calculator/1.0"
DEFAULT_AYANAMSHA = 1  # SE_SIDM_LAHIRI

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG

# Supabase configuration (SUPABASE_SERVICE_ROLE_KEY stays strictly server-side)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = (
    os.environ.get("SUPABASE_ANON_KEY", "").strip()
    or os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
)
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def get_supabase_diagnostic() -> Dict[str, object]:
    """
    Return safe boolean diagnostics confirming whether Supabase URL and keys
    are loaded without exposing any actual secret values.
    """
    return {
        "env_file_path": str(ENV_PATH),
        "env_file_exists": ENV_PATH.is_file(),
        "supabase_url_loaded": bool(SUPABASE_URL),
        "supabase_anon_key_loaded": bool(SUPABASE_ANON_KEY),
        "supabase_service_role_key_loaded": bool(SUPABASE_SERVICE_ROLE_KEY),
        "supabase_configured": bool(SUPABASE_URL and SUPABASE_ANON_KEY),
    }


def validate_production_config(cfg: Mapping[str, Any]) -> None:
    """
    Fail fast with a clear, actionable error when running in production mode
    (DEBUG is False) without a strong SECRET_KEY.
    """
    if cfg.get("DEBUG") or cfg.get("TESTING"):
        return

    secret = str(cfg.get("SECRET_KEY") or "").strip()
    if secret in _INSECURE_SECRET_PLACEHOLDERS or len(secret) < 16:
        raise RuntimeError(
            "Invalid production configuration: SECRET_KEY must be set to a strong "
            "random string (at least 16 characters) when DEBUG is disabled. "
            "Set SECRET_KEY in your hosting provider's environment variables."
        )


class Config:
    SECRET_KEY = SECRET_KEY
    DEBUG = DEBUG
    CACHE_TYPE = CACHE_TYPE
    CACHE_DEFAULT_TIMEOUT = CACHE_DEFAULT_TIMEOUT
    EPHE_PATH = EPHE_PATH
    GEOCODER_USER_AGENT = GEOCODER_USER_AGENT
    DEFAULT_AYANAMSHA = DEFAULT_AYANAMSHA
    SESSION_COOKIE_HTTPONLY = SESSION_COOKIE_HTTPONLY
    SESSION_COOKIE_SAMESITE = SESSION_COOKIE_SAMESITE
    SESSION_COOKIE_SECURE = SESSION_COOKIE_SECURE

    SUPABASE_URL = SUPABASE_URL
    SUPABASE_ANON_KEY = SUPABASE_ANON_KEY
    SUPABASE_SERVICE_ROLE_KEY = SUPABASE_SERVICE_ROLE_KEY


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
