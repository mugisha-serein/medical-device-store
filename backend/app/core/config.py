from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path
from sqlalchemy.engine import make_url


DATABASE_PATH = (Path(__file__).resolve().parents[2] / "activelifemedical.sqlite3").as_posix()


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Active Life Medical API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{DATABASE_PATH}"
    DATABASE_URL_SYNC: str = f"sqlite:///{DATABASE_PATH}"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # JWT
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Flutterwave
    FLW_SECRET_KEY: str = ""
    FLW_PUBLIC_KEY: str = ""
    FLW_WEBHOOK_SECRET: str = ""
    FLW_BASE_URL: str = "https://api.flutterwave.com/v3"

    # Email (Resend)
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@activelife.rw"

    # Rate limiting
    RATE_LIMIT_LOGIN: str = "5/minute"
    RATE_LIMIT_REGISTER: str = "3/minute"
    RATE_LIMIT_BYPASS_IPS: list[str] = []  # Trusted proxy IPs exempt from rate limiting
    JWT_ADMIN_BYPASS: bool = True  # Allow admin JWT holders to bypass rate limits

    # Brute-force protection
    BF_MAX_FAILURES: int = 5          # Failed attempts before lockout
    BF_LOCKOUT_SECONDS: int = 900     # Lockout duration (15 minutes)
    BF_WINDOW_SECONDS: int = 900      # Sliding window for counting failures (15 minutes)

    @model_validator(mode="after")
    def validate_jwt_signing_key(self):
        value = self.JWT_SECRET_KEY.strip()
        if len(value) < 32 or value.upper() in {"CHANGE-ME-IN-PRODUCTION", "CHANGE_ME_IN_PRODUCTION"}:
            raise ValueError("JWT_SECRET_KEY must be a unique secret of at least 32 characters.")
        return self

    @model_validator(mode="after")
    def validate_sqlite_configuration(self):
        try:
            async_url = make_url(self.DATABASE_URL)
            sync_url = make_url(self.DATABASE_URL_SYNC)
            valid = (
                async_url.drivername == "sqlite+aiosqlite"
                and sync_url.drivername == "sqlite"
                and bool(async_url.database)
                and async_url.database == sync_url.database
                and not async_url.query and not sync_url.query
                and not async_url.host and not sync_url.host
                and not async_url.username and not sync_url.username
            )
        except Exception:
            valid = False
        if not valid:
            raise ValueError("SQLite async and sync URLs must reference the same database without URI options.") from None
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "hide_input_in_errors": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()
