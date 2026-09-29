"""Measure page rendering before it is enabled for Pi runs (ADR-0013 §4).

Renders each URL of a list with the production :class:`BrowserRenderer` (same
etiquette, same User-Agent) and records per page: outcome, seconds, peak RSS of
this process and its children (Playwright's driver and every Chromium
process), sub-requests seen and blocked, and, with ``--classify``, the page
classifier's probability. Rendered DOMs are saved next to the report so the
pages can be labelled. Makes live network calls; never run in CI::

    xvfb-run -a python -m apps.menu_pipeline.measure_render \\
        --urls var/render-measure/urls.json --out var/render-measure/$(hostname) --classify

``urls.json`` is a list of ``{"url": ..., ...}`` objects (other keys are copied
into the report), e.g. the S6d render probe's list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from apps.discovery.web_client import FetchResult
from apps.menu_pipeline.models import DEFAULT_ROOT
from apps.menu_pipeline.render import BrowserRenderer

if TYPE_CHECKING:
    from collections.abc import Callable

_USER_AGENT = "helios-v2-discovery/0.1 (+https://github.com/First-Helios/First-Helios)"


def tree_rss_kb(root: int, proc: Path = Path("/proc")) -> int:
    """Resident memory (kB) of ``root`` and all its descendants, from ``/proc``."""
    parents: dict[int, int] = {}
    rss: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(encoding="utf-8")
        except OSError:
            continue  # the process exited while we looked
        fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        pid = int(entry.name)
        parents[pid] = int(fields.get("PPid", "0").strip() or 0)
        rss[pid] = int(fields.get("VmRSS", "0 kB").split()[0])  # kB
    total, stack, seen = 0, [root], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += rss.get(pid, 0)
        stack.extend(child for child, parent in parents.items() if parent == pid)
    return total


class PeakSampler:
    """Samples a process tree's RSS in a background thread; ``peak_kb`` since reset."""

    def __init__(self, sample: Callable[[], int], interval_s: float = 0.2) -> None:
        self._sample = sample
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.peak_kb = 0

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak_kb = max(self.peak_kb, self._sample())
            self._stop.wait(self._interval)

    def reset(self) -> None:
        self.peak_kb = self._sample()

    def __enter__(self) -> PeakSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m apps.menu_pipeline.measure_render")
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--classify", action="store_true", help="score pages (menu extra)")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--min-interval", type=float, default=3.0)
    args = parser.parse_args()

    items = json.loads(args.urls.read_text(encoding="utf-8"))
    (args.out / "rendered").mkdir(parents=True, exist_ok=True)
    classifier = None
    if args.classify:
        from apps.menu_pipeline.classifier import load_page_classifier  # noqa: PLC0415

        classifier = load_page_classifier(model_root=args.model_root)
    last: dict[str, float] = {}

    def pace(host: str, crawl_delay: float) -> None:
        wait = max(args.min_interval, crawl_delay) - (time.monotonic() - last.get(host, -1e9))
        if wait > 0:
            time.sleep(wait)
        last[host] = time.monotonic()

    rows = []
    with (
        BrowserRenderer(user_agent=_USER_AGENT) as renderer,
        PeakSampler(lambda: tree_rss_kb(os.getpid())) as sampler,
        (args.out / "measure.jsonl").open("w", encoding="utf-8") as sink,
    ):
        for item in items:
            url = str(item["url"])
            before = (renderer.stats.subrequests, renderer.stats.subrequests_blocked)
            sampler.reset()
            started = time.monotonic()
            outcome = renderer.render(url, pace=pace)
            row: dict[str, object] = {
                **item,
                "secs": round(time.monotonic() - started, 2),
                "peak_rss_mb": round(sampler.peak_kb / 1024, 1),
                "subrequests": renderer.stats.subrequests - before[0],
                "subrequests_blocked": renderer.stats.subrequests_blocked - before[1],
            }
            if isinstance(outcome, FetchResult):
                name = hashlib.sha256(url.encode()).hexdigest()[:12]
                (args.out / "rendered" / f"{name}.html").write_text(outcome.text, "utf-8")
                row.update(outcome="rendered", final_url=outcome.url, html=f"{name}.html")
                if classifier is not None:
                    row["probability"] = round(classifier.probability(outcome.text, outcome.url), 4)
            else:
                row.update(outcome=outcome.outcome, reason=outcome.reason_code)
            rows.append(row)
            sink.write(json.dumps(row) + "\n")
            sink.flush()
            print(row["outcome"], row.get("reason", ""), row["secs"], url[:80], flush=True)  # noqa: T201
        summary = {
            **renderer.stats.summary(),
            "peak_rss_mb": max((float(str(r["peak_rss_mb"])) for r in rows), default=None),
        }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", "utf-8")
    print(json.dumps(summary))  # noqa: T201


if __name__ == "__main__":
    main()
