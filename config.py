"""
Application configuration.
"""
import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
    DEBUG = os.environ.get("DEBUG", "true").lower() == "true"
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 300
    # Swiss Ephemeris data directory (relative to project root)
    EPHE_PATH = os.environ.get("EPHE_PATH", os.path.join(os.path.dirname(__file__), "ephe"))
    # Nominatim user agent
    GEOCODER_USER_AGENT = "hindu-tithi-birthday-calculator/1.0"
    # Default ayanamsha (Lahiri = 1 in pyswisseph)
    DEFAULT_AYANAMSHA = 1  # SE_SIDM_LAHIRI


class ProductionConfig(Config):
    DEBUG = False


class DevelopmentConfig(Config):
    DEBUG = True
