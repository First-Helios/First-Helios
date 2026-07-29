"""Application settings.

Single source of truth for environment-derived configuration. Reads
DATABASE_URL once, normalized to the psycopg driver, so the app, Alembic,
and the test suite all agree on where the database lives instead of each
re-reading and re-normalizing the environment variable independently.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.helios_core.db.url import normalize_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    database_url: str = "postgresql+psycopg://helios:helios@localhost:5432/helios"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        return normalize_database_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()
