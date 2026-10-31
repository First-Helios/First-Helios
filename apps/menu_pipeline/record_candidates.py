"""Record-only re-crawl of discovery's candidate pages (ADR-0013 Amendment 24 item 4(b)).

For each venue (a JSON line with ``gers``, ``website`` and ``address``) it runs
discovery's own candidate enumeration, :meth:`SiteFetcher.discover_menu_attempt`,
with a :class:`RecordingVerifier` in place of the page check: the verifier keeps
every page discovery checks and accepts none, so discovery fetches every candidate
it ranks (own-site paths, sitemap and homepage links, the homepage itself when
nothing verified (ADR-0026), platform pages). Each page's
body and final URL are written under ``--out`` with the verdicts of the weights
files named by ``--weights`` and of the S4 heuristic.

Nothing is written to a database: no session is opened, and the fetcher is the
same robots.txt-obeying, per-host rate-limited ``SiteFetcher`` with the Helios
User-Agent that ``resolve_urls`` uses, on its own cache directory under ``--out``.
No rendering. Re-running skips venues already recorded::

    uv run --extra menu python -m apps.menu_pipeline.record_candidates \\
        --venues var/menu-eval/p5-29-r1b/venues.jsonl --out var/audits/p5-29-classifier-v3/r1b-crawl \\
        --weights config/page_classifier_v2.json --weights config/page_classifier_v3.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from apps.discovery.menu_url import ordering_platform_host, page_menu_signal
from apps.discovery.resolve_urls import _USER_AGENT
from apps.discovery.web_client import CaptureFailure, SiteFetcher
from apps.menu_pipeline.classifier import ClassifierWeights, PageClassifier, load_embedding
from apps.menu_pipeline.models import DEFAULT_ROOT
from packages.helios_parsing.segment import segment


@dataclass(frozen=True, slots=True)
class CheckedPage:
    """A page discovery handed to its page check: final URL, text and the S4 knob."""

    url: str
    html: str
    trust_path: bool


@dataclass(slots=True)
class RecordingVerifier:
    """A page check that records every page and accepts none, so discovery tries them all."""

    seen: list[CheckedPage] = field(default_factory=list)
    name: str = "record-only"

    def is_menu(self, html: str, url: str, *, trust_path: bool) -> bool:
        self.seen.append(CheckedPage(url, html, trust_path))
        return False


def record_venue(
    fetcher: SiteFetcher, recorder: RecordingVerifier, website: str, address: str | None
) -> tuple[str, list[CheckedPage], str | None]:
    """Discovery's outcome for the venue, the pages it checked, and its homepage text."""
    recorder.seen.clear()
    outcome = fetcher.discover_menu_attempt(website, address=address)
    if isinstance(outcome, CaptureFailure):
        reason = outcome.reason_code
    else:  # no page verifies: only chain or PDF notes come back
        reason = "+".join(sorted({type(item).__name__ for item in outcome}))
    homepage = fetcher.fetch(website)  # the cached answer: no second request
    text = homepage.text if homepage is not None and homepage.status == 200 else None  # noqa: PLR2004
    return reason, list(recorder.seen), text


def page_id(gers: str, page: CheckedPage) -> str:
    body = hashlib.sha256(page.html.encode("utf-8", errors="ignore")).hexdigest()
    return hashlib.sha256(f"{gers}|{page.url}|{body}".encode()).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.record_candidates")
    parser.add_argument("--venues", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--weights", type=Path, action="append", required=True)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args()

    weights = [ClassifierWeights.load(path) for path in args.weights]
    embed = load_embedding(weights[0].model, args.model_root)
    classifiers = [PageClassifier(w, embed) for w in weights]
    (args.out / "pages").mkdir(parents=True, exist_ok=True)
    done_path, pages_path = args.out / "venues-out.jsonl", args.out / "candidates.jsonl"
    done = (
        {json.loads(line)["position"] for line in done_path.open()} if done_path.exists() else set()
    )
    recorder = RecordingVerifier()
    with (
        SiteFetcher(
            cache_dir=args.out / "site-cache",
            user_agent=_USER_AGENT,
            min_interval_s=args.min_interval,
            page_check=recorder,
        ) as fetcher,
        done_path.open("a") as done_out,
        pages_path.open("a") as pages_out,
    ):
        for line in args.venues.open():
            venue = json.loads(line)
            if venue["position"] in done:
                continue
            started = time.monotonic()
            reason, seen, homepage = record_venue(
                fetcher, recorder, venue["website"], venue.get("address")
            )
            for rank, page in enumerate(seen, start=1):
                pid = page_id(venue["gers"], page)
                (args.out / "pages" / f"{pid}.html").write_text(page.html, encoding="utf-8")
                row: dict[str, Any] = {
                    "position": venue["position"],
                    "gers": venue["gers"],
                    "pool": venue["pool"],
                    "rank": rank,
                    "page_id": pid,
                    "url": page.url,
                    "platform": ordering_platform_host(page.url) is not None,
                    "trust_path": page.trust_path,
                    "same_as_homepage": page.html == homepage,
                    "n_blocks": len(segment(page.html)),
                    "s4": page_menu_signal(page.html, page.url),
                    "s4_discovery": page_menu_signal(
                        page.html, page.url, trust_path=page.trust_path
                    ),
                }
                for classifier in classifiers:
                    p = classifier.probability(page.html, page.url)
                    row[f"p_{classifier.name}"] = p
                    row[classifier.name] = p >= classifier.threshold
                pages_out.write(json.dumps(row) + "\n")
            done_out.write(
                json.dumps(
                    {
                        "position": venue["position"],
                        "gers": venue["gers"],
                        "pool": venue["pool"],
                        "outcome": reason,
                        "pages": len(seen),
                        "seconds": round(time.monotonic() - started, 1),
                    }
                )
                + "\n"
            )
            pages_out.flush()
            done_out.flush()


if __name__ == "__main__":
    main()
