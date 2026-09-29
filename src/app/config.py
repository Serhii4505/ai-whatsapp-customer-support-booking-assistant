"""Validated application settings for the mock-first foundation."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ALLOWED_INTEGRATION_MODES = {"mock"}
DEFAULT_KNOWLEDGE_BASE_PATH = Path(__file__).resolve().parents[2] / "demo" / "knowledge_base.json"
DEFAULT_CALENDAR_CONFIG_PATH = Path(__file__).resolve().parents[2] / "demo" / "calendar.json"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development", min_length=1, max_length=32)
    app_name: str = Field(
        default="AI WhatsApp Customer Support & Booking Assistant",
        min_length=1,
        max_length=120,
    )
    app_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    demo_company: str = Field(default="Northstar Service Studio", min_length=1, max_length=120)
    default_language: str = Field(default="en", pattern=r"^[a-z]{2}$")
    business_timezone: str = Field(default="Europe/Warsaw", min_length=1, max_length=64)
    database_path: Path = Path("data/assistant.sqlite3")
    whatsapp_mode: str = "mock"
    whatsapp_verify_token: SecretStr = SecretStr("phase-2-local-verify-token")
    whatsapp_app_secret: SecretStr = SecretStr("phase-2-local-app-secret")
    webhook_max_body_bytes: int = Field(default=262_144, ge=1_024, le=1_048_576)
    calendar_mode: str = "mock"
    calendar_config_path: Path = DEFAULT_CALENDAR_CONFIG_PATH
    crm_mode: str = "mock"
    gemini_mode: str = "mock"
    ai_min_confidence: float = Field(default=0.75, ge=0.5, le=1.0)
    knowledge_base_path: Path = DEFAULT_KNOWLEDGE_BASE_PATH
    log_level: str = "INFO"

    @field_validator("app_env", "default_language", "log_level", mode="before")
    @classmethod
    def normalize_lower_or_upper(cls, value: object, info):  # type: ignore[no-untyped-def]
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped.upper() if info.field_name == "log_level" else stripped.lower()

    @field_validator("demo_company", "app_name")
    @classmethod
    def strip_display_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("business_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @field_validator("database_path")
    @classmethod
    def validate_database_path(cls, value: Path) -> Path:
        if not str(value).strip():
            raise ValueError("database_path must not be blank")
        if value.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise ValueError("database_path must use .db, .sqlite or .sqlite3")
        return value

    @field_validator("knowledge_base_path")
    @classmethod
    def validate_knowledge_base_path(cls, value: Path) -> Path:
        if value.suffix.lower() != ".json":
            raise ValueError("knowledge_base_path must use .json")
        return value

    @field_validator("calendar_config_path")
    @classmethod
    def validate_calendar_config_path(cls, value: Path) -> Path:
        if value.suffix.lower() != ".json":
            raise ValueError("calendar_config_path must use .json")
        return value

    @field_validator("whatsapp_mode", "calendar_mode", "crm_mode", "gemini_mode")
    @classmethod
    def enforce_phase_1_mock_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in ALLOWED_INTEGRATION_MODES:
            raise ValueError("This portfolio build permits mock integration mode only")
        return normalized


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""

    return Settings()
