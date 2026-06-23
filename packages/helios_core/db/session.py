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

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, autoflush=False, autocommit=False)
