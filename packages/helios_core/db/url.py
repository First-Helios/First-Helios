"""Database URL helpers."""


def normalize_database_url(database_url: str) -> str:
    """Normalize Postgres URLs to explicitly use the psycopg (v3) driver."""
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url
