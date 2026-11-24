"""Score reviewed site fixtures against a frozen HTTP cache without contacting the sites."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from apps.discovery.web_client import PageVerifier, SiteFetcher
from apps.menu_pipeline.classifier import load_verifier
from apps.menu_pipeline.coverage_eval import (
    collect_site,
    coverage_metrics,
    coverage_site,
    site_fixture,
)


def replay(
    fixtures: Path, archive: Path, verifier: PageVerifier, *, follow_menu_hubs: bool = False
) -> dict[str, Any]:
    records = list(archive.glob("*.json"))
    if not records:
        raise ValueError(f"No archived HTTP records in {archive}")
    totals: Counter[str] = Counter()
    venues = []
    misses = 0

    def missing(request: httpx.Request) -> httpx.Response:
        nonlocal misses
        misses += 1
        raise httpx.ConnectError("absent from frozen archive", request=request)

    with (
        tempfile.TemporaryDirectory() as scratch,
        httpx.Client(transport=httpx.MockTransport(missing)) as client,
    ):
        cache = Path(scratch)
        for path in records:
            (cache / path.name).symlink_to(path.resolve())
        # A clock earlier than the captures keeps frozen entries fresh. SiteFetcher
        # replaces cache entries atomically, so new entries only affect scratch.
        with SiteFetcher(
            cache_dir=cache,
            user_agent="helios-coverage-replay",
            client=client,
            min_interval_s=0,
            clock=lambda: 0,
            resolve=lambda _: ["93.184.216.34"],
            page_check=verifier,
            follow_menu_hubs=follow_menu_hubs,
            random_token=lambda: "coverage-replay",
        ) as fetcher:
            for path in sorted(fixtures.rglob("*.json")):
                obj = json.loads(path.read_text())
                if obj.get("status", "reviewed") != "reviewed":
                    continue
                fixture = site_fixture(obj)
                before = misses
                captured, cost = collect_site(fetcher, fixture, lambda: misses)
                counts = coverage_site(fixture, captured, cost)
                totals.update(counts)
                venues.append(
                    {
                        "site": fixture.site,
                        "split": fixture.split,
                        "counts": counts,
                        "cache_misses": misses - before,
                        "urls": [p.url for p in captured],
                    }
                )
    if not venues:
        raise ValueError("No reviewed site fixtures")
    return {
        "totals": totals,
        "metrics": coverage_metrics(totals),
        "cache_misses": misses,
        "venues": venues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--model-root", default=Path("var/models"), type=Path)
    parser.add_argument("--follow-menu-hubs", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            replay(
                args.fixtures,
                args.archive,
                load_verifier(model_root=args.model_root),
                follow_menu_hubs=args.follow_menu_hubs,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
