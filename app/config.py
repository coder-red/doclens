from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    provider: str = "auto"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    max_pages: int = 5
    max_image_px: int = 2000

    db_path: Path = Path("data/ledgerlens.db")
    export_dir: Path = Path("data")

    webhook_url: str | None = None
    webhook_secret: str | None = None
    webhook_timeout_s: float = 10.0

    app_name: str = "LedgerLens"


@lru_cache
def get_settings() -> Settings:
    return Settings()
