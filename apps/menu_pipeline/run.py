"""CLI: fetch every saved menu URL into ``menu-page`` Bronze (ADR-0013 slice 3)::

    python -m apps.menu_pipeline.run --limit N

For each resolved menu URL of a current venue: fetch (robots + rate limited),
segment, classify with the page classifier, and write a Capture with a durable
bundle under ``var/replay/menu-page/``, plus a Version when the segmented text
(or the URL or render) changed. Pages the classifier rejects, PDFs, JavaScript-
only pages and failed fetches are Captures with a reason code. No extraction
and no Menu writes yet (slice 5).

Resumable: commits after every URL, and a URL fetched in the last 20 days is
skipped, so a re-run after an interruption picks up where it stopped.
``--limit`` counts URLs fetched. Needs the ``menu`` extra (worker image) and
model files matching ``config/models.yaml`` under ``--model-root``. Crawls live
sites, so it makes network calls and is not exercised in CI.

``--render`` renders JavaScript-only pages and refused platform pages with
headed Chromium (ADR-0013 §4; run under ``xvfb-run -a``). It stays off for Pi
runs until the Pi measurement is recorded.
"""

from __future__ import annotations

import argparse
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from apps.discovery.web_client import SiteFetcher
from apps.menu_pipeline.bundle import BundleStore
from apps.menu_pipeline.classifier import load_page_classifier
from apps.menu_pipeline.models import DEFAULT_ROOT
from apps.menu_pipeline.page_bronze import run_menu_pages
from apps.menu_pipeline.render import BrowserRenderer
from packages.helios_core.db.session import get_sessionmaker

_USER_AGENT = "helios-v2-menu-pipeline/0.1 (+https://github.com/First-Helios/First-Helios)"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.run", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="max URLs fetched")
    parser.add_argument("--cache-dir", type=Path, default=Path("var/site-cache"))
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(),
        help="deploy directory that bundle paths (var/replay/...) are relative to",
    )
    parser.add_argument(
        "--min-interval", type=float, default=1.0, help="seconds between requests per host"
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
    try:
        verifier = load_page_classifier(model_root=args.model_root)
    except ModuleNotFoundError as error:
        raise SystemExit(
            f"the page classifier needs the `menu` extra (worker image): {error}"
        ) from error
    renderer = BrowserRenderer(user_agent=_USER_AGENT) if args.render else None

    with (
        renderer or nullcontext(),
        SiteFetcher(
            cache_dir=args.cache_dir, user_agent=_USER_AGENT, min_interval_s=args.min_interval
        ) as fetcher,
        get_sessionmaker()() as session,
    ):
        report = run_menu_pages(
            session,
            fetcher=fetcher,
            verifier=verifier,
            bundles=BundleStore(args.base_dir),
            renderer=renderer,
            now=datetime.now(UTC),
            limit=args.limit,
            on_page=session.commit,  # one URL per transaction
        )
        session.commit()

    print("menu-page run complete: " + json.dumps(report.summary()))  # noqa: T201 - CLI output
    if renderer is not None:
        print("renders: " + json.dumps(renderer.stats.summary()))  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
