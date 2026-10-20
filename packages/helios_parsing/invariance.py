"""Invariance suite (ADR-0017 item 1): which repair, validator and [5b] decisions change
when a correct extraction is written in another, meaning-preserving style.

Ported from P5-20's scratch ``invariance.py`` (session P5-24). A page's gold rows are
written as the model would write them (``{"b","n","p","v"}`` per gold price, grouped by
gold section in label order: a perfect output), then each style ``VARIANTS`` names is
applied page-wide (a model writes in one style consistently) and the result goes
through the harness exactly as model output does (``output.rows_of``, the validator,
[5b]). Each gold (item, amount) gets a status, the best decision of a row matched to the
item at that amount: ``accept`` > ``downgrade`` > ``reject`` > ``absent`` (no row
carries it after the repairs). A **flip** is a status that differs from the unchanged
output's. Every decision should depend on page evidence, never on output style, so a
harness change that adds flips is rejected (ADR-0017 items 1-2); today's flips are
recorded as debt.

The styles (ADR-0017 item 1's list):

- ``claim_next`` / ``claim_price_block``: the block claim on the item's next block, or
  on the block printing its price (within the item's span: before the next gold item);
- ``price_short`` / ``price_two`` / ``price_dollar``: "18.5", "18.50", "$18.50";
- ``case_lower`` / ``case_upper`` / ``case_title`` / ``whitespace``: the name's letter
  case and spacing;
- ``variant_in_name`` / ``variant_in_name_paren``: the variant written into the name
  ("Horchata Large", "Horchata (Large)") instead of ``v``;
- ``empty_v``: ``"v": ""`` instead of no ``v``;
- ``section_upper`` / ``section_none`` / ``section_generic``: the section label upper
  case, empty, or "Menu".
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from packages.helios_parsing.evaluation import match
from packages.helios_parsing.output import parse_output, rows_of
from packages.helios_parsing.resolve import RESOLVERS, judge
from packages.helios_parsing.validator import parse_amount

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from decimal import Decimal

    from packages.helios_parsing.evaluation import GoldPage
    from packages.helios_parsing.output import ExtractorOutput
    from packages.helios_parsing.segment import Block
    from packages.helios_parsing.validator import Verdict

    Harness = Callable[[Sequence[Block], list[ExtractorOutput]], Sequence[Verdict]]

VARIANTS = (
    "claim_next",
    "claim_price_block",
    "price_short",
    "price_two",
    "price_dollar",
    "case_lower",
    "case_upper",
    "case_title",
    "whitespace",
    "variant_in_name",
    "variant_in_name_paren",
    "empty_v",
    "section_upper",
    "section_none",
    "section_generic",
)
_RANK = {"accept": 3, "downgrade": 2, "reject": 1, "absent": 0}
_PRINTED_AMOUNT = re.compile(r"\$?\s?\d{1,4}(?:[.,]\d{1,2})?")


@dataclass(frozen=True, slots=True)
class _Out:
    """One output row as the model writes it, with the gold item it was written from."""

    item: int
    section: str
    block: str
    name: str
    price: str
    variant: str | None


def harness(blocks: Sequence[Block], outputs: list[ExtractorOutput]) -> Sequence[Verdict]:
    """The pipeline's own reading of model output: repairs, the validator, [5b]."""
    return judge(blocks, rows_of(outputs, blocks), RESOLVERS).verdicts


def perfect_rows(page: GoldPage) -> list[_Out]:
    """One output row per gold price, in label order."""
    return [
        _Out(g, it.section or "", it.block or "", it.name, p.amount, p.variant or None)
        for g, it in enumerate(page.items)
        for p in it.prices
    ]


def _price_block(blocks: Sequence[Block], start: int, stop: int, amount: str) -> int | None:
    want = parse_amount(amount)
    for j in range(start, min(stop, len(blocks))):
        if any(parse_amount(m.group(0)) == want for m in _PRINTED_AMOUNT.finditer(blocks[j].text)):
            return j
    return None


def _price(amount: str, style: str) -> str:
    value = parse_amount(amount)
    if value is None:
        return amount
    if style == "price_short":  # 18.50 -> 18.5, 18.00 -> 18
        return format(value.normalize(), "f")
    if style == "price_two":
        return f"{value:.2f}"
    return "$" + amount


def restyle(
    rows: Sequence[_Out], style: str, blocks: Sequence[Block], page: GoldPage
) -> list[_Out]:
    """Every row written in one of ``VARIANTS``'s styles."""
    index = {b.id: i for i, b in enumerate(blocks)}
    starts = sorted(index.get(it.block or "", -1) for it in page.items)
    out = []
    for r in rows:
        i = index.get(r.block)
        stop = min((s for s in starts if i is not None and s > i), default=len(blocks))
        if style == "claim_next" and i is not None and i + 1 < stop:
            r = replace(r, block=blocks[i + 1].id)
        elif style == "claim_price_block" and i is not None:
            j = _price_block(blocks, i, stop, r.price)
            if j is not None:
                r = replace(r, block=blocks[j].id)
        elif style.startswith("price_"):
            r = replace(r, price=_price(r.price, style))
        elif style == "case_lower":
            r = replace(r, name=r.name.lower())
        elif style == "case_upper":
            r = replace(r, name=r.name.upper())
        elif style == "case_title":
            r = replace(r, name=r.name.title())
        elif style == "whitespace":
            r = replace(r, name=" " + r.name.replace(" ", "  ") + " ")
        elif style == "variant_in_name" and r.variant:
            r = replace(r, name=f"{r.name} {r.variant}", variant=None)
        elif style == "variant_in_name_paren" and r.variant:
            r = replace(r, name=f"{r.name} ({r.variant})", variant=None)
        elif style == "empty_v" and not r.variant:
            r = replace(r, variant="")
        elif style == "section_upper":
            r = replace(r, section=r.section.upper())
        elif style == "section_none":
            r = replace(r, section="")
        elif style == "section_generic":
            r = replace(r, section="Menu")
        out.append(r)
    return out


def as_output(rows: Sequence[_Out]) -> ExtractorOutput:
    """The rows as one chunk's generated JSON, read by the pipeline's own parser."""
    sections: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        item = {"b": r.block, "n": r.name, "p": r.price}
        if r.variant is not None:
            item["v"] = r.variant
        sections.setdefault(r.section, []).append(item)
    return parse_output(
        json.dumps({"sections": [{"section": s, "items": items} for s, items in sections.items()]})
    )


def statuses(page: GoldPage, verdicts: Sequence[Verdict]) -> dict[tuple[int, Decimal], str]:
    """Each gold (item, amount) a row carries: the best decision of such a row."""
    out: dict[tuple[int, Decimal], str] = {}
    for v in verdicts:
        g = match(v.row, page.items)
        amount = parse_amount(v.row.amount)
        if g is None or amount is None:
            continue
        if amount not in {parse_amount(p.amount) for p in page.items[g].prices}:
            continue
        key = (g, amount)
        if _RANK[v.decision] > _RANK[out.get(key, "absent")]:
            out[key] = v.decision
    return out


def invariance_page(
    page: GoldPage, blocks: Sequence[Block], run: Harness = harness
) -> Counter[str]:
    """One page's counts: ``gold_prices``, ``base:<status>``, and per style
    ``flip:<style>``, ``lost_accept:<style>`` and ``gained_accept:<style>``."""
    rows = perfect_rows(page)
    keys = {(r.item, amount) for r in rows if (amount := parse_amount(r.price)) is not None}
    base = statuses(page, run(blocks, [as_output(rows)]))
    c: Counter[str] = Counter(gold_prices=len(keys))
    c.update(f"base:{base.get(k, 'absent')}" for k in keys)
    for style in VARIANTS:
        after = statuses(page, run(blocks, [as_output(restyle(rows, style, blocks, page))]))
        for k in keys:
            a, b = base.get(k, "absent"), after.get(k, "absent")
            if a != b:
                c[f"flip:{style}"] += 1
                c[f"lost_accept:{style}"] += int(a == "accept")
                c[f"gained_accept:{style}"] += int(b == "accept")
    return c


def added_flips(
    baseline: Mapping[str, Mapping[str, int]], current: Mapping[str, Mapping[str, int]]
) -> list[tuple[str, str, int, int]]:
    """(page, style, before, after) wherever a page flips more under a style than in the
    baseline run (both: page id -> ``invariance_page`` counts); ADR-0017 rejects any."""
    return [
        (pid, style, before, after)
        for pid, counts in sorted(current.items())
        for style in VARIANTS
        if (after := counts.get(f"flip:{style}", 0))
        > (before := baseline.get(pid, {}).get(f"flip:{style}", 0))
    ]
