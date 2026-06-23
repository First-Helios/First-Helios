"""Database engine and session factory.

Reads DATABASE_URL from the environment. Defaults to the local docker-compose
Postgres for development.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://helios:helios@localhost:5432/helios",
)

# CI or hosting environments may provide a bare postgresql:// URL; pin psycopg (v3) explicitly.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, autoflush=False)
