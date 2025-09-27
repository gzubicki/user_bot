"""Configuration helpers with hot-reload support."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic import BaseModel, Field
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


class LoggingSettings(BaseModel):
    level: str = Field("INFO", alias="LOG_LEVEL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    webhook_secret: str = Field(..., alias="WEBHOOK_SECRET")
    database_url: str = Field(..., alias="DATABASE_URL")
    admin_chat_ids: List[int] = Field(default_factory=list, alias="ADMIN_CHAT_IDS")

    subscription: SubscriptionSettings
    rate_limits: RateLimitSettings
    scheduler: SchedulerSettings
    logging: LoggingSettings

    @field_validator("bot_tokens", mode="before")
    @classmethod
    def split_tokens(cls, value: Iterable[str] | str) -> List[str]:
        if isinstance(value, str):
            return [token.strip() for token in value.split(",") if token.strip()]
        return list(value)

    @field_validator("admin_chat_ids", mode="before")
    @classmethod
    def parse_chat_ids(cls, value: Iterable[int | str] | str | None) -> List[int]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",") if item.strip()]
            return [int(item) for item in parts]
        return [int(item) for item in value]


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
    "LoggingSettings",
    "get_settings",
    "reload_settings",
]
