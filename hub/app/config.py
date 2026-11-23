"""Typed settings loaded from the environment / .env.

Lab 6 (Task 4): no secret lives in source code. If a required secret is missing
or too weak, pydantic raises at import time and the server refuses to start.
"""
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- required secrets (no defaults on purpose) ---
    DATABASE_URL: str = Field(pattern=r"^postgres(ql)?://")
    SESSION_SECRET: str = Field(min_length=32)
    PAYMENT_WEBHOOK_SECRET: str = Field(min_length=32)

    # --- behaviour ---
    ENV: str = Field(default="development", pattern=r"^(development|test|production)$")
    PUBLIC_ORIGIN: str = "https://localhost:8443"   # used for Origin checks (CSRF / WebSocket hijacking)
    COOKIE_SECURE: bool = True
    SESSION_TTL_SECONDS: int = 60 * 60 * 8
    RATE_LIMIT_PER_MINUTE: int = 120
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024

    # --- connection pool (Lab 7, Task 4) ---
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 10
    DB_POOL_TIMEOUT: float = 5.0        # seconds to wait for a free connection before failing
    DB_POOL_MAX_IDLE: float = 300.0     # close idle connections after 5 minutes

    # --- optional integrations: blank means "simulate and log to the outbox" ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "Campus Events Hub <no-reply@campus-hub.local>"
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""

    @field_validator("SESSION_SECRET", "PAYMENT_WEBHOOK_SECRET")
    @classmethod
    def not_placeholder(cls, v: str) -> str:
        if "change-me" in v.lower():
            raise ValueError("replace the placeholder secret from .env.example")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
