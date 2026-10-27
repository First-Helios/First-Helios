"""CLI: withdraw saved menu URLs whose stored page is another place's (ADR-0015 Amendment 2)::

    python -m apps.discovery.place_sweep [--dry-run] [--base-dir .]

The wrong-place check ``place-v1`` runs on every page discovery verifies from
now on; this applies it to the menu URLs already saved, from the stored
``menu-page`` bundles, without fetching anything. For each resolved menu-URL
record whose latest ``menu-page`` Version holds a bundle of the same URL, the
venue's current Overture address is checked against that page. A page
``place-v1`` rejects is withdrawn exactly as a failed re-verification is:
``_withdraw_menu`` writes the ``rejected/menu_not_verified`` observation
(``verification_failure: wrong_place``, the bundle Capture's fetch time) and the
``menu-url-reverify`` unassignment to ``needs_review``.

Nothing else is written. The next ``python -m apps.menu_pipeline.rescore`` (or
extraction run) withdraws the record's Menu streams (R4, ``menu_url_withdrawn``),
and the next Gold refresh drops its rows. The record is retried on ADR-0015's
schedule, and re-assigned when a URL verifies again. Registry menu URLs are never
checked (the registry wins, D3.2). Commits after every withdrawal.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from apps.discovery.lifecycle import lock_lifecycle
from apps.discovery.place_check import (
    PlaceArea,
    load_place_area,
    place_verdict,
    read_blocks,
    stored_pages,
)
from apps.discovery.url_pipeline import (
    MENU_URL_NAMESPACE,
    UrlDiscoveryReport,
    _saved_record,
    _withdraw_menu,
    iter_venues_to_resolve,
)
from apps.discovery.web_client import CaptureFailure
from packages.helios_core.db.session import get_sessionmaker

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session


@dataclass(slots=True)
class PlaceSweepReport:
    """Counts from one sweep (menu-page records unless named otherwise)."""

    pages: int = 0
    checked: int = 0
    wrong_place: int = 0
    withdrawn: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    wrong_place_keys: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        return {
            "pages": self.pages,
            "checked": self.checked,
            "wrong_place": self.wrong_place,
            "withdrawn": self.withdrawn,
            "skipped": dict(sorted(self.skipped.items())),
            "wrong_place_keys": sorted(self.wrong_place_keys),
        }


def sweep_places(
    session: Session,
    *,
    place_area: PlaceArea,
    base_dir: Path,
    observed_at: datetime,
    decided_at: datetime,
    dry_run: bool = False,
    commit: Callable[[], None] | None = None,
) -> PlaceSweepReport:
    """Check every saved menu URL's stored page; withdraw the wrong-place ones."""
    report = PlaceSweepReport()
    lock_lifecycle(session)
    venues = {venue.gers_id: venue for venue in iter_venues_to_resolve(session)}
    for key, url, bundle_path, fetched_at in sorted(stored_pages(session)):
        report.pages += 1
        saved = _saved_record(session, namespace=MENU_URL_NAMESPACE, external_key=key)
        venue = venues.get(key.split("|", 1)[0])
        if saved is None or saved.state != "resolved":
            report.skipped["not_resolved"] += 1
            continue
        if saved.payload.get("signal") == "registry":
            report.skipped["registry"] += 1
            continue
        if saved.payload.get("menu_url") != url:
            report.skipped["bundle_not_saved_url"] += 1  # the page of an older URL
            continue
        if venue is None or venue.place is None:
            report.skipped["venue_not_current"] += 1
            continue
        if saved.subject_id != venue.organization_subject_id:
            report.skipped["other_organization"] += 1
            continue
        blocks = read_blocks(base_dir, bundle_path)
        if blocks is None:
            report.skipped["bundle_unreadable"] += 1
            continue
        report.checked += 1
        if not place_verdict(url, blocks, venue.place, place_area).wrong:
            continue
        report.wrong_place += 1
        report.wrong_place_keys.append(key)
        if dry_run:
            continue
        withdrawals = UrlDiscoveryReport()
        _withdraw_menu(
            session,
            venue,
            key,
            CaptureFailure("failed", "wrong_place", fetched_at),
            verifier=str(saved.payload.get("verifier")),
            observed_at=observed_at,
            decided_at=decided_at,
            report=withdrawals,
        )
        report.withdrawn += withdrawals.menu_urls_withdrawn
        if commit is not None:
            commit()
            lock_lifecycle(session)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.discovery.place_sweep")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(),
        help="deploy directory that bundle paths (var/replay/...) are relative to",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the wrong-place pages; write nothing"
    )
    args = parser.parse_args()
    now = datetime.now(UTC)
    with get_sessionmaker()() as session:
        place_area = load_place_area(session, base_dir=args.base_dir)
        report = sweep_places(
            session,
            place_area=place_area,
            base_dir=args.base_dir,
            observed_at=now,
            decided_at=now,
            dry_run=args.dry_run,
            commit=None if args.dry_run else session.commit,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print("place sweep complete: " + json.dumps(report.summary()))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
