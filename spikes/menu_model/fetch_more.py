"""Step 2 (usable-price session): fetch more menu pages for a fresh held-out-3 label set.

Only 4 of the 18 unlabeled stress-run menu pages print prices (most are unpriced chain menus),
so this follows menu links one level deeper, for the sample's own venues only (no new
candidates, no DB): for every venue without a gold page, the menu-looking links on its
already-fetched pages that were never fetched. Same ``SiteFetcher`` settings as step A
(robots.txt, 2 s per host, size cap, disk cache, honest user agent), capped per venue and in
total.

    MENU_SPIKE_DATA=/abs/var/spikes/menu-model uv run python -m spikes.menu_model.fetch_more

Appends to ``pages.jsonl`` (role ``more_menu``; a backup is written first) and prints the
fetched pages that print prices.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict

from apps.discovery.menu_url import menu_links_from_html
from apps.discovery.web_client import SiteFetcher
from spikes.menu_model.fetch_sample import DATA, USER_AGENT, page_flags, page_id
from spikes.menu_model.labeltool import LABELS, blocks_of
from spikes.menu_model.validator import price_tokens

PER_VENUE = 4
TOTAL = 160


def main() -> None:
    manifest = DATA / "pages.jsonl"
    shutil.copy(manifest, DATA / "pages.before-fetch-more.jsonl")
    pages = [json.loads(line) for line in manifest.open(encoding="utf-8")]
    labels = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (LABELS / "pages").glob("*.json")
    }
    gold_venues = {p["gers_id"] for p in pages if labels.get(p["page_id"], {}).get("blocks")}
    seen = {p["url"] for p in pages} | {p.get("final_url") for p in pages}
    todo: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        if p.get("status") != 200 or p["gers_id"] in gold_venues:  # noqa: PLR2004
            continue
        html = (DATA / "pages" / f"{p['page_id']}.html").read_text(encoding="utf-8")
        for url in menu_links_from_html(html, str(p.get("final_url") or p["url"])):
            if url not in seen and url not in todo[p["gers_id"]]:
                todo[p["gers_id"]].append(url)
    jobs = [(v, u) for v, urls in todo.items() for u in urls[:PER_VENUE]][:TOTAL]
    print(f"{len(todo)} venues with unfetched menu links; fetching {len(jobs)} pages")
    with (
        SiteFetcher(cache_dir=DATA / "cache", user_agent=USER_AGENT, min_interval_s=2.0) as f,
        manifest.open("a", encoding="utf-8") as out,
    ):
        for venue, url in jobs:
            result = f.fetch(url)
            rec: dict[str, object] = {"page_id": page_id(url), "url": url, "gers_id": venue}
            rec["role"] = "more_menu"
            if result is None:
                rec |= {"status": None, "blocked_or_failed": True}
            else:
                rec |= {
                    "final_url": result.url,
                    "status": result.status,
                    "content_type": result.content_type,
                    "bytes": len(result.text),
                    **page_flags(result),
                }
                if result.status == 200:  # noqa: PLR2004
                    (DATA / "pages" / f"{rec['page_id']}.html").write_text(result.text, "utf-8")
            out.write(json.dumps(rec) + "\n")
            out.flush()
            if rec.get("status") == 200:  # noqa: PLR2004
                blocks = blocks_of(str(rec["page_id"]))
                toks = price_tokens(blocks)
                priced = sum(
                    1
                    for i, b in enumerate(blocks)
                    if not b.in_chrome and any(t.kind == "money" for t in toks[i])
                )
                print(
                    f"{rec['page_id']} {venue[:8]} priced_blocks={priced:4} {url[:80]}", flush=True
                )


if __name__ == "__main__":
    main()
