"""Where gold prices are lost, per stage (finding for step H).

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.stress.loss TAG [--split=all|dev|ho1|tune|ho2] [--pages]

``tune`` = dev + ho1 (the pages prompts and the validator may be tuned on); ``--pages`` adds
one line per page.

Every gold (item, price) lands in exactly one bucket, in this order:
``item_missed`` (no extracted row matches the item), ``row_unpriced`` (matched rows carry no
price), ``wrong_amount`` (priced, but no row has this amount), ``not_accepted`` (right amount,
validator downgraded/rejected it; by reason), ``accepted`` (usable).
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

from spikes.menu_model.eval_validator import load_gold
from spikes.menu_model.extract import DATA, _match, rows_of, split_pages
from spikes.menu_model.labeltool import blocks_of
from spikes.menu_model.validator import parse_amount, validate


def main() -> None:
    tag = sys.argv[1]
    split = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--split=")), "all")
    gold = load_gold()
    pids = sorted(split_pages(gold, split))
    buckets: Counter[str] = Counter()
    per_format: dict[str, Counter[str]] = {}
    per_page: dict[str, Counter[str]] = {}
    for pid in pids:
        if not (DATA / "extract" / tag / f"{pid}.json").exists():
            continue
        result = json.loads((DATA / "extract" / tag / f"{pid}.json").read_text(encoding="utf-8"))
        items = gold[pid]["items"]
        assert isinstance(items, list)
        extracted = rows_of(
            result,
            repair=True,
            blocks=blocks_of(pid) if os.environ.get("MENU_SPIKE_STITCH") else None,
        )
        verdicts = validate(blocks_of(pid), extracted)
        by_item: dict[int, list[tuple[object, str, list[str]]]] = {}
        for v in verdicts:
            g = _match(v.row, items)
            if g is not None:
                by_item.setdefault(id(g), []).append(
                    (parse_amount(v.row.amount), v.decision, v.reasons)
                )
        fmt = per_format.setdefault(str(gold[pid].get("format")), Counter())
        for it in items:
            rows = by_item.get(id(it), [])
            for p in it["prices"]:
                amt = parse_amount(p["amount"])
                if not rows:
                    bucket = "item_missed"
                elif all(a is None for a, _, _ in rows):
                    bucket = "row_unpriced"
                elif not any(a == amt for a, _, _ in rows):
                    bucket = "wrong_amount"
                elif any(a == amt and d == "accept" for a, d, _ in rows):
                    bucket = "accepted"
                else:
                    reasons = next(r for a, d, r in rows if a == amt)
                    bucket = "not_accepted:" + (reasons[0].split(" ")[0] if reasons else "?")
                buckets[bucket] += 1
                fmt[bucket.split(":")[0]] += 1
                per_page.setdefault(pid, Counter())[bucket.split(":")[0]] += 1
    total = sum(buckets.values())
    print(f"{tag} split={split} gold prices={total}")
    for k, n_k in buckets.most_common():
        print(f"  {k:36} {n_k:5}  {n_k / total:.3f}")
    for f, c in sorted(per_format.items()):
        n = sum(c.values())
        print(f"  [{f}] n={n} " + " ".join(f"{k}={v / n:.2f}" for k, v in c.most_common()))
    if "--pages" in sys.argv:
        for pid, c in sorted(
            per_page.items(), key=lambda kv: -sum(kv[1].values()) + kv[1]["accepted"]
        ):
            n = sum(c.values())
            print(
                f"  {pid} n={n:4} lost={n - c['accepted']:4} "
                + " ".join(f"{k}={v}" for k, v in c.most_common())
            )


if __name__ == "__main__":
    main()
