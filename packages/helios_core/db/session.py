"""Database engine and session factory.

Engine creation is lazy: call get_engine() / get_sessionmaker() rather than
importing a module-level engine, so a bad DATABASE_URL fails at first use
(e.g. an API request's readiness check) rather than at import time, and
tests can swap settings before anything connects.

Connect/pool timeouts are set explicitly: psycopg's default connect timeout
is 130s, and with no pool_timeout a black-holed database holds a worker
thread per request until then, filling the pool and stalling even
``/healthz`` on an otherwise-live process (R38).
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.helios_core.config import get_database_url

_CONNECT_TIMEOUT_SECONDS = 5
_POOL_TIMEOUT_SECONDS = 10


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_database_url(),
        echo=False,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
        pool_timeout=_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=True,
    )


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False)
