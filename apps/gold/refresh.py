"""Rebuild Gold: the whole ``current_menu`` catalog, then the price index, in one transaction.

``python -m apps.gold.refresh [--as-of ISO-8601]``. Both projections are full
deterministic rebuilds at the same instant (default: now), so the index's
as-of matches the menu rows it aggregates (ADR-0006, ADR-0007 Amendment 1).
Run it after an extraction run; scheduling stays with ROADMAP Phase 6. Writes
only the ``gold`` schema.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.gold.catalog import refresh_full_catalog
from packages.helios_core.gold.price_index import refresh_price_index

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


def _instant(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        raise argparse.ArgumentTypeError("--as-of needs a UTC offset, e.g. 2026-09-30T12:00:00Z")
    return instant


def refresh_gold(session: Session, *, effective_instant: datetime) -> dict[str, Any]:
    """Both rebuilds at ``effective_instant`` with one ``refreshed_at``; flushes, no commit."""
    stamp = datetime.now(UTC)
    menu_rows = refresh_full_catalog(
        session, effective_instant=effective_instant, refreshed_at=stamp
    )
    index = refresh_price_index(session, effective_instant=effective_instant, refreshed_at=stamp)
    return {
        "effective_instant": effective_instant.isoformat(),
        "current_menu_rows": menu_rows,
        "price_index": index.summary(),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.gold.refresh", description=__doc__)
    parser.add_argument(
        "--as-of", type=_instant, default=None, help="effective instant (default: now)"
    )
    args = parser.parse_args(argv)
    effective_instant = args.as_of if args.as_of is not None else datetime.now(UTC)
    with get_sessionmaker()() as session:
        summary = refresh_gold(session, effective_instant=effective_instant)
        session.commit()
    print("gold refresh complete: " + json.dumps(summary))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
