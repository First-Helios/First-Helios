"""Repairs toolbelt, stitch v3: re-assemble items the extractor split by line (ADR-0013 §1).

Ported from ``spikes/menu_model/stitch.py`` as frozen at spike commit
``e6e4e1f`` with ``MENU_SPIKE_STITCH=3`` (v1 + v2 + v3 rules, hard-wired). Every
rule is positional and layout-generic, never per site. On layouts that print a
price on its own line the model transcribes line by line: the item comes back
unpriced and the next line ("$7.50/Medium", or a description ending in
"/ 15.95") comes back as its own "item" carrying the price.

1. **Merge.** A priced pseudo-item (a *price line*: nothing left but the amount
   and a size word; or a *description line*: starts lower-case, its block is
   long and comma-listed, or it is a sentence-like line under a heading item)
   whose name block lies 1..``MAX_GAP`` blocks after the unpriced item before it
   gives that item its price and is dropped; several price lines become one row
   per price (size variants).
2. **Drop.** An unpriced sentence-like line right after a heading item is
   dropped without ending the item; a price line (or lower-case line) repeating
   the amount of the priced row just above is an echo and is dropped.
3. **Price fill.** An item still unpriced takes the price(s) of the price-only
   block(s) printed within ``FILL_GAP`` blocks below its name, skipping
   description/icon lines and stopping at a heading, another row's block or a
   block with both words and a price; the label printed with each price
   ("/2 pcs", "Small") becomes its variant. The price comes from the page.
4. **Variant completion.** An item priced from the run of price-only lines
   below it gets the run's other *labelled* prices ("Glass $7" / "Bottle $26");
   an item alone in its block with several inline prices ("Americano $2/$3")
   gets the others. Only when every amount the model gave it is in that run.

Everything moved keeps its evidence: the validator, which runs after this,
still has to ground each price in the item's region.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from packages.helios_parsing.prices import PriceToken, price_tokens
from packages.helios_parsing.validator import Row, norm_tokens, parse_amount, price_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from packages.helios_parsing.segment import Block

MAX_GAP = 3
FILL_GAP = 4
_MONEY_TEXT = re.compile(r"\$?\s?\d{1,4}(?:[.,]\d{1,2})?")
_LETTER = re.compile(r"[^\W\d_]")
_PRICE_ONLY_LETTERS = 12  # "/2 pcs", "Small"
_SENTENCE_WORDS = 7
_SENTENCE_CHARS = 25
_DESCRIPTION_CHARS = 40


def _is_price_line(row: Row) -> bool:
    rest = _MONEY_TEXT.sub(" ", row.item)
    words = [t for t in norm_tokens(rest) if not t.isdigit()]
    variant = set(norm_tokens(row.variant or ""))
    return not [w for w in words if w not in variant] and len(words) <= 3


def _is_description_line(row: Row, text: str) -> bool:
    name = row.item.strip()
    if not name:
        return False
    return name[0].islower() or (len(text) > _DESCRIPTION_CHARS and text.count(",") >= 2)


def _is_sentence_line(row: Row, block: Block, anchor: Block, *, block_priced: bool) -> bool:
    """A sentence-like line under a heading item, in its own non-heading, price-less block.

    Structural gates, not wording alone: "Cheese Quesadilla Served with pico de
    gallo ... 9.99" (an inline item: its block prints a price) and "Fog Cutter"
    (short) stay items.
    """
    if block.heading or not anchor.heading or block_priced:
        return False
    name = row.item.strip()
    return len(name.split()) >= _SENTENCE_WORDS or (
        len(name) > _SENTENCE_CHARS and name.rstrip().endswith(".")
    )


def stitch(rows: Sequence[Row], blocks: Sequence[Block]) -> list[Row]:
    """The rows with split lines merged into their items, then price fill and variant completion."""
    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(list(blocks))
    priced_blocks = {i for i, toks in enumerate(prices) if any(t.kind == "money" for t in toks)}
    out: list[Row] = []
    anchor: int | None = None  # position in ``out`` of the item that absorbs following lines
    anchor_block = -10  # the last block absorbed into the anchor item
    anchor_home = 0  # the anchor item's own name block
    anchor_priced = False
    last_priced: tuple[int, str | None] | None = None
    for row in rows:
        pos = _name_block(row, blocks, index)
        text = blocks[pos].text if pos is not None else ""
        near = pos is not None and anchor is not None and 0 < pos - anchor_block <= MAX_GAP
        sentence = (
            near
            and pos is not None
            and _is_sentence_line(
                row, blocks[pos], blocks[anchor_home], block_priced=pos in priced_blocks
            )
        )
        price_line = _is_price_line(row)
        pseudo = row.amount is not None and (
            price_line or sentence or _is_description_line(row, text)
        )
        if sentence and row.amount is None and pos is not None:
            anchor_block = pos  # dropped; the item keeps absorbing lines
            continue
        if (
            pseudo
            and (price_line or row.item.strip()[:1].islower())
            and out
            and last_priced is not None
            and pos is not None
            and 0 < pos - last_priced[0] <= MAX_GAP
            and parse_amount(last_priced[1]) == parse_amount(row.amount)
        ):
            continue  # "$20.24" echoed as an item right after "Soup  20.24"
        if near and pseudo and anchor is not None and pos is not None:
            base = out[anchor]
            variant = row.variant if price_line else None
            if not anchor_priced:
                out[anchor] = replace(base, amount=row.amount, variant=variant or base.variant)
                anchor_priced = True
            else:
                out.append(replace(base, amount=row.amount, variant=variant))
            anchor_block = pos
            continue
        out.append(row)
        last_priced = (pos, row.amount) if row.amount is not None and pos is not None else None
        if row.amount is None and pos is not None:
            anchor, anchor_block, anchor_priced, anchor_home = len(out) - 1, pos, False, pos
        else:
            anchor = None
    return complete_variants(fill_prices(out, blocks), blocks)


def _run_after(
    pos: int, blocks: Sequence[Block], prices: list[list[PriceToken]], row_blocks: set[int]
) -> list[int]:
    """Price-only blocks printed just below a name block (skipping description/icon lines)."""
    run: list[int] = []
    for j in range(pos + 1, min(pos + 1 + FILL_GAP, len(blocks))):
        toks = [t for t in prices[j] if t.kind == "money"]
        if j in row_blocks or blocks[j].heading:
            break
        if toks and _price_only(blocks[j].text, toks):
            run.append(j)
            continue
        if run or toks:
            break  # end of the price run, or a priced line that is not price-only
    return run


def _priced(row: Row, text: str, toks: list[PriceToken], tok: PriceToken) -> Row:
    """``row`` with the price ``tok`` printed in ``text`` and its label as the variant."""
    amount = text[tok.start : tok.end].replace("$", "").strip()
    return replace(row, amount=amount, variant=price_label(text, toks, tok) or None)


def _run_rows(
    row: Row, blocks: Sequence[Block], prices: list[list[PriceToken]], run: list[int]
) -> list[Row]:
    return [
        _priced(row, blocks[j].text, prices[j], t)
        for j in run
        for t in prices[j]
        if t.kind == "money"
    ]


def fill_prices(rows: Sequence[Row], blocks: Sequence[Block]) -> list[Row]:
    """Unpriced items take the price-only block(s) printed just below them."""
    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(list(blocks))
    row_blocks = {j for r in rows if (j := _name_block(r, blocks, index)) is not None}
    out: list[Row] = []
    for row in rows:
        pos = _name_block(row, blocks, index)
        if row.amount is not None or pos is None or not _names_in(row.item, blocks[pos].text):
            out.append(row)
            continue
        run = _run_after(pos, blocks, prices, row_blocks)
        out.extend(_run_rows(row, blocks, prices, run) if run else [row])
    return out


def complete_variants(rows: Sequence[Row], blocks: Sequence[Block]) -> list[Row]:
    """An item priced from the run of price-only lines below it gets the run's other prices.

    "Glass $7" / "Bottle $26" under a wine, "$4.50" / "Without Ice $5.00" under a
    tea: the model kept the first price and dropped the second. Only when every
    amount the model gave the item is printed in that run (so the run is the
    item's own), the run's missing amounts are added with their printed labels.
    """
    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(list(blocks))
    row_blocks = {j for r in rows if (j := _name_block(r, blocks, index)) is not None}
    groups: dict[tuple[str, int], list[int]] = {}  # (name, name block) -> row positions
    for i, r in enumerate(rows):
        pos = _name_block(r, blocks, index)
        if r.amount is not None and pos is not None and _names_in(r.item, blocks[pos].text):
            groups.setdefault((" ".join(norm_tokens(r.item)), pos), []).append(i)
    per_block: dict[int, int] = {}
    for _, pos in groups:
        per_block[pos] = per_block.get(pos, 0) + 1
    extra: dict[int, list[Row]] = {}  # last row position of a group -> rows to add after it
    for (_, pos), members in groups.items():
        first = rows[members[0]]
        run = _run_after(pos, blocks, prices, row_blocks - {pos})
        cands = _run_rows(first, blocks, prices, run)
        if not run and per_block[pos] == 1:  # inline "Americano $2/$3": one item in the block
            text = blocks[pos].text
            start = text.lower().find(norm_tokens(first.item)[0])
            toks = [t for t in prices[pos] if t.kind == "money" and t.start > start]
            if len(toks) >= 2:
                cands = [_priced(first, text, prices[pos], t) for t in toks]
        printed = {parse_amount(c.amount) for c in cands}
        have = {parse_amount(rows[i].amount) for i in members}
        if not cands or not have <= printed:
            continue
        # from a run below the item, only LABELLED lines ("Bottle $26"): on pages that
        # print every price twice, an unlabelled "$11" right after the item's own price
        # is the next item's leading copy (spike finding 9, held-out-3)
        missing = [
            c for c in cands if parse_amount(c.amount) not in have and (not run or c.variant)
        ]
        if missing:
            extra[members[-1]] = missing
    out: list[Row] = []
    for i, r in enumerate(rows):
        out.append(r)
        out.extend(extra.get(i, []))
    return out


def _name_block(row: Row, blocks: Sequence[Block], index: dict[str, int]) -> int | None:
    """The block the row's name is printed in: the claimed one, else the nearest within 2.

    The model sometimes claims a neighbour's id (a description row claiming the price line).
    """
    pos = index.get(row.claimed_block or "")
    if pos is None:
        return None
    for j in (pos, pos + 1, pos - 1, pos + 2, pos - 2):
        if 0 <= j < len(blocks) and _names_in(row.item, blocks[j].text):
            return j
    return pos


def _names_in(name: str, text: str) -> bool:
    toks = norm_tokens(name)
    return bool(toks) and set(toks) <= set(norm_tokens(text))


def _price_only(text: str, toks: list[PriceToken]) -> bool:
    rest = text
    for t in sorted(toks, key=lambda t: -t.start):
        rest = rest[: t.start] + rest[t.end :]
    return len(_LETTER.findall(rest)) <= _PRICE_ONLY_LETTERS
