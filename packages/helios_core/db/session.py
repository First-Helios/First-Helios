"""Database engine and session factory.

Engine creation is lazy: call get_engine() / get_sessionmaker() rather than
importing a module-level engine, so a bad DATABASE_URL fails at first use
(e.g. an API request's readiness check) rather than at import time, and
tests can swap settings before anything connects.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.helios_core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, echo=False)


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False)
