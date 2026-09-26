"""Draw the owner's 20% spot-check sample of the step-B labels (seeded, reproducible).

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.spotcheck > labels/spotcheck.md

- Page labels: 20% of all labeled pages, drawn per label class (menu / not_menu /
  js_only / empty) so every class is represented.
- Block + gold labels: 20% of the block-labeled menu pages; for each, 20% of its
  labeled blocks (label + text) and 20% of its gold items (name, prices, variants),
  each with the source block text so the check needs no browser.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict

from spikes.menu_model.labeltool import LABELS, blocks_of

SEED = 20260924
SHARE = 0.20


def _take(rng: random.Random, items: list, share: float = SHARE) -> list:  # type: ignore[type-arg]
    return rng.sample(items, max(1, math.ceil(len(items) * share))) if items else []


def main() -> None:
    rng = random.Random(SEED)
    labels = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((LABELS / "pages").glob("*.json"))
    ]
    by_class: dict[str, list[dict[str, object]]] = defaultdict(list)
    for lab in labels:
        by_class[str(lab["page_label"])].append(lab)

    print("# Step B spot-check (20% sample)\n")
    print(
        "Mark each row `ok` or write the correct label. Page labels: **menu** = the page's "
        "main content lists the venue's items (priced or not); **not_menu** includes menu "
        "*hubs* with only category links; **js_only** / **empty** = no server-rendered "
        "content (excluded from classifier metrics).\n"
    )
    print(f"Seed `{SEED}`. {len(labels)} labeled pages.\n")
    print("## 1. Page labels\n")
    print("| # | page | URL | my label | format | note | ok? |")
    print("|---|---|---|---|---|---|---|")
    n = 0
    for cls in sorted(by_class):
        for lab in _take(rng, by_class[cls]):
            n += 1
            print(
                f"| {n} | `{lab['page_id']}` | {lab['url']} | **{cls}** | {lab.get('format')} "
                f"| {str(lab.get('note', '')).replace('|', '/')} | |"
            )

    gold_pages = [lab for lab in labels if lab["page_label"] == "menu" and lab.get("blocks")]
    print(f"\n## 2. Block labels and gold items ({len(gold_pages)} block-labeled menus)\n")
    _blocks_and_items(rng, _take(rng, gold_pages))


def _blocks_and_items(rng: random.Random, pages: list[dict[str, object]]) -> None:
    for lab in pages:
        pid = str(lab["page_id"])
        text = {b.id: b.text for b in blocks_of(pid)}
        blocks = lab["blocks"]
        items = lab["items"]
        assert isinstance(blocks, dict)
        assert isinstance(items, list)
        print(f"### `{pid}` {lab['url']}\n\n{lab.get('note', '')}\n")
        print("Blocks (unlisted blocks inside the region are noise):\n")
        print("| block | my label | text | ok? |")
        print("|---|---|---|---|")
        for bid in sorted(_take(rng, sorted(blocks))):
            t = text.get(bid, "")[:110].replace("|", "/")
            print(f"| {bid} | {blocks[bid]} | {t} | |")
        print("\nGold items:\n")
        print("| block | section | name | prices (variant:amount) | block text | ok? |")
        print("|---|---|---|---|---|---|")
        for it in sorted(_take(rng, items), key=lambda i: str(i["block"])):
            prices = ", ".join(f"{p['variant'] or '-'}:{p['amount']}" for p in it["prices"]) or "—"
            t = text.get(str(it["block"]), "")[:80].replace("|", "/")
            section = str(it.get("section") or "")[:30].replace("|", "/")
            name = str(it["name"]).replace("|", "/")
            print(f"| {it['block']} | {section} | {name} | {prices} | {t} | |")
        print()


def main_ho3() -> None:
    """Held-out-3 (usable-price session): every page, 20% of its blocks and of its items."""
    from spikes.menu_model.eval_validator import HELDOUT_3  # noqa: PLC0415

    rng = random.Random(20260926)
    pages = [
        json.loads((LABELS / "pages" / f"{pid}.json").read_text(encoding="utf-8"))
        for pid in sorted(HELDOUT_3)
    ]
    print("# Held-out-3 spot-check (20% of each page's blocks and gold items)\n")
    print(
        "Nine new venues (candidates batch 2). Mark each row `ok` or write the correction. "
        "Unlisted blocks inside a page's region are noise; the full record is "
        "`labels/review.txt` (per-page specs in `labels/ho3/`). Seed `20260926`.\n"
    )
    _blocks_and_items(rng, pages)


if __name__ == "__main__":
    import sys

    main_ho3() if "--ho3" in sys.argv else main()
