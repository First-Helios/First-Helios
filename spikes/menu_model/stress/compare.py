"""One line per (tag, stitch mode): the Gate Q numbers plus usable prices, on one split.

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.stress.compare --split=tune TAG [TAG ...]

Stitch modes: 1 = v1 row stitching (the st-q40 baseline), 2 = stitch v2 (+ price fill),
3 = v3 (+ variant completion).
Scores only pages present in every tag, so the lines are comparable.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys

from spikes.menu_model.eval_validator import load_gold
from spikes.menu_model.extract import DATA, cmd_score, split_pages


def main() -> None:
    split = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--split=")), "tune")
    tags = [a for a in sys.argv[1:] if not a.startswith("--")]
    pages = split_pages(load_gold(), split)
    common = {p for p in pages if all((DATA / "extract" / t / f"{p}.json").exists() for t in tags)}
    print(f"split={split} pages={len(common)} (of {len(pages)})")
    print(f"{'tag':18} st  items  usable  acc    FR     catch  rows  gen_tok")
    for tag in tags:
        for mode in ("1", "2", "3"):
            os.environ["MENU_SPIKE_STITCH"] = mode
            with contextlib.redirect_stdout(io.StringIO()):
                s = cmd_score(tag, split, repair=True, only=common)
            c = s["counts"]
            print(
                f"{tag:18} {mode}   {s['item_recall_raw']:.3f}  {s['price_recall_accepted']:.3f}"
                f"   {s['price_accuracy_accepted']:.3f}  {s['validator_false_reject']:.3f}"
                f"  {s['validator_catch']:.3f}  {c['rows']:5} {s['gen_tokens_total']:7}"
            )


if __name__ == "__main__":
    main()
