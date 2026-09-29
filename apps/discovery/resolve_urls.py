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
``menu_urls_reverify_deferred`` and ``platform_ambiguous``. The page verifier
is the ADR-0013 page classifier (``classifier-v2``): it needs the ``menu`` extra
(the worker image) and model files matching ``config/models.yaml`` under
``--model-root`` (``python -m apps.menu_pipeline.models download``). Crawls
live restaurant sites (robots + rate limited), so it makes network calls and is
not exercised in CI.

``--render`` renders platform pages the static fetch can't verify and
JavaScript-only own-site pages with headed Chromium (ADR-0013 §4, session S6f);
it needs the worker image and a display, so run it under ``xvfb-run -a``. It
stays off for Pi runs until the Pi measurement is recorded (ADR-0013 §4).
"""

from __future__ import annotations

import argparse
import json
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from apps.discovery.registry import load_registry
from apps.discovery.url_pipeline import resolve_urls
from apps.discovery.web_client import SiteFetcher
from apps.menu_pipeline.classifier import load_page_classifier
from apps.menu_pipeline.models import DEFAULT_ROOT
from apps.menu_pipeline.render import BrowserRenderer
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
    parser.add_argument(
        "--model-root", type=Path, default=DEFAULT_ROOT, help="verified model files (ADR-0013)"
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="render pages that need JavaScript with headed Chromium (run under xvfb-run -a)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    registry = load_registry(args.config or _DEFAULT_CONFIG, missing_ok=args.config is None)
    try:
        page_check = load_page_classifier(model_root=args.model_root)
    except ModuleNotFoundError as error:
        raise SystemExit(
            f"the page classifier needs the `menu` extra (worker image): {error}"
        ) from error
    now = datetime.now(UTC)
    renderer = BrowserRenderer(user_agent=_USER_AGENT) if args.render else None

    with (
        renderer or nullcontext(),
        SiteFetcher(
            cache_dir=args.cache_dir,
            user_agent=_USER_AGENT,
            min_interval_s=args.min_interval,
            page_check=page_check,
            renderer=renderer,
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
    if renderer is not None:
        print("renders: " + json.dumps(renderer.stats.summary()))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
