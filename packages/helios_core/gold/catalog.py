"""Full deterministic rebuild of the entire ``gold.current_menu`` catalog.

The bounded :func:`refresh_current_menu` replaces a caller-supplied scope set;
this replaces the *whole* projection from the current catalog. It enumerates
every current eligible operating scope's priced targets
(:func:`enumerate_current_requests`), clears all existing Gold rows so a scope
that has left the current catalog loses its rows (ADR-0004 §5 retired-predecessor
exclusion), then reuses the accepted bounded refresh to record ``select_price``
per request. No source layer is mutated; the caller owns the commit.
``refreshed_at`` is the only non-deterministic column and is excluded from
rebuild-equality checks. Full-catalog enumeration is the follow-up ADR-0006's
Owner decision deferred; targeted incremental refresh remains deferred.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete

from packages.helios_core.domains.menu.enumeration import enumerate_current_requests
from packages.helios_core.gold.models import CurrentMenu
from packages.helios_core.gold.refresh import refresh_current_menu

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session


def refresh_full_catalog(
    session: Session,
    *,
    effective_instant: datetime,
    refreshed_at: datetime | None = None,
) -> int:
    """Rebuild the whole ``gold.current_menu`` catalog as of ``effective_instant``.

    Enumerates the current priced catalog, drops every existing projection row
    (whole-table replacement, unlike the bounded per-family refresh), then
    records the deterministic ``select_price`` result for each enumerated
    request. Returns the number of rows written. Enumeration is a deterministic
    function of committed Bronze/Identity/Menu, so a rebuild over unchanged
    sources yields identical business columns and re-running is idempotent. The
    command flushes; the caller owns the commit.
    """
    requests = enumerate_current_requests(session, effective_instant=effective_instant)
    session.execute(delete(CurrentMenu))
    session.flush()
    return refresh_current_menu(session, requests, refreshed_at=refreshed_at)
