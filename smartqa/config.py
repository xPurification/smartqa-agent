"""Configuration management using Pydantic Settings with .env support."""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from smartqa.models import BrowserMode


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    claude_api_key: str = Field(default="", description="Anthropic API key for Claude")
    claude_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model identifier",
    )
    browser: BrowserMode = Field(
        default=BrowserMode.HEADLESS,
        description="Browser mode: headless or headed",
    )
    timeout_seconds: int = Field(
        default=30,
        ge=5,
        description="Default timeout for browser operations in seconds",
    )
    screenshot_dir: Path = Field(
        default=Path("screenshots"),
        description="Directory to save failure screenshots",
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        description="Maximum retries for flaky operations",
    )
    heal_attempts: int = Field(
        default=5,
        ge=1,
        description="Maximum self-healing attempts per selector failure",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    api_host: str = Field(default="0.0.0.0", description="FastAPI bind host")
    api_port: int = Field(default=8000, ge=1, le=65535, description="FastAPI bind port")

    def ensure_screenshot_dir(self) -> Path:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        return self.screenshot_dir


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
