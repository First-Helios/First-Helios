"""Measure the stage [5] validator with gold rows and injected corruptions.

    MENU_SPIKE_DATA=... uv run python -m spikes.menu_model.eval_validator [--fuzzy]

For every reviewed menu page with priced gold items:

- **correct rows** — all gold (item, variant, price) rows, validated together as
  one extraction; anything not ``accept`` is a false reject;
- **corruptions** — the same full row list with one row corrupted (so the
  validator sees realistic context). Types, as the tracker specifies:
  ``mutated_price`` (±0.50 / ±1.00 / a changed last digit), ``swapped_prices``
  (two nearby items with different amounts trade prices; each corrupted row
  counts), ``invented_item`` (a name from another page not grounded here, with
  a real price from this page), ``other_section_price`` (an amount taken from
  an item in a different section). A price corruption is caught when that row
  is not accepted; an invented item only when it is rejected.

A corruption that happens to equal a legitimate price inside the item's own
region cannot be caught by static grounding; those are counted separately as
``indistinguishable`` and reported, not hidden.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from decimal import Decimal
from typing import TYPE_CHECKING

from spikes.menu_model.labeltool import LABELS, blocks_of
from spikes.menu_model.validator import Row, norm_tokens, parse_amount, validate

if TYPE_CHECKING:
    from spikes.menu_model.segment import Block

SEED = 7
PER_TYPE_PER_PAGE = 10


def gold_rows(label: dict[str, object]) -> list[Row]:
    rows: list[Row] = []
    items = label["items"]
    assert isinstance(items, list)
    for it in items:
        for p in it["prices"]:
            rows.append(
                Row(
                    item=it["name"],
                    amount=p["amount"],
                    variant=p.get("variant"),
                    section=it.get("section"),
                    claimed_block=it.get("block"),
                )
            )
    return rows


def load_gold() -> dict[str, dict[str, object]]:
    out = {}
    for path in sorted((LABELS / "pages").glob("*.json")):
        label = json.loads(path.read_text(encoding="utf-8"))
        if (
            label.get("reviewed")
            and label.get("page_label") == "menu"
            and any(it["prices"] for it in label.get("items") or [])
        ):
            out[label["page_id"]] = label
    return out


def _mutate(amount: Decimal, rng: random.Random) -> Decimal:
    choice = rng.choice(["+0.50", "-0.50", "+1.00", "-1.00", "digit"])
    if choice == "digit":
        cents = int(amount * 100)
        last = cents % 10
        new_last = rng.choice([d for d in range(10) if d != last])
        return Decimal(cents - last + new_last) / 100
    new = amount + Decimal(choice)
    return new if new > 0 else amount + Decimal("1.00")


def main() -> None:  # noqa: C901, PLR0915 - a flat evaluation script
    fuzzy = "--fuzzy" in sys.argv
    rng = random.Random(SEED)
    gold = load_gold()
    all_names = [(pid, r.item) for pid, lab in gold.items() for r in gold_rows(lab)]
    fr = Counter[str]()
    caught = Counter[str]()
    total = Counter[str]()
    indist = Counter[str]()
    for pid, label in gold.items():
        blocks = blocks_of(pid)
        rows = [r for r in gold_rows(label) if r.amount is not None]
        if not rows:
            continue
        verdicts = validate(blocks, rows, fuzzy=fuzzy)
        for v in verdicts:
            fr["rows"] += 1
            if v.decision != "accept":
                fr["false_reject"] += 1
                fr[f"reason:{','.join(v.reasons)}"] += 1
        accepted_price = {
            i: parse_amount(r.amount)
            for i, (r, v) in enumerate(zip(rows, verdicts, strict=True))
            if v.decision == "accept"
        }
        idx = list(accepted_price)  # corrupt only rows the validator accepts when clean
        if not idx:
            continue

        def run(  # noqa: PLR0913 - binds this page's blocks explicitly
            corrupt: list[Row],
            at: list[int],
            kind: str,
            legit: list[set[Decimal]],
            blocks: list[Block] = blocks,
        ) -> None:
            vs = validate(blocks, corrupt, fuzzy=fuzzy)
            for k, i in enumerate(at):
                total[kind] += 1
                ok = (
                    vs[i].decision == "reject"
                    if kind == "invented_item"
                    else vs[i].decision != "accept"
                )
                if ok:
                    caught[kind] += 1
                elif parse_amount(corrupt[i].amount) in legit[k]:
                    indist[kind] += 1

        def own_prices(i: int, rows: list[Row] = rows) -> set[Decimal]:
            name = rows[i].item
            return {
                a for j, r in enumerate(rows) if r.item == name and (a := parse_amount(r.amount))
            }

        for _ in range(min(PER_TYPE_PER_PAGE, len(idx))):
            i = rng.choice(idx)
            amt = accepted_price[i]
            assert amt is not None
            new = _mutate(amt, rng)
            c = list(rows)
            c[i] = Row(rows[i].item, f"{new:.2f}", rows[i].variant, rows[i].section)
            run(c, [i], "mutated_price", [own_prices(i)])

        for _ in range(min(PER_TYPE_PER_PAGE, len(idx))):
            i = rng.choice(idx)
            near = [
                j
                for j in idx
                if 0 < abs(j - i) <= 3  # noqa: PLR2004
                and rows[j].item != rows[i].item
                and accepted_price[j] != accepted_price[i]
            ]
            if not near:
                continue
            j = rng.choice(near)
            c = list(rows)
            c[i] = Row(rows[i].item, rows[j].amount, rows[i].variant, rows[i].section)
            c[j] = Row(rows[j].item, rows[i].amount, rows[j].variant, rows[j].section)
            run(c, [i, j], "swapped_prices", [own_prices(i), own_prices(j)])

        page_tokens = {t for b in blocks for t in norm_tokens(b.text)}
        foreign = [n for p, n in all_names if p != pid and not set(norm_tokens(n)) <= page_tokens]
        for _ in range(min(PER_TYPE_PER_PAGE, len(foreign))):
            name = rng.choice(foreign)
            pos = rng.randrange(len(rows) + 1)
            c = [*rows[:pos], Row(name, rows[rng.choice(idx)].amount), *rows[pos:]]
            run(c, [pos], "invented_item", [set()])

        for _ in range(min(PER_TYPE_PER_PAGE, len(idx))):
            i = rng.choice(idx)
            others = [
                j
                for j in idx
                if rows[j].section != rows[i].section and accepted_price[j] not in own_prices(i)
            ]
            if not others:
                continue
            j = rng.choice(others)
            c = list(rows)
            c[i] = Row(rows[i].item, rows[j].amount, rows[i].variant, rows[i].section)
            run(c, [i], "other_section_price", [own_prices(i)])

    print(f"pages={len(gold)} fuzzy={fuzzy}")
    rows_n = fr["rows"] or 1
    print(
        f"correct rows={fr['rows']} false_reject={fr['false_reject']} rate={fr['false_reject'] / rows_n:.3f}"
    )
    for k, n in sorted(fr.items()):
        if k.startswith("reason:"):
            print(f"  {k} {n}")
    all_t = sum(total.values()) or 1
    for kind in sorted(total):
        print(
            f"{kind:20} n={total[kind]:4} caught={caught[kind]:4} "
            f"rate={caught[kind] / total[kind]:.3f} indistinguishable={indist[kind]}"
        )
    print(
        f"{'ALL':20} n={sum(total.values()):4} caught={sum(caught.values()):4} rate={sum(caught.values()) / all_t:.3f}"
    )


if __name__ == "__main__":
    main()
