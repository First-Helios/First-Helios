"""Anonymized label summary for the docs PR (no URLs, venue names or page text).

MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.labels_summary > summary.md
"""

from __future__ import annotations

import json
from collections import Counter

from spikes.menu_model.eval_validator import DEV_PAGES, HELDOUT_1
from spikes.menu_model.labeltool import LABELS, blocks_of


def main() -> None:
    labels = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((LABELS / "pages").glob("*.json"))
    ]
    pages = Counter(lab["page_label"] for lab in labels)
    formats = Counter(str(lab.get("format")) for lab in labels if lab["page_label"] == "menu")
    print("| Page label | Pages |\n|---|---|")
    for k, v in pages.most_common():
        print(f"| `{k}` | {v} |")
    print(f"| total | {sum(pages.values())} |\n")
    print("| Menu page format | Pages |\n|---|---|")
    for k, v in formats.most_common():
        print(f"| `{k}` | {v} |")
    gold = [lab for lab in labels if lab["page_label"] == "menu" and lab.get("blocks")]
    blocks: Counter[str] = Counter()
    print("\n| Page | Split | Format | Blocks | Items | Prices | Variant prices | Unpriced items |")
    print("|---|---|---|---|---|---|---|---|")
    rows = []
    for lab in gold:
        pid = lab["page_id"]
        split = "dev" if pid in DEV_PAGES else "ho1" if pid in HELDOUT_1 else "ho2"
        all_blocks = blocks_of(pid)
        blocks.update(lab["blocks"].get(b.id, "noise") for b in all_blocks)
        items = lab["items"]
        prices = [p for it in items for p in it["prices"]]
        rows.append(
            (
                split,
                str(lab.get("format")),
                len(all_blocks),
                len(items),
                len(prices),
                sum(1 for p in prices if p.get("variant")),
                sum(1 for it in items if not it["prices"]),
            )
        )
    for i, r in enumerate(sorted(rows), 1):
        print(f"| P{i:02d} | " + " | ".join(str(x) for x in r) + " |")
    tot = [sum(int(r[k]) for r in rows) for k in range(2, 7)]
    print("| total | | | " + " | ".join(str(x) for x in tot) + " |\n")
    print("| Block class | Blocks |\n|---|---|")
    for k, v in blocks.most_common():
        print(f"| `{k}` | {v} |")


if __name__ == "__main__":
    main()
