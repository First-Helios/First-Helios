"""Per-request database session dependency for the read API.

Read-only: the session is never committed here. ``apps`` is the composition
root (ADR-0004) and reads Identity/Gold through their published models; it holds
no write path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.helios_core.db.session import get_sessionmaker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session


def get_session() -> Iterator[Session]:
    """Yield a session bound to the configured engine, closed after the request."""
    with get_sessionmaker()() as session:
        yield session
