"""
Application configuration for different environments.

Environment variables:
    FLASK_ENV: "development", "production", or "testing"
    DATABASE_URL: Database connection string (PostgreSQL recommended for production)
    SECRET_KEY: Flask secret key (MUST be set in production!)
    PASSWORD_ENC_KEY: Key for encrypting displayed passwords
    UPLOAD_ROOT: Root directory for uploaded files
    MAX_CONCURRENT_JOBS: Maximum number of simultaneous scraping jobs
    JOB_TIMEOUT_SECONDS: Maximum runtime for a single job
    REDIS_URL: Redis connection URL (for rate limiting and Celery)
    CELERY_BROKER_URL: Celery broker URL (defaults to REDIS_URL)
    CELERY_RESULT_BACKEND: Celery result backend (defaults to REDIS_URL)
"""
import os
from pathlib import Path


class Config:
    """Base configuration."""
    
    # Flask core
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-me-in-production")
    
    # Database
    # Default: SQLite for easy development
    # Production: Set DATABASE_URL to PostgreSQL connection string
    # Example: postgresql://user:password@localhost:5432/mektep_db
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///../instance/mektep_platform.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # SQLAlchemy pool settings (important for PostgreSQL)
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  # Test connections before using
        "pool_recycle": 300,    # Recycle connections after 5 minutes
    }
    
    # Security
    PASSWORD_ENC_KEY = os.getenv("PASSWORD_ENC_KEY", "")
    
    # File storage
    UPLOAD_ROOT = os.getenv("UPLOAD_ROOT", "out/platform_uploads")
    
    # Bootstrap admin (first run)
    BOOTSTRAP_SUPERADMIN_USER = os.getenv("BOOTSTRAP_SUPERADMIN_USER", "")
    BOOTSTRAP_SUPERADMIN_PASS = os.getenv("BOOTSTRAP_SUPERADMIN_PASS", "")
    
    # Job processing limits
    MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))
    JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", str(30 * 60)))  # 30 min default
    
    # Playwright/scraping settings
    SCRAPER_HEADLESS = os.getenv("SCRAPER_HEADLESS", "1") == "1"
    SCRAPER_SLOWMO_MS = int(os.getenv("SCRAPER_SLOWMO_MS", "0"))
    
    # Redis (for rate limiting, caching, and Celery)
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Celery (async task queue)
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
    
    # Use Celery for background jobs (set to False to use threads)
    USE_CELERY = os.getenv("USE_CELERY", "0") == "1"

    # Скачивание десктопного приложения:
    # DESKTOP_DOWNLOAD_PATH — путь к exe/zip (например dist/Mektep Desktop.zip)
    # DESKTOP_DOWNLOAD_URL — внешняя ссылка (если задана, используется вместо пути)
    DESKTOP_DOWNLOAD_PATH = os.getenv("DESKTOP_DOWNLOAD_PATH", "")
    DESKTOP_DOWNLOAD_URL = os.getenv("DESKTOP_DOWNLOAD_URL", "https://github.com/ed-baer97/pdf-to-excel-scraper-main/releases/download/v1.0.0/Mektep.Desktop.exe")


class DevelopmentConfig(Config):
    """Development configuration."""
    
    DEBUG = True
    TESTING = False
    
    # More verbose SQLAlchemy logging in dev
    # SQLALCHEMY_ECHO = True
    
    # Shorter timeouts for faster feedback
    JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", str(10 * 60)))  # 10 min


class ProductionConfig(Config):
    """Production configuration."""
    
    DEBUG = False
    TESTING = False
    
    # In production, SECRET_KEY MUST be set via environment variable
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    
    # Production should use PostgreSQL (set DATABASE_URL in .env)
    # Handle Heroku-style postgres:// URLs
    _db_url = os.getenv("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or None
    
    # Stricter pool settings for production
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
    }
    
    # More concurrent jobs allowed in production
    MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))


class TestingConfig(Config):
    """Testing configuration."""
    
    DEBUG = True
    TESTING = True
    
    # Use in-memory SQLite for tests
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    
    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False
    
    # Fast job timeouts for tests
    JOB_TIMEOUT_SECONDS = 60
    MAX_CONCURRENT_JOBS = 1


# Config selector
config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """Get configuration based on FLASK_ENV environment variable."""
    env = os.getenv("FLASK_ENV", "development").lower()
    return config_by_name.get(env, DevelopmentConfig)


# Legacy aliases for backward compatibility
DevConfig = DevelopmentConfig
ProdConfig = ProductionConfig
TestConfig = TestingConfig
