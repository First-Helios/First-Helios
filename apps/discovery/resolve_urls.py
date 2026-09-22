"""CLI: resolve website + menu-URL for discovered venues (ADR-0010).

Run after Overture seeding, on the Orange Pi against the staging database::

    python -m apps.discovery.resolve_urls --config config/sources.yaml

Idempotent and re-runnable: a venue that already has a resolved website/menu-URL
record is skipped, and the site fetcher caches every response on disk, so a
re-run neither re-assigns nor re-crawls. Crawls live restaurant sites (robots
+ rate limited), so it makes network calls and is not exercised in CI.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from apps.discovery.registry import load_registry
from apps.discovery.url_pipeline import resolve_urls
from apps.discovery.web_client import SiteFetcher
from packages.helios_core.db.session import get_sessionmaker

_USER_AGENT = "helios-v2-discovery/0.1 (+https://github.com/First-Helios/First-Helios)"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.discovery.resolve_urls", description=__doc__
    )
    parser.add_argument("--config", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--cache-dir", type=Path, default=Path("var/site-cache"))
    parser.add_argument(
        "--min-interval", type=float, default=1.0, help="seconds between requests per host"
    )
    parser.add_argument("--limit", type=int, default=None, help="max venues to process this run")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    registry = load_registry(args.config)
    now = datetime.now(UTC)

    with (
        SiteFetcher(
            cache_dir=args.cache_dir,
            user_agent=_USER_AGENT,
            min_interval_s=args.min_interval,
        ) as fetcher,
        get_sessionmaker()() as session,
    ):
        report = resolve_urls(
            session,
            resolver=fetcher,
            registry=registry,
            decided_at=now,
            observed_at=now,
            limit=args.limit,
        )
        session.commit()

    print(  # noqa: T201 - CLI output
        "url resolution complete: "
        f"venues={report.venues} websites_resolved={report.websites_resolved} "
        f"websites_reused={report.websites_reused} without_website={report.without_website} "
        f"menu_urls_found={report.menu_urls_found} menu_urls_reused={report.menu_urls_reused} "
        f"menu_urls_absent={report.menu_urls_absent}"
    )


if __name__ == "__main__":
    main()
