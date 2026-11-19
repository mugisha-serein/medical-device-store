from pydantic import model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "Active Life Medical API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://activelifemedical:activelifemedical@localhost:5432/activelifemedical"
    DATABASE_URL_SYNC: str = "postgresql://activelifemedical:activelifemedical@localhost:5432/activelifemedical"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
