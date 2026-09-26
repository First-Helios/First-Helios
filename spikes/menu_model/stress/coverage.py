"""Step 3 (adaptive second pass): a label-free per-page coverage signal.

    MENU_SPIKE_DATA=... MENU_SPIKE_STITCH=2 uv run python -m spikes.menu_model.stress.coverage TAG [--split=tune]

coverage = validator-accepted priced rows / printed prices in the page's non-chrome blocks
(``$``/decimal price tokens, i.e. what the extractor was shown). It needs no gold, so a
production run can compute it; here it is printed next to the page's usable-price share
(gold) to choose the threshold below which a page is re-extracted with a stronger setup.
"""

from __future__ import annotations

import json
import sys

from spikes.menu_model.eval_validator import load_gold
from spikes.menu_model.extract import DATA, _match, rows_of, split_pages
from spikes.menu_model.labeltool import blocks_of
from spikes.menu_model.validator import parse_amount, price_tokens, validate


def page_coverage(result: dict[str, object], pid: str) -> tuple[float, int, int, list]:  # type: ignore[type-arg]
    """(coverage, accepted priced rows, printed prices, verdicts) for one extracted page."""
    blocks = blocks_of(pid)
    printed = sum(
        sum(1 for t in toks if t.kind == "money")
        for b, toks in zip(blocks, price_tokens(blocks), strict=True)
        if not b.in_chrome
    )
    verdicts = validate(blocks, rows_of(result, repair=True, blocks=blocks))
    accepted = sum(1 for v in verdicts if v.decision == "accept" and v.row.amount)
    return (accepted / printed if printed else 1.0), accepted, printed, verdicts


def usable(pid: str, verdicts: list) -> tuple[int, int]:  # type: ignore[type-arg]
    items = load_gold()[pid]["items"]
    assert isinstance(items, list)
    got = set()
    for v in verdicts:
        g = _match(v.row, items)
        amt = parse_amount(v.row.amount)
        if (
            v.decision == "accept"
            and g is not None
            and amt is not None
            and amt in {parse_amount(p["amount"]) for p in g["prices"]}
        ):
            got.add((id(g), amt))
    return len(got), sum(len(it["prices"]) for it in items)


def main() -> None:
    tag = sys.argv[1]
    split = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--split=")), "tune")
    print(f"{'page':14} cover  acc/printed   usable")
    for pid in sorted(split_pages(load_gold(), split)):
        path = DATA / "extract" / tag / f"{pid}.json"
        if not path.exists():
            continue
        cov, acc, printed, verdicts = page_coverage(
            json.loads(path.read_text(encoding="utf-8")), pid
        )
        u, n = usable(pid, verdicts)
        print(f"{pid}  {cov:.2f}  {acc:4}/{printed:<4}   {u / n:.2f} ({u}/{n})")


if __name__ == "__main__":
    main()
