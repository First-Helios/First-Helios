"""Spike step A: pick a stratified venue sample from the owner's CSV and fetch pages.

Every request goes through Helios's ``SiteFetcher`` (robots.txt, per-host rate
limit, size cap, disk cache). Per venue it records S4's own verdict
(``discover_menu_url``, the baseline for step C) and fetches a small page pool
independent of that verdict, so S4's misses can be labeled too:
the homepage, up to 2 menu-looking anchors, 1 platform link and 1 ordinary
internal link (a likely non-menu).

    MENU_SPIKE_DATA=/abs/var/spikes/menu-model uv run python -m spikes.menu_model.fetch_sample

Writes ``venues.jsonl`` and ``pages.jsonl`` (manifest + format flags) and the
cache under ``$MENU_SPIKE_DATA``; nothing is committed and nothing touches a DB.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from apps.discovery.menu_url import (
    menu_links_from_html,
    platform_links_from_html,
    platform_signal,
    same_resource,
    same_site,
)
from apps.discovery.web_client import FetchResult, SiteFetcher

DATA = Path(os.environ.get("MENU_SPIKE_DATA", "var/spikes/menu-model"))
USER_AGENT = "helios-v2-menu-spike/0.1 (+https://github.com/First-Helios/First-Helios)"
SEED = 20260923
TARGET_VENUES = int(os.environ.get("MENU_SPIKE_VENUES", "70"))  # overshoot for blocks/dead sites

# Coarse strata over Overture's primary_category, first match wins.
STRATA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("coffee_bakery", ("coffee", "cafe", "bakery", "tea", "donut", "dessert", "ice_cream")),
    # before "bar": "barbecue" contains it
    ("american_bbq", ("american", "bbq", "barbecue", "diner", "steak", "southern")),
    ("bar", ("bar", "pub", "brewery", "winery", "lounge")),
    ("fast_food", ("fast_food", "burger", "sandwich", "chicken", "hot_dog")),
    ("mexican_latin", ("mexican", "texmex", "tex_mex", "latin", "taco")),
    ("asian", ("asian", "chinese", "japanese", "sushi", "thai", "vietnamese", "korean", "indian")),
    ("pizza_italian", ("pizza", "italian")),
)


def stratum(category: str) -> str:
    for name, needles in STRATA:
        if any(n in category for n in needles):
            return name
    return "other"


def pick_venues(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Round-robin across strata (own sites and platform sites kept separate)."""
    rng = random.Random(SEED)
    buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        kind = "platform" if platform_signal(row["website"]) else "own"
        buckets[f"{stratum(row['primary_category'] or '')}/{kind}"].append(row)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    picked: list[dict[str, str]] = []
    keys = sorted(buckets)
    while len(picked) < TARGET_VENUES and any(buckets.values()):
        for key in keys:
            if buckets[key] and len(picked) < TARGET_VENUES:
                picked.append(buckets[key].pop())
    return picked


class _Scan(HTMLParser):
    """Visible-text size, script/img counts and same-page links, no dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_chars = 0
        self.scripts = 0
        self.imgs = 0
        self.menu_imgs = 0
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag in {"script", "style", "noscript", "template"}:
            self._skip += 1
            self.scripts += tag == "script"
        elif tag == "img":
            self.imgs += 1
            if "menu" in (a.get("src", "") + a.get("alt", "")).lower():
                self.menu_imgs += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "template"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.text_chars += len(data.strip())


def page_flags(result: FetchResult) -> dict[str, object]:
    ctype = result.content_type.lower()
    is_pdf = "pdf" in ctype or urlsplit(result.url).path.lower().endswith(".pdf")
    if is_pdf or "html" not in ctype and ctype:
        return {"is_pdf": is_pdf, "text_chars": 0, "js_only": False, "image_only": False}
    scan = _Scan()
    scan.feed(result.text)
    return {
        "is_pdf": False,
        "text_chars": scan.text_chars,
        "prices_seen": len(re.findall(r"\$\s?\d{1,3}(?:[.,]\d{2})?\b", result.text)),
        # Noted, not fetched: SiteFetcher decodes bodies to text, which breaks PDF bytes.
        "pdf_links": sum(1 for h in scan.links if re.search(r"\.pdf($|\?)", h, re.IGNORECASE)),
        "menu_pdf_links": sum(
            1 for h in scan.links if re.search(r"menu[^/]*\.pdf($|\?)", h, re.IGNORECASE)
        ),
        # Heuristics, reviewed by hand during labeling:
        "js_only": scan.text_chars < 300 and scan.scripts >= 3,
        "image_only": scan.text_chars < 600 and scan.menu_imgs > 0,
    }


def other_link(html: str, base: str, exclude: set[str]) -> str | None:
    """One same-site, non-menu internal link (a likely non-menu page)."""
    scan = _Scan()
    scan.feed(html)
    for href in scan.links:
        url = urljoin(base, href).split("#", 1)[0]
        if (
            url.startswith("http")
            and same_site(url, base)
            and not same_resource(url, base)
            and url not in exclude
            and not re.search(r"menu|\.(pdf|jpe?g|png)$", url, re.IGNORECASE)
        ):
            return url
    return None


def page_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:12]


def main() -> None:
    # Held-out-3 batch (usable-price session): MENU_SPIKE_CANDIDATES=candidates-2.csv appends
    # to the manifests and skips venues and website hosts already in the sample.
    batch2 = os.environ.get("MENU_SPIKE_CANDIDATES")
    with (DATA / (batch2 or "candidates.csv")).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if batch2:
        old = [json.loads(line) for line in (DATA / "venues.jsonl").open(encoding="utf-8")]
        known = {v["gers_id"] for v in old}
        hosts = {urlsplit(v["website"]).netloc.removeprefix("www.") for v in old}
        rows = [
            r
            for r in rows
            if r["gers_id"] not in known
            and urlsplit(r["website"]).netloc.removeprefix("www.") not in hosts
        ]
    venues = pick_venues(rows)
    pages_dir = DATA / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    mode = "a" if batch2 else "w"
    with (
        SiteFetcher(cache_dir=DATA / "cache", user_agent=USER_AGENT, min_interval_s=2.0) as f,
        (DATA / "venues.jsonl").open(mode, encoding="utf-8") as vout,
        (DATA / "pages.jsonl").open(mode, encoding="utf-8") as pout,
    ):

        def grab(url: str, venue: str, role: str) -> FetchResult | None:
            if url in seen:
                return None
            seen.add(url)
            result = f.fetch(url)
            record: dict[str, object] = {"page_id": page_id(url), "url": url, "gers_id": venue}
            record["role"] = role
            if result is None:
                record |= {"status": None, "blocked_or_failed": True}
            else:
                record |= {
                    "final_url": result.url,
                    "status": result.status,
                    "content_type": result.content_type,
                    "bytes": len(result.text),
                    **page_flags(result),
                }
                if result.status == 200:  # noqa: PLR2004
                    (pages_dir / f"{record['page_id']}.html").write_text(result.text, "utf-8")
            pout.write(json.dumps(record) + "\n")
            pout.flush()
            return result

        for n, v in enumerate(venues, 1):
            website = v["website"]
            s4 = f.discover_menu_url(website)
            v_out: dict[str, object] = {**v, "stratum": stratum(v["primary_category"] or "")}
            v_out |= {"s4_menu_url": s4.menu_url if s4 else None}
            v_out |= {"s4_signal": s4.signal if s4 else None}
            vout.write(json.dumps(v_out) + "\n")
            vout.flush()
            home = grab(website, v["gers_id"], "homepage")
            if s4:
                grab(s4.menu_url, v["gers_id"], "s4_menu")
            if home is not None and home.status == 200:  # noqa: PLR2004
                base = home.url
                menus = menu_links_from_html(home.text, base)[:2]
                for url in menus:
                    grab(url, v["gers_id"], "anchor_menu")
                for url in platform_links_from_html(home.text, base)[:1]:
                    grab(url, v["gers_id"], "platform_link")
                other = other_link(home.text, base, set(menus))
                if other:
                    grab(other, v["gers_id"], "anchor_other")
            print(f"[{n}/{len(venues)}] {v['name'][:40]!r}: s4={'yes' if s4 else 'no'}")

    stats = Counter(json.loads(line)["role"] for line in (DATA / "pages.jsonl").open())
    print("pages by role:", dict(stats))


if __name__ == "__main__":
    main()
