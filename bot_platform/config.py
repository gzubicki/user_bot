"""Configuration helpers with hot-reload support."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SubscriptionSettings(BaseModel):
    setup_cost_stars: int = Field(..., alias="SUBSCRIPTION_SETUP_COST_STARS")
    extra_chat_cost_stars: int = Field(..., alias="SUBSCRIPTION_EXTRA_CHAT_COST_STARS")
    extra_chat_period_days: int = Field(..., alias="SUBSCRIPTION_EXTRA_CHAT_PERIOD_DAYS")
    yearly_cost_stars: int = Field(0, alias="SUBSCRIPTION_YEARLY_COST_STARS")
    yearly_period_days: int = Field(365, alias="SUBSCRIPTION_YEARLY_PERIOD_DAYS")


class RateLimitSettings(BaseModel):
    max_bots_total: int = Field(..., alias="MAX_BOTS_TOTAL")
    max_chats_per_bot: int = Field(..., alias="MAX_CHATS_PER_BOT")
    max_media_file_mb: int = Field(..., alias="MAX_MEDIA_FILE_MB")
    user_call_cooldown_seconds: int = Field(..., alias="USER_CALL_COOLDOWN_SECONDS")
    user_calls_per_minute: int = Field(..., alias="USER_CALLS_PER_MINUTE")
    user_calls_per_hour: int = Field(..., alias="USER_CALLS_PER_HOUR")
    chat_calls_per_minute: int = Field(..., alias="CHAT_CALLS_PER_MINUTE")
    user_submission_cooldown_seconds: int = Field(..., alias="USER_SUBMISSION_COOLDOWN_SECONDS")
    user_submissions_per_5_minutes: int = Field(..., alias="USER_SUBMISSIONS_PER_5_MINUTES")
    user_submissions_per_day: int = Field(..., alias="USER_SUBMISSIONS_PER_DAY")
    rate_limit_automute_minutes: int = Field(..., alias="RATE_LIMIT_AUTOMUTE_MINUTES")


class SchedulerSettings(BaseModel):
    config_reload_interval_seconds: int = Field(..., alias="CONFIG_RELOAD_INTERVAL_SECONDS")
    backup_schedule_cron: str = Field(..., alias="BACKUP_SCHEDULE_CRON")
    backup_retention_days: int = Field(..., alias="BACKUP_RETENTION_DAYS")


class ModerationSettings(BaseModel):
    moderator_chat_id: int = Field(..., alias="MODERATION_CHAT_ID")


class LoggingSettings(BaseModel):
    level: str = Field("INFO", alias="LOG_LEVEL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    webhook_secret: str = Field(..., alias="WEBHOOK_SECRET")
    webhook_base_url: str | None = Field(None, alias="WEBHOOK_BASE_URL")
    database_url: str = Field(..., alias="DATABASE_URL")
    admin_chat_id: int = Field(..., alias="ADMIN_CHAT_ID")

    subscription: SubscriptionSettings
    rate_limits: RateLimitSettings
    scheduler: SchedulerSettings
    moderation: ModerationSettings
    logging: LoggingSettings

    @field_validator("admin_chat_id", mode="before")
    @classmethod
    def parse_chat_id(cls, value: int | str) -> int:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("ADMIN_CHAT_ID nie może być puste")
            return int(value)
        return int(value)

    @field_validator("webhook_base_url", mode="before")
    @classmethod
    def normalize_webhook_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("WEBHOOK_BASE_URL musi zaczynać się od http:// lub https://")
        if value.endswith("/"):
            value = value.rstrip("/")
        return value

def _settings_source(env_file: str | Path | None = None) -> Settings:
    return Settings(_env_file=env_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""

    return _settings_source()


def reload_settings(env_file: str | Path | None = None) -> Settings:
    """Invalidate cache and reload settings (used by scheduler)."""

    get_settings.cache_clear()  # type: ignore[attr-defined]
    return _settings_source(env_file)


__all__ = [
    "Settings",
    "SubscriptionSettings",
    "RateLimitSettings",
    "SchedulerSettings",
    "ModerationSettings",
    "LoggingSettings",
    "get_settings",
    "reload_settings",
]
