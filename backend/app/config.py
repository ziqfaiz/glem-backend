from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load validated application settings from environment variables or `.env`."""

    app_name: str = "Glem Destination API"
    database_url: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the lifetime of this process."""
    return Settings()
