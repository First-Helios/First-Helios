"""Step C baselines: stage [0] structured-parse coverage and the S4 pre-filter.

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.baselines [--json OUT]

C1 — for every labeled page: schema.org JSON-LD menu items, embedded app-state
(name, price) pairs, host platform. Structured rows are then run through the
stage [5] validator against the page's *visible* blocks, which measures whether
the structured data agrees with what a visitor sees (stale JSON-LD is a real
hazard: it would outrank ``dom``/``llm`` under ADR-0005 §11).

C2 — S4's cheap pre-filter, two views:

- **venue level, as recorded:** ``venues.jsonl`` ``s4_menu_url`` vs the label of
  that fetched page. Positive = ``menu``; ``js_only``/``empty`` are counted
  apart (neither a hit nor a miss for text classifiers). Recall is over venues
  where *any* fetched page is labeled ``menu`` (bounded by what step A fetched).
- **page level:** S4's page predicate
  (``apps.discovery.menu_url.page_menu_signal``, path/title/first heading) applied
  to every labeled page. This is the like-for-like baseline for the stage [1]
  page classifier.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from apps.discovery.menu_url import page_menu_signal, platform_signal
from spikes.menu_model.labeltool import LABELS
from spikes.menu_model.segment import segment
from spikes.menu_model.stage0 import embedded_state_items, jsonld_menu_items, platform_of
from spikes.menu_model.validator import Row, norm_tokens, validate

DATA = Path(os.environ.get("MENU_SPIKE_DATA", "var/spikes/menu-model"))
TEXT_LABELS = ("menu", "not_menu")


def _load() -> tuple[
    list[dict[str, object]], dict[str, dict[str, object]], dict[str, dict[str, object]]
]:
    pages = [json.loads(line) for line in (DATA / "pages.jsonl").open(encoding="utf-8")]
    labels = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (LABELS / "pages").glob("*.json")
    }
    venues = {
        v["gers_id"]: v for v in map(json.loads, (DATA / "venues.jsonl").open(encoding="utf-8"))
    }
    return pages, labels, venues


def _html(page_id: str) -> str:
    return (DATA / "pages" / f"{page_id}.html").read_text(encoding="utf-8")


def _grounding(page_id: str, items: list[dict[str, object]]) -> Counter[str]:
    rows = [Row(item=str(it["name"]), amount=p) for it in items for p in it["prices"]]  # type: ignore[attr-defined]
    return Counter(v.decision for v in validate(segment(_html(page_id)), rows))


def _gold_recall(label: dict[str, object], items: list[dict[str, object]]) -> tuple[int, int]:
    got = {" ".join(norm_tokens(str(it["name"]))) for it in items}
    gold = [" ".join(norm_tokens(str(it["name"]))) for it in label.get("items") or []]  # type: ignore[attr-defined]
    return sum(1 for g in gold if g in got), len(gold)


def stage0(
    pages: list[dict[str, object]], labels: dict[str, dict[str, object]]
) -> dict[str, object]:
    by_id = {str(p["page_id"]): p for p in pages}
    per_page = []
    for pid, label in sorted(labels.items()):
        if label["page_label"] not in ("menu", "js_only"):
            continue
        html = _html(pid)
        url = str(by_id[pid]["final_url"] or by_id[pid]["url"])
        ld = jsonld_menu_items(html)
        state = embedded_state_items(html)
        priced = [it for it in ld if it["prices"]] or state
        rec: dict[str, object] = {
            "page_id": pid,
            "venue": by_id[pid]["gers_id"],
            "label": label["page_label"],
            "format": label.get("format"),
            "host_platform": "platform" if platform_signal(url) else "own_site",
            "platforms": platform_of(html, url),
            "jsonld_items": len(ld),
            "jsonld_priced": sum(1 for it in ld if it["prices"]),
            "state_priced": len(state),
            "gold_items": len(label.get("items") or []),  # type: ignore[arg-type]
        }
        if priced and label["page_label"] == "menu":
            rec["grounding"] = dict(_grounding(pid, priced))
            if label.get("items"):
                rec["gold_recall"] = _gold_recall(label, priced)
        per_page.append(rec)
    return {"pages": per_page}


def s4(
    pages: list[dict[str, object]],
    labels: dict[str, dict[str, object]],
    venues: dict[str, dict[str, object]],
) -> dict[str, object]:
    by_venue: dict[str, list[dict[str, object]]] = defaultdict(list)
    for p in pages:
        by_venue[str(p["gers_id"])].append(p)

    def lab(p: dict[str, object]) -> str:
        return str(labels.get(str(p["page_id"]), {}).get("page_label", "unlabeled"))

    outcomes: Counter[str] = Counter()
    false_pos, missed = [], []
    for gid, v in venues.items():
        vpages = by_venue[gid]
        has_menu = any(lab(p) == "menu" for p in vpages)
        s4_url = v.get("s4_menu_url")
        if not s4_url:
            outcomes["no_verdict+venue_has_menu" if has_menu else "no_verdict+no_menu_found"] += 1
            if has_menu:
                missed.append(
                    {
                        "venue": v["name"],
                        "menu_pages": [p["url"] for p in vpages if lab(p) == "menu"],
                    }
                )
            continue
        s4_page = next((p for p in vpages if p["role"] == "s4_menu" and p["url"] == s4_url), None)
        s4_label = lab(s4_page) if s4_page else "not_fetched"
        if s4_page and s4_page.get("status") != 200:  # noqa: PLR2004
            s4_label = f"http_{s4_page.get('status')}"
        outcomes[f"verdict:{s4_label}"] += 1
        if s4_label == "not_menu":
            false_pos.append(
                {
                    "venue": v["name"],
                    "url": s4_url,
                    "signal": v.get("s4_signal"),
                    "note": labels[str(s4_page["page_id"])].get("note", "") if s4_page else "",
                    "venue_has_other_menu_page": has_menu,
                }
            )
    tp = outcomes["verdict:menu"]
    fp = outcomes["verdict:not_menu"]
    venues_with_menu = sum(1 for gid in venues if any(lab(p) == "menu" for p in by_venue[gid]))

    # page level: S4's own predicate over every labeled page with text
    conf: Counter[str] = Counter()
    for p in pages:
        label = lab(p)
        if label == "unlabeled":
            continue
        pred = page_menu_signal(_html(str(p["page_id"])), str(p["final_url"] or p["url"]))
        conf[f"{label}:{'pos' if pred else 'neg'}"] += 1
    ptp, pfp, pfn = conf["menu:pos"], conf["not_menu:pos"], conf["menu:neg"]
    return {
        "venue_level": {
            "outcomes": dict(outcomes),
            "precision_text": tp / (tp + fp) if tp + fp else None,
            "recall": tp / venues_with_menu if venues_with_menu else None,
            "venues_with_menu_page": venues_with_menu,
            "false_positives": false_pos,
            "missed": missed,
        },
        "page_level": {
            "confusion": dict(conf),
            "precision": ptp / (ptp + pfp) if ptp + pfp else None,
            "recall": ptp / (ptp + pfn) if ptp + pfn else None,
        },
    }


def main() -> None:
    pages, labels, venues = _load()
    s0 = stage0(pages, labels)
    pre = s4(pages, labels, venues)

    rows = s0["pages"]
    assert isinstance(rows, list)
    menu = [r for r in rows if r["label"] == "menu"]
    menu_venues = {r["venue"] for r in menu}
    ld_any = [r for r in menu if r["jsonld_items"]]
    ld_priced = [r for r in menu if r["jsonld_priced"]]
    st_priced = [r for r in menu if r["state_priced"]]
    covered = [r for r in menu if r["jsonld_priced"] or r["state_priced"]]
    print(f"C1 stage [0] on {len(menu)} menu pages ({len(menu_venues)} venues):")
    print(
        f"  JSON-LD MenuItem present      {len(ld_any):3} pages {len({r['venue'] for r in ld_any})} venues"
    )
    print(
        f"  JSON-LD MenuItem with price   {len(ld_priced):3} pages {len({r['venue'] for r in ld_priced})} venues"
    )
    print(
        f"  embedded state (name, price)  {len(st_priced):3} pages {len({r['venue'] for r in st_priced})} venues"
    )
    print(f"  => structured priced coverage {len(covered):3}/{len(menu)} pages, "
          f"{len({r['venue'] for r in covered})}/{len(menu_venues)} venues")  # fmt: skip
    gold_pages = [r for r in menu if r["gold_items"]]
    print(
        f"  gold pages with structured prices: {sum(1 for r in gold_pages if 'gold_recall' in r)}/{len(gold_pages)}"
    )
    for r in covered:
        print(f"    {r['page_id']} ld={r['jsonld_items']}/{r['jsonld_priced']} state={r['state_priced']} "
              f"grounding={r.get('grounding')} gold_recall={r.get('gold_recall')}")  # fmt: skip
    js = [r for r in rows if r["label"] == "js_only"]
    print(f"  js_only pages: {len(js)}; with priced structured data: "
          f"{sum(1 for r in js if r['jsonld_priced'] or r['state_priced'])}")  # fmt: skip
    plat = Counter(p for r in js for p in r["platforms"] if p not in ("wordpress",))
    print(f"  js_only platform fingerprints: {dict(plat.most_common())}")
    print(f"  menu page formats: {dict(Counter(str(r['format']) for r in menu).most_common())}")

    vl, pl = pre["venue_level"], pre["page_level"]
    assert isinstance(vl, dict) and isinstance(pl, dict)
    print(f"\nC2 S4 pre-filter, venue level (as recorded): {vl['outcomes']}")
    print(f"  precision (menu vs not_menu verdicts) = {vl['precision_text']:.3f}; "
          f"recall = {vl['recall']:.3f} of {vl['venues_with_menu_page']} venues with a fetched menu page")  # fmt: skip
    for fp in vl["false_positives"]:
        print(
            f"    FP [{fp['signal']}] {urlsplit(fp['url']).netloc}{urlsplit(fp['url']).path[:50]} | {fp['note'][:70]}"
        )
    for m in vl["missed"]:
        print(f"    MISS {m['venue'][:30]}: {[urlsplit(u).path[:40] for u in m['menu_pages']]}")
    print(f"C2 S4 predicate, page level: {pl['confusion']}")
    print(f"  precision = {pl['precision']:.3f}; recall = {pl['recall']:.3f}")

    if "--json" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(
            json.dumps({"stage0": s0, "s4": pre}, indent=1, default=str), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
