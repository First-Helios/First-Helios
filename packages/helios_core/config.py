"""Application settings.

Single source of truth for environment-derived configuration. Reads
DATABASE_URL once, normalized to the psycopg driver, so the app, Alembic,
and the test suite all agree on where the database lives instead of each
re-reading and re-normalizing the environment variable independently.

DATABASE_URL has no default: the old one (``localhost:5432/helios``) is the
V1 legacy archive's address, so an unset variable silently aimed the write
CLIs and ``alembic upgrade`` at it. Settings still load without it (``/healthz``
and non-database tests need no database); code that connects goes through
``get_database_url()``, which fails loudly.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.helios_core.db.url import normalize_database_url


class DatabaseUrlNotSetError(RuntimeError):
    """Raised when code needs a database but DATABASE_URL is unset or blank."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False)

    database_url: str | None = None
    # Read API (ADR-0008): CORS is locked to the frontend origin(s); never a
    # wildcard. Override with a JSON list in CORS_ALLOW_ORIGINS.
    cors_allow_origins: list[str] = ["http://localhost:5173"]

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return normalize_database_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_database_url() -> str:
    """Return the configured database URL, or fail with an actionable error."""
    url = get_settings().database_url
    if url is None:
        raise DatabaseUrlNotSetError(
            "DATABASE_URL is not set. Export it for the database you intend to use "
            "(e.g. a disposable *_test database); there is no default."
        )
    return url
