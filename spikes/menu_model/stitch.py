"""Deterministic row stitching (after the stress test): re-assemble items the LLM split by line.

On layouts where a price sits on its own line, the extractor transcribes line by line: the
item row comes back unpriced and the next line ("$7.50/Medium", or a description ending in
"/ 15.95") comes back as its own "item" carrying the price. This pass moves such a price onto
the unpriced item just before it and drops the pseudo-item:

- the priced row's claimed block lies 1..MAX_GAP blocks after the anchor item's block (the
  item's own block, or the last line already stitched onto it), in document order;
- the priced row is a **price line** (nothing left but the amount and a size word) or a
  **description line** (starts lower-case, or its block text is long and comma-listed);
- several price lines after one item become one row per price (size variants).

Everything moved keeps its evidence: the price still has to be grounded in the item's region
by the validator, which runs after this.

**v2** (``stitch(..., v2=True)``, ``MENU_SPIKE_STITCH=2``; from the dev/ho1 loss analysis):

- a description line is also any long sentence-like line (>= 7 words, or ending in ".");
- an unpriced description line right after an item is dropped instead of becoming the anchor
  (the model transcribed it as an "item"; its successor price line must still reach the item);
- a price line repeating the amount of the priced item just above is dropped (an echo);
- **price fill**: an item still unpriced takes the price(s) printed in the price-only
  block(s) that follow its name block within ``FILL_GAP`` blocks, skipping only non-heading,
  non-price lines (descriptions, icon text) and stopping at any heading, any other extracted
  row's block or any block with both words and a price. The price comes from the page, not
  the model; several consecutive price-only blocks become one row each, with the label
  printed with the price ("/2 pcs", "Small") as the variant.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from spikes.menu_model.validator import PriceToken, Row, norm_tokens, price_label, price_tokens

if TYPE_CHECKING:
    from spikes.menu_model.segment import Block

MAX_GAP = 3
FILL_GAP = 4
_MONEY_TEXT = re.compile(r"\$?\s?\d{1,4}(?:[.,]\d{1,2})?")


def _is_price_line(row: Row) -> bool:
    rest = _MONEY_TEXT.sub(" ", row.item)
    words = [t for t in norm_tokens(rest) if not t.isdigit()]
    variant = set(norm_tokens(row.variant or ""))
    return len([w for w in words if w not in variant]) == 0 and len(words) <= 3  # noqa: PLR2004


def _is_description_line(row: Row, text: str) -> bool:
    name = row.item.strip()
    if not name:
        return False
    return name[0].islower() or (len(text) > 40 and text.count(",") >= 2)  # noqa: PLR2004


def _is_sentence_line(
    row: Row, block: Block | None, anchor: Block | None, *, block_priced: bool
) -> bool:
    """v2: a sentence-like line under a heading item, in its own non-heading, price-less block.

    Structural gates, not wording alone: "Cheese Quesadilla Served with pico de gallo ... 9.99"
    (an inline item: its block prints a price) and "Fog Cutter" (short) stay items.
    """
    name = row.item.strip()
    if block is None or anchor is None or block.heading or not anchor.heading:
        return False
    if block_priced:
        return False
    return len(name.split()) >= 7 or (len(name) > 25 and name.rstrip().endswith("."))  # noqa: PLR2004


def stitch(rows: list[Row], blocks: list[Block], *, v2: bool = False) -> tuple[list[Row], int]:
    """Stitched rows and how many pseudo-item rows were merged into an item (or dropped)."""
    index = {b.id: i for i, b in enumerate(blocks)}
    priced_blocks = (
        {i for i, toks in enumerate(price_tokens(blocks)) if any(t.kind == "money" for t in toks)}
        if v2
        else set()
    )
    out: list[Row] = []
    anchor: int | None = None  # position in ``out`` of the item that absorbs following lines
    anchor_block = -10  # the last block absorbed into the anchor item
    anchor_home = 0  # the anchor item's own name block
    anchor_priced = False
    last_priced: tuple[int, str | None] | None = None
    merged = 0
    for row in rows:
        pos = index.get(row.claimed_block or "")
        if v2:
            pos = _name_block(row, blocks, index)
        text = blocks[pos].text if pos is not None else ""
        near = pos is not None and anchor is not None and 0 < pos - anchor_block <= MAX_GAP
        sentence = (
            v2
            and near
            and anchor is not None
            and _is_sentence_line(
                row,
                blocks[pos] if pos is not None else None,
                blocks[anchor_home],
                block_priced=pos is not None and pos in priced_blocks,
            )
        )
        desc = _is_description_line(row, text) or sentence
        pseudo = row.amount is not None and (_is_price_line(row) or desc)
        if sentence and row.amount is None:
            anchor_block = pos if pos is not None else anchor_block  # drop, keep the anchor
            merged += 1
            continue
        if (
            v2
            and pseudo
            and _is_price_line(row)
            and out
            and last_priced is not None
            and pos is not None
            and 0 < pos - last_priced[0] <= MAX_GAP
            and last_priced[1] == row.amount
        ):
            merged += 1  # "$20.24" echoed as an item right after "Soup  20.24"
            continue
        if near and pseudo and anchor is not None:
            base = out[anchor]
            variant = row.variant if _is_price_line(row) else None
            if not anchor_priced:
                out[anchor] = replace(base, amount=row.amount, variant=variant or base.variant)
                anchor_priced = True
            else:
                out.append(replace(base, amount=row.amount, variant=variant))
            anchor_block = pos if pos is not None else anchor_block
            merged += 1
            continue
        out.append(row)
        last_priced = (pos, row.amount) if row.amount is not None and pos is not None else None
        if row.amount is None and pos is not None:
            anchor, anchor_block, anchor_priced = len(out) - 1, pos, False
            anchor_home = pos
        else:
            anchor = None
    if v2:
        out, filled = fill_prices(out, blocks)
        merged += filled
    return out, merged


def fill_prices(rows: list[Row], blocks: list[Block]) -> tuple[list[Row], int]:
    """v2 price fill: unpriced items take the price-only block(s) printed just below them."""

    index = {b.id: i for i, b in enumerate(blocks)}
    prices = price_tokens(blocks)
    row_blocks = {j for r in rows if (j := _name_block(r, blocks, index)) is not None}
    out: list[Row] = []
    filled = 0
    for row in rows:
        pos = _name_block(row, blocks, index)
        if row.amount is not None or pos is None or not _names_in(row.item, blocks[pos].text):
            out.append(row)
            continue
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
        if not run:
            out.append(row)
            continue
        filled += 1
        for j in run:
            for t in [t for t in prices[j] if t.kind == "money"]:
                label = price_label(blocks[j].text, prices[j], t) or None
                amount = blocks[j].text[t.start : t.end].replace("$", "").strip()
                out.append(
                    replace(row, amount=amount, variant=label, claimed_block=row.claimed_block)
                )
    return out, filled


def _name_block(row: Row, blocks: list[Block], index: dict[str, int]) -> int | None:
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
    return len(re.findall(r"[^\W\d_]", rest)) <= 12  # noqa: PLR2004 - "/2 pcs", "Small"
