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
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from spikes.menu_model.validator import Row, norm_tokens

if TYPE_CHECKING:
    from spikes.menu_model.segment import Block

MAX_GAP = 3
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


def stitch(rows: list[Row], blocks: list[Block]) -> tuple[list[Row], int]:
    """Stitched rows and how many pseudo-item rows were merged into an item."""
    index = {b.id: i for i, b in enumerate(blocks)}
    out: list[Row] = []
    anchor: int | None = None  # position in ``out`` of the item that absorbs following lines
    anchor_block = -10
    anchor_priced = False
    merged = 0
    for row in rows:
        pos = index.get(row.claimed_block or "")
        text = blocks[pos].text if pos is not None else ""
        near = pos is not None and anchor is not None and 0 < pos - anchor_block <= MAX_GAP
        pseudo = row.amount is not None and (_is_price_line(row) or _is_description_line(row, text))
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
        if row.amount is None and pos is not None:
            anchor, anchor_block, anchor_priced = len(out) - 1, pos, False
        else:
            anchor = None
    return out, merged
