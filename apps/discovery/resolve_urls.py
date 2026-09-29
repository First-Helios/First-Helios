"""CLI: resolve website + menu-URL for discovered venues (ADR-0010).

Run after Overture seeding, on the Orange Pi against the staging database::

    python -m apps.discovery.resolve_urls --config config/sources.yaml

Idempotent and re-runnable: a venue whose website and menu-URL records are
current and unchanged is skipped without writing or crawling, and commits land
every 100 venues, so a re-run after an interruption skips the committed work.
Failed/skipped sites are recorded in Bronze and retried after 20 days. ``--limit`` counts only venues that
need work. Records a human put in ``needs_review`` are never re-assigned. A
saved menu URL is re-verified when the page verifier changes or 90 days after
its last pass, and withdrawn to ``needs_review`` if it no longer verifies
(ADR-0015); the report counts ``menu_urls_reverified``, ``menu_urls_withdrawn``,
``menu_urls_reverify_deferred`` and ``platform_ambiguous``. Crawls
live restaurant sites (robots + rate limited), so it makes network calls and is
not exercised in CI.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from apps.discovery.registry import load_registry
from apps.discovery.url_pipeline import resolve_urls
from apps.discovery.web_client import SiteFetcher
from packages.helios_core.db.session import get_sessionmaker

_USER_AGENT = "helios-v2-discovery/0.1 (+https://github.com/First-Helios/First-Helios)"
_DEFAULT_CONFIG = Path("config/sources.yaml")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m apps.discovery.resolve_urls", description=__doc__
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"registry file (default {_DEFAULT_CONFIG}; an explicit path must exist)",
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("var/site-cache"))
    parser.add_argument(
        "--min-interval", type=float, default=1.0, help="seconds between requests per host"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="max venues that need work (a write or crawl)"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    registry = load_registry(args.config or _DEFAULT_CONFIG, missing_ok=args.config is None)
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
            on_batch=session.commit,  # commit every 100 venues (D3.3)
        )
        session.commit()

    print(  # noqa: T201 - CLI output
        "url resolution complete: "
        + " ".join(f"{name}={value}" for name, value in asdict(report).items())
    )


if __name__ == "__main__":
    main()
